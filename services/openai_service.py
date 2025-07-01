"""
Enhanced OpenAI Realtime API service with conversation transcription capture - FIXED
"""
import asyncio
import json
import base64
import websockets
from typing import Optional, Callable, Awaitable
from utils.logger import LoggerMixin


class OpenAIConnection(LoggerMixin):
    """Enhanced OpenAI Realtime API connection with transcription capture - FIXED"""
    
    def __init__(self, device_id: str, system_prompt: str, api_key: str,
             audio_callback: Callable[[str, bytes], Awaitable[None]],
             conversation_service=None):
        super().__init__()
        self.device_id = device_id
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.audio_callback = audio_callback
        self.conversation_service = conversation_service
        
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.session_configured = False
        
        # Transcription tracking
        self.current_ai_response = ""
        self.ai_response_start_time = None
        
        # ENHANCED AUDIO BUFFERING
        self.audio_buffer = bytearray()
        self.min_audio_duration_ms = 200
        self.pending_audio_queue = []  # Queue audio while waiting for config
        
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
        """Handle messages from OpenAI with transcription capture"""
        msg_type = data.get('type')
        self.log_info(f"📨 OpenAI message for {self.device_id}: {msg_type}")
        
        if msg_type == 'session.created':
            self.log_info(f"🎉 Session created for {self.device_id}")
            await self._configure_session()
        
        elif msg_type == 'session.updated':
            self.session_configured = True
            self.log_info(f"✅ Session configured for {self.device_id}")
            
            # Process any queued audio
            await self._process_queued_audio()
            
            # Add system message to conversation
            if self.conversation_service:
                await self.conversation_service.add_system_message(
                    self.device_id,
                    "OpenAI session configured and ready",
                    metadata={"event": "session_configured"}
                )
        
        elif msg_type == 'input_audio_buffer.speech_started':
            self.log_info(f"🎤 Speech started detected for {self.device_id}")
            
        elif msg_type == 'input_audio_buffer.speech_stopped':
            self.log_info(f"🔇 Speech stopped detected for {self.device_id}")
        
        elif msg_type == 'conversation.item.input_audio_transcription.completed':
            # FIXED: Capture user speech transcription
            transcript = data.get('transcript', '')
            item_id = data.get('item_id', '')
            
            self.log_info(f"📝 User transcription for {self.device_id}: {transcript[:100]}...")
            
            # Add user message to conversation
            if self.conversation_service and transcript.strip():
                await self.conversation_service.add_user_message(
                    self.device_id,
                    transcript,
                    confidence=None,
                    duration_ms=None,
                )
        
        elif msg_type == 'conversation.item.input_audio_transcription.failed':
            # Handle transcription failure
            error = data.get('error', {})
            self.log_warning(f"⚠️ User transcription failed for {self.device_id}: {error}")
            
            if self.conversation_service:
                await self.conversation_service.add_system_message(
                    self.device_id,
                    f"User transcription failed: {error.get('message', 'Unknown error')}",
                    metadata={"event": "transcription_failed", "error": error}
                )
        
        elif msg_type == 'response.created':
            response_id = data.get('response', {}).get('id', 'unknown')
            self.log_info(f"🤖 Response created for {self.device_id}: {response_id}")
            
            # Reset AI response tracking
            self.current_ai_response = ""
            self.ai_response_start_time = asyncio.get_event_loop().time()
        
        elif msg_type == 'response.output_item.added':
            item = data.get('item', {})
            item_type = item.get('type', 'unknown')
            self.log_info(f"📝 Output item added for {self.device_id}: {item_type}")
        
        elif msg_type == 'response.content_part.added':
            part = data.get('part', {})
            part_type = part.get('type', 'unknown')
            self.log_info(f"📄 Content part added for {self.device_id}: {part_type}")
        
        elif msg_type == 'response.audio_transcript.delta':
            # FIXED: Handle AI response transcription deltas
            delta = data.get('delta', '')
            if delta:
                self.current_ai_response += delta
                self.log_info(f"📝 AI transcript delta for {self.device_id}: +{len(delta)} chars")
        
        elif msg_type == 'response.audio_transcript.done':
            # FIXED: AI transcription completed
            transcript = data.get('transcript', '')
            if transcript:
                self.current_ai_response = transcript
            
            self.log_info(f"📝 AI transcript completed for {self.device_id}: {len(self.current_ai_response)} chars")
            
            # Add AI text response to conversation
            if self.conversation_service and self.current_ai_response.strip():
                await self.conversation_service.add_ai_message(
                    self.device_id,
                    self.current_ai_response,
                    duration_ms=None,
                    metadata={
                        "content_type": "text_transcript",
                        "response_length": len(self.current_ai_response)
                    }
                )
        
        elif msg_type == 'response.audio.delta':
            # Forward audio to ESP32
            audio_b64 = data.get('delta')
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                self.log_info(f"🔊 Received audio delta for {self.device_id}: {len(audio_data)} bytes")
                try:
                    await self.audio_callback(self.device_id, audio_data)
                except Exception as e:
                    self.log_error(f"Audio callback error for {self.device_id}: {e}")
            else:
                self.log_warning(f"⚠️ Empty audio delta for {self.device_id}")
        
        elif msg_type == 'response.audio.done':
            self.log_info(f"🎵 Audio response completed for {self.device_id}")
            
            # Calculate approximate duration if we have start time
            duration_ms = None
            if self.ai_response_start_time:
                duration_seconds = asyncio.get_event_loop().time() - self.ai_response_start_time
                duration_ms = int(duration_seconds * 1000)
            
            # Add AI audio completion to conversation
            if self.conversation_service:
                await self.conversation_service.add_system_message(
                    self.device_id,
                    "AI audio response completed",
                    metadata={
                        "event": "audio_response_completed",
                        "duration_ms": duration_ms
                    }
                )
        
        elif msg_type == 'response.done':
            response_id = data.get('response', {}).get('id', 'unknown')
            self.log_info(f"✅ Response completed for {self.device_id}: {response_id}")
            
            # Add system message about response completion
            if self.conversation_service:
                await self.conversation_service.add_system_message(
                    self.device_id,
                    f"AI response completed: {response_id}",
                    metadata={
                        "event": "response_completed",
                        "response_id": response_id
                    }
                )
        
        elif msg_type == 'error':
            error = data.get('error', {})
            error_message = error.get('message', 'Unknown error')
            error_code = error.get('code', 'unknown')
            self.log_error(f"❌ OpenAI error for {self.device_id}: {error_code} - {error_message}")
            
            # Add error to conversation
            if self.conversation_service:
                await self.conversation_service.add_system_message(
                    self.device_id,
                    f"OpenAI error: {error_code} - {error_message}",
                    metadata={
                        "event": "openai_error",
                        "error_code": error_code,
                        "error_message": error_message
                    }
                )
        
        elif msg_type == 'conversation.item.created':
            item = data.get('item', {})
            item_type = item.get('type', 'unknown')
            self.log_info(f"💬 Conversation item created for {self.device_id}: {item_type}")
            
            # Add system message about conversation item
            if self.conversation_service:
                await self.conversation_service.add_system_message(
                    self.device_id,
                    f"Conversation item created: {item_type}",
                    metadata={
                        "event": "conversation_item_created",
                        "item_type": item_type,
                        "item_id": item.get('id')
                    }
                )
        
        else:
            self.log_info(f"🤔 Unhandled message type for {self.device_id}: {msg_type}")
    
    async def _configure_session(self):
        """Configure the OpenAI session with enhanced settings for transcription"""
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
                    "silence_duration_ms": 500
                }
            }
        }
        
        await self.websocket.send(json.dumps(config))
        self.log_info(f"✅ Session config sent for {self.device_id}")
        self.log_info(f"📋 Config details: modalities={config['session']['modalities']}, voice={config['session']['voice']}")
    
    async def _process_queued_audio(self):
        """Process audio that was queued while waiting for session configuration"""
        if self.pending_audio_queue:
            self.log_info(f"🎵 Processing {len(self.pending_audio_queue)} queued audio chunks for {self.device_id}")
            
            for audio_data in self.pending_audio_queue:
                await self._send_audio_to_openai(audio_data)
            
            self.pending_audio_queue.clear()
            self.log_info(f"✅ Finished processing queued audio for {self.device_id}")
    
    async def send_audio(self, audio_data: bytes) -> bool:
        """Send audio data to OpenAI with improved buffering"""
        if not self.is_connected:
            self.log_warning(f"❌ Cannot send audio for {self.device_id}: not connected")
            return False
        
        if not self.session_configured:
            # Queue the audio for later processing
            self.pending_audio_queue.append(audio_data)
            self.log_info(f"🎵 Queued audio for {self.device_id}: {len(audio_data)} bytes (queue size: {len(self.pending_audio_queue)})")
            return True
        
        return await self._send_audio_to_openai(audio_data)
    
    async def _send_audio_to_openai(self, audio_data: bytes) -> bool:
        """Actually send audio to OpenAI"""
        try:
            # Add to buffer
            self.audio_buffer.extend(audio_data)
            
            # Only send if we have sufficient audio data
            sample_rate = 16000
            bytes_per_second = sample_rate * 2  # 16-bit PCM
            min_bytes = (self.min_audio_duration_ms * bytes_per_second) // 1000
            
            if len(self.audio_buffer) >= min_bytes:
                self.log_info(f"🎵 Encoding {len(self.audio_buffer)} bytes for OpenAI ({self.device_id})")
                
                # Encode to base64
                audio_b64 = base64.b64encode(self.audio_buffer).decode('utf-8')
                
                # Send as input_audio_buffer.append
                message = {
                    "type": "input_audio_buffer.append",
                    "audio": audio_b64
                }
                
                await self.websocket.send(json.dumps(message))
                self.log_info(f"✅ Sent audio to OpenAI for {self.device_id}: {len(self.audio_buffer)} bytes")
                
                # Clear buffer
                self.audio_buffer.clear()
                return True
            else:
                self.log_info(f"🎵 Buffering audio for {self.device_id}: {len(self.audio_buffer)}/{min_bytes} bytes")
                return True
            
        except Exception as e:
            self.log_error(f"❌ Failed to send audio for {self.device_id}: {e}")
            return False
    
    async def commit_audio_buffer(self):
        """Manually commit the audio buffer to trigger response generation"""
        if not self.is_connected or not self.session_configured:
            return False
        
        try:
            # Send any remaining buffered audio first
            if len(self.audio_buffer) > 0:
                audio_b64 = base64.b64encode(self.audio_buffer).decode('utf-8')
                message = {
                    "type": "input_audio_buffer.append",
                    "audio": audio_b64
                }
                await self.websocket.send(json.dumps(message))
                self.audio_buffer.clear()
                await asyncio.sleep(0.1)  # Small delay
            
            # Now commit
            message = {
                "type": "input_audio_buffer.commit"
            }
            await self.websocket.send(json.dumps(message))
            self.log_info(f"🎯 Audio buffer committed for {self.device_id}")
            return True
        except Exception as e:
            self.log_error(f"❌ Failed to commit audio buffer for {self.device_id}: {e}")
            return False
    
    async def create_response(self):
        """Manually trigger response creation"""
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
            except Exception as e:
                self.log_warning(f"⚠️ Error closing OpenAI websocket for {self.device_id}: {e}")


