"""
User-related data models
"""
from pydantic import BaseModel, validator, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class UserStatus(str, Enum):
    """User account status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class UserRegistrationRequest(BaseModel):
    """Request model for user registration"""
    device_id: str = Field(..., description="Device ID in format ABCD1234")
    name: str = Field(..., min_length=1, max_length=100, description="User's name")
    age: int = Field(..., ge=1, le=120, description="User's age")
    
    @validator('device_id')
    def validate_device_id(cls, v):
        import re
        if not re.match(r'^[A-Z]{4}\d{4}$', v):
            raise ValueError('Device ID must be 4 uppercase letters followed by 4 digits')
        return v


class UserProgress(BaseModel):
    """User learning progress"""
    season: int = Field(default=1, ge=1, description="Current season")
    episode: int = Field(default=1, ge=1, le=7, description="Current episode")
    words_learnt: List[str] = Field(default_factory=list, description="List of learned words")
    topics_learnt: List[str] = Field(default_factory=list, description="List of learned topics")
    total_time: float = Field(default=0.0, ge=0, description="Total time spent in seconds")
    episodes_completed: int = Field(default=0, ge=0, description="Total episodes completed")
    
    def advance_episode(self, episodes_per_season: int = 7) -> bool:
        """Advance to next episode/season. Returns True if advanced to new season"""
        self.episodes_completed += 1
        self.episode += 1
        
        if self.episode > episodes_per_season:
            self.episode = 1
            self.season += 1
            return True
        return False


class User(BaseModel):
    """Complete user model"""
    device_id: str
    name: str
    age: int
    status: UserStatus = UserStatus.ACTIVE
    progress: UserProgress = Field(default_factory=UserProgress)
    created_at: Optional[datetime] = None
    last_active: Optional[datetime] = None
    last_completed_episode: Optional[datetime] = None
    
    class Config:
        use_enum_values = True


class UserResponse(BaseModel):
    """Response model for user data"""
    device_id: str
    name: str
    age: int
    status: str
    season: int
    episode: int
    words_learnt_count: int
    topics_learnt_count: int
    total_time_hours: float
    episodes_completed: int
    created_at: Optional[datetime]
    last_active: Optional[datetime]
    
    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        """Create response from User model"""
        return cls(
            device_id=user.device_id,
            name=user.name,
            age=user.age,
            status=user.status.value,
            season=user.progress.season,
            episode=user.progress.episode,
            words_learnt_count=len(user.progress.words_learnt),
            topics_learnt_count=len(user.progress.topics_learnt),
            total_time_hours=round(user.progress.total_time / 3600, 2),
            episodes_completed=user.progress.episodes_completed,
            created_at=user.created_at,
            last_active=user.last_active
        )


class SessionInfo(BaseModel):
    """Current session information"""
    device_id: str
    session_duration: float
    current_season: int
    current_episode: int
    is_connected: bool
    is_openai_connected: bool
    session_start_time: datetime