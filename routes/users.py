"""
Enhanced User management routes with daily episode limits
"""
from fastapi import APIRouter, HTTPException, status, Query, Depends
from typing import List, Optional

from models.user import UserResponse, SessionInfo, DailyUsageStats
from services.user_service import get_user_service, UserService
from services.websocket_service import get_websocket_manager, WebSocketConnectionManager
from utils.exceptions import (
    ValidationException, UserNotFoundException,
    handle_validation_error, handle_user_error, handle_generic_error
)
from utils.logger import LoggerMixin
from pydantic import BaseModel


router = APIRouter(prefix="/users", tags=["Users"])


def get_user_service_dependency():
    """Dependency to get user service"""
    return get_user_service()


def get_websocket_manager_dependency():
    """Dependency to get websocket manager"""
    return get_websocket_manager()


class ProgressUpdateRequest(BaseModel):
    """Request model for updating user progress"""
    words_learnt: Optional[List[str]] = None
    topics_learnt: Optional[List[str]] = None


class UserRoutes(LoggerMixin):
    """Enhanced user route handlers with daily limits"""
    
    def __init__(self):
        super().__init__()
        self.user_service = get_user_service()
        self.websocket_manager = get_websocket_manager()


user_routes = UserRoutes()


@router.get("/{device_id}",
            response_model=UserResponse,
            summary="Get user information",
            description="Retrieve detailed information for a specific user including daily episode limits")
async def get_user(device_id: str, user_service: UserService = Depends(get_user_service_dependency)):
    """
    Get comprehensive user information including progress, statistics, and daily limits
    
    - **device_id**: Unique device identifier
    
    Returns user data with:
    - Current learning progress
    - Daily episode usage (played today, remaining)
    - Session statistics
    - Daily limits status
    """
    try:
        user_response = await user_service.get_user(device_id)
        
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"User info retrieved with daily limits: {device_id}")
        return user_response
        
    except ValidationException as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Invalid device ID: {device_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except UserNotFoundException as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"User not found: {device_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=handle_user_error(e)
        )
    
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to get user {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/daily-limits",
            summary="Check daily episode limits",
            description="Check if user can play another episode today and get daily usage info")
async def check_daily_limits(device_id: str, user_service: UserService = Depends(get_user_service_dependency)):
    """
    Check daily episode limits for a user
    
    - **device_id**: Unique device identifier
    
    Returns:
    - Episodes played today
    - Remaining episodes
    - Can play episode status
    - Daily limit information
    """
    try:
        limit_info = await user_service.check_episode_limit(device_id)
        
        user_routes.log_info(f"Daily limits checked for {device_id}: {limit_info['episodes_played_today']}/3 episodes used")
        return limit_info
        
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
        user_routes.log_error(f"Failed to check daily limits for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/daily-usage",
            response_model=List[DailyUsageStats],
            summary="Get daily usage statistics",
            description="Get daily usage statistics for the past N days")
async def get_daily_usage_stats(device_id: str, days: int = Query(default=7, ge=1, le=30),
                               user_service: UserService = Depends(get_user_service_dependency)):
    """
    Get daily usage statistics for a user
    
    - **device_id**: Unique device identifier
    - **days**: Number of past days to include (1-30, default: 7)
    
    Returns daily statistics including:
    - Episodes played per day
    - Session time per day
    - Session count per day
    - Efficiency scores
    """
    try:
        stats = await user_service.get_daily_usage_stats(device_id, days)
        
        user_routes.log_info(f"Daily usage stats retrieved for {device_id}: {days} days")
        return stats
        
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
        user_routes.log_error(f"Failed to get daily usage stats for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/statistics",
            summary="Get comprehensive user statistics",
            description="Get comprehensive statistics including daily limits and usage patterns")
async def get_user_statistics(device_id: str, user_service: UserService = Depends(get_user_service_dependency)):
    """
    Get detailed statistics for a user including learning progress, time tracking, and daily usage
    
    - **device_id**: Unique device identifier
    
    Returns comprehensive statistics including:
    - Learning progress and completion rates
    - Time statistics and session patterns
    - Daily usage and limits
    - Weekly and monthly episode totals
    """
    try:
        statistics = await user_service.get_user_statistics(device_id)
        
        user_routes.log_info(f"User statistics retrieved with daily usage: {device_id}")
        return statistics
        
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
        user_routes.log_error(f"Failed to get statistics for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/session",
            summary="Get current session information",
            description="Get information about the user's current session including daily limits")
async def get_session_info(device_id: str):
    """
    Get current session information including connection status, duration, and daily limits
    
    - **device_id**: Unique device identifier
    
    Returns session info with:
    - Connection status and duration
    - Current learning position
    - Daily limits and remaining episodes
    """
    try:
        # Get connection info from WebSocket manager
        connections = user_routes.websocket_manager.get_active_connections()
        connection_info = connections.get(device_id)
        
        if connection_info:
            session_info = await user_routes.user_service.get_user_session_info(
                device_id=device_id,
                session_duration=connection_info["duration"],
                is_connected=True,
                is_openai_connected=device_id in user_routes.websocket_manager.openai_service.active_connections
            )
        else:
            # User exists but not currently connected
            session_info = await user_routes.user_service.get_user_session_info(
                device_id=device_id,
                session_duration=0.0,
                is_connected=False,
                is_openai_connected=False
            )
        
        return session_info
        
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
        user_routes.log_error(f"Failed to get session info for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.put("/{device_id}/progress",
            response_model=UserResponse,
            summary="Update user progress",
            description="Update user's learning progress with new words or topics")