class OpenAIService(LoggerMixin):
    """Enhanced OpenAI service with conversation transcription - FIXED"""
    
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key
        self.active_connections = {}
        self.conversation_service = None
    
    def set_conversation_service(self, conversation_service):
        """Set the conversation service for transcription capture"""
        self.conversation_service = conversation_service
    
    async def create_connection(self, device_id: str, system_prompt: str,
                              audio_callback: Callable[[str, bytes], Awaitable[None]]) -> OpenAIConnection:
        """Create new OpenAI connection with conversation tracking"""
        # Close existing connection safely
        if device_id in self.active_connections:
            await self.close_connection(device_id)
        
        connection = OpenAIConnection(
            device_id=device_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
            audio_callback=audio_callback,
            conversation_service=self.conversation_service
        )
        
        await connection.connect()
        self.active_connections[device_id] = connection
        
        self.log_info(f"✅ Created OpenAI connection for {device_id} with transcription capture")
        return connection
    
    async def send_audio(self, device_id: str, audio_data: bytes) -> bool:
        """Send audio to OpenAI"""
        if device_id not in self.active_connections:
            return False
        return await self.active_connections[device_id].send_audio(audio_data)
    
    async def commit_audio_buffer(self, device_id: str) -> bool:
        """Commit audio buffer for a specific device"""
        if device_id not in self.active_connections:
            return False
        return await self.active_connections[device_id].commit_audio_buffer()
    
    async def create_response(self, device_id: str) -> bool:
        """Trigger response creation for a device"""
        if device_id not in self.active_connections:
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
                # Connection was already removed by another call
                self.log_warning(f"⚠️ OpenAI connection for {device_id} already removed")
            except Exception as e:
                self.log_error(f"❌ Error closing OpenAI connection for {device_id}: {e}")
                # Still try to remove from active_connections
                try:
                    del self.active_connections[device_id]
                except KeyError:
                    pass
    
    async def close_all_connections(self):
        """Close all connections"""
        # Create a list of device_ids to avoid dictionary changed during iteration
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
        
        # Set up conversation service connection
        try:
            from services.conversation_service import get_conversation_service
            conversation_service = get_conversation_service()
            _openai_service.set_conversation_service(conversation_service)
        except ImportError:
            # Conversation service might not be available yet
            pass
    
    return _openai_service