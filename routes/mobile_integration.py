# routes/mobile_integration.py - New endpoints for mobile app integration
"""
Mobile app integration endpoints for linking Firebase users with ESP32 devices
"""
from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Optional
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth

from models.user import UserResponse
from services.user_service import get_user_service, UserService
from services.websocket_service import get_websocket_manager
from utils.exceptions import ValidationException, UserNotFoundException
from utils.logger import LoggerMixin


router = APIRouter(prefix="/mobile", tags=["Mobile Integration"])


# Request/Response models
class DeviceLinkRequest(BaseModel):
    device_id: str
    child_id: str
    firebase_uid: str
    parent_email: str


class DeviceLinkResponse(BaseModel):
    success: bool
    message: str
    device_id: str
    child_id: str


class ChildMetricsResponse(BaseModel):
    words_learnt: List[str]
    topics_learnt: List[str]
    total_sessions: int
    total_session_time: float  # in seconds
    current_episode: int
    current_season: int
    last_activity: Optional[str]
    streak_days: int


class TranscriptResponse(BaseModel):
    id: str
    date: str
    time: str
    duration: str
    episode_title: str
    conversation_count: int
    preview: str


class DeviceStatusResponse(BaseModel):
    connected: bool
    last_seen: Optional[str]
    device_id: str


# Firebase token validation
async def verify_firebase_token(authorization: str):
    """Verify Firebase ID token from Authorization header"""
    try:
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format"
            )
        
        token = authorization.replace("Bearer ", "")
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )


def get_user_service_dependency():
    return get_user_service()


def get_websocket_manager_dependency():
    return get_websocket_manager()


@router.post("/link-device", response_model=DeviceLinkResponse)
async def link_device_to_account(
    request: DeviceLinkRequest,
    authorization: str,
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Link an ESP32 device to a child's account
    
    This endpoint connects a physical teddy bear (ESP32 device) to a specific
    child profile in the mobile app.
    """
    firebase_user = await verify_firebase_token(authorization)
    
    # Verify the Firebase UID matches the request
    if firebase_user['uid'] != request.firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firebase UID mismatch"
        )
    
    try:
        # Check if device exists and is registered
        device_user = await user_service.get_user(request.device_id)
        
        # Check if device is already linked to another account
        if hasattr(device_user, 'firebase_uid') and device_user.firebase_uid:
            if device_user.firebase_uid != request.firebase_uid:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Device is already linked to another account"
                )
        
        # Update device with Firebase linking information
        await user_service.link_device_to_firebase_user(
            device_id=request.device_id,
            firebase_uid=request.firebase_uid,
            child_id=request.child_id,
            parent_email=request.parent_email
        )
        
        return DeviceLinkResponse(
            success=True,
            message="Device linked successfully",
            device_id=request.device_id,
            child_id=request.child_id
        )
        
    except UserNotFoundException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found. Please check the device ID."
        )
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to link device"
        )


@router.get("/device/{device_id}/metrics", response_model=ChildMetricsResponse)
async def get_device_metrics(
    device_id: str,
    authorization: str,
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Get learning metrics for a specific device
    
    Returns comprehensive learning statistics including words learned,
    topics mastered, session time, and current progress.
    """
    firebase_user = await verify_firebase_token(authorization)
    
    try:
        # Get device user data
        device_user = await user_service.get_user(device_id)
        
        # Verify user has access to this device
        if not hasattr(device_user, 'firebase_uid') or device_user.firebase_uid != firebase_user['uid']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this device"
            )
        
        # Get user statistics
        stats = await user_service.get_user_statistics(device_id)
        
        return ChildMetricsResponse(
            words_learnt=stats.get('words_learnt', []),
            topics_learnt=stats.get('topics_learnt', []),
            total_sessions=stats.get('total_sessions', 0),
            total_session_time=stats.get('total_session_time', 0),
            current_episode=stats.get('current_episode', 1),
            current_season=stats.get('current_season', 1),
            last_activity=stats.get('last_activity'),
            streak_days=stats.get('streak_days', 0)
        )
        
    except UserNotFoundException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch metrics"
        )


