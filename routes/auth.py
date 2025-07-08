"""
Complete Authentication Routes
Handles both ESP32 device registration and Firebase mobile authentication
"""
from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import firebase_admin
from firebase_admin import auth as firebase_auth

from models.user import UserRegistrationRequest, UserResponse
from services.user_service import get_user_service, UserService
from utils.exceptions import (
    ValidationException, UserAlreadyExistsException, 
    handle_validation_error, handle_user_error, handle_generic_error
)
from utils.logger import LoggerMixin
from utils.security import SecurityValidator
from utils.validators import DeviceValidator

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

# Dependency injection
def get_user_service_dependency():
    """Dependency to get user service"""
    return get_user_service()

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class DeviceIdValidationRequest(BaseModel):
    """Request model for device ID validation"""
    device_id: str = Field(..., description="Device ID to validate")

class FirebaseUserRegister(BaseModel):
    """Request model for Firebase user registration"""
    firebase_uid: str = Field(..., description="Firebase user ID")
    email: str = Field(..., description="User email")
    display_name: str = Field(..., description="User display name")
    firebase_token: str = Field(..., description="Firebase ID token")

class FirebaseUserLogin(BaseModel):
    """Request model for Firebase user login"""
    firebase_uid: str = Field(..., description="Firebase user ID")
    firebase_token: str = Field(..., description="Firebase ID token")

class DeviceLinkRequest(BaseModel):
    """Request model for linking device to Firebase user"""
    device_id: str = Field(..., description="ESP32 device ID")
    child_name: Optional[str] = Field(None, description="Child's name for the device")
    firebase_uid: str = Field(..., description="Firebase user ID")

class ChildProfile(BaseModel):
    """Child profile model"""
    id: str
    name: str
    age: int
    avatar: str = "bear"
    device_id: Optional[str] = None
    created_at: datetime

# ============================================================================
# FIREBASE TOKEN VERIFICATION
# ============================================================================

