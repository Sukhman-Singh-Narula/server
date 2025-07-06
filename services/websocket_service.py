"""
Enhanced WebSocket service with real-time response generation and audio buffering
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


class AudioBuffer:
    """2MB Audio buffer for storing OpenAI responses"""
    
    def __init__(self, max_size: int = 2 * 1024 * 1024):  # 2MB default
        self.max_size = max_size
        self.buffer = bytearray()
        self.chunks_count = 0
        self.is_complete = False
        self.created_at = time.time()
        self.response_started = False
    
    def add_chunk(self, audio_data: bytes) -> bool:
        """Add audio chunk to buffer. Returns False if buffer would exceed limit."""
        if len(self.buffer) + len(audio_data) > self.max_size:
            return False
        
        self.buffer.extend(audio_data)
        self.chunks_count += 1
        if not self.response_started:
            self.response_started = True
        return True
    
    def get_size(self) -> int:
        """Get current buffer size in bytes"""
        return len(self.buffer)
    
    def clear(self):
        """Clear the buffer"""
        self.buffer.clear()
        self.chunks_count = 0
        self.is_complete = False
        self.response_started = False
    
    def get_chunks(self, chunk_size: int = 4096):
        """Generator to yield buffer data in chunks"""
        for i in range(0, len(self.buffer), chunk_size):
            yield bytes(self.buffer[i:i + chunk_size])


class WebSocketConnectionManager(LoggerMixin):
    """Enhanced WebSocket connection manager with real-time response buffering"""
    
    def __init__(self):
        super().__init__()
        self.firebase_service = get_firebase_service()
        self.openai_service = get_openai_service()
        
        # Active connections: device_id -> WebSocket
        self.connections: Dict[str, WebSocket] = {}
        self.connection_times: Dict[str, float] = {}
        
        # Audio buffering system
        self.audio_buffers: Dict[str, AudioBuffer] = {}
        self.buffer_timers: Dict[str, asyncio.Task] = {}
        
        # Keepalive and activity tracking
        self.keepalive_tasks: Dict[str, asyncio.Task] = {}
        self.last_activity: Dict[str, float] = {}
        self.last_audio_time: Dict[str, float] = {}
        
        # Real-time response tracking
        self.response_generation_started: Dict[str, bool] = {}
        
        # Configuration
        self.keepalive_interval = 10  
        self.connection_timeout = 300  
        self.activity_timeout = 120   
        self.silence_threshold = 1.0  # Still used for triggering initial response
        self.audio_chunk_size = 4096  
    
    async def connect_device(self, websocket: WebSocket, device_id: str, remote_addr: str) -> bool:
        """Handle ESP32 device connection with real-time response buffering"""
        connection_start_time = time.time()
        
        try:
            # Accept WebSocket connection
            await websocket.accept()
            self.log_info(f"✅ WebSocket accepted for {device_id}")
            
            # Store connection and initialize systems
            self.connections[device_id] = websocket
            self.connection_times[device_id] = connection_start_time
            self.last_activity[device_id] = connection_start_time
            self.audio_buffers[device_id] = AudioBuffer()
            self.last_audio_time[device_id] = connection_start_time
            self.response_generation_started[device_id] = False
            
            # Send immediate acknowledgment
            ack_message = {
                "type": "connection_ack",
                "device_id": device_id,
                "timestamp": connection_start_time,
                "status": "initializing",
                "message": "Server ready with real-time response buffering",
                "buffer_size_mb": 2
            }
            
            if not await self._safe_send_message(websocket, device_id, ack_message):
                return False
            
            # Start keepalive
            self.keepalive_tasks[device_id] = asyncio.create_task(
                self._setup_keepalive_loop(device_id)
            )
            
            # Get user and system prompt
            try:
                self.log_info(f"🔍 Fetching user data for {device_id}...")
                await self._safe_send_status(device_id, "Loading user profile...")
                
                user = await self.firebase_service.get_user(device_id)
                system_prompt_obj = await self.firebase_service.get_system_prompt(
                    user.progress.season, user.progress.episode
                )
                
                self.log_info(f"📋 User data loaded for {device_id}: S{user.progress.season}E{user.progress.episode}")
                
            except Exception as e:
                self.log_error(f"❌ Failed to get user data for {device_id}: {e}")
                error_message = {
                    "type": "error",
                    "error": "user_not_found", 
                    "message": f"Failed to retrieve user data: {str(e)}"
                }
                await self._safe_send_message(websocket, device_id, error_message)
                return False
            
            # Send ready message
            ready_message = {
                "type": "ready", 
                "device_id": device_id,
                "season": user.progress.season,
                "episode": user.progress.episode,
                "real_time_response": True,
                "audio_buffering": True,
                "server_time": datetime.now().isoformat()
            }
            
            if not await self._safe_send_message(websocket, device_id, ready_message):
                return False
            
            # Transition to normal keepalive
            if device_id in self.keepalive_tasks:
                self.keepalive_tasks[device_id].cancel()
            
            self.keepalive_tasks[device_id] = asyncio.create_task(
                self._normal_keepalive_loop(device_id)
            )
            
            # Create OpenAI connection with buffering callback
            asyncio.create_task(
                self._create_openai_connection_async(device_id, system_prompt_obj.prompt)
            )
            
            # Start real-time response detection
            asyncio.create_task(self._real_time_response_loop(device_id))
            
            # Handle messages
            await self._handle_messages_with_keepalive(websocket, device_id)
            
        except Exception as e:
            self.log_error(f"❌ Connection error for {device_id}: {e}", exc_info=True)
            return False
        finally:
            await self._safe_cleanup_device(device_id)
            
        return True
    
    async def _buffer_audio_from_openai(self, device_id: str, audio_data: bytes):
        """Buffer audio from OpenAI in real-time (don't send to ESP32 yet)"""
        if device_id not in self.audio_buffers:
            self.log_warning(f"⚠️ No audio buffer found for {device_id}")
            return
        
        buffer = self.audio_buffers[device_id]
        
        if buffer.add_chunk(audio_data):
            self.log_info(f"🎵 Buffered {len(audio_data)} bytes for {device_id} (total: {buffer.get_size()} bytes)")
            
            # Log first audio chunk received
            if buffer.chunks_count == 1:
                self.log_info(f"🎤 First audio response chunk received for {device_id}")
            
            # Check buffer usage
            if buffer.get_size() > (buffer.max_size * 0.9):
                self.log_warning(f"⚠️ Audio buffer nearly full for {device_id}: {buffer.get_size()}/{buffer.max_size} bytes")
        else:
            self.log_error(f"❌ Audio buffer overflow for {device_id}! Size: {buffer.get_size()}, attempted: {len(audio_data)}")
    
    async def _stream_buffered_audio(self, device_id: str):
        """Stream buffered audio to ESP32 when END signal received"""
        self.log_info(f"📤 Received END signal from {device_id}, streaming buffered audio...")
        
        if device_id not in self.audio_buffers or device_id not in self.connections:
            self.log_warning(f"⚠️ Missing buffer or connection for {device_id}")
            return
        
        buffer = self.audio_buffers[device_id]
        websocket = self.connections[device_id]
        
        if buffer.get_size() == 0:
            self.log_info(f"📭 No buffered audio for {device_id}")
            await websocket.send_text("NODATA")
            return
        
        self.log_info(f"🔊 Streaming {buffer.get_size()} bytes of audio to {device_id}")
        
        try:
            # Send audio chunks immediately without delay
            chunk_count = 0
            for chunk in buffer.get_chunks(self.audio_chunk_size):
                await websocket.send_bytes(chunk)
                chunk_count += 1
                
                # Log progress every 100 chunks
                if chunk_count % 100 == 0:
                    self.log_info(f"📤 Streamed chunk {chunk_count} to {device_id}")
            
            # Send EOF signal
            await websocket.send_text("EOF")
            self.log_info(f"🏁 Sent EOF to {device_id} after {chunk_count} chunks")
            
            # Clear buffer for next session
            buffer.clear()
            self.response_generation_started[device_id] = False
            
        except Exception as e:
            self.log_error(f"❌ Error streaming audio to {device_id}: {e}")
    
    async def _real_time_response_loop(self, device_id: str):
        """Monitor for audio input and trigger real-time OpenAI responses"""
        last_response_trigger = 0
        
        while device_id in self.connections:
            try:
                await asyncio.sleep(0.5)
                
                if device_id not in self.last_audio_time:
                    continue
                
                current_time = time.time()
                silence_duration = current_time - self.last_audio_time[device_id]
                
                # Trigger response after silence threshold if we haven't already
                if (silence_duration >= self.silence_threshold and 
                    current_time - last_response_trigger > 3.0 and  # Don't trigger too frequently
                    not self.response_generation_started.get(device_id, False)):
                    
                    # Only trigger if we received recent audio
                    if current_time - self.last_audio_time[device_id] < 10.0:
                        self.log_info(f"🎯 Triggering real-time response for {device_id} after {silence_duration:.1f}s silence")
                        
                        try:
                            await self.openai_service.commit_audio_buffer(device_id)
                            await self.openai_service.create_response(device_id)
                            self.response_generation_started[device_id] = True
                            last_response_trigger = current_time
                            self.log_info(f"✅ Real-time response triggered for {device_id}")
                        except Exception as e:
                            self.log_warning(f"⚠️ Failed to trigger response for {device_id}: {e}")
                
            except Exception as e:
                self.log_error(f"❌ Real-time response loop error for {device_id}: {e}")
                break
    
    async def _handle_messages_with_keepalive(self, websocket: WebSocket, device_id: str):
        """Handle incoming messages with support for END signal"""
        try:
            while device_id in self.connections:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(), 
                        timeout=self.keepalive_interval + 5
                    )
                    
                    # Update activity timestamp
                    self.last_activity[device_id] = time.time()
                    
                    if message["type"] == "websocket.receive":
                        if "bytes" in message:
                            audio_data = message["bytes"]
                            await self._handle_audio_data(device_id, audio_data)
                        
                        elif "text" in message:
                            text_content = message["text"]
                            
                            # Check for END message
                            if text_content.strip().upper() == "END":
                                await self._stream_buffered_audio(device_id)
                            else:
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
                        self.log_info(f"🔌 WebSocket connection closed for {device_id}")
                        break
                    else:
                        self.log_error(f"❌ Message handling error for {device_id}: {e}")
                        break
                    
        except Exception as e:
            self.log_error(f"❌ Message handling error for {device_id}: {e}", exc_info=True)
    
    async def _handle_text_message(self, device_id: str, data: dict):
        """Handle JSON text messages"""
        self.last_activity[device_id] = time.time()
        
        msg_type = data.get("type")
        
        # Handle END message in JSON format
        if msg_type == "end" or msg_type == "audio_end":
            await self._stream_buffered_audio(device_id)
            return
        
        if msg_type in ["ping", "client_ping", "heartbeat"]:
            if device_id in self.connections:
                buffer_status = {}
                if device_id in self.audio_buffers:
                    buffer = self.audio_buffers[device_id]
                    buffer_status = {
                        "buffer_size": buffer.get_size(),
                        "buffer_chunks": buffer.chunks_count,
                        "response_started": buffer.response_started
                    }
                
                pong_response = {
                    "type": "pong", 
                    "timestamp": time.time(),
                    **buffer_status
                }
                await self._safe_send_message(self.connections[device_id], device_id, pong_response)
        
        elif msg_type in ["pong", "client_pong"]:
            self.log_info(f"🏓 Received pong from {device_id}")
    
    async def _handle_simple_command(self, device_id: str, command: str):
        """Handle simple text commands including END"""
        self.last_activity[device_id] = time.time()
        
        command = command.strip().upper()
        
        if command == "END":
            await self._stream_buffered_audio(device_id)
            return
        
        if command in ["PING", "HEARTBEAT"]:
            if device_id in self.connections:
                pong_response = {
                    "type": "pong", 
                    "timestamp": time.time(),
                    "command_received": command
                }
                await self._safe_send_message(self.connections[device_id], device_id, pong_response)
    
    async def _handle_audio_data(self, device_id: str, audio_data: bytes):
        """Handle audio data from ESP32 - forward to OpenAI for real-time processing"""
        # Update activity and audio timestamps
        current_time = time.time()
        self.last_activity[device_id] = current_time
        self.last_audio_time[device_id] = current_time
        
        # Forward audio to OpenAI immediately for real-time processing
        if device_id in self.openai_service.active_connections:
            try:
                await self.openai_service.send_audio(device_id, audio_data)
                # Don't log every chunk to avoid spam
            except Exception as e:
                self.log_warning(f"⚠️ Failed to forward audio to OpenAI for {device_id}: {e}")
    
    async def _create_openai_connection_async(self, device_id: str, system_prompt: str):
        """Create OpenAI connection with buffering callback"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use buffering callback instead of direct send
                await self.openai_service.create_connection(
                    device_id=device_id,
                    system_prompt=system_prompt,
                    audio_callback=self._send_audio_to_esp32
                )
                self.log_info(f"✅ OpenAI connected for {device_id} with real-time buffering")
                
                # Notify client
                if device_id in self.connections:
                    notification = {
                        "type": "openai_ready",
                        "device_id": device_id,
                        "message": "AI ready for real-time conversation with buffering"
                    }
                    await self._safe_send_message(self.connections[device_id], device_id, notification)
                
                return True
                
            except Exception as e:
                self.log_warning(f"⚠️ OpenAI connection attempt {attempt + 1} failed for {device_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
        
        self.log_error(f"❌ Failed to connect to OpenAI after {max_retries} attempts for {device_id}")
        return False
    
    # Utility methods...
    async def _safe_send_message(self, websocket: WebSocket, device_id: str, message: dict) -> bool:
        """Safely send message with connection state checking"""
        try:
            if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                return False
            
            await websocket.send_text(json.dumps(message))
            return True
            
        except Exception as e:
            self.log_warning(f"⚠️ Failed to send message to {device_id}: {e}")
            return False
    
    async def _safe_send_status(self, device_id: str, status_message: str):
        """Safely send status update"""
        if device_id in self.connections:
            status_msg = {
                "type": "status_update",
                "message": status_message,
                "timestamp": time.time()
            }
            await self._safe_send_message(self.connections[device_id], device_id, status_msg)
    
    async def _setup_keepalive_loop(self, device_id: str):
        """Setup phase keepalive"""
        while device_id in self.connections:
            try:
                await asyncio.sleep(2)
                
                if device_id not in self.connections:
                    break
                
                websocket = self.connections[device_id]
                if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                    break
                
                setup_ping = {
                    "type": "setup_ping",
                    "message": "Setup in progress..."
                }
                
                if not await self._safe_send_message(websocket, device_id, setup_ping):
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log_error(f"❌ Setup keepalive error for {device_id}: {e}")
                break
    
    async def _normal_keepalive_loop(self, device_id: str):
        """Normal keepalive with buffer status"""
        while device_id in self.connections:
            try:
                await asyncio.sleep(self.keepalive_interval)
                
                if device_id not in self.connections:
                    break
                
                websocket = self.connections[device_id]
                if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                    break
                
                current_time = time.time()
                
                # Include buffer status in ping
                buffer_status = {}
                if device_id in self.audio_buffers:
                    buffer = self.audio_buffers[device_id]
                    buffer_status = {
                        "buffer_size": buffer.get_size(),
                        "buffer_chunks": buffer.chunks_count,
                        "response_active": self.response_generation_started.get(device_id, False)
                    }
                
                ping_message = {
                    "type": "server_ping",
                    "timestamp": current_time,
                    **buffer_status
                }
                
                if not await self._safe_send_message(websocket, device_id, ping_message):
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log_error(f"❌ Keepalive error for {device_id}: {e}")
                break
    
    async def _safe_cleanup_device(self, device_id: str):
        """Safe cleanup of device resources"""
        self.log_info(f"🧹 Cleaning up {device_id}")
        
        # Cancel tasks
        for task_dict, name in [(self.keepalive_tasks, "keepalive"), (self.buffer_timers, "timers")]:
            if device_id in task_dict:
                try:
                    task_dict[device_id].cancel()
                    del task_dict[device_id]
                except Exception as e:
                    self.log_warning(f"⚠️ Error canceling {name} for {device_id}: {e}")
        
        # Close OpenAI connection
        try:
            await self.openai_service.close_connection(device_id)
        except Exception as e:
            self.log_warning(f"⚠️ Error closing OpenAI for {device_id}: {e}")
        
        # Update session time
        if device_id in self.connection_times:
            try:
                session_duration = time.time() - self.connection_times[device_id]
                await self.firebase_service.increment_user_time(device_id, session_duration)
                del self.connection_times[device_id]
            except Exception as e:
                self.log_warning(f"⚠️ Error updating session time for {device_id}: {e}")
                try:
                    del self.connection_times[device_id]
                except KeyError:
                    pass
        
        # Clean up data structures
        collections = [
            (self.connections, "connections"),
            (self.audio_buffers, "audio_buffers"),
            (self.last_audio_time, "last_audio_time"),
            (self.last_activity, "last_activity"),
            (self.response_generation_started, "response_generation_started")
        ]
        
        for collection, name in collections:
            try:
                if device_id in collection:
                    del collection[device_id]
            except Exception as e:
                self.log_warning(f"⚠️ Error cleaning {name} for {device_id}: {e}")
        
        self.log_info(f"✅ Cleanup completed for {device_id}")
    
    def get_active_connections(self) -> Dict[str, dict]:
        """Get active connection info with real-time buffer status"""
        current_time = time.time()
        return {
            device_id: {
                "device_id": device_id,
                "connected_at": self.connection_times.get(device_id, 0),
                "duration": current_time - self.connection_times.get(device_id, current_time),
                "buffer_size": self.audio_buffers[device_id].get_size() if device_id in self.audio_buffers else 0,
                "buffer_chunks": self.audio_buffers[device_id].chunks_count if device_id in self.audio_buffers else 0,
                "response_active": self.response_generation_started.get(device_id, False),
                "openai_connected": device_id in self.openai_service.active_connections
            }
            for device_id in self.connections.keys()
        }
    
    async def disconnect_device(self, device_id: str):
        """Manually disconnect a device"""
        if device_id in self.connections:
            try:
                await self.connections[device_id].close()
            except:
                pass
            await self._safe_cleanup_device(device_id)
    
    async def shutdown(self):
        """Shutdown manager"""
        self.log_info("🛑 Shutting down WebSocket manager")
        
        tasks = []
        for device_id in list(self.connections.keys()):
            tasks.append(self._safe_cleanup_device(device_id))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_audio_to_esp32(self, device_id: str, audio_data: bytes):
        """Send audio response from OpenAI to ESP32 - FIXED VERSION"""
        if device_id in self.connections:
            try:
                websocket = self.connections[device_id]

                # CRITICAL FIX: Check WebSocket state before sending
                if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                    self.log_warning(f"⚠️ WebSocket not connected for {device_id}, cannot send audio")
                    return

                self.log_info(f"🔊 Sending {len(audio_data)} bytes of audio to ESP32 {device_id}")

                # FIXED: Send as binary data, not text
                await websocket.send_bytes(audio_data)

                self.log_info(f"✅ Successfully sent {len(audio_data)} bytes to ESP32 {device_id}")
                self.last_activity[device_id] = time.time()


# Global instance
_websocket_manager: Optional[WebSocketConnectionManager] = None

def get_websocket_manager() -> WebSocketConnectionManager:
    """Get WebSocket manager singleton"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketConnectionManager()
    return _websocket_manager
