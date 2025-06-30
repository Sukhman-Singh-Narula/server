"""
Conversation transcript models for storing AI and user conversations
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class MessageType(str, Enum):
    """Types of conversation messages"""
    USER_SPEECH = "user_speech"
    AI_RESPONSE = "ai_response"
    SYSTEM_MESSAGE = "system_message"
    ERROR_MESSAGE = "error_message"
    SESSION_START = "session_start"
    SESSION_END = "session_end"


class ConversationMessage(BaseModel):
    """Individual conversation message with timestamp"""
    message_id: str = Field(..., description="Unique message identifier")
    timestamp: datetime = Field(default_factory=datetime.now, description="Message timestamp")
    type: MessageType = Field(..., description="Type of message")
    content: str = Field(..., description="Message content/transcription")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Transcription confidence")
    duration_ms: Optional[int] = Field(default=None, description="Audio duration in milliseconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Get duration in seconds"""
        return self.duration_ms / 1000.0 if self.duration_ms else None


class ConversationSession(BaseModel):
    """Complete conversation session"""
    session_id: str = Field(..., description="Unique session identifier")
    device_id: str = Field(..., description="Device ID")
    season: int = Field(..., description="Season number")
    episode: int = Field(..., description="Episode number")
    
    # Session timing
    start_time: datetime = Field(default_factory=datetime.now, description="Session start time")
    end_time: Optional[datetime] = Field(default=None, description="Session end time")
    duration_seconds: float = Field(default=0.0, description="Total session duration")
    
    # Conversation data
    messages: List[ConversationMessage] = Field(default_factory=list, description="All conversation messages")
    system_prompt: str = Field(..., description="System prompt used")
    
    # Session statistics
    user_message_count: int = Field(default=0, description="Number of user messages")
    ai_message_count: int = Field(default=0, description="Number of AI messages")
    total_user_speech_duration: float = Field(default=0.0, description="Total user speech time in seconds")
    total_ai_response_duration: float = Field(default=0.0, description="Total AI response time in seconds")
    
    # Session outcome
    completed_successfully: bool = Field(default=False, description="Whether session completed successfully")
    completion_reason: Optional[str] = Field(default=None, description="Reason for session completion")
    
    @property
    def is_active(self) -> bool:
        """Check if session is currently active"""
        return self.end_time is None
    
    @property
    def message_count(self) -> int:
        """Total number of messages in session"""
        return len(self.messages)
    
    def add_message(self, message_type: MessageType, content: str, 
                   confidence: Optional[float] = None, duration_ms: Optional[int] = None,
                   metadata: Dict[str, Any] = None) -> ConversationMessage:
        """Add a new message to the conversation"""
        import uuid
        
        message = ConversationMessage(
            message_id=str(uuid.uuid4()),
            type=message_type,
            content=content,
            confidence=confidence,
            duration_ms=duration_ms,
            metadata=metadata or {}
        )
        
        self.messages.append(message)
        
        # Update statistics
        if message_type == MessageType.USER_SPEECH:
            self.user_message_count += 1
            if duration_ms:
                self.total_user_speech_duration += duration_ms / 1000.0
        elif message_type == MessageType.AI_RESPONSE:
            self.ai_message_count += 1
            if duration_ms:
                self.total_ai_response_duration += duration_ms / 1000.0
        
        return message
    
    def end_session(self, completion_reason: str = "normal_completion", 
                   completed_successfully: bool = True):
        """End the conversation session"""
        self.end_time = datetime.now()
        self.duration_seconds = (self.end_time - self.start_time).total_seconds()
        self.completion_reason = completion_reason
        self.completed_successfully = completed_successfully
    
    def get_conversation_summary(self) -> Dict[str, Any]:
        """Get a summary of the conversation"""
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "season": self.season,
            "episode": self.episode,
            "duration_minutes": round(self.duration_seconds / 60, 2),
            "message_counts": {
                "user_messages": self.user_message_count,
                "ai_messages": self.ai_message_count,
                "total_messages": self.message_count
            },
            "speech_duration": {
                "user_speech_minutes": round(self.total_user_speech_duration / 60, 2),
                "ai_response_minutes": round(self.total_ai_response_duration / 60, 2)
            },
            "completed_successfully": self.completed_successfully,
            "completion_reason": self.completion_reason
        }


class ConversationSearchRequest(BaseModel):
    """Request model for searching conversations"""
    device_id: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    message_type: Optional[MessageType] = None
    search_text: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


class ConversationSummary(BaseModel):
    """Summary of a conversation session for listings"""
    session_id: str
    device_id: str
    season: int
    episode: int
    start_time: datetime
    duration_minutes: float
    message_count: int
    user_message_count: int
    ai_message_count: int
    completed_successfully: bool
    
    @classmethod
    def from_session(cls, session: ConversationSession) -> "ConversationSummary":
        """Create summary from full session"""
        return cls(
            session_id=session.session_id,
            device_id=session.device_id,
            season=session.season,
            episode=session.episode,
            start_time=session.start_time,
            duration_minutes=round(session.duration_seconds / 60, 2),
            message_count=session.message_count,
            user_message_count=session.user_message_count,
            ai_message_count=session.ai_message_count,
            completed_successfully=session.completed_successfully
        )


class ConversationAnalytics(BaseModel):
    """Analytics for conversations over time"""
    device_id: str
    total_sessions: int
    total_duration_hours: float
    average_session_duration_minutes: float
    total_messages: int
    user_messages: int
    ai_messages: int
    
    # Quality metrics
    completion_rate: float  # Percentage of successfully completed sessions
    average_messages_per_session: float
    speech_to_silence_ratio: float  # User speech time vs total time
    
    # Daily statistics
    sessions_by_date: Dict[str, int]  # Date -> session count
    duration_by_date: Dict[str, float]  # Date -> total duration


class TranscriptExportRequest(BaseModel):
    """Request model for exporting transcripts"""
    device_id: str
    session_ids: Optional[List[str]] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    format: str = Field(default="json", description="Export format: json, csv, txt")
    include_metadata: bool = Field(default=True, description="Include message metadata")
    include_timestamps: bool = Field(default=True, description="Include timestamps")


class ConversationStats(BaseModel):
    """Real-time conversation statistics"""
    session_id: str
    elapsed_time_minutes: float
    messages_exchanged: int
    user_speech_percentage: float
    ai_response_percentage: float
    last_activity: datetime
    estimated_completion_time: Optional[float] = None  # Minutes