"""
User service for handling user-related business logic
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from models.user import User, UserProgress, UserRegistrationRequest, UserResponse, SessionInfo
from services.firebase_service import get_firebase_service
from utils.exceptions import UserAlreadyExistsException, UserNotFoundException, ValidationException
from utils.validators import UserValidator, DeviceValidator
from utils.logger import LoggerMixin, log_user_registration


class UserService(LoggerMixin):
    """Service for user-related operations"""
    
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
        Get user information
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            UserResponse: User information
            
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
        return UserResponse.from_user(user)
    
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
        
        if topics_learnt:
            # Add new topics (avoid duplicates)
            existing_topics = set(user.progress.topics_learnt)
            new_topics = [topic for topic in topics_learnt if topic not in existing_topics]
            user.progress.topics_learnt.extend(new_topics)
        
        # Update in Firebase
        updated_user = await self.firebase_service.update_user_progress(device_id, user.progress)
        
        self.log_info(f"Progress updated for user {device_id}")
        return UserResponse.from_user(updated_user)
    
    async def advance_episode(self, device_id: str) -> UserResponse:
        """
        Advance user to next episode/season
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            UserResponse: Updated user information
        """
        from config.settings import get_settings
        settings = get_settings()
        
        # Get current user
        user = await self.firebase_service.get_user(device_id)
        
        # Store old progress for logging
        old_progress = user.progress.dict()
        
        # Advance episode
        advanced_to_new_season = user.progress.advance_episode(settings.episodes_per_season)
        
        # Update in Firebase
        updated_user = await self.firebase_service.update_user_progress(device_id, user.progress)
        
        # Log progress update
        from utils.logger import log_user_progress
        log_user_progress(device_id, old_progress, user.progress.dict())
        
        self.log_info(f"Episode advanced for user {device_id} - Season {user.progress.season}, Episode {user.progress.episode}")
        
        return UserResponse.from_user(updated_user)
    
    async def get_user_session_info(self, device_id: str, session_duration: float = 0.0,
                                  is_connected: bool = False, is_openai_connected: bool = False) -> SessionInfo:
        """
        Get current session information for user
        
        Args:
            device_id: Unique device identifier
            session_duration: Current session duration in seconds
            is_connected: Whether WebSocket is connected
            is_openai_connected: Whether OpenAI connection is active
            
        Returns:
            SessionInfo: Current session information
        """
        # Get user data
        user = await self.firebase_service.get_user(device_id)
        
        return SessionInfo(
            device_id=device_id,
            session_duration=session_duration,
            current_season=user.progress.season,
            current_episode=user.progress.episode,
            is_connected=is_connected,
            is_openai_connected=is_openai_connected,
            session_start_time=datetime.now()  # This would be tracked by connection manager
        )
    
    async def get_user_statistics(self, device_id: str) -> Dict[str, Any]:
        """
        Get comprehensive user statistics
        
        Args:
            device_id: Unique device identifier
            
        Returns:
            Dict[str, Any]: User statistics
        """
        user = await self.firebase_service.get_user(device_id)
        
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
            "completion_stats": {
                "completion_rate": self._calculate_completion_rate(user),
                "episodes_remaining_in_season": 7 - user.progress.episode,
                "estimated_season_completion": self._estimate_completion_time(user)
            }
        }
    
    def _calculate_average_session_time(self, user: User) -> float:
        """Calculate average session time for user"""
        if user.progress.episodes_completed == 0:
            return 0.0
        return user.progress.total_time / user.progress.episodes_completed
    
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
    
    async def search_users(self, name_query: str = None, min_age: int = None, 
                         max_age: int = None, season: int = None) -> List[UserResponse]:
        """
        Search users based on criteria (Note: This would require Firestore queries)
        
        Args:
            name_query: Partial name to search for
            min_age: Minimum age filter
            max_age: Maximum age filter
            season: Current season filter
            
        Returns:
            List[UserResponse]: Matching users
        """
        # Note: This is a simplified implementation
        # In a real application, you'd implement proper Firestore queries
        self.log_info("Search functionality would require Firestore collection queries")
        return []
    
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