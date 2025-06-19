"""
Authentication and user registration routes
"""
from fastapi import APIRouter, HTTPException, status, Depends
from models.user import UserRegistrationRequest, UserResponse
from services.user_service import get_user_service, UserService
from utils.exceptions import (
    ValidationException, UserAlreadyExistsException, 
    handle_validation_error, handle_user_error, handle_generic_error
)
from utils.logger import LoggerMixin
from utils.security import SecurityValidator


router = APIRouter(prefix="/auth", tags=["Authentication"])


def get_user_service_dependency():
    """Dependency to get user service"""
    return get_user_service()


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
        
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"User registered successfully: {user_data.device_id}")
        
        return user_response
        
    except ValidationException as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Registration validation failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except UserAlreadyExistsException as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Registration failed - user exists: {e.device_id}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=handle_user_error(e)
        )
    
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Registration failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/verify/{device_id}",
            summary="Verify device registration", 
            description="Check if a device ID is registered and get basic info")
async def verify_device(device_id: str, user_service: UserService = Depends(get_user_service_dependency)):
    """
    Verify if a device is registered without returning sensitive information
    
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


@router.get("/registration-stats",
            summary="Get registration statistics",
            description="Get general registration statistics (admin endpoint)")
async def get_registration_stats():
    """
    Get registration statistics (would typically require admin authentication)
    """
    # Note: In a real application, this would require admin authentication
    # and would pull actual statistics from the database
    
    import logging
    logger = logging.getLogger(__name__)
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

