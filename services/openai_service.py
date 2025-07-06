"""
OPTIMIZED: OpenAI Realtime API service with proper server VAD configuration
Tuned for best conversation flow with ESP32 silence detection
"""
import asyncio
import json
import base64
import websockets
import time
from typing import Optional, Callable, Dict
from utils.logger import LoggerMixin


class OpenAIConnection(LoggerMixin):
    """OpenAI Realtime API connection with optimized server VAD"""
    
    def __init__(self, device_id: str, system_prompt: str, api_key: str,
                 audio_callback: Callable[[str, bytes], None]):
        super().__init__()
        self.device_id = device_id
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.audio_callback = audio_callback
        
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.session_configured = False
        self.listen_task: Optional[asyncio.Task] = None
        
        # Response state tracking
        self.is_responding = False
        self.last_response_time = 0
        
    async def connect(self):
        """Connect to OpenAI Realtime API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "OpenAI-Beta": "realtime=v1"
            }
            
            self.websocket = await websockets.connect(
                "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17",
                extra_headers=headers,
                ping_interval=30,
                ping_timeout=10
            )
            
            self.is_connected = True
            self.log_info(f"✅ Connected to OpenAI Realtime API for {self.device_id}")
            
            # Start listening for messages
            self.listen_task = asyncio.create_task(self._listen_loop())
            
        except Exception as e:
            self.log_error(f"❌ Failed to connect to OpenAI for {self.device_id}: {e}")
            raise
    
    async def _listen_loop(self):
        """Listen for messages from OpenAI"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    self.log_error(f"❌ JSON decode error for {self.device_id}: {e}")
                except Exception as e:
                    self.log_error(f"❌ Message handling error for {self.device_id}: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            self.log_info(f"🔌 OpenAI connection closed for {self.device_id}")
            self.is_connected = False
        except Exception as e:
            self.log_error(f"❌ Listen loop error for {self.device_id}: {e}")
            self.is_connected = False
    
    async def _handle_message(self, data: dict):
        """Handle messages from OpenAI"""
        msg_type = data.get('type')
        
        if msg_type == 'session.created':
            self.log_info(f"🎉 Session created for {self.device_id}")
            await self._configure_session()
        
        elif msg_type == 'session.updated':
            self.session_configured = True
            self.log_info(f"✅ Session configured for {self.device_id} with server VAD")
        
        elif msg_type == 'input_audio_buffer.speech_started':
            self.log_info(f"🎤 Speech detected by OpenAI VAD for {self.device_id}")
        
        elif msg_type == 'input_audio_buffer.speech_stopped':
            self.log_info(f"🔇 Speech ended by OpenAI VAD for {self.device_id}")
            # OpenAI VAD will automatically trigger response - no manual intervention needed
        
        elif msg_type == 'response.created':
            self.is_responding = True
            response_id = data.get('response', {}).get('id', 'unknown')
            self.log_info(f"🤖 Response created by OpenAI VAD for {self.device_id}: {response_id}")
        
        elif msg_type == 'response.output_item.added':
            item = data.get('item', {})
            item_type = item.get('type', 'unknown')
            self.log_info(f"📝 Output item added for {self.device_id}: {item_type}")
        
        elif msg_type == 'response.content_part.added':
            part = data.get('part', {})
            part_type = part.get('type', 'unknown')
            self.log_info(f"📄 Content part added for {self.device_id}: {part_type}")
        
        elif msg_type == 'response.audio.delta':
            # Forward audio to ESP32 immediately
            audio_b64 = data.get('delta')
            if audio_b64:
                try:
                    audio_data = base64.b64decode(audio_b64)
                    self.log_info(f"🔊 Received audio delta for {self.device_id}: {len(audio_data)} bytes")
                    
                    # Forward to ESP32
                    if self.audio_callback:
                        await self.audio_callback(self.device_id, audio_data)
                        self.log_info(f"✅ Audio forwarded to ESP32 for {self.device_id}")
                    
                except Exception as e:
                    self.log_error(f"❌ Failed to process audio delta for {self.device_id}: {e}")
            else:
                self.log_warning(f"⚠️ Empty audio delta for {self.device_id}")
        
        elif msg_type == 'response.audio.done':
            self.log_info(f"🎵 Audio response completed for {self.device_id}")
            # Send end-of-audio marker
            if self.audio_callback:
                try:
                    await self.audio_callback(self.device_id, b'')
                    self.log_info(f"🏁 Sent end-of-audio marker to {self.device_id}")
                except Exception as e:
                    self.log_warning(f"⚠️ Failed to send end marker for {self.device_id}: {e}")
        
        elif msg_type == 'response.done':
            self.is_responding = False
            self.last_response_time = time.time()
            response_id = data.get('response', {}).get('id', 'unknown')
            self.log_info(f"✅ Response completed for {self.device_id}: {response_id}")
        
        elif msg_type == 'error':
            error = data.get('error', {})
            error_message = error.get('message', 'Unknown error')
            error_code = error.get('code', 'unknown')
            self.log_error(f"❌ OpenAI error for {self.device_id}: {error_code} - {error_message}")
        
        elif msg_type == 'conversation.item.created':
            item = data.get('item', {})
            self.log_info(f"💬 Conversation item created for {self.device_id}: {item.get('type', 'unknown')}")
        
        elif msg_type == 'conversation.item.input_audio_transcription.completed':
            transcript = data.get('transcript', '')
            self.log_info(f"📝 Transcription for {self.device_id}: {transcript[:100]}...")
        
        else:
            # Log unknown message types for debugging
            self.log_info(f"🤔 Unhandled message type for {self.device_id}: {msg_type}")
    
    async def _configure_session(self):
        """Configure OpenAI session with OPTIMIZED server VAD"""
        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": self.system_prompt,
                "voice": "ballad",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    # ✅ OPTIMIZED SETTINGS for ESP32 + OpenAI VAD combination
                    "threshold": 0.6,               # Higher threshold (less sensitive to noise)
                    "prefix_padding_ms": 300,       # Keep some audio before speech detection
                    "silence_duration_ms": 1200     # Wait 1.2 seconds of silence before responding
                    # This gives ESP32 silence detection time to work without conflicts
                }
            }
        }
        
        await self.websocket.send(json.dumps(config))
        self.log_info(f"📋 Session configured with optimized server VAD for {self.device_id}")
        self.log_info(f"🎯 VAD Settings: threshold=0.6, silence=1200ms, padding=300ms")
    
    async def send_audio(self, audio_data: bytes) -> bool:
        """Send audio data to OpenAI (no manual triggering needed)"""
        if not self.is_connected or not self.session_configured:
            self.log_warning(f"❌ Cannot send audio for {self.device_id}: connected={self.is_connected}, configured={self.session_configured}")
            return False
        
        try:
            # Encode to base64
            audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            
            # Send as input_audio_buffer.append
            message = {
                "type": "input_audio_buffer.append",
                "audio": audio_b64
            }
            
            await self.websocket.send(json.dumps(message))
            self.log_info(f"📤 Sent {len(audio_data)} bytes to OpenAI for {self.device_id}")
            return True
            
        except Exception as e:
            self.log_error(f"❌ Failed to send audio for {self.device_id}: {e}")
            return False
    
    # ✅ REMOVED: commit_audio_buffer() and create_response() methods
    # OpenAI server VAD handles this automatically now!
    
    async def close(self):
        """Close the OpenAI connection"""
        self.is_connected = False
        
        # Cancel listen task
        if self.listen_task and not self.listen_task.done():
            self.listen_task.cancel()
            try:
                await self.listen_task
            except asyncio.CancelledError:
                pass
        
        # Close websocket
        if self.websocket:
            try:
                await self.websocket.close()
                self.log_info(f"🔌 Closed OpenAI connection for {self.device_id}")
            except Exception as e:
                self.log_warning(f"⚠️ Error closing OpenAI websocket for {self.device_id}: {e}")


