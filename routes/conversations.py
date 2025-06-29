"""
Conversation management routes for transcript access and analytics
"""
from fastapi import APIRouter, HTTPException, status, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List, Optional
import io
import json

from models.conversation import (
    ConversationSummary, ConversationSearchRequest, ConversationAnalytics,
    TranscriptExportRequest, ConversationStats, MessageType
)
from services.conversation_service import get_conversation_service, ConversationService
from services.user_service import get_user_service
from utils.exceptions import (
    ValidationException, UserNotFoundException,
    handle_validation_error, handle_user_error, handle_generic_error
)
from utils.validators import DeviceValidator
from utils.logger import LoggerMixin
from pydantic import BaseModel


router = APIRouter(prefix="/conversations", tags=["Conversations"])


def get_conversation_service_dependency():
    """Dependency to get conversation service"""
    return get_conversation_service()


def get_user_service_dependency():
    """Dependency to get user service"""
    return get_user_service()


class ConversationRoutes(LoggerMixin):
    """Conversation route handlers"""
    
    def __init__(self):
        super().__init__()
        self.conversation_service = get_conversation_service()
        self.user_service = get_user_service()


conversation_routes = ConversationRoutes()


@router.get("/{device_id}",
            response_model=List[ConversationSummary],
            summary="Get user's conversation sessions",
            description="Get a list of conversation sessions for a specific user")
async def get_user_conversations(
    device_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    conversation_service: ConversationService = Depends(get_conversation_service_dependency)
):
    """
    Get conversation sessions for a user
    
    - **device_id**: Unique device identifier
    - **limit**: Maximum number of sessions to return (1-500, default: 50)
    
    Returns a list of conversation summaries including:
    - Session metadata (ID, dates, duration)
    - Message counts and completion status
    - Learning context (season/episode)
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Verify user exists
        await conversation_routes.user_service.get_user(device_id)
        
        # Get conversation sessions
        sessions = await conversation_service.get_user_sessions(device_id, limit)
        
        conversation_routes.log_info(f"Retrieved {len(sessions)} conversation sessions for {device_id}")
        return sessions
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except UserNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=handle_user_error(e)
        )
    
    except Exception as e:
        conversation_routes.log_error(f"Failed to get conversations for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/session/{session_id}",
            summary="Get specific conversation session",
            description="Get complete conversation transcript for a specific session")
async def get_conversation_session(
    device_id: str,
    session_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service_dependency)
):
    """
    Get complete conversation session with full transcript
    
    - **device_id**: Unique device identifier
    - **session_id**: Specific session identifier
    
    Returns complete session data including:
    - Full message transcript with timestamps
    - Session metadata and statistics
    - AI and user message details
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Get session
        session = await conversation_service.get_session(session_id)
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Session not found", "session_id": session_id}
            )
        
        # Verify session belongs to user
        if session.device_id != device_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Session does not belong to specified device", "device_id": device_id}
            )
        
        conversation_routes.log_info(f"Retrieved conversation session {session_id} for {device_id}")
        
        # Return session data (convert to dict for JSON response)
        return {
            "session_id": session.session_id,
            "device_id": session.device_id,
            "season": session.season,
            "episode": session.episode,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "duration_seconds": session.duration_seconds,
            "duration_minutes": round(session.duration_seconds / 60, 2),
            "completed_successfully": session.completed_successfully,
            "completion_reason": session.completion_reason,
            "message_count": session.message_count,
            "user_message_count": session.user_message_count,
            "ai_message_count": session.ai_message_count,
            "total_user_speech_duration": session.total_user_speech_duration,
            "total_ai_response_duration": session.total_ai_response_duration,
            "messages": [
                {
                    "message_id": msg.message_id,
                    "timestamp": msg.timestamp,
                    "type": msg.type.value,
                    "content": msg.content,
                    "confidence": msg.confidence,
                    "duration_ms": msg.duration_ms,
                    "duration_seconds": msg.duration_seconds,
                    "metadata": msg.metadata
                }
                for msg in session.messages
            ],
            "system_prompt": session.system_prompt if len(session.system_prompt) < 500 else session.system_prompt[:500] + "...",
            "summary": session.get_conversation_summary()
        }
        
    except HTTPException:
        raise
    
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except Exception as e:
        conversation_routes.log_error(f"Failed to get session {session_id} for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/active",
            summary="Get active conversation session",
            description="Get the currently active conversation session for a user")
