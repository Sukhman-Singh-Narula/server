
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Optional, Callable
from fastapi import WebSocket, WebSocketDisconnect

from config.settings import get_settings
from models.websocket import ConnectionData, ConnectionStatus, SessionStats, DisconnectionReason
from models.user import User
from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from utils.exceptions import (
    WebSocketConnectionException, UserNotFoundException, 
    SystemPromptNotFoundException, SessionTimeoutException
)
from utils.logger import LoggerMixin, log_websocket_connection, log_websocket_disconnection
from utils.validators import AudioValidator


class WebSocketConnectionManager(LoggerMixin):
    """Manager for ESP32 WebSocket connections"""
    
    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.firebase_service = get_firebase_service()
        self.openai_service = get_openai_service()
        
        # Active connections: device_id -> ConnectionData
        self.connections: Dict[str, ConnectionData] = {}
        
        # Session statistics: device_id -> SessionStats
        self.session_stats: Dict[str, SessionStats] = {}
        
        # WebSocket connections: device_id -> WebSocket
        self.websockets: Dict[str, WebSocket] = {}
        
        # Cleanup task (will be started when event loop is available)
        self.cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_started = False
    
    async def _ensure_cleanup_task_started(self):
        """Start cleanup task if not already started"""
        if not self._cleanup_started:
            try:
                self.cleanup_task = asyncio.create_task(self._cleanup_expired_sessions())
                self._cleanup_started = True
                self.log_info("Cleanup task started")
            except Exception as e:
                self.log_error(f"Failed to start cleanup task: {e}")
    
    async def connect_device(self, websocket: WebSocket, device_id: str, 
                           remote_addr: str) -> bool:
        """
        Handle new ESP32 device connection
        
        Args:
            websocket: FastAPI WebSocket connection
            device_id: Unique device identifier
            remote_addr: Client IP address
            
        Returns:
            bool: True if connection successful
        """
        try:
            # Accept WebSocket connection first
            await websocket.accept()
            self.log_info(f"WebSocket accepted for device {device_id}")
            
            # Ensure cleanup task is running
            await self._ensure_cleanup_task_started()
            
            # Check for existing connection
            if device_id in self.connections:
                await self._close_existing_connection(device_id, "duplicate_connection")
            
            # Get user data
            user = await self.firebase_service.get_user(device_id)
            if not user:
                await websocket.close(code=4001, reason="User not registered")
                return False
            
            # Get system prompt for current episode
            system_prompt_obj = await self.firebase_service.get_system_prompt(
                user.progress.season, user.progress.episode
            )
            if not system_prompt_obj:
                await websocket.close(code=4002, reason="System prompt not found")
                return False
            
            # Create connection data
            session_id = f"{device_id}_{int(time.time())}"
            connection_data = ConnectionData(
                device_id=device_id,
                status=ConnectionStatus.CONNECTED,
                session_id=session_id,
                user_data=self.firebase_service._user_to_dict(user),
                system_prompt=system_prompt_obj.prompt
            )
            
            # Store connection and websocket
            self.connections[device_id] = connection_data
            self.session_stats[device_id] = SessionStats()
            self.websockets[device_id] = websocket
            
            # Log connection
            log_websocket_connection(device_id, remote_addr)
            self.log_info(f"Device connected: {device_id} - Season {user.progress.season}, Episode {user.progress.episode}")
            
            # Create OpenAI connection with proper callbacks
            await self._create_openai_connection(device_id, system_prompt_obj.prompt)
            
            # Handle the WebSocket session - this will block until disconnection
            await self._handle_device_session(websocket, device_id)
            
            return True
            
        except UserNotFoundException:
            await websocket.close(code=4001, reason="User not registered")
            return False
        except SystemPromptNotFoundException:
            await websocket.close(code=4002, reason="System prompt not found")
            return False
        except Exception as e:
            self.log_error(f"Failed to connect device {device_id}: {e}", exc_info=True)
            try:
                await websocket.close(code=4003, reason="Connection failed")
            except:
                pass
            return False
    
    async def _handle_device_session(self, websocket: WebSocket, device_id: str):
        """Handle the entire WebSocket session for a device"""
        connection_data = self.connections.get(device_id)
        if not connection_data:
            return
        
        try:
            # Send initial connection success message to ESP32
            welcome_message = {
                "type": "connection_established",
                "device_id": device_id,
                "session_id": connection_data.session_id,
                "season": connection_data.user_data.get("progress", {}).get("season", 1),
                "episode": connection_data.user_data.get("progress", {}).get("episode", 1),
                "status": "ready_for_audio"
            }
            await websocket.send_text(json.dumps(welcome_message))
            self.log_info(f"Sent welcome message to {device_id}")
            
            # Main message handling loop
            await self._handle_device_messages(websocket, device_id)
            
        except WebSocketDisconnect:
            self.log_info(f"WebSocket client disconnected: {device_id}")
        except Exception as e:
            self.log_error(f"Error in device session for {device_id}: {e}")
        finally:
            # Ensure cleanup happens
            await self.disconnect_device(device_id, DisconnectionReason.CLIENT_DISCONNECT)
    
    async def _create_openai_connection(self, device_id: str, system_prompt: str):
        """Create OpenAI connection for device"""
        try:
            await self.openai_service.create_connection(
                device_id=device_id,
                system_prompt=system_prompt,
                audio_callback=self._handle_openai_audio,
                completion_callback=self._handle_conversation_completion
            )
            
            # Update connection status
            if device_id in self.connections:
                self.connections[device_id].status = ConnectionStatus.CONNECTED
                
        except Exception as e:
            self.log_error(f"Failed to create OpenAI connection for {device_id}: {e}")
            # Continue without OpenAI connection - this will cause issues but won't crash
    
    async def _handle_device_messages(self, websocket: WebSocket, device_id: str):
        """Handle incoming messages from ESP32 device"""
        connection_data = self.connections.get(device_id)
        if not connection_data:
            return
        
        try:
            # Send initial connection success message to ESP32
            welcome_message = {
                "type": "connection_established",
                "device_id": device_id,
                "session_id": connection_data.session_id,
                "season": connection_data.user_data.get("progress", {}).get("season", 1),
                "episode": connection_data.user_data.get("progress", {}).get("episode", 1),
                "status": "ready_for_audio",
                "audio_config": {
                    "sample_rate": 16000,
                    "format": "pcm16",
                    "channels": 1,
                    "chunk_size_ms": 100
                }
            }
            await websocket.send_text(json.dumps(welcome_message))
            
            # Track audio streaming state
            audio_stream_active = False
            audio_buffer_size = 0
            last_audio_time = time.time()
            last_response_time = time.time()
            
            # Start a background task to periodically trigger responses
            async def periodic_response_trigger():
                nonlocal audio_buffer_size, last_response_time, last_audio_time
                while device_id in self.connections:
                    try:
                        await asyncio.sleep(2)  # Check every 2 seconds
                        current_time = time.time()
                        
                        # If we have audio data and haven't triggered a response recently
                        if (audio_buffer_size > 8000 and 
                            current_time - last_response_time > 5 and
                            current_time - last_audio_time > 1):
                            
                            self.log_info(f"Periodic response trigger for {device_id} (buffer: {audio_buffer_size} bytes)")
                            openai_conn = self.openai_service.get_connection(device_id)
                            if openai_conn:
                                await openai_conn.commit_audio()
                                await openai_conn.create_response()
                                audio_buffer_size = 0
                                last_response_time = current_time
                    except Exception as e:
                        self.log_error(f"Error in periodic trigger for {device_id}: {e}")
                        break
            
            # Start the periodic trigger task
            trigger_task = asyncio.create_task(periodic_response_trigger())
            
            while True:
                try:
                    # Receive data from ESP32 - could be text or binary
                    message = await websocket.receive()
                    
                    if message["type"] == "websocket.receive":
                        if "bytes" in message:
                            # Handle raw PCM16 audio data from ESP32
                            audio_data = message["bytes"]
                            await self._handle_pcm_audio_data(device_id, audio_data, connection_data)
                            
                            # Track audio streaming for VAD simulation
                            audio_stream_active = True
                            audio_buffer_size += len(audio_data)
                            last_audio_time = time.time()
                            
                            # If VAD is disabled, we need to manually trigger responses
                            # after we've received enough audio or after silence
                            current_time = time.time()
                            if not self.settings.vad_enabled:
                                # Check if we should trigger a response (after silence or buffer size)
                                if (current_time - last_audio_time > 2.0 and audio_buffer_size > 16000) or audio_buffer_size > 64000:
                                    self.log_info(f"Triggering manual response for {device_id} (buffer: {audio_buffer_size} bytes)")
                                    await self.openai_service.get_connection(device_id).commit_audio()
                                    await self.openai_service.get_connection(device_id).create_response()
                                    audio_buffer_size = 0
                        
                        elif "text" in message:
                            # Handle text messages (commands, etc.)
                            text_message = message["text"]
                            
                            # Check if this might be binary data incorrectly received as text
                            if len(text_message) > 100 and all(ord(c) < 256 for c in text_message):
                                # This might be binary audio data received as text
                                try:
                                    # Convert text back to bytes if it's actually audio data
                                    audio_data = text_message.encode('latin1')
                                    self.log_info(f"Received binary audio as text from {device_id}, converting: {len(audio_data)} bytes")
                                    await self._handle_pcm_audio_data(device_id, audio_data, connection_data)
                                    
                                    # Track audio streaming for VAD simulation
                                    audio_stream_active = True
                                    audio_buffer_size += len(audio_data)
                                    last_audio_time = time.time()
                                    
                                    # Check if we should trigger a response
                                    current_time = time.time()
                                    if not self.settings.vad_enabled:
                                        if (current_time - last_audio_time > 1.5 and audio_buffer_size > 8000) or audio_buffer_size > 32000:
                                            self.log_info(f"Triggering manual response for {device_id} (buffer: {audio_buffer_size} bytes)")
                                            openai_conn = self.openai_service.get_connection(device_id)
                                            if openai_conn:
                                                await openai_conn.commit_audio()
                                                await openai_conn.create_response()
                                            audio_buffer_size = 0
                                    continue
                                except Exception as e:
                                    self.log_error(f"Failed to process potential audio data: {e}")
                            
                            try:
                                # Try to parse as JSON first
                                text_data = json.loads(text_message)
                                await self._handle_text_message(device_id, text_data)
                            except json.JSONDecodeError:
                                # Not JSON, handle as simple command
                                await self._handle_simple_command(device_id, text_message)
                    
                    elif message["type"] == "websocket.disconnect":
                        self.log_info(f"WebSocket client disconnected: {device_id}")
                        break
                
                except WebSocketDisconnect:
                    self.log_info(f"WebSocket client disconnected: {device_id}")
                    break
                except Exception as e:
                    self.log_error(f"Error receiving data from {device_id}: {e}")
                    break
                    
        except Exception as e:
            self.log_error(f"Error handling messages for {device_id}: {e}")
        finally:
            await self.disconnect_device(device_id, DisconnectionReason.CLIENT_DISCONNECT)
    
    async def _handle_pcm_audio_data(self, device_id: str, audio_data: bytes, connection_data: ConnectionData):
        """Handle raw PCM16 audio data from ESP32"""
        try:
            # Update activity and stats
            connection_data.update_activity()
            self.session_stats[device_id].add_sent_data(len(audio_data))
            
            # Validate audio data
            is_valid, error = AudioValidator.validate_audio_data(audio_data)
            if not is_valid:
                self.log_warning(f"Invalid audio data from {device_id}: {error}")
                return
            
            # Log audio reception
            self.log_info(f"Received PCM16 audio from {device_id}: {len(audio_data)} bytes")
            
            # Forward raw PCM16 data directly to OpenAI (it expects PCM16)
            success = await self.openai_service.send_audio(device_id, audio_data)
            if not success:
                self.log_warning(f"Failed to send audio to OpenAI for {device_id}")
            else:
                self.log_info(f"Forwarded audio to OpenAI for {device_id}: {len(audio_data)} bytes")
                
        except Exception as e:
            self.log_error(f"Error handling PCM audio from {device_id}: {e}")
    
    async def _handle_simple_command(self, device_id: str, command: str):
        """Handle simple text commands from ESP32"""
        command = command.strip().lower()
        
        if command == "start_conversation":
            # ESP32 is ready to start conversation
            response = {
                "type": "conversation_started",
                "status": "ready",
                "message": "You can start speaking now"
            }
            if device_id in self.websockets:
                await self.websockets[device_id].send_text(json.dumps(response))
            self.log_info(f"Conversation started for {device_id}")
        
        elif command == "stop_conversation":
            # ESP32 wants to stop conversation
            response = {
                "type": "conversation_stopped",
                "status": "stopped"
            }
            if device_id in self.websockets:
                await self.websockets[device_id].send_text(json.dumps(response))
            self.log_info(f"Conversation stopped for {device_id}")
        
        elif command in ["ping", "heartbeat"]:
            # Simple ping/heartbeat
            pong_response = {
                "type": "pong",
                "timestamp": time.time()
            }
            if device_id in self.websockets:
                await self.websockets[device_id].send_text(json.dumps(pong_response))
        
        else:
            self.log_info(f"Unknown simple command from {device_id}: {command}")
    
    async def _handle_text_message(self, device_id: str, message_data: dict):
        """Handle JSON text messages from ESP32"""
        message_type = message_data.get("type")
        
        if message_type == "ping":
            # Respond to ping with pong
            pong_message = {
                "type": "pong",
                "timestamp": message_data.get("timestamp", time.time())
            }
            if device_id in self.websockets:
                await self.websockets[device_id].send_text(json.dumps(pong_message))
        
        elif message_type == "status_request":
            # Send current status
            connection_data = self.connections.get(device_id)
            if connection_data:
                status_message = {
                    "type": "status_response",
                    "device_id": device_id,
                    "session_duration": connection_data.connection_duration,
                    "openai_connected": device_id in self.openai_service.active_connections,
                    "current_season": connection_data.user_data.get("progress", {}).get("season", 1),
                    "current_episode": connection_data.user_data.get("progress", {}).get("episode", 1)
                }
                await self.websockets[device_id].send_text(json.dumps(status_message))
        
        elif message_type == "trigger_response":
            # Manual trigger for OpenAI response (when VAD is disabled)
            openai_connection = self.openai_service.get_connection(device_id)
            if openai_connection:
                await openai_connection.commit_audio()
                await openai_connection.create_response()
                self.log_info(f"Manual response triggered for {device_id}")
            
            response = {
                "type": "response_triggered",
                "status": "processing"
            }
            if device_id in self.websockets:
                await self.websockets[device_id].send_text(json.dumps(response))
        
        elif message_type == "start_conversation":
            # ESP32 is starting a conversation session
            response = {
                "type": "conversation_ready",
                "status": "listening",
                "openai_ready": device_id in self.openai_service.active_connections,
                "vad_enabled": self.settings.vad_enabled,
                "manual_trigger_required": not self.settings.vad_enabled
            }
            if device_id in self.websockets:
                await self.websockets[device_id].send_text(json.dumps(response))
            self.log_info(f"Conversation session started for {device_id}")
        
        elif message_type == "end_conversation":
            # ESP32 wants to end the conversation
            response = {
                "type": "conversation_ended",
                "status": "completed"
            }
            if device_id in self.websockets:
                await self.websockets[device_id].send_text(json.dumps(response))
            self.log_info(f"Conversation ended for {device_id}")
        
        elif message_type == "heartbeat":
            # Heartbeat from ESP32
            response = {
                "type": "heartbeat_ack",
                "timestamp": time.time()
            }
            if device_id in self.websockets:
                await self.websockets[device_id].send_text(json.dumps(response))
            self.log_info(f"Heartbeat received from {device_id}")
        
        elif message_type == "audio_start":
            # ESP32 is about to send audio
            self.log_info(f"Audio stream starting for {device_id}")
            
        elif message_type == "audio_end":
            # ESP32 finished sending audio chunk
            self.log_info(f"Audio stream ended for {device_id}")
            
            # If VAD is disabled, trigger response after audio ends
            if not self.settings.vad_enabled:
                openai_connection = self.openai_service.get_connection(device_id)
                if openai_connection:
                    await openai_connection.commit_audio()
                    await openai_connection.create_response()
                    self.log_info(f"Auto-triggered response after audio end for {device_id}")
        
        elif message_type == "audio":
            # ESP32 sent audio metadata (but actual audio should be binary)
            audio_info = message_data.get("info", {})
            self.log_info(f"Audio metadata from {device_id}: {audio_info}")
        
        else:
            self.log_info(f"Unknown message type from {device_id}: {message_type}")
    
    async def _handle_openai_audio(self, device_id: str, audio_data: bytes):
        """Handle audio response from OpenAI and send raw PCM16 to ESP32"""
        if device_id not in self.websockets:
            self.log_warning(f"No WebSocket connection for device {device_id}")
            return
        
        try:
            # Update stats
            if device_id in self.session_stats:
                self.session_stats[device_id].add_received_data(len(audio_data))
            
            # OpenAI sends PCM16 format, send it directly to ESP32
            websocket = self.websockets[device_id]
            await websocket.send_bytes(audio_data)
            
            self.log_info(f"Sent PCM16 audio to ESP32 {device_id}: {len(audio_data)} bytes")
            
        except Exception as e:
            self.log_error(f"Error sending OpenAI audio to {device_id}: {e}")
    
    async def _handle_conversation_completion(self, device_id: str):
        """Handle conversation completion from OpenAI"""
        connection_data = self.connections.get(device_id)
        if not connection_data:
            return
        
        try:
            # Get current user data
            user = await self.firebase_service.get_user(device_id)
            
            # Advance episode
            old_progress = user.progress.dict()
            advanced_to_new_season = user.progress.advance_episode(
                self.settings.episodes_per_season
            )
            
            # Update user progress in Firebase
            await self.firebase_service.update_user_progress(device_id, user.progress)
            
            # Log progress update
            from utils.logger import log_user_progress
            log_user_progress(device_id, old_progress, user.progress.dict())
            
            self.log_info(f"Episode completed for {device_id} - Advanced to Season {user.progress.season}, Episode {user.progress.episode}")
            
            # Send completion notification to ESP32
            if device_id in self.websockets:
                completion_message = {
                    "type": "episode_complete",
                    "new_season": user.progress.season,
                    "new_episode": user.progress.episode,
                    "total_completed": user.progress.episodes_completed
                }
                try:
                    await self.websockets[device_id].send_text(json.dumps(completion_message))
                except:
                    pass  # Don't fail if we can't send notification
            
            # Close connections after a short delay to allow ESP32 to process
            asyncio.create_task(self._delayed_disconnect(device_id, 5.0))
            
        except Exception as e:
            self.log_error(f"Error handling conversation completion for {device_id}: {e}")
    
    async def _delayed_disconnect(self, device_id: str, delay: float):
        """Disconnect device after a delay"""
        await asyncio.sleep(delay)
        await self.disconnect_device(device_id, DisconnectionReason.SESSION_COMPLETE)
    
    async def disconnect_device(self, device_id: str, reason: DisconnectionReason):
        """
        Disconnect device and cleanup resources
        
        Args:
            device_id: Unique device identifier
            reason: Reason for disconnection
        """
        if device_id not in self.connections:
            return
        
        connection_data = self.connections[device_id]
        session_duration = connection_data.connection_duration
        
        try:
            # Update session time in Firebase
            await self.firebase_service.increment_user_time(device_id, session_duration)
            
            # Close OpenAI connection
            await self.openai_service.close_connection(device_id)
            
            # Close WebSocket connection
            if device_id in self.websockets:
                websocket = self.websockets[device_id]
                try:
                    await websocket.close(code=1000, reason=f"Session ended: {reason.value}")
                except:
                    pass  # Connection might already be closed
                del self.websockets[device_id]
            
            # Clean up connections
            del self.connections[device_id]
            
            # Get final stats
            final_stats = self.session_stats.pop(device_id, SessionStats())
            
            # Log disconnection
            log_websocket_disconnection(device_id, session_duration, reason.value)
            self.log_info(f"Device disconnected: {device_id} - Duration: {session_duration:.2f}s, Reason: {reason.value}")
            
        except Exception as e:
            self.log_error(f"Error during disconnect for {device_id}: {e}")
    
    async def _close_existing_connection(self, device_id: str, reason: str):
        """Close existing connection for device"""
        if device_id in self.connections:
            self.log_info(f"Closing existing connection for {device_id}: {reason}")
            await self.disconnect_device(device_id, DisconnectionReason.CLIENT_DISCONNECT)
    
    async def _cleanup_expired_sessions(self):
        """Periodically cleanup expired sessions"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                current_time = time.time()
                timeout_seconds = self.settings.session_timeout_minutes * 60
                
                expired_devices = []
                for device_id, connection_data in self.connections.items():
                    if (current_time - connection_data.last_activity.timestamp()) > timeout_seconds:
                        expired_devices.append(device_id)
                
                for device_id in expired_devices:
                    self.log_info(f"Session timeout for device {device_id}")
                    await self.disconnect_device(device_id, DisconnectionReason.TIMEOUT)
                    
            except Exception as e:
                self.log_error(f"Error in cleanup task: {e}")
    
    def get_session_duration(self, device_id: str) -> float:
        """Get current session duration for device"""
        if device_id in self.connections:
            return self.connections[device_id].connection_duration
        return 0.0
    
    def get_connection_info(self, device_id: str) -> Optional[Dict]:
        """Get connection information for device"""
        if device_id not in self.connections:
            return None
        
        connection_data = self.connections[device_id]
        stats = self.session_stats.get(device_id, SessionStats())
        
        return {
            "device_id": device_id,
            "status": connection_data.status.value,
            "session_id": connection_data.session_id,
            "connected_at": connection_data.connected_at.isoformat(),
            "last_activity": connection_data.last_activity.isoformat(),
            "session_duration": connection_data.connection_duration,
            "current_season": connection_data.user_data.get("progress", {}).get("season"),
            "current_episode": connection_data.user_data.get("progress", {}).get("episode"),
            "bytes_sent": stats.bytes_sent,
            "bytes_received": stats.bytes_received,
            "messages_sent": stats.messages_sent,
            "messages_received": stats.messages_received
        }
    
    def get_all_connections(self) -> Dict[str, Dict]:
        """Get information for all active connections"""
        return {
            device_id: self.get_connection_info(device_id)
            for device_id in self.connections.keys()
        }
    
    async def shutdown(self):
        """Shutdown connection manager and cleanup resources"""
        self.log_info("Shutting down WebSocket connection manager")
        
        # Cancel cleanup task
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect all devices
        for device_id in list(self.connections.keys()):
            await self.disconnect_device(device_id, DisconnectionReason.SERVER_SHUTDOWN)
        
        # Close all OpenAI connections
        await self.openai_service.close_all_connections()


# Global WebSocket manager instance
_websocket_manager: Optional[WebSocketConnectionManager] = None


def get_websocket_manager() -> WebSocketConnectionManager:
    """Get WebSocket manager singleton"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketConnectionManager()
    return _websocket_manager