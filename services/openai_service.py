"""
FIXED OpenAI service - Resolves "unpack requires a buffer of 4 bytes" error
"""
import asyncio
import json
import base64
import struct
import websockets
from typing import Optional, Callable
from utils.logger import LoggerMixin


class OpenAIConnection(LoggerMixin):
    """FIXED OpenAI Realtime API connection with robust audio processing"""
    
    def _init_(self, device_id: str, system_prompt: str, api_key: str,
                 audio_callback: Callable[[str, bytes], None]):
        super()._init_()
        self.device_id = device_id
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.audio_callback = audio_callback
        
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.session_configured = False
        
        # FIXED: Add audio buffer validation
        self.audio_buffer = bytearray()
        self.total_audio_received = 0
        
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
            item_type = item.get('type', 'unknown')
            self.log_info(f"📝 Output item added for {self.device_id}: {item_type}")
            
            if item_type == 'audio':
                self.log_info(f"🎵 Audio output item created for {self.device_id}")
        
        elif msg_type == 'response.content_part.added':
            part = data.get('part', {})
            part_type = part.get('type', 'unknown')
            self.log_info(f"📄 Content part added for {self.device_id}: {part_type}")
        
        elif msg_type == 'response.audio.delta':
            # Forward audio to ESP32
            audio_b64 = data.get('delta')
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                self.log_info(f"🔊 Received audio delta for {self.device_id}: {len(audio_data)} bytes")
                self.audio_callback(self.device_id, audio_data)
            else:
                self.log_warning(f"⚠ Empty audio delta for {self.device_id}")
        
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
        
        elif msg_type == 'conversation.item.created':
            item = data.get('item', {})
            self.log_info(f"💬 Conversation item created for {self.device_id}: {item.get('type', 'unknown')}")
        
        elif msg_type == 'conversation.item.input_audio_transcription.completed':
            transcript = data.get('transcript', '')
            self.log_info(f"📝 Transcription completed for {self.device_id}: {transcript[:50]}...")
        
        else:
            self.log_info(f"🤔 Unhandled message type for {self.device_id}: {msg_type}")
    
    async def _configure_session(self):
        """Configure the OpenAI session"""
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
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800
                }
            }
        }
        
        await self.websocket.send(json.dumps(config))
        self.log_info(f"✅ Session config sent for {self.device_id}")
    
    def _validate_audio_buffer(self, audio_data: bytes) -> bool:
        """FIXED: Validate audio buffer before processing"""
        if not audio_data:
            self.log_warning(f"❌ Empty audio buffer for {self.device_id}")
            return False
        
        if len(audio_data) % 2 != 0:
            self.log_warning(f"❌ Audio buffer size {len(audio_data)} is not 16-bit aligned for {self.device_id}")
            return False
        
        # Check if buffer has reasonable size (at least 100ms of audio at 24kHz)
        min_samples = 24000 * 0.1  # 100ms
        if len(audio_data) < min_samples * 2:  # 2 bytes per 16-bit sample
            self.log_warning(f"⚠ Audio buffer too small for {self.device_id}: {len(audio_data)} bytes")
            return False
        
        return True
    
    def _process_audio_safely(self, audio_data: bytes) -> bytes:
        """FIXED: Safely process audio data with validation"""
        try:
            if not self._validate_audio_buffer(audio_data):
                return b""
            
            # Log audio statistics
            sample_count = len(audio_data) // 2
            self.log_info(f"🔍 Processing audio for {self.device_id}: {len(audio_data)} bytes, {sample_count} samples")
            
            # Convert bytes to 16-bit samples for analysis
            samples = []
            for i in range(0, len(audio_data), 2):
                if i + 1 < len(audio_data):
                    sample = struct.unpack('<h', audio_data[i:i+2])[0]
                    samples.append(sample)
            
            if len(samples) >= 8:
                self.log_info(f"🔍 First 8 samples: {samples[:8]}")
                self.log_info(f"🔍 Last 8 samples: {samples[-8:]}")
            
            # Calculate audio level
            if samples:
                max_amplitude = max(abs(s) for s in samples)
                avg_amplitude = sum(abs(s) for s in samples) / len(samples)
                self.log_info(f"📊 Audio levels for {self.device_id}: max={max_amplitude}, avg={avg_amplitude:.1f}")
            
            return audio_data
            
        except Exception as e:
            self.log_error(f"❌ Error processing audio for {self.device_id}: {e}")
            return b""
    
    async def send_audio(self, audio_data: bytes) -> bool:
        """FIXED: Send audio data to OpenAI with validation"""
        if not self.is_connected or not self.session_configured:
            self.log_warning(f"❌ Cannot send audio for {self.device_id}: connected={self.is_connected}, configured={self.session_configured}")
            return False
        
        try:
            # FIXED: Process and validate audio before sending
            processed_audio = self._process_audio_safely(audio_data)
            if not processed_audio:
                self.log_warning(f"⚠ Audio validation failed for {self.device_id}, skipping")
                return False
            
            self.total_audio_received += len(processed_audio)
            self.log_info(f"🎵 Sending validated audio to OpenAI for {self.device_id}: {len(processed_audio)} bytes (total: {self.total_audio_received})")
            
            # Encode to base64
            audio_b64 = base64.b64encode(processed_audio).decode('utf-8')
            
            # Send as input_audio_buffer.append
            message = {
                "type": "input_audio_buffer.append",
                "audio": audio_b64
            }
            
            await self.websocket.send(json.dumps(message))
            self.log_info(f"✅ Successfully sent audio to OpenAI for {self.device_id}: {len(processed_audio)} bytes")
            return True
            
        except Exception as e:
            self.log_error(f"❌ Failed to send audio for {self.device_id}: {e}")
            return False
    
    async def commit_audio_buffer(self):
        """Commit the audio buffer to trigger response generation"""
        if not self.is_connected or not self.session_configured:
            return False
        
        try:
            message = {
                "type": "input_audio_buffer.commit"
            }
            await self.websocket.send(json.dumps(message))
            self.log_info(f"🎯 Audio buffer committed for {self.device_id} (total audio: {self.total_audio_received} bytes)")
            
            # Reset audio tracking
            self.total_audio_received = 0
            return True
        except Exception as e:
            self.log_error(f"❌ Failed to commit audio buffer for {self.device_id}: {e}")
            return False
    
    async def create_response(self):
        """Trigger response creation"""
        if not self.is_connected or not self.session_configured:
            return False
        
        try:
            message = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": "Please respond with both text and audio. Provide a helpful and engaging response.",
                }
            }
            await self.websocket.send(json.dumps(message))
            self.log_info(f"🚀 Response creation triggered for {self.device_id}")
            return True
        except Exception as e:
            self.log_error(f"❌ Failed to create response for {self.device_id}: {e}")
            return False
    
    async def close(self):
        """Close the connection"""
        self.is_connected = False
        if self.websocket:
            try:
                await self.websocket.close()
                self.log_info(f"🔌 Closed OpenAI connection for {self.device_id}")
            except Exception as e:
                self.log_warning(f"⚠ Error closing OpenAI websocket for {self.device_id}: {e}")