async def get_active_conversation(
    device_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service_dependency)
):
    """
    Get currently active conversation session
    
    - **device_id**: Unique device identifier
    
    Returns:
    - Active session information if connected
    - Real-time conversation statistics
    - Current session progress
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Get active session
        active_session = conversation_service.get_active_session(device_id)
        
        if not active_session:
            return {
                "device_id": device_id,
                "has_active_session": False,
                "message": "No active conversation session"
            }
        
        # Get real-time stats
        session_stats = conversation_service.get_session_stats(device_id)
        
        conversation_routes.log_info(f"Retrieved active conversation for {device_id}: {active_session.session_id}")
        
        return {
            "device_id": device_id,
            "has_active_session": True,
            "session_id": active_session.session_id,
            "season": active_session.season,
            "episode": active_session.episode,
            "start_time": active_session.start_time,
            "is_active": active_session.is_active,
            "message_count": active_session.message_count,
            "user_message_count": active_session.user_message_count,
            "ai_message_count": active_session.ai_message_count,
            "current_stats": session_stats.dict() if session_stats else None,
            "recent_messages": [
                {
                    "timestamp": msg.timestamp,
                    "type": msg.type.value,
                    "content": msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                }
                for msg in active_session.messages[-5:]  # Last 5 messages
            ]
        }
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except Exception as e:
        conversation_routes.log_error(f"Failed to get active conversation for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.post("/{device_id}/search",
             response_model=List[ConversationSummary],
             summary="Search conversations",
             description="Search through conversation sessions based on various criteria")
async def search_conversations(
    device_id: str,
    search_request: ConversationSearchRequest,
    conversation_service: ConversationService = Depends(get_conversation_service_dependency)
):
    """
    Search conversation sessions based on criteria
    
    - **device_id**: Unique device identifier
    - **search_request**: Search criteria including text, dates, message types
    
    Search options:
    - Text content search
    - Date range filtering
    - Season/episode filtering
    - Message type filtering
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Set device_id in search request
        search_request.device_id = device_id
        
        # Perform search
        results = await conversation_service.search_conversations(search_request)
        
        conversation_routes.log_info(f"Conversation search for {device_id} returned {len(results)} results")
        return results
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except Exception as e:
        conversation_routes.log_error(f"Failed to search conversations for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/analytics",
            response_model=ConversationAnalytics,
            summary="Get conversation analytics",
            description="Get comprehensive analytics for user's conversations")
