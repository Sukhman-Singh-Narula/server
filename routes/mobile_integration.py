# routes/mobile.py - Mobile app specific routes
"""
Mobile app integration routes for account management and teddy bear functionality
"""
from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from utils.firebase_auth import verify_firebase_token, get_current_user
from services.user_service import get_user_service, UserService
from services.websocket_service import get_websocket_manager
from utils.exceptions import ValidationException, UserNotFoundException
from utils.logger import LoggerMixin
import logging

router = APIRouter(prefix="/mobile", tags=["Mobile Integration"])
logger = logging.getLogger(__name__)

# Request/Response Models
class ChildProfile(BaseModel):
    id: str
    name: str
    age: int
    avatar: str = "bear"
    deviceId: Optional[str] = None
    created_at: str

class AccountDetails(BaseModel):
    displayName: str
    email: str
    phoneNumber: Optional[str] = None
    subscription: str = "free"
    avatar: Optional[str] = None

class SubscriptionStatus(BaseModel):
    status: str
    expiresAt: Optional[str] = None
    features: List[str]

class TeddyStatus(BaseModel):
    isConnected: bool
    batteryLevel: int
    lastSyncTime: Optional[str] = None

class DeviceMetrics(BaseModel):
    wordsLearned: List[str]
    topicsLearned: List[str]
    totalSessions: int
    totalMinutes: int
    currentEpisode: int
    currentSeason: int
    lastActivity: Optional[str]
    streakDays: int

class LearningProgress(BaseModel):
    completedEpisodes: List[Dict[str, Any]]
    currentEpisode: Optional[Dict[str, Any]]

def get_user_service_dependency():
    return get_user_service()

def get_websocket_manager_dependency():
    return get_websocket_manager()