class OpenAIService(LoggerMixin):
    """OpenAI service managing multiple connections (simplified)"""
    
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key
        self.active_connections: Dict[str, OpenAIConnection] = {}
    
    async def create_connection(self, device_id: str, system_prompt: str,
                              audio_callback: Callable[[str, bytes], None]) -> OpenAIConnection:
        """Create new OpenAI connection"""
        # Close existing connection if it exists
        if device_id in self.active_connections:
            await self.close_connection(device_id)
        
        self.log_info(f"🔗 Creating OpenAI connection for {device_id}")
        
        connection = OpenAIConnection(
            device_id=device_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
            audio_callback=audio_callback
        )
        
        await connection.connect()
        self.active_connections[device_id] = connection
        
        self.log_info(f"✅ OpenAI connection created for {device_id} with server VAD")
        return connection
    
    async def send_audio(self, device_id: str, audio_data: bytes) -> bool:
        """Send audio to OpenAI for a specific device"""
        if device_id not in self.active_connections:
            self.log_warning(f"⚠️ No OpenAI connection for {device_id}")
            return False
        
        return await self.active_connections[device_id].send_audio(audio_data)
    
    # ✅ REMOVED: commit_audio_buffer() and create_response() methods
    # These are no longer needed since OpenAI VAD handles everything automatically
    
    async def close_connection(self, device_id: str):
        """Close connection for a specific device"""
        if device_id in self.active_connections:
            try:
                await self.active_connections[device_id].close()
                del self.active_connections[device_id]
                self.log_info(f"✅ Closed OpenAI connection for {device_id}")
            except Exception as e:
                self.log_error(f"❌ Error closing OpenAI connection for {device_id}: {e}")
                # Still try to remove from active connections
                try:
                    del self.active_connections[device_id]
                except KeyError:
                    pass
    
    async def close_all_connections(self):
        """Close all OpenAI connections"""
        self.log_info("🛑 Closing all OpenAI connections")
        
        # Create a list to avoid dictionary changed during iteration
        device_ids = list(self.active_connections.keys())
        for device_id in device_ids:
            await self.close_connection(device_id)
        
        self.log_info("✅ All OpenAI connections closed")
    
    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.active_connections)
    
    def is_connected(self, device_id: str) -> bool:
        """Check if device has active OpenAI connection"""
        return (device_id in self.active_connections and 
                self.active_connections[device_id].is_connected)


# Global instance
_openai_service: Optional[OpenAIService] = None


def get_openai_service() -> OpenAIService:
    """Get OpenAI service singleton"""
    global _openai_service
    if _openai_service is None:
        from config.settings import get_settings
        settings = get_settings()
        _openai_service = OpenAIService(settings.openai_api_key)
    return _openai_service
