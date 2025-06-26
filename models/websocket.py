"""
WebSocket related data models
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum
import json


class ConnectionStatus(str, Enum):
    """WebSocket connection status"""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class AudioMessageType(str, Enum):
    """Types of audio messages"""
    AUDIO_DATA = "audio_data"
    AUDIO_START = "audio_start"
    AUDIO_END = "audio_end"
    SESSION_UPDATE = "session_update"
    ERROR = "error"


class WebSocketMessage(BaseModel):
    """Base WebSocket message model"""
    type: AudioMessageType
    timestamp: datetime = Field(default_factory=datetime.now)
    device_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    def to_json(self) -> str:
        """Convert message to JSON string"""
        return json.dumps(self.dict(), default=str)


class AudioMetadata(BaseModel):
    """Audio data metadata"""
    sample_rate: int = 16000
    channels: int = 1
    bits_per_sample: int = 16
    duration_ms: Optional[float] = None
    size_bytes: int = 0
    format: str = "pcm16"


class ConnectionData(BaseModel):
    """WebSocket connection data"""
    device_id: str
    status: ConnectionStatus = ConnectionStatus.CONNECTING
    connected_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)
    session_id: str
    user_data: Optional[Dict[str, Any]] = None
    system_prompt: Optional[str] = None
    audio_stats: Dict[str, Any] = Field(default_factory=dict)
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.now()
    
    @property
    def connection_duration(self) -> float:
        """Get connection duration in seconds"""
        return (datetime.now() - self.connected_at).total_seconds()


class OpenAIConnectionConfig(BaseModel):
    """Configuration for OpenAI connection"""
    model: str = "gpt-4o-mini-realtime-preview-2024-10-01"
    voice: str = "ballad"
    input_audio_format: str = "pcm16"
    output_audio_format: str = "pcm16"
    modalities: list[str] = Field(default_factory=lambda: ["text", "audio"])
    instructions: str = ""
    
    def to_openai_config(self) -> Dict[str, Any]:
        """Convert to OpenAI session configuration"""
        return {
            "type": "session.update",
            "session": {
                "modalities": self.modalities,
                "instructions": self.instructions,
                "voice": self.voice,
                "input_audio_format": self.input_audio_format,
                "output_audio_format": self.output_audio_format,
                "input_audio_transcription": {
                    "model": "whisper-1"
                }
            }
        }


class SessionStats(BaseModel):
    """Session statistics"""
    bytes_sent: int = 0
    bytes_received: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    audio_duration_sent: float = 0.0
    audio_duration_received: float = 0.0
    errors_count: int = 0
    
    def add_sent_data(self, bytes_count: int, duration: float = 0.0):
        """Add sent data statistics"""
        self.bytes_sent += bytes_count
        self.messages_sent += 1
        self.audio_duration_sent += duration
    
    def add_received_data(self, bytes_count: int, duration: float = 0.0):
        """Add received data statistics"""
        self.bytes_received += bytes_count
        self.messages_received += 1
        self.audio_duration_received += duration
    
    def add_error(self):
        """Increment error count"""
        self.errors_count += 1


class DisconnectionReason(str, Enum):
    """Reasons for WebSocket disconnection"""
    CLIENT_DISCONNECT = "client_disconnect"
    SERVER_SHUTDOWN = "server_shutdown"
    TIMEOUT = "timeout"
    ERROR = "error"
    INVALID_AUTH = "invalid_auth"
    RATE_LIMIT = "rate_limit"
    SESSION_COMPLETE = "session_complete"


class DisconnectionInfo(BaseModel):
    """Information about WebSocket disconnection"""
    reason: DisconnectionReason
    message: Optional[str] = None
    session_duration: float = 0.0
    final_stats: Optional[SessionStats] = None
    timestamp: datetime = Field(default_factory=datetime.now)