"""
Fixed OpenAI Realtime API service for handling audio conversations
"""
import asyncio
import json
import base64
from typing import Optional, Dict, Any, Callable
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from config.settings import get_settings
from models.websocket import OpenAIConnectionConfig, AudioMetadata
from utils.exceptions import OpenAIConnectionException
from utils.logger import LoggerMixin, log_openai_interaction


class OpenAIService(LoggerMixin):
    """Service for managing OpenAI Realtime API connections"""
    
    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.active_connections: Dict[str, 'OpenAIConnection'] = {}
    
    async def create_connection(self, device_id: str, system_prompt: str,
                              audio_callback: Callable[[str, bytes], None],
                              completion_callback: Callable[[str], None]) -> 'OpenAIConnection':
        """
        Create a new OpenAI connection for a device
        
        Args:
            device_id: Unique device identifier
            system_prompt: System prompt for the conversation
            audio_callback: Callback function for audio data
            completion_callback: Callback function for conversation completion
            
        Returns:
            OpenAIConnection: Active connection object
        """
        if device_id in self.active_connections:
            await self.close_connection(device_id)
        
        try:
            connection = OpenAIConnection(
                device_id=device_id,
                system_prompt=system_prompt,
                audio_callback=audio_callback,
                completion_callback=completion_callback,
                settings=self.settings
            )
            
            await connection.connect()
            self.active_connections[device_id] = connection
            
            log_openai_interaction(device_id, "connect", "success")
            self.log_info(f"OpenAI connection created for device {device_id}")
            
            return connection
            
        except Exception as e:
            log_openai_interaction(device_id, "connect", "failed", {"error": str(e)})
            self.log_error(f"Failed to create OpenAI connection for {device_id}: {e}")
            raise OpenAIConnectionException(device_id, "Failed to create connection", str(e))
    
    async def close_connection(self, device_id: str):
        """
        Close OpenAI connection for a device
        
        Args:
            device_id: Unique device identifier
        """
        if device_id in self.active_connections:
            connection = self.active_connections[device_id]
            await connection.close()
            del self.active_connections[device_id]
            
            log_openai_interaction(device_id, "disconnect", "success")
            self.log_info(f"OpenAI connection closed for device {device_id}")
    
    async def send_audio(self, device_id: str, audio_data: bytes) -> bool:
        """
        Send audio data to OpenAI
        
        Args:
            device_id: Unique device identifier
            audio_data: Raw audio bytes
            
        Returns:
            bool: True if sent successfully
        """
        if device_id not in self.active_connections:
            return False
        
        connection = self.active_connections[device_id]
        return await connection.send_audio(audio_data)
    
    def get_connection(self, device_id: str) -> Optional['OpenAIConnection']:
        """Get active connection for device"""
        return self.active_connections.get(device_id)
    
    async def close_all_connections(self):
        """Close all active connections"""
        for device_id in list(self.active_connections.keys()):
            await self.close_connection(device_id)


