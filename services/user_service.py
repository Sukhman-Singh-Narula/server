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
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


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
    
    async def link_device_to_firebase_user(
        self, 
        device_id: str, 
        firebase_uid: str, 
        child_id: str, 
        parent_email: str
    ) -> bool:
        """
        Link an ESP32 device to a Firebase user account
        
        Args:
            device_id: ESP32 device identifier
            firebase_uid: Firebase user UID
            child_id: Child profile ID from mobile app
            parent_email: Parent's email address
            
        Returns:
            True if linking was successful
            
        Raises:
            ValidationException: If device or user data is invalid
            UserNotFoundException: If device is not found
        """
        try:
            # Get the existing device user
            existing_user = await self.get_user(device_id)
            
            # Update the user document with Firebase linking info
            update_data = {
                'firebase_uid': firebase_uid,
                'child_id': child_id,
                'parent_email': parent_email,
                'linked_at': self._get_current_timestamp(),
                'linked': True
            }
            
            # Update in Firebase/Firestore
            await self.firebase_service.update_user_document(device_id, update_data)
            
            logger.info(f"Device {device_id} linked to Firebase user {firebase_uid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to link device {device_id} to Firebase user {firebase_uid}: {e}")
            raise e

    async def get_devices_by_firebase_uid(self, firebase_uid: str) -> List[Dict[str, Any]]:
        """
        Get all devices linked to a Firebase user
        
        Args:
            firebase_uid: Firebase user UID
            
        Returns:
            List of device dictionaries with user info
        """
        try:
            # Query Firestore for all users with this Firebase UID
            users_collection = self.firebase_service.db.collection('users')
            query = users_collection.where('firebase_uid', '==', firebase_uid)
            docs = query.stream()
            
            devices = []
            for doc in docs:
                user_data = doc.to_dict()
                devices.append({
                    'device_id': doc.id,
                    'name': user_data.get('name'),
                    'age': user_data.get('age'),
                    'child_id': user_data.get('child_id'),
                    'linked_at': user_data.get('linked_at'),
                    'last_activity': user_data.get('last_activity'),
                    'current_episode': user_data.get('current_episode', 1),
                    'current_season': user_data.get('current_season', 1)
                })
            
            logger.info(f"Found {len(devices)} devices for Firebase user {firebase_uid}")
            return devices
            
        except Exception as e:
            logger.error(f"Failed to get devices for Firebase user {firebase_uid}: {e}")
            return []

    async def get_user_transcripts(self, device_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get conversation transcripts for a device
        
        Args:
            device_id: ESP32 device identifier
            limit: Maximum number of transcripts to return
            
        Returns:
            List of transcript dictionaries
        """
        try:
            # Query transcripts collection
            transcripts_collection = self.firebase_service.db.collection('transcripts')
            query = (transcripts_collection
                    .where('device_id', '==', device_id)
                    .order_by('timestamp', direction='DESCENDING')
                    .limit(limit))
            
            docs = query.stream()
            
            transcripts = []
            for doc in docs:
                transcript_data = doc.to_dict()
                transcripts.append({
                    'id': doc.id,
                    'date': transcript_data.get('date'),
                    'time': transcript_data.get('time'),
                    'duration': transcript_data.get('duration'),
                    'episode_title': transcript_data.get('episode_title'),
                    'conversation_count': transcript_data.get('conversation_count', 0),
                    'preview': transcript_data.get('preview', ''),
                    'timestamp': transcript_data.get('timestamp')
                })
            
            logger.info(f"Retrieved {len(transcripts)} transcripts for device {device_id}")
            return transcripts
            
        except Exception as e:
            logger.error(f"Failed to get transcripts for device {device_id}: {e}")
            return []

    async def save_conversation_transcript(
        self, 
        device_id: str, 
        conversation_data: Dict[str, Any]
    ) -> str:
        """
        Save a conversation transcript
        
        Args:
            device_id: ESP32 device identifier
            conversation_data: Dictionary containing conversation details
            
        Returns:
            Document ID of the saved transcript
        """
        try:
            transcript_doc = {
                'device_id': device_id,
                'date': conversation_data.get('date'),
                'time': conversation_data.get('time'),
                'duration': conversation_data.get('duration'),
                'episode_title': conversation_data.get('episode_title'),
                'season': conversation_data.get('season'),
                'episode': conversation_data.get('episode'),
                'conversation_count': conversation_data.get('conversation_count'),
                'preview': conversation_data.get('preview'),
                'full_transcript': conversation_data.get('full_transcript', []),
                'timestamp': self._get_current_timestamp(),
                'words_introduced': conversation_data.get('words_introduced', []),
                'topics_covered': conversation_data.get('topics_covered', [])
            }
            
            # Save to Firestore
            doc_ref = await self.firebase_service.db.collection('transcripts').add(transcript_doc)
            
            logger.info(f"Saved transcript for device {device_id}: {doc_ref.id}")
            return doc_ref.id
            
        except Exception as e:
            logger.error(f"Failed to save transcript for device {device_id}: {e}")
            raise e

    async def update_learning_progress(
        self, 
        device_id: str, 
        words_learned: List[str] = None,
        topics_learned: List[str] = None
    ) -> bool:
        """
        Update learning progress for a user
        
        Args:
            device_id: ESP32 device identifier
            words_learned: New words learned in this session
            topics_learned: New topics learned in this session
            
        Returns:
            True if update was successful
        """
        try:
            # Get current user data
            user_data = await self.get_user(device_id)
            
            # Update progress
            current_words = set(user_data.words_learnt or [])
            current_topics = set(user_data.topics_learnt or [])
            
            if words_learned:
                current_words.update(words_learned)
            
            if topics_learned:
                current_topics.update(topics_learned)
            
            update_data = {
                'words_learnt': list(current_words),
                'topics_learnt': list(current_topics),
                'last_activity': self._get_current_timestamp(),
                'total_words_count': len(current_words),
                'total_topics_count': len(current_topics)
            }
            
            # Update in Firestore
            await self.firebase_service.update_user_document(device_id, update_data)
            
            logger.info(f"Updated learning progress for device {device_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update learning progress for device {device_id}: {e}")
            raise e

    async def get_user_statistics(self, device_id: str) -> Dict[str, Any]:
        """
        Get comprehensive statistics for a user
        
        Args:
            device_id: ESP32 device identifier
            
        Returns:
            Dictionary containing user statistics
        """
        try:
            # Get user data
            user_data = await self.get_user(device_id)
            
            # Get session statistics from sessions collection
            sessions_collection = self.firebase_service.db.collection('sessions')
            query = sessions_collection.where('device_id', '==', device_id)
            sessions = list(query.stream())
            
            total_sessions = len(sessions)
            total_session_time = sum(
                session.to_dict().get('duration_seconds', 0) 
                for session in sessions
            )
            
            # Calculate streak days (simplified - you might want a more sophisticated calculation)
            streak_days = 0
            if user_data.last_activity:
                # Simple calculation - could be enhanced
                from datetime import datetime, timedelta
                last_activity = datetime.fromisoformat(user_data.last_activity.replace('Z', '+00:00'))
                now = datetime.now()
                if (now - last_activity).days < 2:  # Allow for one day gap
                    streak_days = 1  # Simplified streak calculation
            
            return {
                'words_learnt': user_data.words_learnt or [],
                'topics_learnt': user_data.topics_learnt or [],
                'total_sessions': total_sessions,
                'total_session_time': total_session_time,
                'current_episode': user_data.current_episode or 1,
                'current_season': user_data.current_season or 1,
                'last_activity': user_data.last_activity,
                'streak_days': streak_days,
                'total_words_count': len(user_data.words_learnt or []),
                'total_topics_count': len(user_data.topics_learnt or []),
                'average_session_duration': total_session_time / total_sessions if total_sessions > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Failed to get statistics for device {device_id}: {e}")
            return {
                'words_learnt': [],
                'topics_learnt': [],
                'total_sessions': 0,
                'total_session_time': 0,
                'current_episode': 1,
                'current_season': 1,
                'last_activity': None,
                'streak_days': 0,
                'total_words_count': 0,
                'total_topics_count': 0,
                'average_session_duration': 0
            }

    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'
    
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