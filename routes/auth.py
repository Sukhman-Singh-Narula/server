# routes/auth.py - Extended with mobile endpoints
"""
Authentication and user registration routes with mobile integration
"""
from fastapi import APIRouter, HTTPException, status, Depends
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from models.user import UserRegistrationRequest, UserResponse
from services.user_service import get_user_service, UserService
from utils.exceptions import (
    ValidationException, UserAlreadyExistsException, 
    handle_validation_error, handle_user_error, handle_generic_error
)
from utils.logger import LoggerMixin
from utils.security import SecurityValidator
from utils.firebase_auth import verify_firebase_token, get_current_user
import logging

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

# Mobile app models
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

def get_user_service_dependency():
    """Dependency to get user service"""
    return get_user_service()

# Original ESP32 endpoints
@router.post("/register", 
             response_model=UserResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Register a new user",
             description="Register a new ESP32 device user with name and age")
async def register_user(user_data: UserRegistrationRequest, user_service: UserService = Depends(get_user_service_dependency)):
    """
    Register a new user with device ID validation
    
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
        
        logger.info(f"User registered successfully: {user_data.device_id}")
        return user_response
        
    except ValidationException as e:
        logger.warning(f"Registration validation failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message
        )
    except UserAlreadyExistsException as e:
        logger.warning(f"User already exists: {user_data.device_id}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this device ID already exists"
        )
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )

@router.get("/verify/{device_id}",
            summary="Verify device registration",
            description="Check if a device ID is registered")
async def verify_device_registration(device_id: str):
    """
    Verify if a device is registered
    
    - **device_id**: Device ID to verify
    """
    try:
        user_service = get_user_service()
        user_response = await user_service.get_user(device_id)
        
        logger.info(f"Device verification successful: {device_id}")
        
        return {
            "registered": True,
            "device_id": device_id,
            "user_name": user_response.name
        }
        
    except Exception:
        # Don't expose internal errors for security
        # Return false instead of raising 404
        return {
            "registered": False,
            "device_id": device_id
        }

@router.post("/validate-device-id",
             summary="Validate device ID format",
             description="Check if device ID follows the correct format")
async def validate_device_id(device_id: str):
    """
    Validate device ID format without checking registration
    
    - **device_id**: Device ID to validate
    """
    from utils.validators import DeviceValidator
    
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

# Mobile app integration endpoints
@router.post("/link-device", response_model=DeviceLinkResponse)
async def link_device_to_account(
    request: DeviceLinkRequest,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token),
    user_service: UserService = Depends(get_user_service_dependency)
):
    """
    Link an ESP32 device to a child's account (Mobile App Integration)
    
    This endpoint connects a physical teddy bear (ESP32 device) to a specific
    child profile in the mobile app.
    """
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
        
        logger.info(f"Device linked successfully: {request.device_id} -> {request.child_id}")
        
        return DeviceLinkResponse(
            success=True,
            message="Device linked successfully",
            device_id=request.device_id,
            child_id=request.child_id
        )
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message
        )
    except Exception as e:
        logger.error(f"Device linking error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to link device"
        )

@router.get("/me",
            summary="Get current user info",
            description="Get information about the currently authenticated user")
async def get_current_user_info(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get current authenticated user information
    
    Returns Firebase user data for the authenticated user.
    """
    return {
        "uid": current_user.get('uid'),
        "email": current_user.get('email'),
        "email_verified": current_user.get('email_verified'),
        "name": current_user.get('name'),
        "picture": current_user.get('picture'),
        "provider_data": current_user.get('firebase', {}).get('identities', {})
    }

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