@router.get("/device/{device_id}/transcripts", response_model=List[TranscriptResponse])
async def get_device_transcripts(
    device_id: str,
    authorization: str,
    limit: int = 10,
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Get recent conversation transcripts for a device
    
    Returns a list of recent conversations between the child and their teddy bear.
    """
    firebase_user = await verify_firebase_token(authorization)
    
    try:
        # Get device user data
        device_user = await user_service.get_user(device_id)
        
        # Verify user has access to this device
        if not hasattr(device_user, 'firebase_uid') or device_user.firebase_uid != firebase_user['uid']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this device"
            )
        
        # Get transcripts (you'll need to implement this in your user service)
        transcripts = await user_service.get_user_transcripts(device_id, limit)
        
        return [
            TranscriptResponse(
                id=transcript['id'],
                date=transcript['date'],
                time=transcript['time'],
                duration=transcript['duration'],
                episode_title=transcript['episode_title'],
                conversation_count=transcript['conversation_count'],
                preview=transcript['preview']
            )
            for transcript in transcripts
        ]
        
    except UserNotFoundException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch transcripts"
        )


@router.get("/device/{device_id}/status", response_model=DeviceStatusResponse)
async def get_device_status(
    device_id: str,
    authorization: str,
    websocket_manager = Depends(get_websocket_manager_dependency),
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Get the current connection status of a device
    
    Returns whether the teddy bear is currently online and when it was last seen.
    """
    firebase_user = await verify_firebase_token(authorization)
    
    try:
        # Get device user data
        device_user = await user_service.get_user(device_id)
        
        # Verify user has access to this device
        if not hasattr(device_user, 'firebase_uid') or device_user.firebase_uid != firebase_user['uid']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this device"
            )
        
        # Check WebSocket connection status
        connection_info = await websocket_manager.get_connection_info(device_id)
        
        return DeviceStatusResponse(
            connected=connection_info is not None,
            last_seen=connection_info.get('last_seen') if connection_info else device_user.last_seen,
            device_id=device_id
        )
        
    except UserNotFoundException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch device status"
        )


@router.post("/device/{device_id}/test-connection")
async def test_device_connection(
    device_id: str,
    authorization: str,
    websocket_manager = Depends(get_websocket_manager_dependency),
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Test the connection to a specific device
    
    Attempts to ping the device and verify it's responsive.
    """
    firebase_user = await verify_firebase_token(authorization)
    
    try:
        # Get device user data
        device_user = await user_service.get_user(device_id)
        
        # Verify user has access to this device
        if not hasattr(device_user, 'firebase_uid') or device_user.firebase_uid != firebase_user['uid']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this device"
            )
        
        # Test connection
        connection_test = await websocket_manager.test_connection(device_id)
        
        return {
            "success": connection_test.get('success', False),
            "message": connection_test.get('message', 'Connection test completed'),
            "response_time": connection_test.get('response_time'),
            "device_id": device_id
        }
        
    except UserNotFoundException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "device_id": device_id
        }


@router.get("/user/devices")
async def get_user_devices(
    authorization: str,
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Get all devices linked to the authenticated user
    
    Returns a list of all ESP32 devices linked to the user's Firebase account.
    """
    firebase_user = await verify_firebase_token(authorization)
    
    try:
        # Get all devices for this Firebase user
        devices = await user_service.get_devices_by_firebase_uid(firebase_user['uid'])
        
        return {
            "devices": devices,
            "count": len(devices)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user devices"
        )


# Update services/user_service.py to add these methods:
"""
Add these methods to your UserService class:

async def link_device_to_firebase_user(self, device_id: str, firebase_uid: str, child_id: str, parent_email: str):
    # Update the device user document with Firebase linking info
    pass

async def get_user_transcripts(self, device_id: str, limit: int = 10):
    # Fetch conversation transcripts for the device
    pass

async def get_devices_by_firebase_uid(self, firebase_uid: str):
    # Get all devices linked to a Firebase user
    pass
"""