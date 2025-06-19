"""
Firebase service for handling database operations
"""
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import Client, DocumentSnapshot, CollectionReference

from config.settings import get_settings
from models.user import User, UserProgress, UserStatus
from models.system_prompt import SystemPrompt, PromptType
from utils.exceptions import (
    FirebaseException, UserNotFoundException, UserAlreadyExistsException,
    SystemPromptNotFoundException
)
from utils.logger import LoggerMixin


class FirebaseService(LoggerMixin):
    """Service for Firebase Firestore operations"""
    
    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.db: Optional[Client] = None
        self._initialize_firebase()
    
    def _initialize_firebase(self):
        """Initialize Firebase Admin SDK"""
        try:
            # Check if Firebase is already initialized
            try:
                firebase_admin.get_app()
                self.log_info("Firebase already initialized")
            except ValueError:
                # Initialize Firebase
                cred = credentials.Certificate(self.settings.firebase_credentials_path)
                firebase_admin.initialize_app(cred)
                self.log_info("Firebase initialized successfully")
            
            self.db = firestore.client()
            
        except Exception as e:
            self.log_error(f"Failed to initialize Firebase: {e}", exc_info=True)
            raise FirebaseException("initialize", str(e))
    
    # User operations
    async def create_user(self, device_id: str, name: str, age: int) -> User:
        """
        Create a new user in Firebase
        
        Args:
            device_id: Unique device identifier
            name: User's name
            age: User's age
            
        Returns:
            User: Created user object
            
        Raises:
            UserAlreadyExistsException: If user already exists
            FirebaseException: If database operation fails
        """
        try:
            # Check if user already exists
            existing_user = await self.get_user(device_id, raise_if_not_found=False)
            if existing_user:
                raise UserAlreadyExistsException(device_id)
            
            # Create new user
            user = User(
                device_id=device_id,
                name=name,
                age=age,
                status=UserStatus.ACTIVE,
                progress=UserProgress(),
                created_at=datetime.now(),
                last_active=datetime.now()
            )
            
            # Save to Firebase
            user_data = self._user_to_dict(user)
            await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: self.db.collection('users').document(device_id).set(user_data)
            )
            
            self.log_info(f"User created: {device_id}", extra={"device_id": device_id})
            return user
            
        except UserAlreadyExistsException:
            raise
        except Exception as e:
            self.log_error(f"Failed to create user {device_id}: {e}", exc_info=True)
            raise FirebaseException("create_user", str(e), "users", device_id)
    
    async def get_user(self, device_id: str, raise_if_not_found: bool = True) -> Optional[User]:
        """
        Retrieve user from Firebase
        
        Args:
            device_id: Unique device identifier
            raise_if_not_found: Whether to raise exception if user not found
            
        Returns:
            Optional[User]: User object if found, None otherwise
            
        Raises:
            UserNotFoundException: If user not found and raise_if_not_found is True
            FirebaseException: If database operation fails
        """
        try:
            doc_snapshot = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.collection('users').document(device_id).get()
            )
            
            if not doc_snapshot.exists:
                if raise_if_not_found:
                    raise UserNotFoundException(device_id)
                return None
            
            user_data = doc_snapshot.to_dict()
            return self._dict_to_user(user_data)
            
        except UserNotFoundException:
            raise
        except Exception as e:
            self.log_error(f"Failed to get user {device_id}: {e}", exc_info=True)
            raise FirebaseException("get_user", str(e), "users", device_id)
    
    async def update_user(self, device_id: str, updates: Dict[str, Any]) -> User:
        """
        Update user data in Firebase
        
        Args:
            device_id: Unique device identifier
            updates: Dictionary of fields to update
            
        Returns:
            User: Updated user object
            
        Raises:
            UserNotFoundException: If user not found
            FirebaseException: If database operation fails
        """
        try:
            # Verify user exists
            await self.get_user(device_id)
            
            # Add timestamp to updates
            updates['last_active'] = datetime.now()
            
            # Update in Firebase
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.collection('users').document(device_id).update(updates)
            )
            
            # Return updated user
            return await self.get_user(device_id)
            
        except UserNotFoundException:
            raise
        except Exception as e:
            self.log_error(f"Failed to update user {device_id}: {e}", exc_info=True)
            raise FirebaseException("update_user", str(e), "users", device_id)
    
    async def update_user_progress(self, device_id: str, progress: UserProgress) -> User:
        """
        Update user progress in Firebase
        
        Args:
            device_id: Unique device identifier
            progress: Updated progress object
            
        Returns:
            User: Updated user object
        """
        updates = {
            'progress.season': progress.season,
            'progress.episode': progress.episode,
            'progress.words_learnt': progress.words_learnt,
            'progress.topics_learnt': progress.topics_learnt,
            'progress.total_time': progress.total_time,
            'progress.episodes_completed': progress.episodes_completed,
            'last_completed_episode': datetime.now()
        }
        
        return await self.update_user(device_id, updates)
    
    async def increment_user_time(self, device_id: str, time_seconds: float):
        """
        Increment user's total time spent
        
        Args:
            device_id: Unique device identifier
            time_seconds: Time to add in seconds
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.collection('users').document(device_id).update({
                    'progress.total_time': firestore.Increment(time_seconds),
                    'last_active': datetime.now()
                })
            )
            
        except Exception as e:
            self.log_error(f"Failed to increment time for {device_id}: {e}", exc_info=True)
            raise FirebaseException("increment_time", str(e), "users", device_id)
    
    # System prompt operations
    async def create_system_prompt(self, season: int, episode: int, prompt: str, 
                                 prompt_type: PromptType = PromptType.LEARNING,
                                 metadata: Dict[str, Any] = None) -> SystemPrompt:
        """
        Create or update system prompt in Firebase
        
        Args:
            season: Season number
            episode: Episode number
            prompt: Prompt content
            prompt_type: Type of prompt
            metadata: Additional metadata
            
        Returns:
            SystemPrompt: Created prompt object
        """
        try:
            prompt_obj = SystemPrompt(
                season=season,
                episode=episode,
                prompt=prompt,
                prompt_type=prompt_type,
                metadata=metadata or {},
                created_at=datetime.now(),
                updated_at=datetime.now(),
                version=1,
                is_active=True
            )
            
            # Check if prompt already exists to increment version
            existing_prompt = await self.get_system_prompt(season, episode, raise_if_not_found=False)
            if existing_prompt:
                prompt_obj.version = existing_prompt.version + 1
            
            prompt_data = self._system_prompt_to_dict(prompt_obj)
            doc_id = f"season_{season}_episode_{episode}"
            
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.collection('system_prompts').document(doc_id).set(prompt_data)
            )
            
            self.log_info(f"System prompt created: Season {season}, Episode {episode}")
            return prompt_obj
            
        except Exception as e:
            self.log_error(f"Failed to create system prompt S{season}E{episode}: {e}", exc_info=True)
            raise FirebaseException("create_system_prompt", str(e), "system_prompts")
    
    async def get_system_prompt(self, season: int, episode: int, 
                              raise_if_not_found: bool = True) -> Optional[SystemPrompt]:
        """
        Retrieve system prompt from Firebase
        
        Args:
            season: Season number
            episode: Episode number
            raise_if_not_found: Whether to raise exception if not found
            
        Returns:
            Optional[SystemPrompt]: Prompt object if found, None otherwise
        """
        try:
            doc_id = f"season_{season}_episode_{episode}"
            doc_snapshot = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.collection('system_prompts').document(doc_id).get()
            )
            
            if not doc_snapshot.exists:
                if raise_if_not_found:
                    raise SystemPromptNotFoundException(season, episode)
                return None
            
            prompt_data = doc_snapshot.to_dict()
            return self._dict_to_system_prompt(prompt_data)
            
        except SystemPromptNotFoundException:
            raise
        except Exception as e:
            self.log_error(f"Failed to get system prompt S{season}E{episode}: {e}", exc_info=True)
            raise FirebaseException("get_system_prompt", str(e), "system_prompts")
    
    async def get_all_prompts_for_season(self, season: int) -> List[SystemPrompt]:
        """
        Get all prompts for a specific season
        
        Args:
            season: Season number
            
        Returns:
            List[SystemPrompt]: List of prompts for the season
        """
        try:
            prompts = []
            query = self.db.collection('system_prompts').where('season', '==', season)
            
            docs = await asyncio.get_event_loop().run_in_executor(
                None, lambda: query.get()
            )
            
            for doc in docs:
                prompt_data = doc.to_dict()
                prompts.append(self._dict_to_system_prompt(prompt_data))
            
            return sorted(prompts, key=lambda p: p.episode)
            
        except Exception as e:
            self.log_error(f"Failed to get prompts for season {season}: {e}", exc_info=True)
            raise FirebaseException("get_season_prompts", str(e), "system_prompts")
    
    # Utility methods
    def _user_to_dict(self, user: User) -> Dict[str, Any]:
        """Convert User object to dictionary for Firebase"""
        return {
            'device_id': user.device_id,
            'name': user.name,
            'age': user.age,
            'status': user.status if isinstance(user.status, str) else user.status.value,
            'progress': {
                'season': user.progress.season,
                'episode': user.progress.episode,
                'words_learnt': user.progress.words_learnt,
                'topics_learnt': user.progress.topics_learnt,
                'total_time': user.progress.total_time,
                'episodes_completed': user.progress.episodes_completed
            },
            'created_at': user.created_at,
            'last_active': user.last_active,
            'last_completed_episode': user.last_completed_episode
        }
    
    def _dict_to_user(self, data: Dict[str, Any]) -> User:
        """Convert Firebase dictionary to User object"""
        progress_data = data.get('progress', {})
        progress = UserProgress(
            season=progress_data.get('season', 1),
            episode=progress_data.get('episode', 1),
            words_learnt=progress_data.get('words_learnt', []),
            topics_learnt=progress_data.get('topics_learnt', []),
            total_time=progress_data.get('total_time', 0.0),
            episodes_completed=progress_data.get('episodes_completed', 0)
        )
        
        return User(
            device_id=data['device_id'],
            name=data['name'],
            age=data['age'],
            status=UserStatus(data.get('status', 'active')),
            progress=progress,
            created_at=data.get('created_at'),
            last_active=data.get('last_active'),
            last_completed_episode=data.get('last_completed_episode')
        )
    
    def _system_prompt_to_dict(self, prompt: SystemPrompt) -> Dict[str, Any]:
        """Convert SystemPrompt object to dictionary for Firebase"""
        return {
            'season': prompt.season,
            'episode': prompt.episode,
            'prompt': prompt.prompt,
            'prompt_type': prompt.prompt_type if isinstance(prompt.prompt_type, str) else prompt.prompt_type.value,
            'metadata': prompt.metadata,
            'created_at': prompt.created_at,
            'updated_at': prompt.updated_at,
            'version': prompt.version,
            'is_active': prompt.is_active
        }
    
    def _dict_to_system_prompt(self, data: Dict[str, Any]) -> SystemPrompt:
        """Convert Firebase dictionary to SystemPrompt object"""
        return SystemPrompt(
            season=data['season'],
            episode=data['episode'],
            prompt=data['prompt'],
            prompt_type=PromptType(data.get('prompt_type', 'learning')),
            metadata=data.get('metadata', {}),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            version=data.get('version', 1),
            is_active=data.get('is_active', True)
        )
    
    async def health_check(self) -> bool:
        """Check Firebase connection health"""
        try:
            # Try a simple read operation
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.collection('_health_check').limit(1).get()
            )
            return True
        except Exception as e:
            self.log_error(f"Firebase health check failed: {e}")
            return False


# Global Firebase service instance
_firebase_service: Optional[FirebaseService] = None


def get_firebase_service() -> FirebaseService:
    """Get Firebase service singleton"""
    global _firebase_service
    if _firebase_service is None:
        _firebase_service = FirebaseService()
    return _firebase_service