async def update_progress(device_id: str, progress_update: ProgressUpdateRequest):
    """
    Update user's learning progress
    
    - **device_id**: Unique device identifier
    - **words_learnt**: List of new words learned
    - **topics_learnt**: List of new topics learned
    
    Note: This does not advance episodes or affect daily limits
    """
    try:
        updated_user = await user_routes.user_service.update_user_progress(
            device_id=device_id,
            words_learnt=progress_update.words_learnt,
            topics_learnt=progress_update.topics_learnt
        )
        
        user_routes.log_info(f"Progress updated for user: {device_id}")
        return updated_user
        
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
        user_routes.log_error(f"Failed to update progress for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.post("/{device_id}/advance-episode",
             response_model=UserResponse,
             summary="Advance to next episode",
             description="Advance user to next episode/season (respects daily limits)")
async def advance_episode(device_id: str):
    """
    Advance user to the next episode or season
    
    - **device_id**: Unique device identifier
    
    **Important**: This endpoint respects daily limits. Users can only advance 3 episodes per day.
    
    Returns:
    - Updated user information
    - Error if daily limit exceeded
    
    Note: This is typically done automatically when conversations complete
    """
    try:
        updated_user = await user_routes.user_service.advance_episode(device_id)
        
        user_routes.log_info(f"Episode advanced for user: {device_id} (daily limit respected)")
        return updated_user
        
    except ValidationException as e:
        # Check if this is a daily limit error
        if "daily limit" in str(e).lower() or "episode limit" in str(e).lower():
            user_routes.log_warning(f"Daily episode limit exceeded for {device_id}: {e.message}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Daily Episode Limit Exceeded",
                    "message": e.message,
                    "code": "DAILY_EPISODE_LIMIT_EXCEEDED",
                    "daily_limit": 3,
                    "retry_after": "tomorrow"
                }
            )
        else:
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
        user_routes.log_error(f"Failed to advance episode for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{device_id}/session-duration",
            summary="Get session duration",
            description="Get current session duration in seconds")
async def get_session_duration(device_id: str):
    """
    Get the duration of the current session
    
    - **device_id**: Unique device identifier
    """
    try:
        # Validate device ID format
        from utils.validators import DeviceValidator
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise ValidationException(error_msg, "device_id", device_id)
        
        # Get session duration from WebSocket manager
        connections = user_routes.websocket_manager.get_active_connections()
        connection_info = connections.get(device_id)
        duration = connection_info["duration"] if connection_info else 0.0
        
        return {
            "device_id": device_id,
            "session_duration_seconds": duration,
            "session_duration_minutes": round(duration / 60, 2),
            "is_connected": duration > 0
        }
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except Exception as e:
        user_routes.log_error(f"Failed to get session duration for {device_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.delete("/{device_id}",
               summary="Delete user account",
               description="Soft delete user account (deactivate)")
async def delete_user(device_id: str):
    """
    Soft delete user account (sets status to inactive)
    
    - **device_id**: Unique device identifier
    
    Note: This preserves conversation history and daily usage data
    """
    try:
        success = await user_routes.user_service.delete_user(device_id)
        
        if success:
            user_routes.log_info(f"User deleted: {device_id}")
            return {"message": "User account deactivated successfully", "device_id": device_id}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "Failed to delete user account"}
            )
        
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
        user_routes.log_error(f"Failed to delete user {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/",
            summary="Get all active connections",
            description="Get information about all currently connected users (admin endpoint)")
async def get_active_connections():
    """
    Get information about all currently active connections
    
    Note: This would typically require admin authentication in production
    
    Returns detailed connection info including:
    - Active connection count
    - Connection details with daily usage
    - Session durations and activity
    """
    try:
        connections = user_routes.websocket_manager.get_active_connections()
        
        return {
            "active_connections": len(connections),
            "connections": connections,
            "note": "Daily episode limits are enforced per device"
        }
        
    except Exception as e:
        user_routes.log_error(f"Failed to get active connections: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


# Additional endpoint for admin monitoring
@router.get("/admin/daily-usage-summary",
            summary="Get daily usage summary for all users",
            description="Admin endpoint to get daily usage summary across all users")
async def get_daily_usage_summary():
    """
    Get daily usage summary across all users (admin endpoint)
    
    Note: This would typically require admin authentication in production
    
    Returns:
    - Total episodes played today across all users
    - Users at daily limit
    - Usage patterns and statistics
    """
    try:
        # This would require additional Firebase queries to get all users
        # For now, return a placeholder response
        return {
            "message": "Daily usage summary endpoint",
            "note": "This would require admin authentication and additional Firebase queries in production",
            "daily_limit_per_user": 3,
            "statistics": {
                "total_users": "Would fetch from database",
                "users_at_limit_today": "Would calculate from database",
                "total_episodes_today": "Would sum from all users",
                "average_sessions_per_user": "Would calculate"
            }
        }
        
    except Exception as e:
        user_routes.log_error(f"Failed to get daily usage summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )