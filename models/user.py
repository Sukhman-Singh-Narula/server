"""
Enhanced User-related data models with daily episode limits
"""
from pydantic import BaseModel, validator, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from enum import Enum


class UserStatus(str, Enum):
    """User account status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class DailyUsage(BaseModel):
    """Daily usage tracking for episode limits"""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    episodes_played: int = Field(default=0, ge=0, description="Episodes played today")
    total_session_time: float = Field(default=0.0, ge=0, description="Total session time in seconds")
    sessions_count: int = Field(default=0, ge=0, description="Number of sessions today")
    last_episode_time: Optional[datetime] = Field(default=None, description="Last episode completion time")
    
    @property
    def can_play_episode(self) -> bool:
        """Check if user can play another episode today"""
        return self.episodes_played < 3
    
    @property
    def remaining_episodes(self) -> int:
        """Get remaining episodes for today"""
        return max(0, 3 - self.episodes_played)


class UserProgress(BaseModel):
    """Enhanced user learning progress with daily limits"""
    season: int = Field(default=1, ge=1, description="Current season")
    episode: int = Field(default=1, ge=1, le=7, description="Current episode")
    words_learnt: List[str] = Field(default_factory=list, description="List of learned words")
    topics_learnt: List[str] = Field(default_factory=list, description="List of learned topics")
    total_time: float = Field(default=0.0, ge=0, description="Total time spent in seconds")
    episodes_completed: int = Field(default=0, ge=0, description="Total episodes completed")
    
    # Daily usage tracking
    daily_usage: DailyUsage = Field(default_factory=lambda: DailyUsage(date=date.today().isoformat()))
    usage_history: List[DailyUsage] = Field(default_factory=list, description="Historical daily usage")
    
    def update_daily_usage(self) -> DailyUsage:
        """Update or create today's usage entry"""
        today = date.today().isoformat()
        
        if self.daily_usage.date != today:
            # New day - archive old usage and create new
            if self.daily_usage.episodes_played > 0:
                self.usage_history.append(self.daily_usage)
            
            # Keep only last 30 days of history
            if len(self.usage_history) > 30:
                self.usage_history = self.usage_history[-30:]
            
            # Create new daily usage
            self.daily_usage = DailyUsage(date=today)
        
        return self.daily_usage
    
    def can_advance_episode(self) -> tuple[bool, str]:
        """Check if user can advance to next episode today"""
        self.update_daily_usage()
        
        if not self.daily_usage.can_play_episode:
            return False, f"Daily episode limit reached. You can play {self.daily_usage.remaining_episodes} more episodes today."
        
        return True, "Can advance episode"
    
    def advance_episode(self, episodes_per_season: int = 7) -> tuple[bool, bool]:
        """
        Advance to next episode/season with daily limit check
        
        Returns:
            tuple[bool, bool]: (success, advanced_to_new_season)
        """
        can_advance, message = self.can_advance_episode()
        if not can_advance:
            raise ValueError(message)
        
        # Update daily usage
        self.daily_usage.episodes_played += 1
        self.daily_usage.last_episode_time = datetime.now()
        
        # Advance episode
        self.episodes_completed += 1
        self.episode += 1
        
        advanced_to_new_season = False
        if self.episode > episodes_per_season:
            self.episode = 1
            self.season += 1
            advanced_to_new_season = True
        
        return True, advanced_to_new_season
    
    def add_session_time(self, session_duration: float):
        """Add session time to daily usage"""
        self.update_daily_usage()
        self.daily_usage.total_session_time += session_duration
        self.daily_usage.sessions_count += 1
        self.total_time += session_duration


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


class User(BaseModel):
    """Complete user model with enhanced progress tracking"""
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
    """Enhanced response model for user data with daily limits"""
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
    
    # Daily usage information
    episodes_played_today: int
    remaining_episodes_today: int
    session_time_today_minutes: float
    sessions_today: int
    can_play_episode: bool
    
    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        """Create response from User model"""
        user.progress.update_daily_usage()  # Ensure daily usage is current
        
        return cls(
            device_id=user.device_id,
            name=user.name,
            age=user.age,
            status=user.status if isinstance(user.status, str) else user.status.value,
            season=user.progress.season,
            episode=user.progress.episode,
            words_learnt_count=len(user.progress.words_learnt),
            topics_learnt_count=len(user.progress.topics_learnt),
            total_time_hours=round(user.progress.total_time / 3600, 2),
            episodes_completed=user.progress.episodes_completed,
            created_at=user.created_at,
            last_active=user.last_active,
            
            # Daily usage
            episodes_played_today=user.progress.daily_usage.episodes_played,
            remaining_episodes_today=user.progress.daily_usage.remaining_episodes,
            session_time_today_minutes=round(user.progress.daily_usage.total_session_time / 60, 2),
            sessions_today=user.progress.daily_usage.sessions_count,
            can_play_episode=user.progress.daily_usage.can_play_episode
        )


class SessionInfo(BaseModel):
    """Enhanced current session information with daily limits"""
    device_id: str
    session_duration: float
    current_season: int
    current_episode: int
    is_connected: bool
    is_openai_connected: bool
    session_start_time: datetime
    
    # Daily limits info
    episodes_played_today: int
    remaining_episodes_today: int
    can_play_episode: bool


class DailyUsageStats(BaseModel):
    """Daily usage statistics for analytics"""
    date: str
    episodes_played: int
    session_time_minutes: float
    sessions_count: int
    efficiency_score: Optional[float] = None  # episodes per hour
    
    @classmethod
    def from_daily_usage(cls, daily_usage: DailyUsage) -> "DailyUsageStats":
        """Create stats from daily usage"""
        efficiency = None
        if daily_usage.total_session_time > 0:
            efficiency = (daily_usage.episodes_played * 3600) / daily_usage.total_session_time
        
        return cls(
            date=daily_usage.date,
            episodes_played=daily_usage.episodes_played,
            session_time_minutes=round(daily_usage.total_session_time / 60, 2),
            sessions_count=daily_usage.sessions_count,
            efficiency_score=round(efficiency, 2) if efficiency else None
        )