# Account Management Endpoints
@router.get("/account/details", response_model=AccountDetails)
async def get_account_details(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get account details for authenticated user"""
    try:
        # For now, return basic Firebase user info
        # In production, you'd fetch additional data from your database
        return AccountDetails(
            displayName=firebase_user.get('name', 'User'),
            email=firebase_user.get('email', ''),
            phoneNumber=firebase_user.get('phone_number'),
            subscription="free",
            avatar=firebase_user.get('picture')
        )
    except Exception as e:
        logger.error(f"Error fetching account details: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch account details")

@router.get("/account/children", response_model=List[ChildProfile])
async def get_child_profiles(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get child profiles for authenticated user"""
    try:
        # Mock data for now - in production, fetch from database
        return [
            ChildProfile(
                id="child_1",
                name="Emma",
                age=6,
                avatar="bear",
                deviceId=None,  # Will be set when device is connected
                created_at="2024-01-01T00:00:00Z"
            )
        ]
    except Exception as e:
        logger.error(f"Error fetching child profiles: {e}")
        return []

@router.post("/account/children", response_model=ChildProfile)
async def add_child_profile(
    child_data: dict,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Add a new child profile"""
    try:
        from datetime import datetime
        import uuid
        
        new_child = ChildProfile(
            id=str(uuid.uuid4()),
            name=child_data.get('name'),
            age=child_data.get('age'),
            avatar=child_data.get('avatar', 'bear'),
            deviceId=None,
            created_at=datetime.utcnow().isoformat() + 'Z'
        )
        
        # In production, save to database here
        logger.info(f"Added child profile: {new_child.name} for user {firebase_user.get('uid')}")
        
        return new_child
    except Exception as e:
        logger.error(f"Error adding child profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to add child profile")

@router.get("/account/subscription", response_model=SubscriptionStatus)
async def get_subscription_status(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get subscription status for authenticated user"""
    try:
        return SubscriptionStatus(
            status="free",
            expiresAt=None,
            features=["basic_learning", "single_device"]
        )
    except Exception as e:
        logger.error(f"Error fetching subscription status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch subscription status")

# Teddy Bear Management
@router.get("/teddy", response_model=Dict[str, Any])
async def get_teddy(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get teddy bear status and information"""
    try:
        # Mock teddy data
        return {
            "connectionStatus": {
                "isConnected": False,
                "batteryLevel": 85,
                "lastSyncTime": "2024-01-15T10:30:00Z"
            },
            "name": "Bern",
            "personality": "friendly_teacher"
        }
    except Exception as e:
        logger.error(f"Error fetching teddy: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch teddy information")

@router.post("/teddy", response_model=Dict[str, Any])
async def save_teddy(
    teddy_data: dict,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Save or update teddy bear configuration"""
    try:
        # In production, save teddy configuration to database
        logger.info(f"Saved teddy configuration for user {firebase_user.get('uid')}")
        
        return {
            "success": True,
            "message": "Teddy configuration saved",
            "connectionStatus": teddy_data.get("connectionStatus", {
                "isConnected": False,
                "batteryLevel": 100
            })
        }
    except Exception as e:
        logger.error(f"Error saving teddy: {e}")
        raise HTTPException(status_code=500, detail="Failed to save teddy configuration")

# Learning Progress
@router.get("/learning/progress", response_model=LearningProgress)
async def get_learning_progress(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get learning progress for user"""
    try:
        # Mock learning progress data
        return LearningProgress(
            completedEpisodes=[
                {
                    "id": "ep_1",
                    "title": "First Meeting",
                    "season": 1,
                    "episode": 1,
                    "completedAt": "2024-01-10T00:00:00Z",
                    "score": 85
                }
            ],
            currentEpisode={
                "id": "ep_2",
                "title": "Learning Colors",
                "season": 1,
                "episode": 2,
                "progress": 60
            }
        )
    except Exception as e:
        logger.error(f"Error fetching learning progress: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch learning progress")

# User Document Management (Firebase UID based)
@router.get("/users/firebase/{firebase_uid}")
async def get_user_by_firebase_uid(
    firebase_uid: str,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get user by Firebase UID"""
    try:
        # Verify user can only access their own data
        if firebase_user.get('uid') != firebase_uid:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Return basic user info
        return {
            "firebaseUID": firebase_uid,
            "email": firebase_user.get('email'),
            "displayName": firebase_user.get('name'),
            "created": True
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user by Firebase UID: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user")

@router.post("/users/create")
async def create_user_document(
    user_data: dict,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Create user document"""
    try:
        # Verify user can only create their own document
        if firebase_user.get('uid') != user_data.get('firebaseUID'):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # In production, create user document in database
        logger.info(f"Created user document for {firebase_user.get('uid')}")
        
        return {
            "success": True,
            "message": "User document created",
            "firebaseUID": firebase_user.get('uid')
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user document: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user document")

# Device Integration Endpoints
@router.get("/device/{device_id}/metrics", response_model=DeviceMetrics)
async def get_device_metrics(
    device_id: str,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token),
    user_service: UserService = Depends(get_user_service_dependency)
):
    """Get learning metrics for a specific device"""
    try:
        # Check if user has access to this device (simplified for now)
        # In production, verify device ownership through database
        
        # Try to get real data from existing backend
        try:
            user_stats = await user_service.get_user_statistics(device_id)
            return DeviceMetrics(
                wordsLearned=user_stats.get('words_learnt', []),
                topicsLearned=user_stats.get('topics_learnt', []),
                totalSessions=user_stats.get('total_sessions', 0),
                totalMinutes=int(user_stats.get('total_session_time', 0) / 60),
                currentEpisode=user_stats.get('current_episode', 1),
                currentSeason=user_stats.get('current_season', 1),
                lastActivity=user_stats.get('last_activity'),
                streakDays=user_stats.get('streak_days', 0)
            )
        except:
            # Return mock data if real data not available
            return DeviceMetrics(
                wordsLearned=['Hola', 'Adiós', 'Gracias', 'Por favor'],
                topicsLearned=['Greetings', 'Politeness'],
                totalSessions=5,
                totalMinutes=45,
                currentEpisode=2,
                currentSeason=1,
                lastActivity="2024-01-15T10:30:00Z",
                streakDays=3
            )
    except Exception as e:
        logger.error(f"Error fetching device metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch device metrics")

@router.get("/device/{device_id}/status")
async def get_device_status(
    device_id: str,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token),
    websocket_manager = Depends(get_websocket_manager_dependency)
):
    """Get device connection status"""
    try:
        # Check WebSocket connection status
        connection_info = await websocket_manager.get_connection_info(device_id)
        
        return {
            "connected": connection_info is not None,
            "lastSeen": connection_info.get('last_seen') if connection_info else None,
            "device_id": device_id
        }
    except Exception as e:
        logger.error(f"Error fetching device status: {e}")
        return {
            "connected": False,
            "lastSeen": None,
            "device_id": device_id
        }

@router.get("/device/{device_id}/transcripts")
async def get_device_transcripts(
    device_id: str,
    limit: int = 10,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token),
    user_service: UserService = Depends(get_user_service_dependency)
):
    """Get conversation transcripts for a device"""
    try:
        # Try to get real transcripts
        try:
            transcripts = await user_service.get_user_transcripts(device_id, limit)
            return {"transcripts": transcripts}
        except:
            # Return mock transcripts
            return {
                "transcripts": [
                    {
                        "id": "1",
                        "date": "2024-01-15",
                        "time": "10:30 AM",
                        "duration": "5 minutes",
                        "episode_title": "First Meeting",
                        "conversation_count": 8,
                        "preview": 'Child: "Hello!" | Bern: "¡Hola! ¿Cómo te llamas?"'
                    }
                ]
            }
    except Exception as e:
        logger.error(f"Error fetching device transcripts: {e}")
        return {"transcripts": []}

@router.post("/device/{device_id}/test-connection")
async def test_device_connection(
    device_id: str,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token),
    websocket_manager = Depends(get_websocket_manager_dependency)
):
    """Test connection to a device"""
    try:
        # Test connection logic
        connection_test = await websocket_manager.test_connection(device_id)
        
        return {
            "success": connection_test.get('success', False),
            "message": connection_test.get('message', 'Connection test completed'),
            "device_id": device_id
        }
    except Exception as e:
        logger.error(f"Error testing device connection: {e}")
        return {
            "success": False,
            "error": str(e),
            "device_id": device_id
        }

@router.get("/user/devices")
async def get_user_devices(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token),
    user_service: UserService = Depends(get_user_service_dependency)
):
    """Get all devices linked to user"""
    try:
        devices = await user_service.get_devices_by_firebase_uid(firebase_user.get('uid'))
        return {
            "devices": devices,
            "count": len(devices)
        }
    except Exception as e:
        logger.error(f"Error fetching user devices: {e}")
        return {
            "devices": [],
            "count": 0
        }