class OpenAIService(LoggerMixin):
    """FIXED OpenAI service with robust error handling"""
    
    def _init_(self, api_key: str):
        super()._init_()
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
        self.log_info(f"✅ Created OpenAI connection for {device_id}")
        return connection
    
    async def send_audio(self, device_id: str, audio_data: bytes) -> bool:
        """Send audio to OpenAI with validation"""
        if device_id not in self.active_connections:
            self.log_warning(f"❌ No OpenAI connection for {device_id}")
            return False
        
        return await self.active_connections[device_id].send_audio(audio_data)
    
    async def commit_audio_buffer(self, device_id: str) -> bool:
        """Commit audio buffer for a device"""
        if device_id not in self.active_connections:
            self.log_warning(f"❌ No OpenAI connection for {device_id}")
            return False
        return await self.active_connections[device_id].commit_audio_buffer()
    
    async def create_response(self, device_id: str) -> bool:
        """Trigger response creation for a device"""
        if device_id not in self.active_connections:
            self.log_warning(f"❌ No OpenAI connection for {device_id}")
            return False
        return await self.active_connections[device_id].create_response()
    
    async def close_connection(self, device_id: str):
        """Close connection safely"""
        if device_id in self.active_connections:
            try:
                await self.active_connections[device_id].close()
                del self.active_connections[device_id]
                self.log_info(f"✅ Closed OpenAI connection for {device_id}")
            except KeyError:
                self.log_warning(f"⚠ OpenAI connection for {device_id} already removed")
            except Exception as e:
                self.log_error(f"❌ Error closing OpenAI connection for {device_id}: {e}")
                try:
                    del self.active_connections[device_id]
                except KeyError:
                    pass
    
    async def close_all_connections(self):
        """Close all connections"""
        device_ids = list(self.active_connections.keys())
        for device_id in device_ids:
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