async def verify_firebase_token(authorization: Optional[str] = Header(None)):
    """Verify Firebase ID token from Authorization header"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )
    
    token = authorization.split(" ")[1]
    
    try:
        decoded_token = firebase_auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        logger.warning(f"Firebase token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Firebase token: {str(e)}"
        )

# ============================================================================
# ESP32 DEVICE REGISTRATION ENDPOINTS
# ============================================================================

@router.post("/register", 
             response_model=UserResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Register a new ESP32 device user",
             description="Register a new ESP32 device user with name and age")
async def register_user(
    user_data: UserRegistrationRequest, 
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Register a new ESP32 device user with device ID validation
    
    - **device_id**: Must be 4 uppercase letters followed by 4 digits (e.g., ABCD1234)
    - **name**: User's name (1-100 characters)
    - **age**: User's age (1-120 years)
    """
    try:
        # Sanitize input data
        sanitized_name = SecurityValidator.sanitize_input(user_data.name)
        user_data.name = sanitized_name
        
        # Register user
        user_response = await user_service.register_user(user_data)
        
        logger.info(f"ESP32 user registered successfully: {user_data.device_id}")
        return user_response
        
    except ValidationException as e:
        logger.warning(f"Registration validation failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except UserAlreadyExistsException as e:
        logger.warning(f"Registration failed - user exists: {e.device_id}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=handle_user_error(e)
        )
    
    except Exception as e:
        logger.error(f"Registration failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )

@router.get("/verify/{device_id}",
            summary="Verify ESP32 device registration", 
            description="Check if a device ID is registered and get basic info")
async def verify_device(
    device_id: str, 
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Verify if an ESP32 device is registered without returning sensitive information
    
    - **device_id**: Device ID to verify
    """
    try:
        # Get user (this will raise UserNotFoundException if not found)
        user_response = await user_service.get_user(device_id)
        
        # Return minimal verification info
        return {
            "registered": True,
            "device_id": device_id,
            "registration_date": user_response.created_at,
            "last_active": user_response.last_active,
            "current_season": user_response.season,
            "current_episode": user_response.episode
        }
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except Exception:
        # Don't expose whether user exists or not for security
        # Return false instead of raising 404
        return {
            "registered": False,
            "device_id": device_id
        }

@router.post("/validate-device-id",
             summary="Validate device ID format",
             description="Check if device ID follows the correct format")
async def validate_device_id(request: DeviceIdValidationRequest):
    """
    Validate device ID format without checking registration
    
    - **device_id**: Device ID to validate
    """
    device_id = request.device_id
    is_valid = DeviceValidator.validate_device_id(device_id)
    error_message = None
    
    if not is_valid:
        error_message = DeviceValidator.get_device_validation_error(device_id)
    
    return {
        "device_id": device_id,
        "is_valid": is_valid,
        "error_message": error_message,
        "format_requirement": "4 uppercase letters followed by 4 digits (e.g., ABCD1234)"
    }

# ============================================================================
# FIREBASE MOBILE AUTHENTICATION ENDPOINTS
# ============================================================================

@router.post("/mobile/register", 
             status_code=status.HTTP_201_CREATED,
             summary="Register Firebase user in backend",
             description="Register a Firebase authenticated user in the backend system")
async def register_firebase_user(user_data: FirebaseUserRegister):
    """
    Register a Firebase authenticated user in the backend system
    
    - **firebase_uid**: Firebase user ID
    - **email**: User's email address
    - **display_name**: User's display name
    - **firebase_token**: Firebase ID token for verification
    """
    try:
        # Verify the Firebase token
        decoded_token = firebase_auth.verify_id_token(user_data.firebase_token)
        
        if decoded_token['uid'] != user_data.firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token UID doesn't match provided Firebase UID"
            )
        
        # TODO: Save Firebase user to your database
        # For now, create a response based on Firebase data
        user_response = {
            "firebase_uid": user_data.firebase_uid,
            "email": user_data.email,
            "display_name": user_data.display_name,
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "subscription": "free",
            "child_profiles": []
        }
        
        logger.info(f"Firebase user registered: {user_data.firebase_uid}")
        return user_response
        
    except firebase_auth.InvalidIdTokenError:
        logger.warning(f"Invalid Firebase token for user: {user_data.firebase_uid}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase token"
        )
    except Exception as e:
        logger.error(f"Firebase registration failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )

@router.post("/mobile/login",
             summary="Login Firebase user",
             description="Login a Firebase authenticated user and sync with backend")
async def login_firebase_user(user_data: FirebaseUserLogin):
    """
    Login a Firebase authenticated user and sync with backend
    
    - **firebase_uid**: Firebase user ID
    - **firebase_token**: Firebase ID token for verification
    """
    try:
        # Verify the Firebase token
        decoded_token = firebase_auth.verify_id_token(user_data.firebase_token)
        
        if decoded_token['uid'] != user_data.firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token UID doesn't match provided Firebase UID"
            )
        
        # TODO: Get user from your database
        # For now, return Firebase token data
        user_response = {
            "firebase_uid": decoded_token['uid'],
            "email": decoded_token.get('email'),
            "name": decoded_token.get('name'),
            "login_time": datetime.now().isoformat(),
            "subscription": "free",
            "child_profiles": []
        }
        
        logger.info(f"Firebase user logged in: {decoded_token['uid']}")
        return user_response
        
    except firebase_auth.InvalidIdTokenError:
        logger.warning(f"Invalid Firebase token for login: {user_data.firebase_uid}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase token"
        )
    except Exception as e:
        logger.error(f"Firebase login failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )

@router.post("/mobile/link-device",
             summary="Link ESP32 device to Firebase user",
             description="Link an ESP32 device to a Firebase user account")
async def link_device_to_account(
    request: DeviceLinkRequest,
    user_token = Depends(verify_firebase_token)
):
    """
    Link an ESP32 device to a Firebase user account
    
    - **device_id**: ESP32 device ID (ABCD1234 format)
    - **child_name**: Optional child's name for the device
    - **firebase_uid**: Firebase user ID
    """
    try:
        # Validate device ID format
        if not DeviceValidator.validate_device_id(request.device_id):
            error_msg = DeviceValidator.get_device_validation_error(request.device_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid device ID format: {error_msg}"
            )
        
        # Verify token matches request
        if user_token['uid'] != request.firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token UID doesn't match requested Firebase UID"
            )
        
        # TODO: Link device to user in database
        # For now, return success response
        link_response = {
            "success": True,
            "device_id": request.device_id,
            "firebase_uid": request.firebase_uid,
            "child_name": request.child_name,
            "linked_at": datetime.now().isoformat()
        }
        
        logger.info(f"Device linked: {request.device_id} to user {request.firebase_uid}")
        return link_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Device linking failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Device linking failed: {str(e)}"
        )

# ============================================================================
# MOBILE ACCOUNT ENDPOINTS
# ============================================================================

@router.get("/mobile/account/details",
            summary="Get account details",
            description="Get Firebase user account details")
async def get_account_details(user_token = Depends(verify_firebase_token)):
    """Get user account details from Firebase token"""
    return {
        "displayName": user_token.get('name', 'User'),
        "email": user_token.get('email', ''),
        "phoneNumber": user_token.get('phone_number'),
        "avatar": user_token.get('picture'),
        "subscription": "free",
        "firebase_uid": user_token.get('uid'),
        "created_at": datetime.now().isoformat()
    }

@router.get("/mobile/account/children",
            summary="Get child profiles",
            description="Get all child profiles for the user")
async def get_child_profiles(user_token = Depends(verify_firebase_token)):
    """Get all child profiles for the authenticated user"""
    # TODO: Get actual child profiles from database
    # For now, return mock data
    return [
        {
            "id": "child_1",
            "name": "Emma",
            "age": 6,
            "avatar": "bear",
            "device_id": None,
            "created_at": datetime.now().isoformat()
        }
    ]

@router.post("/mobile/account/children",
             summary="Add child profile",
             description="Add a new child profile")
async def add_child_profile(
    child_data: dict,
    user_token = Depends(verify_firebase_token)
):
    """Add a new child profile"""
    # TODO: Add child to database
    # For now, return mock response
    return {
        "id": f"child_{datetime.now().timestamp()}",
        "name": child_data.get("name"),
        "age": child_data.get("age"),
        "avatar": child_data.get("avatar", "bear"),
        "device_id": None,
        "created_at": datetime.now().isoformat()
    }

@router.get("/mobile/account/subscription",
            summary="Get subscription status",
            description="Get user subscription status")
async def get_subscription_status(user_token = Depends(verify_firebase_token)):
    """Get user subscription status"""
    return {
        "status": "free",
        "expires_at": None,
        "features": ["basic_learning", "single_device"]
    }

@router.put("/mobile/account/preferences",
            summary="Update user preferences",
            description="Update user account preferences")
async def update_preferences(
    preferences: dict,
    user_token = Depends(verify_firebase_token)
):
    """Update user preferences"""
    # TODO: Save preferences to database
    return {
        "success": True,
        "preferences": preferences,
        "updated_at": datetime.now().isoformat()
    }

# ============================================================================
# ADMIN/STATS ENDPOINTS
# ============================================================================

@router.get("/registration-stats",
            summary="Get registration statistics",
            description="Get general registration statistics (admin endpoint)")
async def get_registration_stats():
    """
    Get registration statistics (would typically require admin authentication)
    """
    logger.info("Registration stats requested")
    
    return {
        "message": "Registration statistics endpoint",
        "note": "This would require admin authentication and database queries in production",
        "stats": {
            "total_users": "Would fetch from database",
            "active_users": "Would fetch from database", 
            "new_registrations_today": "Would fetch from database",
            "average_age": "Would calculate from database"
        }
    }

# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.get("/health",
            summary="Authentication service health check",
            description="Check if authentication service is healthy")
async def auth_health_check():
    """Health check for authentication service"""
    return {
        "service": "authentication",
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "features": {
            "esp32_registration": True,
            "firebase_auth": True,
            "device_linking": True
        }
    }
