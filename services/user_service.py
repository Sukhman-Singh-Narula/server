"""
Enhanced User service with daily episode limits and conversation tracking
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, date

from models.user import (
    User, UserProgress, UserRegistrationRequest, UserResponse, 
    SessionInfo, DailyUsage, DailyUsageStats
)
from services.firebase_service import get_firebase_service
from utils.exceptions import (
    UserAlreadyExistsException, UserNotFoundException, ValidationException
)
from utils.validators import UserValidator, DeviceValidator
from utils.logger import LoggerMixin, log_user_registration


class UserService(LoggerMixin):
    """Enhanced service for user-related operations with daily limits"""
    
    def __init__(self):
        super().__init__()
        self.firebase_service = get_firebase_service()
    
    async def register_user(self, registration_data: UserRegistrationRequest) -> UserResponse:
        """
        Register a new user
        
        Args:
            registration_data: User registration information
            
        Returns:
            UserResponse: Created user information
            
        Raises:
            ValidationException: If validation fails
            UserAlreadyExistsException: If user already exists
        """
        # Validate device ID
        if not DeviceValidator.validate_device_id(registration_data.device_id):
            error_msg = DeviceValidator.get_device_validation_error(registration_data.device_id)
            raise ValidationException(error_msg, "device_id", registration_data.device_id)
        
        # Validate user name
        is_valid, error_msg = UserValidator.validate_user_name(registration_data.name)
        if not is_valid:
            raise ValidationException(error_msg, "name", registration_data.name)
        
        # Validate user age
        is_valid, error_msg = UserValidator.validate_user_age(registration_data.age)
        if not is_valid:
            raise ValidationException(error_msg, "age", registration_data.age)
        
        try:
            # Create user in Firebase
            user = await self.firebase_service.create_user(
                device_id=registration_data.device_id,
                name=registration_data.name,
                age=registration_data.age
            )
            
            # Log registration
            log_user_registration(registration_data.device_id, registration_data.name, registration_data.age)
            
            # Return user response
            return UserResponse.from_user(user)
            
        except UserAlreadyExistsException:
            raise
        except Exception as e:
            self.log_error(f"Failed to register user {registration_data.device_id}: {e}")
            raise ValidationException(f"Registration failed: {str(e)}")
    
    async def get_user(self, device_id: str) -> UserResponse:
        """
        Get user information with current daily usage
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            UserResponse: User information with daily limits
            
        Raises:
            ValidationException: If device ID is invalid
            UserNotFoundException: If user not found
        """
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Get user from Firebase
        user = await self.firebase_service.get_user(device_id)
        
        # Update daily usage to ensure it's current
        user.progress.update_daily_usage()
        
        # Save updated daily usage if it changed
        await self.firebase_service.update_user_progress(device_id, user.progress)
        
        return UserResponse.from_user(user)
    
    async def check_episode_limit(self, device_id: str) -> Dict[str, Any]:
        """
        Check if user can play another episode today
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            Dict with limit information
        """
        user = await self.firebase_service.get_user(device_id)
        user.progress.update_daily_usage()
        
        daily_usage = user.progress.daily_usage
        
        return {
            "device_id": device_id,
            "date": daily_usage.date,
            "episodes_played_today": daily_usage.episodes_played,
            "remaining_episodes": daily_usage.remaining_episodes,
            "can_play_episode": daily_usage.can_play_episode,
            "daily_limit": 3,
            "last_episode_time": daily_usage.last_episode_time,
            "total_session_time_today": round(daily_usage.total_session_time / 60, 2)  # minutes
        }
    
    async def advance_episode(self, device_id: str) -> UserResponse:
        """
        Advance user to next episode/season with daily limit check
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            UserResponse: Updated user information
            
        Raises:
            ValidationException: If daily limit exceeded or other validation fails
        """
        from config.settings import get_settings
        settings = get_settings()
        
        # Get current user
        user = await self.firebase_service.get_user(device_id)
        
        # Check daily limit
        can_advance, message = user.progress.can_advance_episode()
        if not can_advance:
            self.log_warning(f"Episode advance blocked for {device_id}: {message}")
            raise ValidationException(message, "daily_limit", user.progress.daily_usage.episodes_played)
        
        # Store old progress for logging
        old_progress = user.progress.dict()
        
        try:
            # Advance episode (this will also update daily usage)
            success, advanced_to_new_season = user.progress.advance_episode(settings.episodes_per_season)
            
            if not success:
                raise ValidationException("Failed to advance episode")
            
            # Update in Firebase
            updated_user = await self.firebase_service.update_user_progress(device_id, user.progress)
            
            # Log progress update
            from utils.logger import log_user_progress
            log_user_progress(device_id, old_progress, user.progress.dict())
            
            # Log daily limit usage
            self.log_info(f"Episode advanced for {device_id} - Season {user.progress.season}, Episode {user.progress.episode}. Daily usage: {user.progress.daily_usage.episodes_played}/3")
            
            if advanced_to_new_season:
                self.log_info(f"User {device_id} advanced to new season: {user.progress.season}")
            
            return UserResponse.from_user(updated_user)
            
        except ValueError as e:
            # This should be caught by the can_advance_episode check, but just in case
            raise ValidationException(str(e), "daily_limit")
        except Exception as e:
            self.log_error(f"Failed to advance episode for {device_id}: {e}")
            raise ValidationException(f"Failed to advance episode: {str(e)}")
    
    async def update_user_progress(self, device_id: str, words_learnt: List[str] = None,
                                 topics_learnt: List[str] = None) -> UserResponse:
        """
        Update user learning progress
        
        Args:
            device_id: Unique device identifier
            words_learnt: New words learned
            topics_learnt: New topics learned
            
        Returns:
            UserResponse: Updated user information
        """
        # Get current user
        user = await self.firebase_service.get_user(device_id)
        
        # Update progress
        if words_learnt:
            # Add new words (avoid duplicates)
            existing_words = set(user.progress.words_learnt)
            new_words = [word for word in words_learnt if word not in existing_words]
            user.progress.words_learnt.extend(new_words)
            self.log_info(f"Added {len(new_words)} new words for {device_id}")
        
        if topics_learnt:
            # Add new topics (avoid duplicates)
            existing_topics = set(user.progress.topics_learnt)
            new_topics = [topic for topic in topics_learnt if topic not in existing_topics]
            user.progress.topics_learnt.extend(new_topics)
            self.log_info(f"Added {len(new_topics)} new topics for {device_id}")
        
        # Update daily usage
        user.progress.update_daily_usage()
        
        # Update in Firebase
        updated_user = await self.firebase_service.update_user_progress(device_id, user.progress)
        
        self.log_info(f"Progress updated for user {device_id}")
        return UserResponse.from_user(updated_user)
    
    async def add_session_time(self, device_id: str, session_duration: float):
        """
        Add session time to user's daily usage
        
        Args:
            device_id: Unique device identifier
            session_duration: Session duration in seconds
        """
        try:
            user = await self.firebase_service.get_user(device_id)
            user.progress.add_session_time(session_duration)
            
            # Update in Firebase
            await self.firebase_service.update_user_progress(device_id, user.progress)
            
            self.log_info(f"Added {session_duration:.1f}s session time for {device_id}. Daily total: {user.progress.daily_usage.total_session_time:.1f}s")
            
        except Exception as e:
            self.log_error(f"Failed to add session time for {device_id}: {e}")
    
    async def get_user_session_info(self, device_id: str, session_duration: float = 0.0,
                                  is_connected: bool = False, is_openai_connected: bool = False) -> SessionInfo:
        """
        Get current session information for user with daily limits
        
        Args:
            device_id: Unique device identifier
            session_duration: Current session duration in seconds
            is_connected: Whether WebSocket is connected
            is_openai_connected: Whether OpenAI connection is active
            
        Returns:
            SessionInfo: Current session information with daily limits
        """
        # Get user data
        user = await self.firebase_service.get_user(device_id)
        user.progress.update_daily_usage()
        
        return SessionInfo(
            device_id=device_id,
            session_duration=session_duration,
            current_season=user.progress.season,
            current_episode=user.progress.episode,
            is_connected=is_connected,
            is_openai_connected=is_openai_connected,
            session_start_time=datetime.now(),  # This would be tracked by connection manager
            
            # Daily limits info
            episodes_played_today=user.progress.daily_usage.episodes_played,
            remaining_episodes_today=user.progress.daily_usage.remaining_episodes,
            can_play_episode=user.progress.daily_usage.can_play_episode
        )
    
    async def get_daily_usage_stats(self, device_id: str, days: int = 7) -> List[DailyUsageStats]:
        """
        Get daily usage statistics for the past N days
        
        Args:
            device_id: Unique device identifier
            days: Number of past days to include
            
        Returns:
            List[DailyUsageStats]: Daily usage statistics
        """
        user = await self.firebase_service.get_user(device_id)
        user.progress.update_daily_usage()
        
        stats = []
        
        # Add current day
        stats.append(DailyUsageStats.from_daily_usage(user.progress.daily_usage))
        
        # Add historical days (up to requested number)
        for usage in reversed(user.progress.usage_history[-days+1:]):
            stats.insert(0, DailyUsageStats.from_daily_usage(usage))
        
        return stats[-days:]  # Ensure we only return requested number of days
    
    async def get_user_statistics(self, device_id: str) -> Dict[str, Any]:
        """
        Get comprehensive user statistics with daily usage
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            Dict[str, Any]: User statistics including daily limits
        """
        user = await self.firebase_service.get_user(device_id)
        user.progress.update_daily_usage()
        
        # Calculate weekly and monthly totals
        weekly_episodes = sum(usage.episodes_played for usage in user.progress.usage_history[-7:])
        weekly_episodes += user.progress.daily_usage.episodes_played
        
        monthly_episodes = sum(usage.episodes_played for usage in user.progress.usage_history[-30:])
        monthly_episodes += user.progress.daily_usage.episodes_played
        
        return {
            "user_info": {
                "device_id": user.device_id,
                "name": user.name,
                "age": user.age,
                "status": user.status.value,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_active": user.last_active.isoformat() if user.last_active else None
            },
            "learning_progress": {
                "current_season": user.progress.season,
                "current_episode": user.progress.episode,
                "total_episodes_completed": user.progress.episodes_completed,
                "words_learnt_count": len(user.progress.words_learnt),
                "topics_learnt_count": len(user.progress.topics_learnt),
                "words_learnt": user.progress.words_learnt,
                "topics_learnt": user.progress.topics_learnt
            },
            "time_statistics": {
                "total_time_seconds": user.progress.total_time,
                "total_time_hours": round(user.progress.total_time / 3600, 2),
                "average_session_time": self._calculate_average_session_time(user),
                "last_completed_episode": user.last_completed_episode.isoformat() if user.last_completed_episode else None
            },
            "daily_usage": {
                "today": {
                    "episodes_played": user.progress.daily_usage.episodes_played,
                    "remaining_episodes": user.progress.daily_usage.remaining_episodes,
                    "session_time_minutes": round(user.progress.daily_usage.total_session_time / 60, 2),
                    "sessions_count": user.progress.daily_usage.sessions_count,
                    "can_play_episode": user.progress.daily_usage.can_play_episode
                },
                "weekly_episodes": weekly_episodes,
                "monthly_episodes": monthly_episodes,
                "daily_limit": 3
            },
            "completion_stats": {
                "completion_rate": self._calculate_completion_rate(user),
                "episodes_remaining_in_season": 7 - user.progress.episode,
                "estimated_season_completion": self._estimate_completion_time(user)
            }
        }
    
    def _calculate_average_session_time(self, user: User) -> float:
        """Calculate average session time for user"""
        total_sessions = user.progress.daily_usage.sessions_count
        for usage in user.progress.usage_history:
            total_sessions += usage.sessions_count
        
        if total_sessions == 0:
            return 0.0
        
        total_time = user.progress.total_time
        return total_time / total_sessions
    
    def _calculate_completion_rate(self, user: User) -> float:
        """Calculate learning completion rate as percentage"""
        from config.settings import get_settings
        settings = get_settings()
        
        total_possible_episodes = settings.max_seasons * settings.episodes_per_season
        completion_percentage = (user.progress.episodes_completed / total_possible_episodes) * 100
        return round(completion_percentage, 2)
    
    def _estimate_completion_time(self, user: User) -> Optional[str]:
        """Estimate time to complete current season"""
        if user.progress.episodes_completed == 0:
            return None
        
        avg_time_per_episode = self._calculate_average_session_time(user)
        episodes_remaining = 7 - user.progress.episode
        
        estimated_seconds = avg_time_per_episode * episodes_remaining
        estimated_hours = estimated_seconds / 3600
        
        if estimated_hours < 1:
            return f"{int(estimated_seconds / 60)} minutes"
        else:
            return f"{estimated_hours:.1f} hours"
    
    async def delete_user(self, device_id: str) -> bool:
        """
        Delete user account (soft delete by changing status)
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            bool: True if deleted successfully
        """
        try:
            from models.user import UserStatus
            
            # Update user status to inactive
            await self.firebase_service.update_user(device_id, {
                "status": UserStatus.INACTIVE.value,
                "deleted_at": datetime.now()
            })
            
            self.log_info(f"User soft deleted: {device_id}")
            return True
            
        except Exception as e:
            self.log_error(f"Failed to delete user {device_id}: {e}")
            return False


# Global user service instance
_user_service: Optional[UserService] = None


def get_user_service() -> UserService:
    """Get user service singleton"""
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service