"""
Ultra-Robust WebSocket service that handles client disconnections during setup
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect

from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from utils.logger import LoggerMixin


class WebSocketConnectionManager(LoggerMixin):
    """Ultra-robust WebSocket connection manager"""
    
    def __init__(self):
        super().__init__()
        self.firebase_service = get_firebase_service()
        self.openai_service = get_openai_service()
        
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
        self.keepalive_interval = 10  # Send ping every 10 seconds (more frequent)
        self.connection_timeout = 300  # 5 minutes total timeout
        self.activity_timeout = 120   # 2 minutes of inactivity before warning
        self.silence_threshold = 1.0  # 1 second of silence before committing buffer
    
    async def connect_device(self, websocket: WebSocket, device_id: str, remote_addr: str) -> bool:
        """Handle ESP32 device connection with ultra-robust error handling"""
        connection_start_time = time.time()
        
        try:
            # Accept WebSocket connection
            await websocket.accept()
            self.log_info(f"✅ WebSocket accepted for {device_id}")
            
            # Store connection IMMEDIATELY to prevent race conditions
            self.connections[device_id] = websocket
            self.connection_times[device_id] = connection_start_time
            self.last_activity[device_id] = connection_start_time
            self.audio_buffers[device_id] = bytearray()
            self.last_audio_time[device_id] = connection_start_time
            
            # Send immediate acknowledgment with keepalive info
            ack_message = {
                "type": "connection_ack",
                "device_id": device_id,
                "timestamp": connection_start_time,
                "status": "initializing",
                "message": "Server is setting up your connection. Please wait...",
                "expected_setup_time": "3-5 seconds"
            }
            
            # Check connection before sending
            if not await self._safe_send_message(websocket, device_id, ack_message):
                return False
            
            # Start ultra-frequent keepalive during setup
            self.keepalive_tasks[device_id] = asyncio.create_task(
                self._setup_keepalive_loop(device_id)
            )
            
            # Send periodic status updates during Firebase operations
            status_task = asyncio.create_task(
                self._send_setup_status_updates(device_id)
            )
            
            try:
                # Get user and system prompt with status updates
                self.log_info(f"🔍 Fetching user data for {device_id}...")
                await self._safe_send_status(device_id, "Fetching user profile...")
                
                user = await self.firebase_service.get_user(device_id)
                
                await self._safe_send_status(device_id, f"Loading Season {user.progress.season}, Episode {user.progress.episode}...")
                
                system_prompt_obj = await self.firebase_service.get_system_prompt(
                    user.progress.season, user.progress.episode
                )
                
                self.log_info(f"📋 Retrieved user data for {device_id}: Season {user.progress.season}, Episode {user.progress.episode}")
                
            except Exception as e:
                self.log_error(f"❌ Failed to get user data for {device_id}: {e}")
                error_message = {
                    "type": "error",
                    "error": "user_not_found",
                    "message": f"Failed to retrieve user data: {str(e)}",
                    "device_id": device_id
                }
                await self._safe_send_message(websocket, device_id, error_message)
                status_task.cancel()
                return False
            
            # Cancel status update task
            status_task.cancel()
            
            # Send ready message
            ready_message = {
                "type": "ready", 
                "device_id": device_id,
                "season": user.progress.season,
                "episode": user.progress.episode,
                "openai_connecting": True,
                "keepalive_interval": self.keepalive_interval,
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
            
            # Handle messages with improved error handling
            await self._handle_messages_with_keepalive(websocket, device_id)
            
        except Exception as e:
            self.log_error(f"❌ Connection error for {device_id}: {e}", exc_info=True)
            return False
        finally:
            await self._safe_cleanup_device(device_id)
            
        return True
    
    async def _safe_send_message(self, websocket: WebSocket, device_id: str, message: dict) -> bool:
        """Safely send message with connection state checking"""
        try:
            # Check if WebSocket is still connected
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
                await asyncio.sleep(2)  # Very frequent during setup
                
                if device_id not in self.connections:
                    break
                
                websocket = self.connections[device_id]
                
                # Check connection state
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
    
    async def _send_setup_status_updates(self, device_id: str):
        """Send periodic status updates during setup"""
        status_messages = [
            "Connecting to database...",
            "Verifying user credentials...",
            "Loading learning progress...",
            "Preparing AI assistant...",
            "Almost ready..."
        ]
        
        for i, message in enumerate(status_messages):
            try:
                await asyncio.sleep(0.5)  # Wait between status updates
                await self._safe_send_status(device_id, message)
                
                if device_id not in self.connections:
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log_warning(f"⚠️ Status update error for {device_id}: {e}")
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
                
                # Check for prolonged inactivity
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
                
                # Notify client that OpenAI is ready
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
        
        # Notify client of OpenAI connection failure
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
    
    async def _handle_messages_with_keepalive(self, websocket: WebSocket, device_id: str):
        """Handle incoming messages with robust error handling"""
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
    
    async def _handle_audio_data(self, device_id: str, audio_data: bytes):
        """Handle audio data"""
        self.log_info(f"📤 Audio chunk from {device_id}: {len(audio_data)} bytes")
        
        # Update activity and audio timestamps
        current_time = time.time()
        self.last_activity[device_id] = current_time
        self.last_audio_time[device_id] = current_time
        
        # Simple audio forwarding to OpenAI
        if device_id in self.openai_service.active_connections:
            try:
                await self.openai_service.send_audio(device_id, audio_data)
                self.log_info(f"✅ Forwarded audio to OpenAI for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠️ Failed to forward audio to OpenAI for {device_id}: {e}")
    
    async def _silence_detection_loop(self, device_id: str):
        """Simple silence detection"""
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
    
    async def _handle_text_message(self, device_id: str, data: dict):
        """Handle JSON text messages"""
        self.last_activity[device_id] = time.time()
        
        msg_type = data.get("type")
        self.log_info(f"📝 Text message from {device_id}: {msg_type}")
        
        if msg_type in ["ping", "client_ping", "heartbeat"]:
            if device_id in self.connections:
                pong_response = {
                    "type": "pong", 
                    "timestamp": time.time(),
                    "server_time": datetime.now().isoformat()
                }
                await self._safe_send_message(self.connections[device_id], device_id, pong_response)
        
        elif msg_type in ["pong", "client_pong"]:
            self.log_info(f"🏓 Received pong from {device_id}")
        
        # Add more message type handling as needed
    
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
        """Send audio response from OpenAI to ESP32"""
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
        """Ultra-safe cleanup that prevents KeyError exceptions"""
        self.log_info(f"🧹 Starting safe cleanup for {device_id}")
        
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
        
        # Update session time if connection exists
        if device_id in self.connection_times:
            try:
                session_duration = time.time() - self.connection_times[device_id]
                await self.firebase_service.increment_user_time(device_id, session_duration)
                self.log_info(f"⏱️ Updated session time for {device_id}: {session_duration:.1f}s")
                del self.connection_times[device_id]
            except Exception as e:
                self.log_warning(f"⚠️ Error updating session time for {device_id}: {e}")
                # Still try to delete the key
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
        
        self.log_info(f"✅ Safe cleanup completed for {device_id}")
    
    def get_active_connections(self) -> Dict[str, dict]:
        """Get active connection info"""
        current_time = time.time()
        return {
            device_id: {
                "device_id": device_id,
                "connected_at": self.connection_times.get(device_id, 0),
                "duration": current_time - self.connection_times.get(device_id, current_time),
                "last_activity": self.last_activity.get(device_id, 0),
                "inactive_duration": current_time - self.last_activity.get(device_id, current_time),
                "has_keepalive": device_id in self.keepalive_tasks,
                "buffer_size": len(self.audio_buffers.get(device_id, [])),
                "openai_connected": device_id in self.openai_service.active_connections
            }
            for device_id in self.connections.keys()
        }
    
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