"""
Enhanced WebSocket service with daily limits and conversation transcription
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect

from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from services.user_service import get_user_service
from services.conversation_service import get_conversation_service
from utils.logger import LoggerMixin
from utils.exceptions import ValidationException


class WebSocketConnectionManager(LoggerMixin):
    """Enhanced WebSocket connection manager with daily limits and conversation tracking"""
    
    def __init__(self):
        super().__init__()
        self.firebase_service = get_firebase_service()
        self.openai_service = get_openai_service()
        self.user_service = get_user_service()
        self.conversation_service = get_conversation_service()
        
        # Active connections: device_id -> WebSocket
        self.connections: Dict[str, WebSocket] = {}
        self.connection_times: Dict[str, float] = {}
        
        # Audio buffering
        self.audio_buffers: Dict[str, bytearray] = {}
        self.buffer_timers: Dict[str, asyncio.Task] = {}
        
        # Keepalive and activity tracking
        self.keepalive_tasks: Dict[str, asyncio.Task] = {}
        self.last_activity: Dict[str, float] = {}
        self.last_audio_time: Dict[str, float] = {}
        
        # Configuration
        self.keepalive_interval = 10
        self.connection_timeout = 300
        self.activity_timeout = 120
        self.silence_threshold = 1.0
        
        # Setup OpenAI service connection to conversation service
        self.openai_service.set_conversation_service(self.conversation_service)
    
    async def connect_device(self, websocket: WebSocket, device_id: str, remote_addr: str) -> bool:
        """Handle ESP32 device connection with daily limits and conversation tracking"""
        connection_start_time = time.time()
        
        try:
            # Accept WebSocket connection
            await websocket.accept()
            self.log_info(f"✅ WebSocket accepted for {device_id}")
            
            # Store connection IMMEDIATELY
            self.connections[device_id] = websocket
            self.connection_times[device_id] = connection_start_time
            self.last_activity[device_id] = connection_start_time
            self.audio_buffers[device_id] = bytearray()
            self.last_audio_time[device_id] = connection_start_time
            
            # Send immediate acknowledgment
            ack_message = {
                "type": "connection_ack",
                "device_id": device_id,
                "timestamp": connection_start_time,
                "status": "initializing",
                "message": "Checking daily limits and setting up session..."
            }
            
            if not await self._safe_send_message(websocket, device_id, ack_message):
                return False
            
            # Start keepalive during setup
            self.keepalive_tasks[device_id] = asyncio.create_task(
                self._setup_keepalive_loop(device_id)
            )
            
            try:
                # 1. Check daily episode limits FIRST
                self.log_info(f"🔍 Checking daily limits for {device_id}...")
                await self._safe_send_status(device_id, "Checking daily episode limits...")
                
                limit_info = await self.user_service.check_episode_limit(device_id)
                
                # Check if user can play an episode today
                if not limit_info['can_play_episode']:
                    self.log_warning(f"❌ Daily episode limit exceeded for {device_id}: {limit_info['episodes_played_today']}/3")
                    
                    limit_exceeded_message = {
                        "type": "daily_limit_exceeded",
                        "device_id": device_id,
                        "episodes_played_today": limit_info['episodes_played_today'],
                        "daily_limit": limit_info['daily_limit'],
                        "remaining_episodes": limit_info['remaining_episodes'],
                        "message": f"Daily episode limit reached ({limit_info['episodes_played_today']}/3). Try again tomorrow!",
                        "retry_after": "tomorrow"
                    }
                    
                    await self._safe_send_message(websocket, device_id, limit_exceeded_message)
                    
                    # Wait a moment for message to be sent, then close
                    await asyncio.sleep(2)
                    return False
                
                # 2. Get user and episode data
                self.log_info(f"🔍 Fetching user data for {device_id}...")
                await self._safe_send_status(device_id, "Loading user profile...")
                
                user_response = await self.user_service.get_user(device_id)
                
                await self._safe_send_status(device_id, f"Loading Season {user_response.season}, Episode {user_response.episode}...")
                
                system_prompt_obj = await self.firebase_service.get_system_prompt(
                    user_response.season, user_response.episode
                )
                
                self.log_info(f"📋 Retrieved user data for {device_id}: Season {user_response.season}, Episode {user_response.episode}")
                
                # 3. Start conversation session
                self.log_info(f"💬 Starting conversation session for {device_id}...")
                await self._safe_send_status(device_id, "Starting conversation session...")
                
                conversation_session = await self.conversation_service.start_session(
                    device_id=device_id,
                    season=user_response.season,
                    episode=user_response.episode,
                    system_prompt=system_prompt_obj.prompt
                )
                
                self.log_info(f"💬 Conversation session started: {conversation_session.session_id}")
                
            except Exception as e:
                self.log_error(f"❌ Failed to setup session for {device_id}: {e}")
                error_message = {
                    "type": "error",
                    "error": "setup_failed",
                    "message": f"Failed to setup session: {str(e)}",
                    "device_id": device_id
                }
                await self._safe_send_message(websocket, device_id, error_message)
                return False
            
            # Send ready message with daily limits info
            ready_message = {
                "type": "ready", 
                "device_id": device_id,
                "season": user_response.season,
                "episode": user_response.episode,
                "session_id": conversation_session.session_id,
                "openai_connecting": True,
                "daily_limits": {
                    "episodes_played_today": limit_info['episodes_played_today'],
                    "remaining_episodes": limit_info['remaining_episodes'],
                    "daily_limit": limit_info['daily_limit']
                },
                "server_time": datetime.now().isoformat(),
                "setup_duration": time.time() - connection_start_time
            }
            
            if not await self._safe_send_message(websocket, device_id, ready_message):
                return False
            
            # Transition to normal keepalive
            if device_id in self.keepalive_tasks:
                self.keepalive_tasks[device_id].cancel()
            
            self.keepalive_tasks[device_id] = asyncio.create_task(
                self._normal_keepalive_loop(device_id)
            )
            
            # Create OpenAI connection in background
            asyncio.create_task(
                self._create_openai_connection_async(device_id, system_prompt_obj.prompt)
            )
            
            # Start silence detection task
            asyncio.create_task(self._silence_detection_loop(device_id))
            
            # Handle messages
            await self._handle_messages_with_conversation_tracking(websocket, device_id)
            
        except Exception as e:
            self.log_error(f"❌ Connection error for {device_id}: {e}", exc_info=True)
            return False
        finally:
            await self._safe_cleanup_device(device_id)
            
        return True
    
    async def _handle_messages_with_conversation_tracking(self, websocket: WebSocket, device_id: str):
        """Handle incoming messages with conversation tracking and daily limits"""
        session_start_time = time.time()
        
        try:
            while device_id in self.connections:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(), 
                        timeout=self.keepalive_interval + 5
                    )
                    
                    # Update activity timestamp
                    self.last_activity[device_id] = time.time()
                    
                    self.log_info(f"📥 Message from {device_id}: type={message.get('type')}")
                    
                    if message["type"] == "websocket.receive":
                        if "bytes" in message:
                            audio_data = message["bytes"]
                            self.log_info(f"🎵 Audio from {device_id}: {len(audio_data)} bytes")
                            await self._handle_audio_data(device_id, audio_data)
                        
                        elif "text" in message:
                            text_content = message["text"]
                            self.log_info(f"💬 Text from {device_id}: {text_content[:100]}...")
                            try:
                                text_data = json.loads(text_content)
                                await self._handle_text_message(device_id, text_data)
                            except json.JSONDecodeError:
                                await self._handle_simple_command(device_id, text_content)
                    
                    elif message["type"] == "websocket.disconnect":
                        self.log_info(f"🔌 Disconnect message from {device_id}")
                        break
                
                except asyncio.TimeoutError:
                    continue
                    
                except WebSocketDisconnect:
                    self.log_info(f"🔌 Client disconnected: {device_id}")
                    break
                
                except Exception as e:
                    if "1005" in str(e) or "ConnectionClosed" in str(e):
                        self.log_info(f"🔌 WebSocket connection closed for {device_id}: {e}")
                        break
                    else:
                        self.log_error(f"❌ Message handling error for {device_id}: {e}")
                        break
                    
        except Exception as e:
            self.log_error(f"❌ Message handling error for {device_id}: {e}", exc_info=True)
        finally:
            # Calculate session duration and add to user's daily usage
            session_duration = time.time() - session_start_time
            
            try:
                await self.user_service.add_session_time(device_id, session_duration)
                self.log_info(f"⏱️ Added {session_duration:.1f}s session time for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠️ Failed to add session time for {device_id}: {e}")
            
            # End conversation session
            try:
                await self.conversation_service.end_session(
                    device_id, 
                    "websocket_disconnected", 
                    completed_successfully=True
                )
                self.log_info(f"💬 Conversation session ended for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠️ Failed to end conversation session for {device_id}: {e}")
    
    async def _handle_audio_data(self, device_id: str, audio_data: bytes):
        """Handle audio data with conversation tracking"""
        self.log_info(f"📤 Audio chunk from {device_id}: {len(audio_data)} bytes")
        
        # Update activity and audio timestamps
        current_time = time.time()
        self.last_activity[device_id] = current_time
        self.last_audio_time[device_id] = current_time
        
        # Forward to OpenAI
        if device_id in self.openai_service.active_connections:
            try:
                await self.openai_service.send_audio(device_id, audio_data)
                self.log_info(f"✅ Forwarded audio to OpenAI for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠️ Failed to forward audio to OpenAI for {device_id}: {e}")
                
                # Add system message about audio forwarding failure
                if self.conversation_service:
                    await self.conversation_service.add_system_message(
                        device_id,
                        f"Audio forwarding failed: {str(e)}",
                        metadata={"event": "audio_forward_error", "error": str(e)}
                    )
    
    async def _handle_text_message(self, device_id: str, data: dict):
        """Handle JSON text messages with conversation tracking"""
        self.last_activity[device_id] = time.time()
        
        msg_type = data.get("type")
        self.log_info(f"📝 Text message from {device_id}: {msg_type}")
        
        # Handle episode completion commands
        if msg_type == "episode_complete":
            await self._handle_episode_completion(device_id, data)
        
        elif msg_type == "request_episode_advance":
            await self._handle_episode_advance_request(device_id)
        
        elif msg_type in ["ping", "client_ping", "heartbeat"]:
            if device_id in self.connections:
                pong_response = {
                    "type": "pong", 
                    "timestamp": time.time(),
                    "server_time": datetime.now().isoformat()
                }
                await self._safe_send_message(self.connections[device_id], device_id, pong_response)
        
        elif msg_type in ["pong", "client_pong"]:
            self.log_info(f"🏓 Received pong from {device_id}")
        
        # Add system message to conversation
        if self.conversation_service:
            await self.conversation_service.add_system_message(
                device_id,
                f"Client message: {msg_type}",
                metadata={"message_type": msg_type, "data": data}
            )
    
    async def _handle_episode_completion(self, device_id: str, data: dict):
        """Handle episode completion with daily limits check"""
        try:
            self.log_info(f"🎯 Episode completion requested for {device_id}")
            
            # Check if user can advance (daily limit check)
            limit_info = await self.user_service.check_episode_limit(device_id)
            
            if not limit_info['can_play_episode']:
                # User has already reached daily limit
                response = {
                    "type": "episode_advance_denied",
                    "reason": "daily_limit_exceeded",
                    "episodes_played_today": limit_info['episodes_played_today'],
                    "daily_limit": limit_info['daily_limit'],
                    "message": "Daily episode limit reached. Episode completed but no advancement.",
                    "session_will_end": True
                }
                
                await self._safe_send_message(self.connections[device_id], device_id, response)
                
                # End conversation session as complete
                await self.conversation_service.end_session(
                    device_id, 
                    "episode_completed_daily_limit_reached", 
                    completed_successfully=True
                )
                
                return
            
            # Advance episode (this will update daily usage)
            try:
                updated_user = await self.user_service.advance_episode(device_id)
                
                response = {
                    "type": "episode_advanced",
                    "old_season": data.get("current_season"),
                    "old_episode": data.get("current_episode"),
                    "new_season": updated_user.season,
                    "new_episode": updated_user.episode,
                    "episodes_played_today": updated_user.episodes_played_today,
                    "remaining_episodes_today": updated_user.remaining_episodes_today,
                    "message": f"Advanced to Season {updated_user.season}, Episode {updated_user.episode}",
                    "session_will_end": True
                }
                
                await self._safe_send_message(self.connections[device_id], device_id, response)
                
                # End conversation session as successfully completed
                await self.conversation_service.end_session(
                    device_id, 
                    "episode_completed_and_advanced", 
                    completed_successfully=True
                )
                
                self.log_info(f"✅ Episode advanced for {device_id}: S{updated_user.season}E{updated_user.episode}")
                
            except ValidationException as e:
                if "daily limit" in str(e).lower():
                    # Daily limit was reached during advancement
                    response = {
                        "type": "episode_advance_denied",
                        "reason": "daily_limit_exceeded", 
                        "message": str(e),
                        "session_will_end": True
                    }
                    
                    await self._safe_send_message(self.connections[device_id], device_id, response)
                else:
                    raise
        
        except Exception as e:
            self.log_error(f"❌ Failed to handle episode completion for {device_id}: {e}")
            
            error_response = {
                "type": "episode_advance_error",
                "error": str(e),
                "session_will_end": True
            }
            
            await self._safe_send_message(self.connections[device_id], device_id, error_response)
    
    async def _handle_episode_advance_request(self, device_id: str):
        """Handle request to check if episode can be advanced"""
        try:
            limit_info = await self.user_service.check_episode_limit(device_id)
            
            response = {
                "type": "episode_advance_status",
                "can_advance": limit_info['can_play_episode'],
                "episodes_played_today": limit_info['episodes_played_today'],
                "remaining_episodes": limit_info['remaining_episodes'],
                "daily_limit": limit_info['daily_limit'],
                "message": "Can advance episode" if limit_info['can_play_episode'] else "Daily episode limit reached"
            }
            
            await self._safe_send_message(self.connections[device_id], device_id, response)
            
        except Exception as e:
            self.log_error(f"❌ Failed to check episode advance status for {device_id}: {e}")
            
            error_response = {
                "type": "episode_advance_error",
                "error": str(e)
            }
            
            await self._safe_send_message(self.connections[device_id], device_id, error_response)
    
    # The rest of the methods remain the same as the previous WebSocket service
    # (keeping the audio buffering, keepalive, cleanup, etc.)
    
    async def _safe_send_message(self, websocket: WebSocket, device_id: str, message: dict) -> bool:
        """Safely send message with connection state checking"""
        try:
            if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                self.log_warning(f"⚠️ WebSocket not connected for {device_id}, cannot send message")
                return False
            
            await websocket.send_text(json.dumps(message))
            self.log_info(f"📤 Sent {message.get('type', 'unknown')} message to {device_id}")
            return True
            
        except Exception as e:
            self.log_warning(f"⚠️ Failed to send message to {device_id}: {e}")
            return False
    
    async def _safe_send_status(self, device_id: str, status_message: str):
        """Safely send status update"""
        if device_id in self.connections:
            status_msg = {
                "type": "status_update",
                "device_id": device_id,
                "message": status_message,
                "timestamp": time.time()
            }
            await self._safe_send_message(self.connections[device_id], device_id, status_msg)
    
    async def _setup_keepalive_loop(self, device_id: str):
        """Ultra-frequent keepalive during setup phase"""
        while device_id in self.connections:
            try:
                await asyncio.sleep(2)
                
                if device_id not in self.connections:
                    break
                
                websocket = self.connections[device_id]
                
                if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                    self.log_warning(f"⚠️ WebSocket disconnected during setup for {device_id}")
                    break
                
                setup_ping = {
                    "type": "setup_ping",
                    "device_id": device_id,
                    "timestamp": time.time(),
                    "message": "Setup in progress..."
                }
                
                if not await self._safe_send_message(websocket, device_id, setup_ping):
                    break
                    
            except asyncio.CancelledError:
                self.log_info(f"🛑 Setup keepalive cancelled for {device_id}")
                break
            except Exception as e:
                self.log_error(f"❌ Setup keepalive error for {device_id}: {e}")
                break
    
    async def _normal_keepalive_loop(self, device_id: str):
        """Normal keepalive after setup is complete"""
        while device_id in self.connections:
            try:
                await asyncio.sleep(self.keepalive_interval)
                
                if device_id not in self.connections:
                    break
                
                websocket = self.connections[device_id]
                if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                    self.log_warning(f"⚠️ WebSocket not connected for {device_id}, stopping keepalive")
                    break
                
                current_time = time.time()
                last_activity = self.last_activity.get(device_id, current_time)
                inactive_duration = current_time - last_activity
                
                ping_message = {
                    "type": "server_ping",
                    "timestamp": current_time,
                    "inactive_duration": inactive_duration,
                    "connection_duration": current_time - self.connection_times.get(device_id, current_time)
                }
                
                if not await self._safe_send_message(websocket, device_id, ping_message):
                    break
                
                if inactive_duration > self.activity_timeout:
                    self.log_warning(f"⚠️ Device {device_id} inactive for {inactive_duration:.1f}s")
                    
                    activity_prompt = {
                        "type": "activity_prompt",
                        "message": "No activity detected. Connection will timeout soon.",
                        "timeout_in": self.connection_timeout - inactive_duration
                    }
                    
                    await self._safe_send_message(websocket, device_id, activity_prompt)
                
                if inactive_duration > self.connection_timeout:
                    self.log_warning(f"🕐 Force disconnecting {device_id} due to timeout")
                    break
                    
            except asyncio.CancelledError:
                self.log_info(f"🛑 Keepalive cancelled for {device_id}")
                break
            except Exception as e:
                self.log_error(f"❌ Keepalive error for {device_id}: {e}")
                break
    
    async def _create_openai_connection_async(self, device_id: str, system_prompt: str):
        """Create OpenAI connection asynchronously"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.openai_service.create_connection(
                    device_id=device_id,
                    system_prompt=system_prompt,
                    audio_callback=self._send_audio_to_esp32
                )
                self.log_info(f"✅ OpenAI connected for {device_id} on attempt {attempt + 1}")
                
                if device_id in self.connections:
                    notification = {
                        "type": "openai_ready",
                        "device_id": device_id,
                        "timestamp": time.time(),
                        "message": "AI assistant is ready!"
                    }
                    await self._safe_send_message(self.connections[device_id], device_id, notification)
                
                return True
                
            except Exception as e:
                self.log_warning(f"⚠️ OpenAI connection attempt {attempt + 1} failed for {device_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
        
        self.log_error(f"❌ Failed to connect to OpenAI after {max_retries} attempts for {device_id}")
        
        if device_id in self.connections:
            error_notification = {
                "type": "openai_error",
                "device_id": device_id,
                "error": "Failed to connect to OpenAI",
                "message": "AI assistant unavailable. You can still use basic features.",
                "timestamp": time.time()
            }
            await self._safe_send_message(self.connections[device_id], device_id, error_notification)
        
        return False
    
    async def _silence_detection_loop(self, device_id: str):
        """Simple silence detection with conversation tracking"""
        last_commit_time = 0
        
        while device_id in self.connections:
            try:
                await asyncio.sleep(0.5)
                
                if device_id not in self.last_audio_time:
                    continue
                
                current_time = time.time()
                silence_duration = current_time - self.last_audio_time[device_id]
                
                if (silence_duration >= self.silence_threshold and 
                    current_time - last_commit_time > 2.0):
                    
                    if current_time - self.last_audio_time[device_id] < 10.0:
                        self.log_info(f"🎯 Committing audio buffer for {device_id} after {silence_duration:.1f}s silence")
                        
                        try:
                            await self.openai_service.commit_audio_buffer(device_id)
                            await self.openai_service.create_response(device_id)
                            last_commit_time = current_time
                            self.log_info(f"✅ Successfully triggered response for {device_id}")
                        except Exception as e:
                            self.log_warning(f"⚠️ Failed to commit audio buffer for {device_id}: {e}")
                
            except Exception as e:
                self.log_error(f"❌ Silence detection error for {device_id}: {e}")
                break
    
    async def _handle_simple_command(self, device_id: str, command: str):
        """Handle simple text commands"""
        self.last_activity[device_id] = time.time()
        
        command = command.strip().lower()
        self.log_info(f"📢 Simple command from {device_id}: '{command}'")
        
        if command in ["ping", "heartbeat"]:
            if device_id in self.connections:
                pong_response = {
                    "type": "pong", 
                    "timestamp": time.time(),
                    "command_received": command
                }
                await self._safe_send_message(self.connections[device_id], device_id, pong_response)
    
    async def _send_audio_to_esp32(self, device_id: str, audio_data: bytes):
        """Send audio response from OpenAI to ESP32 - FIXED to be async"""
        if device_id in self.connections:
            try:
                self.log_info(f"🔊 Forwarding {len(audio_data)} bytes of audio to ESP32 {device_id}")
                await self.connections[device_id].send_bytes(audio_data)
                self.log_info(f"✅ Successfully sent {len(audio_data)} bytes to ESP32 {device_id}")
                self.last_activity[device_id] = time.time()
            except Exception as e:
                self.log_error(f"❌ Failed to send audio to ESP32 {device_id}: {e}")
        else:
            self.log_warning(f"⚠️ No WebSocket connection found for device {device_id}")
    
    async def _safe_cleanup_device(self, device_id: str):
        """Ultra-safe cleanup with conversation and session handling"""
        self.log_info(f"🧹 Starting enhanced cleanup for {device_id}")
        
        # Cancel keepalive task
        if device_id in self.keepalive_tasks:
            try:
                self.keepalive_tasks[device_id].cancel()
                del self.keepalive_tasks[device_id]
                self.log_info(f"🛑 Cancelled keepalive task for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠️ Error canceling keepalive for {device_id}: {e}")
        
        # Cancel timer
        if device_id in self.buffer_timers:
            try:
                self.buffer_timers[device_id].cancel()
                del self.buffer_timers[device_id]
                self.log_info(f"⏰ Cancelled timer for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠️ Error canceling timer for {device_id}: {e}")
        
        # Close OpenAI connection
        try:
            await self.openai_service.close_connection(device_id)
            self.log_info(f"🔌 Closed OpenAI connection for {device_id}")
        except Exception as e:
            self.log_warning(f"⚠️ Error closing OpenAI connection for {device_id}: {e}")
        
        # End conversation session
        try:
            await self.conversation_service.end_session(
                device_id, 
                "websocket_cleanup", 
                completed_successfully=False
            )
            self.log_info(f"💬 Ended conversation session for {device_id}")
        except Exception as e:
            self.log_warning(f"⚠️ Error ending conversation session for {device_id}: {e}")
        
        # Update session time if connection exists
        if device_id in self.connection_times:
            try:
                session_duration = time.time() - self.connection_times[device_id]
                await self.user_service.add_session_time(device_id, session_duration)
                self.log_info(f"⏱️ Updated session time for {device_id}: {session_duration:.1f}s")
                del self.connection_times[device_id]
            except Exception as e:
                self.log_warning(f"⚠️ Error updating session time for {device_id}: {e}")
                try:
                    del self.connection_times[device_id]
                except KeyError:
                    pass
        
        # Clean up all connection data safely
        collections_to_clean = [
            (self.connections, "connections"),
            (self.audio_buffers, "audio_buffers"),
            (self.last_audio_time, "last_audio_time"),
            (self.last_activity, "last_activity")
        ]
        
        for collection, name in collections_to_clean:
            try:
                if device_id in collection:
                    del collection[device_id]
                    self.log_info(f"🗑️ Cleaned up {name} for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠️ Error cleaning up {name} for {device_id}: {e}")
        
        self.log_info(f"✅ Enhanced cleanup completed for {device_id}")
    
    def get_active_connections(self) -> Dict[str, dict]:
        """Get active connection info with conversation details"""
        current_time = time.time()
        connections_info = {}
        
        for device_id in self.connections.keys():
            # Get basic connection info
            connection_info = {
                "device_id": device_id,
                "connected_at": self.connection_times.get(device_id, 0),
                "duration": current_time - self.connection_times.get(device_id, current_time),
                "last_activity": self.last_activity.get(device_id, 0),
                "inactive_duration": current_time - self.last_activity.get(device_id, current_time),
                "has_keepalive": device_id in self.keepalive_tasks,
                "buffer_size": len(self.audio_buffers.get(device_id, [])),
                "openai_connected": device_id in self.openai_service.active_connections
            }
            
            # Add conversation info if available
            try:
                active_session = self.conversation_service.get_active_session(device_id)
                if active_session:
                    connection_info["conversation"] = {
                        "session_id": active_session.session_id,
                        "season": active_session.season,
                        "episode": active_session.episode,
                        "message_count": active_session.message_count,
                        "user_messages": active_session.user_message_count,
                        "ai_messages": active_session.ai_message_count
                    }
            except Exception as e:
                self.log_warning(f"Failed to get conversation info for {device_id}: {e}")
            
            connections_info[device_id] = connection_info
        
        return connections_info
    
    def get_all_connections(self) -> Dict[str, dict]:
        """Get all connection information"""
        return self.get_active_connections()
    
    def get_connection_info(self, device_id: str) -> Optional[Dict[str, any]]:
        """Get specific connection information"""
        connections = self.get_active_connections()
        return connections.get(device_id)
    
    async def disconnect_device(self, device_id: str):
        """Manually disconnect a device"""
        if device_id in self.connections:
            try:
                disconnect_msg = {
                    "type": "server_disconnect",
                    "reason": "Manual disconnect",
                    "timestamp": time.time()
                }
                await self._safe_send_message(self.connections[device_id], device_id, disconnect_msg)
                await asyncio.sleep(0.1)
                
                await self.connections[device_id].close()
                self.log_info(f"🔌 Manually disconnected {device_id}")
            except:
                pass
            await self._safe_cleanup_device(device_id)
    
    async def shutdown(self):
        """Shutdown manager"""
        self.log_info("🛑 Shutting down WebSocket manager")
        
        shutdown_tasks = []
        for device_id in list(self.connections.keys()):
            shutdown_tasks.append(self._graceful_disconnect(device_id))
        
        if shutdown_tasks:
            await asyncio.gather(*shutdown_tasks, return_exceptions=True)
        
        self.log_info("✅ WebSocket manager shutdown complete")
    
    async def _graceful_disconnect(self, device_id: str):
        """Gracefully disconnect a device"""
        try:
            shutdown_msg = {
                "type": "server_shutdown",
                "message": "Server is shutting down",
                "timestamp": time.time()
            }
            await self._safe_send_message(self.connections[device_id], device_id, shutdown_msg)
            await asyncio.sleep(0.1)
            await self.connections[device_id].close()
        except:
            pass
        finally:
            await self._safe_cleanup_device(device_id)


# Global instance
_websocket_manager: Optional[WebSocketConnectionManager] = None

def get_websocket_manager() -> WebSocketConnectionManager:
    """Get WebSocket manager singleton"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketConnectionManager()
    return _websocket_manager