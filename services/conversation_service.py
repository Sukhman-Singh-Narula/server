"""
Conversation service for managing conversation transcripts and analytics
"""
import uuid
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from models.conversation import (
    ConversationSession, ConversationMessage, MessageType, ConversationSummary,
    ConversationSearchRequest, ConversationAnalytics, TranscriptExportRequest,
    ConversationStats
)
from services.firebase_service import get_firebase_service
from utils.exceptions import ValidationException
from utils.logger import LoggerMixin


class ConversationService(LoggerMixin):
    """Service for managing conversation transcripts and analytics"""
    
    def __init__(self):
        super().__init__()
        self.firebase_service = get_firebase_service()
        self.active_sessions: Dict[str, ConversationSession] = {}  # device_id -> session
    
    async def start_session(self, device_id: str, season: int, episode: int, 
                           system_prompt: str) -> ConversationSession:
        """
        Start a new conversation session
        
        Args:
            device_id: Device identifier
            season: Season number
            episode: Episode number
            system_prompt: System prompt used for the session
            
        Returns:
            ConversationSession: Created session
        """
        try:
            # End any existing session for this device
            if device_id in self.active_sessions:
                await self.end_session(device_id, "new_session_started")
            
            # Create new session
            session = ConversationSession(
                session_id=str(uuid.uuid4()),
                device_id=device_id,
                season=season,
                episode=episode,
                system_prompt=system_prompt
            )
            
            # Add session start message
            session.add_message(
                MessageType.SESSION_START,
                f"Session started - Season {season}, Episode {episode}",
                metadata={
                    "season": season,
                    "episode": episode,
                    "system_prompt_length": len(system_prompt)
                }
            )
            
            # Store in active sessions
            self.active_sessions[device_id] = session
            
            self.log_info(f"Started conversation session for {device_id}: {session.session_id}")
            return session
            
        except Exception as e:
            self.log_error(f"Failed to start session for {device_id}: {e}")
            raise ValidationException(f"Failed to start conversation session: {str(e)}")
    
    async def add_user_message(self, device_id: str, transcript: str, 
                              confidence: Optional[float] = None,
                              duration_ms: Optional[int] = None) -> Optional[ConversationMessage]:
        """
        Add a user speech message to the active session
        
        Args:
            device_id: Device identifier
            transcript: Transcribed user speech
            confidence: Transcription confidence (0.0-1.0)
            duration_ms: Audio duration in milliseconds
            
        Returns:
            ConversationMessage: Added message, or None if no active session
        """
        if device_id not in self.active_sessions:
            self.log_warning(f"No active session for {device_id} when adding user message")
            return None
        
        session = self.active_sessions[device_id]
        
        message = session.add_message(
            MessageType.USER_SPEECH,
            transcript,
            confidence=confidence,
            duration_ms=duration_ms,
            metadata={
                "audio_duration_ms": duration_ms,
                "transcription_confidence": confidence
            }
        )
        
        self.log_info(f"Added user message to session {session.session_id}: {len(transcript)} chars")
        
        # Save to Firebase periodically (every 5 messages)
        if len(session.messages) % 5 == 0:
            await self._save_session_to_firebase(session)
        
        return message
    
    async def add_ai_message(self, device_id: str, response_text: str,
                            duration_ms: Optional[int] = None,
                            metadata: Dict[str, Any] = None) -> Optional[ConversationMessage]:
        """
        Add an AI response message to the active session
        
        Args:
            device_id: Device identifier
            response_text: AI response text
            duration_ms: Response audio duration in milliseconds
            metadata: Additional metadata
            
        Returns:
            ConversationMessage: Added message, or None if no active session
        """
        if device_id not in self.active_sessions:
            self.log_warning(f"No active session for {device_id} when adding AI message")
            return None
        
        session = self.active_sessions[device_id]
        
        message = session.add_message(
            MessageType.AI_RESPONSE,
            response_text,
            duration_ms=duration_ms,
            metadata={
                "audio_duration_ms": duration_ms,
                **(metadata or {})
            }
        )
        
        self.log_info(f"Added AI message to session {session.session_id}: {len(response_text)} chars")
        
        # Save to Firebase periodically
        if len(session.messages) % 5 == 0:
            await self._save_session_to_firebase(session)
        
        return message
    
    async def add_system_message(self, device_id: str, message: str,
                                metadata: Dict[str, Any] = None) -> Optional[ConversationMessage]:
        """
        Add a system message to the active session
        
        Args:
            device_id: Device identifier
            message: System message text
            metadata: Additional metadata
            
        Returns:
            ConversationMessage: Added message, or None if no active session
        """
        if device_id not in self.active_sessions:
            return None
        
        session = self.active_sessions[device_id]
        
        message_obj = session.add_message(
            MessageType.SYSTEM_MESSAGE,
            message,
            metadata=metadata or {}
        )
        
        self.log_info(f"Added system message to session {session.session_id}: {message}")
        return message_obj
    
    async def end_session(self, device_id: str, completion_reason: str = "normal_completion",
                         completed_successfully: bool = True) -> Optional[ConversationSession]:
        """
        End the active conversation session
        
        Args:
            device_id: Device identifier
            completion_reason: Reason for session completion
            completed_successfully: Whether session completed successfully
            
        Returns:
            ConversationSession: Ended session, or None if no active session
        """
        if device_id not in self.active_sessions:
            self.log_warning(f"No active session to end for {device_id}")
            return None
        
        session = self.active_sessions[device_id]
        
        # Add session end message
        session.add_message(
            MessageType.SESSION_END,
            f"Session ended - {completion_reason}",
            metadata={
                "completion_reason": completion_reason,
                "completed_successfully": completed_successfully,
                "total_messages": len(session.messages)
            }
        )
        
        # End the session
        session.end_session(completion_reason, completed_successfully)
        
        # Save final session to Firebase
        await self._save_session_to_firebase(session)
        
        # Remove from active sessions
        del self.active_sessions[device_id]
        
        self.log_info(f"Ended conversation session {session.session_id} for {device_id}. Duration: {session.duration_seconds:.1f}s, Messages: {len(session.messages)}")
        
        return session
    
    async def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """
        Get a conversation session by ID
        
        Args:
            session_id: Session identifier
            
        Returns:
            ConversationSession: Session if found, None otherwise
        """
        try:
            # Check active sessions first
            for session in self.active_sessions.values():
                if session.session_id == session_id:
                    return session
            
            # Try to load from Firebase
            session_data = await self.firebase_service.get_conversation_session(session_id)
            if session_data:
                return self._dict_to_session(session_data)
            
            return None
            
        except Exception as e:
            self.log_error(f"Failed to get session {session_id}: {e}")
            return None
    
    async def get_user_sessions(self, device_id: str, limit: int = 50) -> List[ConversationSummary]:
        """
        Get conversation sessions for a user
        
        Args:
            device_id: Device identifier
            limit: Maximum number of sessions to return
            
        Returns:
            List[ConversationSummary]: List of session summaries
        """
        try:
            sessions_data = await self.firebase_service.get_user_conversation_sessions(device_id, limit)
            
            summaries = []
            for session_data in sessions_data:
                session = self._dict_to_session(session_data)
                summaries.append(ConversationSummary.from_session(session))
            
            return summaries
            
        except Exception as e:
            self.log_error(f"Failed to get sessions for {device_id}: {e}")
            return []
    
    async def search_conversations(self, search_request: ConversationSearchRequest) -> List[ConversationSummary]:
        """
        Search conversation sessions based on criteria
        
        Args:
            search_request: Search criteria
            
        Returns:
            List[ConversationSummary]: Matching sessions
        """
        try:
            # This would implement Firebase queries based on search criteria
            # For now, we'll return a basic implementation
            sessions_data = await self.firebase_service.search_conversation_sessions(search_request)
            
            summaries = []
            for session_data in sessions_data:
                session = self._dict_to_session(session_data)
                summaries.append(ConversationSummary.from_session(session))
            
            return summaries[:search_request.limit]
            
        except Exception as e:
            self.log_error(f"Failed to search conversations: {e}")
            return []
    
    async def get_conversation_analytics(self, device_id: str, 
                                       days: int = 30) -> ConversationAnalytics:
        """
        Get conversation analytics for a user
        
        Args:
            device_id: Device identifier
            days: Number of days to include in analytics
            
        Returns:
            ConversationAnalytics: Analytics data
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Get sessions in date range
            sessions_data = await self.firebase_service.get_user_conversation_sessions_in_range(
                device_id, start_date, end_date
            )
            
            if not sessions_data:
                return ConversationAnalytics(
                    device_id=device_id,
                    total_sessions=0,
                    total_duration_hours=0.0,
                    average_session_duration_minutes=0.0,
                    total_messages=0,
                    user_messages=0,
                    ai_messages=0,
                    completion_rate=0.0,
                    average_messages_per_session=0.0,
                    speech_to_silence_ratio=0.0,
                    sessions_by_date={},
                    duration_by_date={}
                )
            
            # Calculate analytics
            total_sessions = len(sessions_data)
            total_duration = sum(session.get('duration_seconds', 0) for session in sessions_data)
            total_messages = sum(len(session.get('messages', [])) for session in sessions_data)
            user_messages = sum(
                len([msg for msg in session.get('messages', []) if msg.get('type') == 'user_speech'])
                for session in sessions_data
            )
            ai_messages = sum(
                len([msg for msg in session.get('messages', []) if msg.get('type') == 'ai_response'])
                for session in sessions_data
            )
            
            completed_sessions = sum(
                1 for session in sessions_data if session.get('completed_successfully', False)
            )
            
            # Group by date
            sessions_by_date = {}
            duration_by_date = {}
            
            for session in sessions_data:
                session_date = session.get('start_time', datetime.now()).date().isoformat()
                sessions_by_date[session_date] = sessions_by_date.get(session_date, 0) + 1
                duration_by_date[session_date] = duration_by_date.get(session_date, 0) + session.get('duration_seconds', 0)
            
            return ConversationAnalytics(
                device_id=device_id,
                total_sessions=total_sessions,
                total_duration_hours=round(total_duration / 3600, 2),
                average_session_duration_minutes=round((total_duration / total_sessions) / 60, 2) if total_sessions > 0 else 0.0,
                total_messages=total_messages,
                user_messages=user_messages,
                ai_messages=ai_messages,
                completion_rate=round((completed_sessions / total_sessions) * 100, 2) if total_sessions > 0 else 0.0,
                average_messages_per_session=round(total_messages / total_sessions, 2) if total_sessions > 0 else 0.0,
                speech_to_silence_ratio=0.5,  # This would require more detailed audio analysis
                sessions_by_date=sessions_by_date,
                duration_by_date={date: round(duration / 3600, 2) for date, duration in duration_by_date.items()}
            )
            
        except Exception as e:
            self.log_error(f"Failed to get analytics for {device_id}: {e}")
            raise ValidationException(f"Failed to get conversation analytics: {str(e)}")
    
    async def export_transcripts(self, export_request: TranscriptExportRequest) -> Dict[str, Any]:
        """
        Export conversation transcripts in requested format
        
        Args:
            export_request: Export configuration
            
        Returns:
            Dict with export data
        """
        try:
            # Get sessions based on request criteria
            sessions_data = await self.firebase_service.get_conversation_sessions_for_export(export_request)
            
            if export_request.format == "json":
                return {
                    "format": "json",
                    "device_id": export_request.device_id,
                    "export_date": datetime.now().isoformat(),
                    "sessions": sessions_data
                }
            
            elif export_request.format == "csv":
                # Convert to CSV format
                csv_data = self._convert_to_csv(sessions_data, export_request)
                return {
                    "format": "csv",
                    "device_id": export_request.device_id,
                    "export_date": datetime.now().isoformat(),
                    "csv_data": csv_data
                }
            
            elif export_request.format == "txt":
                # Convert to readable text format
                txt_data = self._convert_to_text(sessions_data, export_request)
                return {
                    "format": "txt",
                    "device_id": export_request.device_id,
                    "export_date": datetime.now().isoformat(),
                    "text_data": txt_data
                }
            
            else:
                raise ValidationException("Unsupported export format", "format", export_request.format)
                
        except Exception as e:
            self.log_error(f"Failed to export transcripts: {e}")
            raise ValidationException(f"Failed to export transcripts: {str(e)}")
    
    def get_active_session(self, device_id: str) -> Optional[ConversationSession]:
        """Get active session for device"""
        return self.active_sessions.get(device_id)
    
    def get_session_stats(self, device_id: str) -> Optional[ConversationStats]:
        """Get real-time stats for active session"""
        if device_id not in self.active_sessions:
            return None
        
        session = self.active_sessions[device_id]
        elapsed_time = (datetime.now() - session.start_time).total_seconds() / 60  # minutes
        
        total_duration = session.total_user_speech_duration + session.total_ai_response_duration
        user_percentage = (session.total_user_speech_duration / total_duration * 100) if total_duration > 0 else 0
        ai_percentage = (session.total_ai_response_duration / total_duration * 100) if total_duration > 0 else 0
        
        return ConversationStats(
            session_id=session.session_id,
            elapsed_time_minutes=round(elapsed_time, 2),
            messages_exchanged=len(session.messages),
            user_speech_percentage=round(user_percentage, 1),
            ai_response_percentage=round(ai_percentage, 1),
            last_activity=session.messages[-1].timestamp if session.messages else session.start_time
        )
    
    async def _save_session_to_firebase(self, session: ConversationSession):
        """Save session to Firebase"""
        try:
            session_data = self._session_to_dict(session)
            await self.firebase_service.save_conversation_session(session.session_id, session_data)
            self.log_info(f"Saved session {session.session_id} to Firebase")
        except Exception as e:
            self.log_error(f"Failed to save session {session.session_id}: {e}")
    
    def _session_to_dict(self, session: ConversationSession) -> Dict[str, Any]:
        """Convert session to dictionary for storage"""
        return {
            "session_id": session.session_id,
            "device_id": session.device_id,
            "season": session.season,
            "episode": session.episode,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "duration_seconds": session.duration_seconds,
            "messages": [
                {
                    "message_id": msg.message_id,
                    "timestamp": msg.timestamp,
                    "type": msg.type.value,
                    "content": msg.content,
                    "confidence": msg.confidence,
                    "duration_ms": msg.duration_ms,
                    "metadata": msg.metadata
                }
                for msg in session.messages
            ],
            "system_prompt": session.system_prompt,
            "user_message_count": session.user_message_count,
            "ai_message_count": session.ai_message_count,
            "total_user_speech_duration": session.total_user_speech_duration,
            "total_ai_response_duration": session.total_ai_response_duration,
            "completed_successfully": session.completed_successfully,
            "completion_reason": session.completion_reason
        }
    
    def _dict_to_session(self, data: Dict[str, Any]) -> ConversationSession:
        """Convert dictionary to session object"""
        session = ConversationSession(
            session_id=data["session_id"],
            device_id=data["device_id"],
            season=data["season"],
            episode=data["episode"],
            start_time=data["start_time"],
            end_time=data.get("end_time"),
            duration_seconds=data.get("duration_seconds", 0.0),
            system_prompt=data["system_prompt"],
            user_message_count=data.get("user_message_count", 0),
            ai_message_count=data.get("ai_message_count", 0),
            total_user_speech_duration=data.get("total_user_speech_duration", 0.0),
            total_ai_response_duration=data.get("total_ai_response_duration", 0.0),
            completed_successfully=data.get("completed_successfully", False),
            completion_reason=data.get("completion_reason")
        )
        
        # Add messages
        for msg_data in data.get("messages", []):
            message = ConversationMessage(
                message_id=msg_data["message_id"],
                timestamp=msg_data["timestamp"],
                type=MessageType(msg_data["type"]),
                content=msg_data["content"],
                confidence=msg_data.get("confidence"),
                duration_ms=msg_data.get("duration_ms"),
                metadata=msg_data.get("metadata", {})
            )
            session.messages.append(message)
        
        return session
    
    def _convert_to_csv(self, sessions_data: List[Dict], export_request: TranscriptExportRequest) -> str:
        """Convert sessions to CSV format"""
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        headers = ["Session ID", "Device ID", "Season", "Episode", "Timestamp", "Type", "Content"]
        if export_request.include_metadata:
            headers.extend(["Confidence", "Duration MS"])
        writer.writerow(headers)
        
        # Write data
        for session in sessions_data:
            for message in session.get("messages", []):
                row = [
                    session["session_id"],
                    session["device_id"],
                    session["season"],
                    session["episode"],
                    message["timestamp"] if export_request.include_timestamps else "",
                    message["type"],
                    message["content"]
                ]
                
                if export_request.include_metadata:
                    row.extend([
                        message.get("confidence", ""),
                        message.get("duration_ms", "")
                    ])
                
                writer.writerow(row)
        
        return output.getvalue()
    
    def _convert_to_text(self, sessions_data: List[Dict], export_request: TranscriptExportRequest) -> str:
        """Convert sessions to readable text format"""
        text_lines = []
        
        for session in sessions_data:
            text_lines.append(f"=== Session {session['session_id']} ===")
            text_lines.append(f"Device: {session['device_id']}")
            text_lines.append(f"Season {session['season']}, Episode {session['episode']}")
            text_lines.append(f"Start: {session['start_time']}")
            text_lines.append("")
            
            for message in session.get("messages", []):
                if message["type"] in ["user_speech", "ai_response"]:
                    timestamp = f"[{message['timestamp']}] " if export_request.include_timestamps else ""
                    speaker = "USER" if message["type"] == "user_speech" else "AI"
                    text_lines.append(f"{timestamp}{speaker}: {message['content']}")
            
            text_lines.append("")
            text_lines.append("-" * 50)
            text_lines.append("")
        
        return "\n".join(text_lines)


# Global conversation service instance
_conversation_service: Optional[ConversationService] = None


def get_conversation_service() -> ConversationService:
    """Get conversation service singleton"""
    global _conversation_service
    if _conversation_service is None:
        _conversation_service = ConversationService()
    return _conversation_service