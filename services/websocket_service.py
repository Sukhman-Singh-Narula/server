"""
FIXED WebSocket service - Resolves audio processing errors
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect
import logging

# Import services - with fallback
try:
    from services.firebase_service import get_firebase_service
    from services.openai_service import get_openai_service
    from utils.logger import LoggerMixin
except ImportError:
    # Fallback logger if utils.logger doesn't exist
    class LoggerMixin:
        def _init_(self):
            self.logger = logging.getLogger(self._class.name_)
        
        def log_info(self, message: str):
            self.logger.info(message)
        
        def log_warning(self, message: str):
            self.logger.warning(message)
        
        def log_error(self, message: str, exc_info: bool = False):
            self.logger.error(message, exc_info=exc_info)


class WebSocketConnectionManager(LoggerMixin):
    """FIXED WebSocket connection manager with robust audio handling"""
    
    def _init_(self):
        super()._init_()
        
        # Initialize services with error handling
        try:
            self.firebase_service = get_firebase_service()
            self.openai_service = get_openai_service()
        except Exception as e:
            self.log_error(f"Failed to initialize services: {e}")
            raise
        
        # Active connections
        self.connections: Dict[str, WebSocket] = {}
        self.connection_times: Dict[str, float] = {}
        
        # Enhanced audio buffering with validation
        self.audio_buffers: Dict[str, bytearray] = {}
        self.buffer_timers: Dict[str, asyncio.Task] = {}
        self.last_audio_time: Dict[str, float] = {}
        self.audio_stats: Dict[str, dict] = {}
        
        # Keepalive tracking
        self.keepalive_tasks: Dict[str, asyncio.Task] = {}
        self.last_activity: Dict[str, float] = {}
        
        # Configuration
        self.keepalive_interval = 10
        self.connection_timeout = 300
        self.activity_timeout = 120
        self.silence_threshold = 1.0
        
        # Audio validation parameters
        self.min_audio_chunk_size = 100  # Minimum 100 bytes
        self.max_audio_chunk_size = 50000  # Maximum 50KB
        self.min_audio_samples = 2400  # Minimum 100ms at 24kHz
    
    def _validate_audio_chunk(self, device_id: str, audio_data: bytes) -> bool:
        """FIXED: Validate incoming audio chunk"""
        if not audio_data:
            self.log_warning(f"❌ Empty audio chunk from {device_id}")
            return False
        
        chunk_size = len(audio_data)
        
        # Check size bounds
        if chunk_size < self.min_audio_chunk_size:
            self.log_warning(f"❌ Audio chunk too small from {device_id}: {chunk_size} bytes (min: {self.min_audio_chunk_size})")
            return False
        
        if chunk_size > self.max_audio_chunk_size:
            self.log_warning(f"❌ Audio chunk too large from {device_id}: {chunk_size} bytes (max: {self.max_audio_chunk_size})")
            return False
        
        # Check 16-bit alignment
        if chunk_size % 2 != 0:
            self.log_warning(f"❌ Audio chunk not 16-bit aligned from {device_id}: {chunk_size} bytes")
            return False
        
        return True
    
    def _update_audio_stats(self, device_id: str, audio_data: bytes):
        """Update audio statistics for monitoring"""
        if device_id not in self.audio_stats:
            self.audio_stats[device_id] = {
                'total_chunks': 0,
                'total_bytes': 0,
                'last_chunk_size': 0,
                'avg_chunk_size': 0,
                'session_start': time.time()
            }
        
        stats = self.audio_stats[device_id]
        stats['total_chunks'] += 1
        stats['total_bytes'] += len(audio_data)
        stats['last_chunk_size'] = len(audio_data)
        stats['avg_chunk_size'] = stats['total_bytes'] / stats['total_chunks']
        
        # Log stats every 10 chunks
        if stats['total_chunks'] % 10 == 0:
            duration = time.time() - stats['session_start']
            self.log_info(f"📊 Audio stats for {device_id}: {stats['total_chunks']} chunks, "
                         f"{stats['total_bytes']} bytes, avg={stats['avg_chunk_size']:.1f}B, "
                         f"duration={duration:.1f}s")
    
    async def connect_device(self, websocket: WebSocket, device_id: str, remote_addr: str) -> bool:
        """Handle ESP32 device connection"""
        connection_start_time = time.time()
        
        try:
            await websocket.accept()
            self.log_info(f"✅ WebSocket accepted for {device_id}")
            
            # Store connection
            self.connections[device_id] = websocket
            self.connection_times[device_id] = connection_start_time
            self.last_activity[device_id] = connection_start_time
            self.audio_buffers[device_id] = bytearray()
            self.last_audio_time[device_id] = connection_start_time
            
            # Send acknowledgment
            ack_message = {
                "type": "connection_ack",
                "device_id": device_id,
                "timestamp": connection_start_time,
                "status": "initializing"
            }
            
            if not await self._safe_send_message(websocket, device_id, ack_message):
                return False
            
            # Start keepalive
            self.keepalive_tasks[device_id] = asyncio.create_task(
                self._keepalive_loop(device_id)
            )
            
            # Get user data
            try:
                self.log_info(f"🔍 Fetching user data for {device_id}...")
                
                user = await self.firebase_service.get_user(device_id)
                system_prompt_obj = await self.firebase_service.get_system_prompt(
                    user.progress.season, user.progress.episode
                )
                
                self.log_info(f"📋 Retrieved user data for {device_id}: Season {user.progress.season}, Episode {user.progress.episode}")
                
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
                "server_time": datetime.now().isoformat()
            }
            
            if not await self._safe_send_message(websocket, device_id, ready_message):
                return False
            
            # Create OpenAI connection
            asyncio.create_task(
                self._create_openai_connection_async(device_id, system_prompt_obj.prompt)
            )
            
            # Start silence detection
            asyncio.create_task(self._silence_detection_loop(device_id))
            
            # Handle messages
            await self._handle_messages(websocket, device_id)
            
        except Exception as e:
            self.log_error(f"❌ Connection error for {device_id}: {e}", exc_info=True)
            return False
        finally:
            await self._safe_cleanup_device(device_id)
            
        return True
    
    async def _safe_send_message(self, websocket: WebSocket, device_id: str, message: dict) -> bool:
        """Safely send message"""
        try:
            if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                return False
            
            await websocket.send_text(json.dumps(message))
            return True
            
        except Exception as e:
            self.log_warning(f"⚠ Failed to send message to {device_id}: {e}")
            return False
    
    async def _keepalive_loop(self, device_id: str):
        """Keepalive loop"""
        while device_id in self.connections:
            try:
                await asyncio.sleep(self.keepalive_interval)
                
                if device_id not in self.connections:
                    break
                
                websocket = self.connections[device_id]
                if hasattr(websocket, 'client_state') and websocket.client_state.name != 'CONNECTED':
                    break
                
                current_time = time.time()
                ping_message = {
                    "type": "server_ping",
                    "timestamp": current_time
                }
                
                if not await self._safe_send_message(websocket, device_id, ping_message):
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log_error(f"❌ Keepalive error for {device_id}: {e}")
                break
    
    async def _create_openai_connection_async(self, device_id: str, system_prompt: str):
        """Create OpenAI connection"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.openai_service.create_connection(
                    device_id=device_id,
                    system_prompt=system_prompt,
                    audio_callback=self._send_audio_to_esp32
                )
                self.log_info(f"✅ OpenAI connected for {device_id}")
                
                if device_id in self.connections:
                    notification = {
                        "type": "openai_ready",
                        "device_id": device_id,
                        "timestamp": time.time()
                    }
                    await self._safe_send_message(self.connections[device_id], device_id, notification)
                
                return True
                
            except Exception as e:
                self.log_warning(f"⚠ OpenAI connection attempt {attempt + 1} failed for {device_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
        
        self.log_error(f"❌ Failed to connect to OpenAI for {device_id}")
        return False
    
    async def _handle_messages(self, websocket: WebSocket, device_id: str):
        """Handle incoming messages"""
        try:
            while device_id in self.connections:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(), 
                        timeout=self.keepalive_interval + 5
                    )
                    
                    self.last_activity[device_id] = time.time()
                    
                    if message["type"] == "websocket.receive":
                        if "bytes" in message:
                            audio_data = message["bytes"]
                            await self._handle_audio_data(device_id, audio_data)
                        
                        elif "text" in message:
                            text_content = message["text"]
                            try:
                                text_data = json.loads(text_content)
                                await self._handle_text_message(device_id, text_data)
                            except json.JSONDecodeError:
                                await self._handle_simple_command(device_id, text_content)
                    
                    elif message["type"] == "websocket.disconnect":
                        break
                
                except asyncio.TimeoutError:
                    continue
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    if "1005" in str(e) or "ConnectionClosed" in str(e):
                        break
                    else:
                        self.log_error(f"❌ Message handling error for {device_id}: {e}")
                        break
                    
        except Exception as e:
            self.log_error(f"❌ Message loop error for {device_id}: {e}")
    
    async def _handle_audio_data(self, device_id: str, audio_data: bytes):
        """FIXED: Handle audio data with validation"""
        # Validate the audio chunk
        if not self._validate_audio_chunk(device_id, audio_data):
            return
        
        self.log_info(f"📤 Valid audio chunk from {device_id}: {len(audio_data)} bytes")
        
        # Update timestamps and statistics
        current_time = time.time()
        self.last_activity[device_id] = current_time
        self.last_audio_time[device_id] = current_time
        self._update_audio_stats(device_id, audio_data)
        
        # Forward to OpenAI with error handling
        if device_id in self.openai_service.active_connections:
            try:
                success = await self.openai_service.send_audio(device_id, audio_data)
                if success:
                    self.log_info(f"✅ Forwarded {len(audio_data)} bytes to OpenAI for {device_id}")
                else:
                    self.log_warning(f"⚠ Failed to forward audio to OpenAI for {device_id}")
            except Exception as e:
                self.log_error(f"❌ Error forwarding audio to OpenAI for {device_id}: {e}")
        else:
            self.log_warning(f"⚠ No OpenAI connection for {device_id}, cannot forward audio")
    
    async def _silence_detection_loop(self, device_id: str):
        """Simple silence detection with commit triggering"""
        last_commit_time = 0
        
        while device_id in self.connections:
            try:
                await asyncio.sleep(0.5)
                
                if device_id not in self.last_audio_time:
                    continue
                
                current_time = time.time()
                silence_duration = current_time - self.last_audio_time[device_id]
                
                # Commit audio buffer after silence threshold
                if (silence_duration >= self.silence_threshold and 
                    current_time - last_commit_time > 2.0):
                    
                    # Only commit if we received audio recently
                    if current_time - self.last_audio_time[device_id] < 10.0:
                        self.log_info(f"🎯 Committing audio buffer for {device_id} after {silence_duration:.1f}s silence")
                        
                        try:
                            # Check if we have enough audio
                            if device_id in self.audio_stats:
                                stats = self.audio_stats[device_id]
                                if stats['total_bytes'] >= self.min_audio_samples * 2:  # 2 bytes per 16-bit sample
                                    await self.openai_service.commit_audio_buffer(device_id)
                                    await self.openai_service.create_response(device_id)
                                    last_commit_time = current_time
                                    self.log_info(f"✅ Successfully triggered response for {device_id}")
                                else:
                                    self.log_warning(f"⚠ Not enough audio data for {device_id}: {stats['total_bytes']} bytes")
                            else:
                                self.log_warning(f"⚠ No audio stats available for {device_id}")
                        except Exception as e:
                            self.log_warning(f"⚠ Failed to commit audio buffer for {device_id}: {e}")
                
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
        
        elif msg_type == "audio_commit_request":
            # Manual audio commit request from ESP32
            try:
                await self.openai_service.commit_audio_buffer(device_id)
                await self.openai_service.create_response(device_id)
                self.log_info(f"🎯 Manual audio commit for {device_id}")
            except Exception as e:
                self.log_error(f"❌ Manual commit failed for {device_id}: {e}")
    
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
            self.log_warning(f"⚠ No WebSocket connection found for device {device_id}")
    
    async def _safe_cleanup_device(self, device_id: str):
        """Safe cleanup that prevents KeyError exceptions"""
        self.log_info(f"🧹 Starting safe cleanup for {device_id}")
        
        # Cancel keepalive task
        if device_id in self.keepalive_tasks:
            try:
                self.keepalive_tasks[device_id].cancel()
                del self.keepalive_tasks[device_id]
                self.log_info(f"🛑 Cancelled keepalive task for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠ Error canceling keepalive for {device_id}: {e}")
        
        # Cancel timer
        if device_id in self.buffer_timers:
            try:
                self.buffer_timers[device_id].cancel()
                del self.buffer_timers[device_id]
                self.log_info(f"⏰ Cancelled timer for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠ Error canceling timer for {device_id}: {e}")
        
        # Close OpenAI connection
        try:
            await self.openai_service.close_connection(device_id)
            self.log_info(f"🔌 Closed OpenAI connection for {device_id}")
        except Exception as e:
            self.log_warning(f"⚠ Error closing OpenAI connection for {device_id}: {e}")
        
        # Update session time
        if device_id in self.connection_times:
            try:
                session_duration = time.time() - self.connection_times[device_id]
                await self.firebase_service.increment_user_time(device_id, session_duration)
                self.log_info(f"⏱ Updated session time for {device_id}: {session_duration:.1f}s")
                del self.connection_times[device_id]
            except Exception as e:
                self.log_warning(f"⚠ Error updating session time for {device_id}: {e}")
                try:
                    del self.connection_times[device_id]
                except KeyError:
                    pass
        
        # Clean up all connection data
        collections_to_clean = [
            (self.connections, "connections"),
            (self.audio_buffers, "audio_buffers"),
            (self.last_audio_time, "last_audio_time"),
            (self.last_activity, "last_activity"),
            (self.audio_stats, "audio_stats")
        ]
        
        for collection, name in collections_to_clean:
            try:
                if device_id in collection:
                    del collection[device_id]
                    self.log_info(f"🗑 Cleaned up {name} for {device_id}")
            except Exception as e:
                self.log_warning(f"⚠ Error cleaning up {name} for {device_id}: {e}")
        
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
                "openai_connected": device_id in self.openai_service.active_connections,
                "audio_stats": self.audio_stats.get(device_id, {})
            }
            for device_id in self.connections.keys()
        }
    
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