"""
Streamlined OpenAI Realtime API service
"""
import asyncio
import json
import base64
import websockets
from typing import Optional, Callable
from utils.logger import LoggerMixin


class OpenAIConnection(LoggerMixin):
    """Simplified OpenAI Realtime API connection"""
    
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
        
    async def connect(self):
        """Connect to OpenAI Realtime API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "OpenAI-Beta": "realtime=v1"
            }
            
            # Connect to OpenAI
            self.websocket = await websockets.connect(
                "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17",
                extra_headers=headers,
                ping_interval=30
            )
            
            self.is_connected = True
            self.log_info(f"Connected to OpenAI for {self.device_id}")
            
            # Start listening for messages
            asyncio.create_task(self._listen_loop())
            
        except Exception as e:
            self.log_error(f"Failed to connect to OpenAI for {self.device_id}: {e}")
            raise
    
    async def _listen_loop(self):
        """Listen for messages from OpenAI"""
        try:
            async for message in self.websocket:
                await self._handle_message(json.loads(message))
        except Exception as e:
            self.log_error(f"Listen loop error for {self.device_id}: {e}")
    
    async def _handle_message(self, data: dict):
        """Handle messages from OpenAI"""
        msg_type = data.get('type')
        self.log_info(f"📨 OpenAI message for {self.device_id}: {msg_type}")
        
        if msg_type == 'session.created':
            self.log_info(f"🎉 Session created for {self.device_id}")
            await self._configure_session()
        
        elif msg_type == 'session.updated':
            self.session_configured = True
            self.log_info(f"✅ Session configured for {self.device_id}")
        
        elif msg_type == 'input_audio_buffer.speech_started':
            self.log_info(f"🎤 Speech started detected for {self.device_id}")
        
        elif msg_type == 'input_audio_buffer.speech_stopped':
            self.log_info(f"🔇 Speech stopped detected for {self.device_id}")
        
        elif msg_type == 'response.created':
            response_id = data.get('response', {}).get('id', 'unknown')
            self.log_info(f"🤖 Response created for {self.device_id}: {response_id}")
        
        elif msg_type == 'response.output_item.added':
            item = data.get('item', {})
            self.log_info(f"📝 Output item added for {self.device_id}: {item.get('type', 'unknown')}")
        
        elif msg_type == 'response.content_part.added':
            part = data.get('part', {})
            self.log_info(f"📄 Content part added for {self.device_id}: {part.get('type', 'unknown')}")
        
        elif msg_type == 'response.audio.delta':
            # Forward audio to ESP32
            audio_b64 = data.get('delta')
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                self.log_info(f"🔊 Received audio delta for {self.device_id}: {len(audio_data)} bytes")
                self.audio_callback(self.device_id, audio_data)
            else:
                self.log_warning(f"⚠️ Empty audio delta for {self.device_id}")
        
        elif msg_type == 'response.audio.done':
            self.log_info(f"🎵 Audio response completed for {self.device_id}")
        
        elif msg_type == 'response.done':
            response_id = data.get('response', {}).get('id', 'unknown')
            self.log_info(f"✅ Response completed for {self.device_id}: {response_id}")
        
        elif msg_type == 'error':
            error = data.get('error', {})
            error_message = error.get('message', 'Unknown error')
            error_code = error.get('code', 'unknown')
            self.log_error(f"❌ OpenAI error for {self.device_id}: {error_code} - {error_message}")
        
        else:
            self.log_info(f"🤔 Unhandled message type for {self.device_id}: {msg_type}")
            # Log the full message for debugging unknown types
            self.log_info(f"📋 Full message: {data}")
    
    async def _configure_session(self):
        """Configure the OpenAI session"""
        config = {
            "type": "session.update",
            "session": {
                "modalities": ['text',"audio"],  # Only audio, no text
                "instructions": self.system_prompt,
                "voice": "ballad",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800  # Wait 800ms before responding
                }
            }
        }
        
        await self.websocket.send(json.dumps(config))
        self.log_info(f"Session config sent for {self.device_id}")
    
    async def send_audio(self, audio_data: bytes) -> bool:
        """Send audio data to OpenAI"""
        if not self.is_connected or not self.session_configured:
            self.log_warning(f"❌ Cannot send audio for {self.device_id}: connected={self.is_connected}, configured={self.session_configured}")
            return False
        
        try:
            self.log_info(f"🎵 Encoding {len(audio_data)} bytes for OpenAI ({self.device_id})")
            
            # Encode to base64
            audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            
            # Send as input_audio_buffer.append
            message = {
                "type": "input_audio_buffer.append",
                "audio": audio_b64
            }
            
            await self.websocket.send(json.dumps(message))
            self.log_info(f"✅ Sent audio to OpenAI for {self.device_id}: {len(audio_data)} bytes")
            return True
            
        except Exception as e:
            self.log_error(f"❌ Failed to send audio for {self.device_id}: {e}")
            return False
    
    async def close(self):
        """Close the connection"""
        self.is_connected = False
        if self.websocket:
            await self.websocket.close()


class OpenAIService(LoggerMixin):
    """Simplified OpenAI service"""
    
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key
        self.active_connections = {}
    
    async def create_connection(self, device_id: str, system_prompt: str,
                              audio_callback: Callable[[str, bytes], None]) -> OpenAIConnection:
        """Create new OpenAI connection"""
        if device_id in self.active_connections:
            await self.close_connection(device_id)
        
        connection = OpenAIConnection(
            device_id=device_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
            audio_callback=audio_callback
        )
        
        await connection.connect()
        self.active_connections[device_id] = connection
        return connection
    
    async def send_audio(self, device_id: str, audio_data: bytes) -> bool:
        """Send audio to OpenAI"""
        if device_id not in self.active_connections:
            return False
        return await self.active_connections[device_id].send_audio(audio_data)
    
    async def close_connection(self, device_id: str):
        """Close connection"""
        if device_id in self.active_connections:
            await self.active_connections[device_id].close()
            del self.active_connections[device_id]
    
    async def close_all_connections(self):
        """Close all connections"""
        for device_id in list(self.active_connections.keys()):
            await self.close_connection(device_id)


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