async def get_conversation_analytics(
    device_id: str,
    days: int = Query(default=30, ge=1, le=365),
    conversation_service: ConversationService = Depends(get_conversation_service_dependency)
):
    """
    Get conversation analytics for a user
    
    - **device_id**: Unique device identifier
    - **days**: Number of days to include in analytics (1-365, default: 30)
    
    Returns comprehensive analytics including:
    - Session counts and completion rates
    - Message statistics and patterns
    - Time usage and efficiency metrics
    - Daily activity patterns
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Verify user exists
        await conversation_routes.user_service.get_user(device_id)
        
        # Get analytics
        analytics = await conversation_service.get_conversation_analytics(device_id, days)
        
        conversation_routes.log_info(f"Generated conversation analytics for {device_id} ({days} days)")
        return analytics
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except UserNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=handle_user_error(e)
        )
    
    except Exception as e:
        conversation_routes.log_error(f"Failed to get analytics for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.post("/{device_id}/export",
             summary="Export conversation transcripts",
             description="Export conversation transcripts in various formats")
async def export_conversations(
    device_id: str,
    export_request: TranscriptExportRequest,
    conversation_service: ConversationService = Depends(get_conversation_service_dependency)
):
    """
    Export conversation transcripts in requested format
    
    - **device_id**: Unique device identifier
    - **export_request**: Export configuration (format, filters, options)
    
    Supported formats:
    - JSON: Complete structured data
    - CSV: Tabular format for analysis
    - TXT: Human-readable transcript
    
    Export options:
    - Include/exclude metadata
    - Include/exclude timestamps
    - Filter by date range, season, episode
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Set device_id in export request
        export_request.device_id = device_id
        
        # Verify user exists
        await conversation_routes.user_service.get_user(device_id)
        
        # Export transcripts
        export_data = await conversation_service.export_transcripts(export_request)
        
        conversation_routes.log_info(f"Exported conversations for {device_id} in {export_request.format} format")
        
        # Return different response types based on format
        if export_request.format == "json":
            return JSONResponse(content=export_data)
        
        elif export_request.format == "csv":
            # Return CSV as downloadable file
            csv_content = export_data["csv_data"]
            filename = f"conversations_{device_id}_{export_data['export_date'][:10]}.csv"
            
            return StreamingResponse(
                io.StringIO(csv_content),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        
        elif export_request.format == "txt":
            # Return TXT as downloadable file
            txt_content = export_data["text_data"]
            filename = f"conversations_{device_id}_{export_data['export_date'][:10]}.txt"
            
            return StreamingResponse(
                io.StringIO(txt_content),
                media_type="text/plain",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        
        else:
            return JSONResponse(content=export_data)
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except UserNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=handle_user_error(e)
        )
    
    except Exception as e:
        conversation_routes.log_error(f"Failed to export conversations for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/season/{season}/episode/{episode}",
            response_model=List[ConversationSummary],
            summary="Get conversations for specific episode",
            description="Get all conversation sessions for a specific season and episode")
async def get_episode_conversations(
    device_id: str,
    season: int,
    episode: int,
    conversation_service: ConversationService = Depends(get_conversation_service_dependency)
):
    """
    Get conversation sessions for a specific season and episode
    
    - **device_id**: Unique device identifier
    - **season**: Season number
    - **episode**: Episode number
    
    Returns all conversation sessions for the specified episode
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Create search request for specific episode
        search_request = ConversationSearchRequest(
            device_id=device_id,
            season=season,
            episode=episode,
            limit=100  # Should be enough for one episode
        )
        
        # Search for sessions
        sessions = await conversation_service.search_conversations(search_request)
        
        conversation_routes.log_info(f"Retrieved {len(sessions)} sessions for {device_id} S{season}E{episode}")
        return sessions
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except Exception as e:
        conversation_routes.log_error(f"Failed to get episode conversations S{season}E{episode} for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


# Admin endpoints
@router.get("/admin/stats",
            summary="Get global conversation statistics",
            description="Admin endpoint for global conversation statistics")
async def get_global_conversation_stats():
    """
    Get global conversation statistics (admin endpoint)
    
    Note: This would typically require admin authentication in production
    
    Returns system-wide conversation statistics
    """
    try:
        # This would require additional Firebase queries
        # For now, return a placeholder response
        return {
            "message": "Global conversation statistics endpoint",
            "note": "This would require admin authentication and global Firebase queries in production",
            "statistics": {
                "total_conversations": "Would fetch from database",
                "conversations_today": "Would calculate from database",
                "average_session_duration": "Would calculate from all sessions",
                "most_active_users": "Would rank users by session count",
                "popular_episodes": "Would rank by session count per episode"
            }
        }
        
    except Exception as e:
        conversation_routes.log_error(f"Failed to get global conversation stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.delete("/{device_id}/session/{session_id}",
               summary="Delete conversation session",
               description="Delete a specific conversation session (admin or user)")
async def delete_conversation_session(device_id: str, session_id: str):
    """
    Delete a specific conversation session
    
    - **device_id**: Unique device identifier
    - **session_id**: Session to delete
    
    Note: This is a soft delete that marks the session as deleted
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # This would implement session deletion in Firebase
        # For now, return a placeholder response
        conversation_routes.log_info(f"Session deletion requested: {session_id} for {device_id}")
        
        return {
            "message": "Session deletion requested",
            "session_id": session_id,
            "device_id": device_id,
            "note": "This would implement soft deletion in Firebase in production"
        }
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except Exception as e:
        conversation_routes.log_error(f"Failed to delete session {session_id} for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )