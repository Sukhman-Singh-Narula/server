"""
Enhanced Firebase service with daily limits and conversation storage
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import Client, DocumentSnapshot, CollectionReference

from config.settings import get_settings
from models.user import User, UserProgress, UserStatus, DailyUsage
from models.system_prompt import SystemPrompt, PromptType
from models.conversation import ConversationSearchRequest, TranscriptExportRequest
from utils.exceptions import (
    FirebaseException, UserNotFoundException, UserAlreadyExistsException,
    SystemPromptNotFoundException
)
from utils.logger import LoggerMixin


class FirebaseService(LoggerMixin):
    """Enhanced service for Firebase Firestore operations with conversation storage"""
    
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
    
    # Enhanced User operations with daily limits
    async def create_user(self, device_id: str, name: str, age: int) -> User:
        """
        Create a new user in Firebase with enhanced progress tracking
        
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
            
            # Create new user with enhanced progress
            user = User(
                device_id=device_id,
                name=name,
                age=age,
                status=UserStatus.ACTIVE,
                progress=UserProgress(),  # This includes daily usage tracking
                created_at=datetime.now(),
                last_active=datetime.now()
            )
            
            # Save to Firebase
            user_data = self._user_to_dict(user)
            await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: self.db.collection('users').document(device_id).set(user_data)
            )
            
            self.log_info(f"User created with daily limits: {device_id}", extra={"device_id": device_id})
            return user
            
        except UserAlreadyExistsException:
            raise
        except Exception as e:
            self.log_error(f"Failed to create user {device_id}: {e}", exc_info=True)
            raise FirebaseException("create_user", str(e), "users", device_id)
    
    async def get_user(self, device_id: str, raise_if_not_found: bool = True) -> Optional[User]:
        """
        Retrieve user from Firebase with enhanced progress
        
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
    
    async def update_user_progress(self, device_id: str, progress: UserProgress) -> User:
        """
        Update user progress in Firebase with daily usage
        
        Args:
            device_id: Unique device identifier
            progress: Updated progress object with daily usage
            
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
            
            # Daily usage updates
            'progress.daily_usage': self._daily_usage_to_dict(progress.daily_usage),
            'progress.usage_history': [self._daily_usage_to_dict(usage) for usage in progress.usage_history],
            
            'last_completed_episode': datetime.now(),
            'last_active': datetime.now()
        }
        
        return await self.update_user(device_id, updates)
    
    # Conversation storage operations
    async def save_conversation_session(self, session_id: str, session_data: Dict[str, Any]):
        """
        Save conversation session to Firebase
        
        Args:
            session_id: Unique session identifier
            session_data: Session data dictionary
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.collection('conversation_sessions').document(session_id).set(session_data)
            )
            
            self.log_info(f"Conversation session saved: {session_id}")
            
        except Exception as e:
            self.log_error(f"Failed to save conversation session {session_id}: {e}", exc_info=True)
            raise FirebaseException("save_conversation_session", str(e), "conversation_sessions", session_id)
    
    async def get_conversation_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get conversation session from Firebase
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            Optional[Dict]: Session data if found, None otherwise
        """
        try:
            doc_snapshot = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.collection('conversation_sessions').document(session_id).get()
            )
            
            if not doc_snapshot.exists:
                return None
            
            return doc_snapshot.to_dict()
            
        except Exception as e:
            self.log_error(f"Failed to get conversation session {session_id}: {e}", exc_info=True)
            raise FirebaseException("get_conversation_session", str(e), "conversation_sessions", session_id)
    
    async def get_user_conversation_sessions(self, device_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get conversation sessions for a user
        
        Args:
            device_id: Device identifier
            limit: Maximum number of sessions to return
            
        Returns:
            List[Dict]: List of session data
        """
        try:
            query = (self.db.collection('conversation_sessions')
                    .where('device_id', '==', device_id)
                    .order_by('start_time', direction=firestore.Query.DESCENDING)
                    .limit(limit))
            
            docs = await asyncio.get_event_loop().run_in_executor(
                None, lambda: query.get()
            )
            
            sessions = []
            for doc in docs:
                sessions.append(doc.to_dict())
            
            return sessions
            
        except Exception as e:
            self.log_error(f"Failed to get conversation sessions for {device_id}: {e}", exc_info=True)
            raise FirebaseException("get_user_conversation_sessions", str(e), "conversation_sessions")
    
    async def get_user_conversation_sessions_in_range(self, device_id: str, 
                                                    start_date: datetime, 
                                                    end_date: datetime) -> List[Dict[str, Any]]:
        """
        Get conversation sessions for a user within a date range
        
        Args:
            device_id: Device identifier
            start_date: Start date
            end_date: End date
            
        Returns:
            List[Dict]: List of session data
        """
        try:
            query = (self.db.collection('conversation_sessions')
                    .where('device_id', '==', device_id)
                    .where('start_time', '>=', start_date)
                    .where('start_time', '<=', end_date)
                    .order_by('start_time', direction=firestore.Query.DESCENDING))
            
            docs = await asyncio.get_event_loop().run_in_executor(
                None, lambda: query.get()
            )
            
            sessions = []
            for doc in docs:
                sessions.append(doc.to_dict())
            
            return sessions
            
        except Exception as e:
            self.log_error(f"Failed to get conversation sessions in range for {device_id}: {e}", exc_info=True)
            raise FirebaseException("get_user_conversation_sessions_in_range", str(e), "conversation_sessions")
    
    async def search_conversation_sessions(self, search_request: ConversationSearchRequest) -> List[Dict[str, Any]]:
        """
        Search conversation sessions based on criteria
        
        Args:
            search_request: Search criteria
            
        Returns:
            List[Dict]: Matching session data
        """
        try:
            query = self.db.collection('conversation_sessions')
            
            # Apply filters
            if search_request.device_id:
                query = query.where('device_id', '==', search_request.device_id)
            
            if search_request.season:
                query = query.where('season', '==', search_request.season)
            
            if search_request.episode:
                query = query.where('episode', '==', search_request.episode)
            
            if search_request.start_date:
                query = query.where('start_time', '>=', search_request.start_date)
            
            if search_request.end_date:
                query = query.where('start_time', '<=', search_request.end_date)
            
            # Apply ordering and limit
            query = query.order_by('start_time', direction=firestore.Query.DESCENDING)
            query = query.limit(search_request.limit)
            
            docs = await asyncio.get_event_loop().run_in_executor(
                None, lambda: query.get()
            )
            
            sessions = []
            for doc in docs:
                session_data = doc.to_dict()
                
                # Apply text search if specified (client-side filtering)
                if search_request.search_text:
                    found_text = False
                    for message in session_data.get('messages', []):
                        if search_request.search_text.lower() in message.get('content', '').lower():
                            found_text = True
                            break
                    
                    if not found_text:
                        continue
                
                # Apply message type filter (client-side filtering)
                if search_request.message_type:
                    found_type = False
                    for message in session_data.get('messages', []):
                        if message.get('type') == search_request.message_type.value:
                            found_type = True
                            break
                    
                    if not found_type:
                        continue
                
                sessions.append(session_data)
            
            return sessions
            
        except Exception as e:
            self.log_error(f"Failed to search conversation sessions: {e}", exc_info=True)
            raise FirebaseException("search_conversation_sessions", str(e), "conversation_sessions")
    
    async def get_conversation_sessions_for_export(self, export_request: TranscriptExportRequest) -> List[Dict[str, Any]]:
        """
        Get conversation sessions for export based on criteria
        
        Args:
            export_request: Export request criteria
            
        Returns:
            List[Dict]: Session data for export
        """
        try:
            query = self.db.collection('conversation_sessions').where('device_id', '==', export_request.device_id)
            
            # Apply specific session IDs if provided
            if export_request.session_ids:
                # For specific sessions, we need to get them individually
                sessions = []
                for session_id in export_request.session_ids:
                    session_data = await self.get_conversation_session(session_id)
                    if session_data:
                        sessions.append(session_data)
                return sessions
            
            # Apply other filters
            if export_request.season:
                query = query.where('season', '==', export_request.season)
            
            if export_request.episode:
                query = query.where('episode', '==', export_request.episode)
            
            if export_request.start_date:
                query = query.where('start_time', '>=', export_request.start_date)
            
            if export_request.end_date:
                query = query.where('start_time', '<=', export_request.end_date)
            
            # Apply ordering
            query = query.order_by('start_time', direction=firestore.Query.ASCENDING)
            
            docs = await asyncio.get_event_loop().run_in_executor(
                None, lambda: query.get()
            )
            
            sessions = []
            for doc in docs:
                sessions.append(doc.to_dict())
            
            return sessions
            
        except Exception as e:
            self.log_error(f"Failed to get conversation sessions for export: {e}", exc_info=True)
            raise FirebaseException("get_conversation_sessions_for_export", str(e), "conversation_sessions")
    
    # System prompt operations (unchanged)
    async def create_system_prompt(self, season: int, episode: int, prompt: str, 
                                 prompt_type: PromptType = PromptType.LEARNING,
                                 metadata: Dict[str, Any] = None) -> SystemPrompt:
        """Create or update system prompt in Firebase"""
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
        """Retrieve system prompt from Firebase"""
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
        """Get all prompts for a specific season"""
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
    
    # Enhanced utility methods
    def _user_to_dict(self, user: User) -> Dict[str, Any]:
        """Convert User object to dictionary for Firebase with daily usage"""
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
                'episodes_completed': user.progress.episodes_completed,
                'daily_usage': self._daily_usage_to_dict(user.progress.daily_usage),
                'usage_history': [self._daily_usage_to_dict(usage) for usage in user.progress.usage_history]
            },
            'created_at': user.created_at,
            'last_active': user.last_active,
            'last_completed_episode': user.last_completed_episode
        }
    
    def _dict_to_user(self, data: Dict[str, Any]) -> User:
        """Convert Firebase dictionary to User object with daily usage"""
        progress_data = data.get('progress', {})
        
        # Handle daily usage
        daily_usage_data = progress_data.get('daily_usage', {})
        daily_usage = DailyUsage(
            date=daily_usage_data.get('date', datetime.now().date().isoformat()),
            episodes_played=daily_usage_data.get('episodes_played', 0),
            total_session_time=daily_usage_data.get('total_session_time', 0.0),
            sessions_count=daily_usage_data.get('sessions_count', 0),
            last_episode_time=daily_usage_data.get('last_episode_time')
        )
        
        # Handle usage history
        usage_history = []
        for usage_data in progress_data.get('usage_history', []):
            usage = DailyUsage(
                date=usage_data.get('date'),
                episodes_played=usage_data.get('episodes_played', 0),
                total_session_time=usage_data.get('total_session_time', 0.0),
                sessions_count=usage_data.get('sessions_count', 0),
                last_episode_time=usage_data.get('last_episode_time')
            )
            usage_history.append(usage)
        
        progress = UserProgress(
            season=progress_data.get('season', 1),
            episode=progress_data.get('episode', 1),
            words_learnt=progress_data.get('words_learnt', []),
            topics_learnt=progress_data.get('topics_learnt', []),
            total_time=progress_data.get('total_time', 0.0),
            episodes_completed=progress_data.get('episodes_completed', 0),
            daily_usage=daily_usage,
            usage_history=usage_history
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
    
    def _daily_usage_to_dict(self, daily_usage: DailyUsage) -> Dict[str, Any]:
        """Convert DailyUsage to dictionary"""
        return {
            'date': daily_usage.date,
            'episodes_played': daily_usage.episodes_played,
            'total_session_time': daily_usage.total_session_time,
            'sessions_count': daily_usage.sessions_count,
            'last_episode_time': daily_usage.last_episode_time
        }
    
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
    
    async def update_user(self, device_id: str, updates: Dict[str, Any]) -> User:
        """Update user data in Firebase"""
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
    
    async def increment_user_time(self, device_id: str, time_seconds: float):
        """Increment user's total time spent"""
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