class OpenAIConnection(LoggerMixin):
    """Individual OpenAI Realtime API connection"""
    
    def __init__(self, device_id: str, system_prompt: str,
                 audio_callback: Callable[[str, bytes], None],
                 completion_callback: Callable[[str], None],
                 settings):
        super().__init__()
        self.device_id = device_id
        self.system_prompt = system_prompt
        self.audio_callback = audio_callback
        self.completion_callback = completion_callback
        self.settings = settings
        
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.is_listening = False
        self.listen_task: Optional[asyncio.Task] = None
        
        # Connection configuration
        self.config = OpenAIConnectionConfig(
            model="gpt-4o-realtime-preview-2024-12-17",  # Updated model
            voice=self.settings.openai_voice_model,
            instructions=system_prompt
        )
        
        # Voice Activity Detection (VAD) settings - enabled for automatic responses
        self.vad_enabled = True  # Enable VAD for automatic response generation
        self.turn_detection = {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500  # Wait 500ms of silence before responding
        }
    
    async def connect(self):
        """Establish connection to OpenAI Realtime API"""
        try:
            # Prepare headers (correct format for websockets library)
            headers = {
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "OpenAI-Beta": "realtime=v1"
            }
            
            # Connect to OpenAI with correct URL format
            self.websocket = await websockets.connect(
                self.settings.openai_realtime_url,
                extra_headers=headers,
                ping_interval=30,
                ping_timeout=10
            )
            
            self.is_connected = True
            
            # Start listening for responses
            self.listen_task = asyncio.create_task(self._listen_loop())
            
            # Wait for session.created event before sending configuration
            # The session configuration will be sent in _handle_session_created
            
            self.log_info(f"Connected to OpenAI for device {self.device_id}")
            
        except Exception as e:
            self.log_error(f"Failed to connect to OpenAI for {self.device_id}: {e}")
            self.is_connected = False
            raise OpenAIConnectionException(self.device_id, "Connection failed", str(e))
    
    async def _send_session_config(self):
        """Send session configuration to OpenAI"""
        try:
            # Create session update configuration
            session_config = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": self.system_prompt,
                    "voice": self.config.voice,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": "whisper-1"
                    },
                    "turn_detection": self.turn_detection if self.vad_enabled else None,
                    "tools": [],
                    "tool_choice": "auto",
                    "temperature": 0.8,
                    "max_response_output_tokens": 4096
                }
            }
            
            await self.websocket.send(json.dumps(session_config))
            self.log_info(f"Session config sent for device {self.device_id}")
            
        except Exception as e:
            self.log_error(f"Failed to send session config for {self.device_id}: {e}")
            raise
    
    async def send_audio(self, audio_data: bytes) -> bool:
        """
        Send audio data to OpenAI
        
        Args:
            audio_data: Raw PCM16 audio bytes
            
        Returns:
            bool: True if sent successfully
        """
        if not self.is_connected or not self.websocket:
            return False
        
        try:
            # Encode audio data to base64
            audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            
            # Create audio append message
            audio_message = {
                "type": "input_audio_buffer.append",
                "audio": audio_b64
            }
            
            await self.websocket.send(json.dumps(audio_message))
            return True
            
        except Exception as e:
            self.log_error(f"Failed to send audio for {self.device_id}: {e}")
            log_openai_interaction(self.device_id, "send_audio", "failed", {"error": str(e)})
            return False
    
    async def commit_audio(self):
        """Commit the audio buffer for processing (used when VAD is disabled)"""
        if not self.is_connected or not self.websocket:
            return
        
        try:
            commit_message = {
                "type": "input_audio_buffer.commit"
            }
            await self.websocket.send(json.dumps(commit_message))
            
        except Exception as e:
            self.log_error(f"Failed to commit audio for {self.device_id}: {e}")
    
    async def create_response(self):
        """Trigger response generation (used when VAD is disabled)"""
        if not self.is_connected or not self.websocket:
            return
            
        try:
            response_message = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"]
                }
            }
            await self.websocket.send(json.dumps(response_message))
            
        except Exception as e:
            self.log_error(f"Failed to create response for {self.device_id}: {e}")
    
    async def _listen_loop(self):
        """Listen for messages from OpenAI"""
        self.is_listening = True
        
        try:
            async for message in self.websocket:
                if not self.is_listening:
                    break
                
                await self._handle_openai_message(message)
                
        except ConnectionClosed:
            self.log_info(f"OpenAI connection closed for device {self.device_id}")
        except Exception as e:
            self.log_error(f"Error in listen loop for {self.device_id}: {e}")
            log_openai_interaction(self.device_id, "listen", "error", {"error": str(e)})
        finally:
            self.is_listening = False
            self.is_connected = False
    
    async def _handle_openai_message(self, message: str):
        """Handle incoming message from OpenAI"""
        try:
            data = json.loads(message)
            message_type = data.get('type')
            
            # Log all message types for debugging
            self.log_info(f"OpenAI message for {self.device_id}: {message_type}")
            
            if message_type == 'session.created':
                await self._handle_session_created(data)
            
            elif message_type == 'session.updated':
                await self._handle_session_updated(data)
            
            elif message_type == 'input_audio_buffer.committed':
                await self._handle_audio_committed(data)
            
            elif message_type == 'input_audio_buffer.speech_started':
                await self._handle_speech_started(data)
            
            elif message_type == 'input_audio_buffer.speech_stopped':
                await self._handle_speech_stopped(data)
            
            elif message_type == 'response.created':
                await self._handle_response_created(data)
            
            elif message_type == 'response.output_item.added':
                await self._handle_output_item_added(data)
            
            elif message_type == 'response.content_part.added':
                await self._handle_content_part_added(data)
            
            elif message_type == 'response.audio.delta':
                await self._handle_audio_delta(data)
            
            elif message_type == 'response.audio.done':
                await self._handle_audio_done(data)
            
            elif message_type == 'response.content_part.done':
                await self._handle_content_part_done(data)
            
            elif message_type == 'response.output_item.done':
                await self._handle_output_item_done(data)
            
            elif message_type == 'response.done':
                await self._handle_response_done(data)
            
            elif message_type == 'error':
                await self._handle_error(data)
            
            else:
                self.log_info(f"Unhandled message type for {self.device_id}: {message_type}")
                
        except json.JSONDecodeError as e:
            self.log_error(f"Failed to parse OpenAI message for {self.device_id}: {e}")
        except Exception as e:
            self.log_error(f"Error handling OpenAI message for {self.device_id}: {e}")
    
    async def _handle_session_created(self, data: Dict[str, Any]):
        """Handle session created event"""
        session_info = data.get('session', {})
        self.log_info(f"OpenAI session created for {self.device_id}", 
                     extra={"session_id": session_info.get('id')})
        
        # Now send our session configuration
        await self._send_session_config()
    
    async def _handle_session_updated(self, data: Dict[str, Any]):
        """Handle session updated event"""
        session_info = data.get('session', {})
        self.log_info(f"OpenAI session updated for {self.device_id}")
    
    async def _handle_audio_committed(self, data: Dict[str, Any]):
        """Handle audio buffer committed"""
        self.log_info(f"Audio buffer committed for {self.device_id}")
    
    async def _handle_speech_started(self, data: Dict[str, Any]):
        """Handle speech detection started"""
        self.log_info(f"Speech started detected for {self.device_id}")
    
    async def _handle_speech_stopped(self, data: Dict[str, Any]):
        """Handle speech detection stopped"""
        self.log_info(f"Speech stopped detected for {self.device_id}")
    
    async def _handle_response_created(self, data: Dict[str, Any]):
        """Handle response creation"""
        response_info = data.get('response', {})
        self.log_info(f"Response created for {self.device_id}: {response_info.get('id')}")
    
    async def _handle_output_item_added(self, data: Dict[str, Any]):
        """Handle output item added"""
        item = data.get('item', {})
        self.log_info(f"Output item added for {self.device_id}: {item.get('type')}")
    
    async def _handle_content_part_added(self, data: Dict[str, Any]):
        """Handle content part added"""
        part = data.get('part', {})
        self.log_info(f"Content part added for {self.device_id}: {part.get('type')}")
    
    async def _handle_audio_delta(self, data: Dict[str, Any]):
        """Handle incoming audio data"""
        try:
            audio_b64 = data.get('delta')
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                
                # Call the audio callback to send to ESP32
                if self.audio_callback:
                    self.audio_callback(self.device_id, audio_data)
                
        except Exception as e:
            self.log_error(f"Error processing audio delta for {self.device_id}: {e}")
    
    async def _handle_audio_done(self, data: Dict[str, Any]):
        """Handle audio completion"""
        self.log_info(f"Audio response completed for device {self.device_id}")
        log_openai_interaction(self.device_id, "audio_response", "completed")
    
    async def _handle_content_part_done(self, data: Dict[str, Any]):
        """Handle content part completion"""
        part = data.get('part', {})
        self.log_info(f"Content part done for {self.device_id}: {part.get('type')}")
    
    async def _handle_output_item_done(self, data: Dict[str, Any]):
        """Handle output item completion"""
        item = data.get('item', {})
        self.log_info(f"Output item done for {self.device_id}: {item.get('type')}")
    
    async def _handle_response_done(self, data: Dict[str, Any]):
        """Handle response completion"""
        response_info = data.get('response', {})
        
        self.log_info(f"Response completed for device {self.device_id}",
                     extra={"response_id": response_info.get('id')})
        
        # Call completion callback
        if self.completion_callback:
            try:
                self.completion_callback(self.device_id)
            except Exception as e:
                self.log_error(f"Error in completion callback for {self.device_id}: {e}")
        
        log_openai_interaction(self.device_id, "conversation", "completed")
    
    async def _handle_error(self, data: Dict[str, Any]):
        """Handle error from OpenAI"""
        error_info = data.get('error', {})
        error_message = error_info.get('message', 'Unknown error')
        error_code = error_info.get('code', 'unknown')
        
        self.log_error(f"OpenAI error for {self.device_id}: {error_message}",
                      extra={"error_code": error_code, "error_data": error_info})
        
        log_openai_interaction(self.device_id, "error", "received", {
            "error_code": error_code,
            "error_message": error_message
        })
    
    async def close(self):
        """Close the OpenAI connection"""
        try:
            self.is_listening = False
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
                await self.websocket.close()
                self.websocket = None
            
            self.log_info(f"OpenAI connection closed for device {self.device_id}")
            
        except Exception as e:
            self.log_error(f"Error closing OpenAI connection for {self.device_id}: {e}")
    
    @property
    def connection_info(self) -> Dict[str, Any]:
        """Get connection information"""
        return {
            "device_id": self.device_id,
            "is_connected": self.is_connected,
            "is_listening": self.is_listening,
            "model": self.config.model,
            "voice": self.config.voice,
            "vad_enabled": self.vad_enabled
        }


# Global OpenAI service instance
_openai_service: Optional[OpenAIService] = None


def get_openai_service() -> OpenAIService:
    """Get OpenAI service singleton"""
    global _openai_service
    if _openai_service is None:
        _openai_service = OpenAIService()
    return _openai_service