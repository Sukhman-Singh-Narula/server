# utils/firebase_auth.py - Firebase Authentication Utilities
"""
Firebase authentication utilities for mobile app integration
"""
import firebase_admin
from firebase_admin import auth, credentials
from fastapi import HTTPException, status, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
import logging
import os
from config.settings import get_settings

logger = logging.getLogger(__name__)
security = HTTPBearer()

# Initialize Firebase Admin SDK
def initialize_firebase():
    """Initialize Firebase Admin SDK if not already initialized"""
    if not firebase_admin._apps:
        try:
            settings = get_settings()
            
            # Check if credentials file exists
            if not os.path.exists(settings.firebase_credentials_path):
                logger.error(f"Firebase credentials file not found: {settings.firebase_credentials_path}")
                raise FileNotFoundError(f"Firebase credentials file not found: {settings.firebase_credentials_path}")
            
            # Initialize with service account credentials
            cred = credentials.Certificate(settings.firebase_credentials_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
            raise e
    else:
        logger.debug("Firebase Admin SDK already initialized")

# Initialize Firebase when module is imported
try:
    initialize_firebase()
except Exception as e:
    logger.warning(f"Firebase initialization failed: {e}")

async def verify_firebase_token(
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """
    Verify Firebase ID token from Authorization header
    
    Args:
        authorization: Authorization header containing Bearer token
        
    Returns:
        Dict containing decoded token data
        
    Raises:
        HTTPException: If token is invalid or missing
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Use 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        # Verify the ID token
        decoded_token = auth.verify_id_token(token)
        logger.debug(f"Token verified successfully for user: {decoded_token.get('uid')}")
        return decoded_token
        
    except auth.ExpiredIdTokenError:
        logger.warning("Expired Firebase token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.RevokedIdTokenError:
        logger.warning("Revoked Firebase token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.InvalidIdTokenError:
        logger.warning("Invalid Firebase token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def verify_firebase_token_credentials(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Alternative method using HTTPBearer security scheme
    
    Args:
        credentials: HTTP authorization credentials
        
    Returns:
        Dict containing decoded token data
    """
    try:
        decoded_token = auth.verify_id_token(credentials.credentials)
        logger.debug(f"Token verified successfully for user: {decoded_token.get('uid')}")
        return decoded_token
        
    except auth.ExpiredIdTokenError:
        logger.warning("Expired Firebase token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except auth.RevokedIdTokenError:
        logger.warning("Revoked Firebase token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked"
        )
    except auth.InvalidIdTokenError:
        logger.warning("Invalid Firebase token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )

async def get_firebase_user(user_id: str) -> Optional[auth.UserRecord]:
    """
    Get Firebase user by UID
    
    Args:
        user_id: Firebase user UID
        
    Returns:
        UserRecord if found, None otherwise
    """
    try:
        user = auth.get_user(user_id)
        return user
    except auth.UserNotFoundError:
        logger.warning(f"Firebase user not found: {user_id}")
        return None
    except Exception as e:
        logger.error(f"Error getting Firebase user {user_id}: {e}")
        return None

async def verify_user_access(
    firebase_user: Dict[str, Any], 
    required_uid: str
) -> bool:
    """
    Verify that the authenticated user has access to the requested resource
    
    Args:
        firebase_user: Decoded Firebase token
        required_uid: Required user UID for access
        
    Returns:
        True if access is allowed, False otherwise
    """
    user_uid = firebase_user.get('uid')
    if user_uid != required_uid:
        logger.warning(f"Access denied: {user_uid} attempted to access {required_uid}")
        return False
    return True

# Dependency functions for FastAPI
async def get_current_user(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
) -> Dict[str, Any]:
    """Dependency to get current authenticated user"""
    return firebase_user

async def get_current_user_uid(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
) -> str:
    """Dependency to get current user UID"""
    return firebase_user.get('uid')

# Optional middleware for request logging
class FirebaseAuthMiddleware:
    """Middleware for Firebase authentication logging"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Log authentication attempts
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization")
            
            if auth_header:
                logger.debug("Firebase authentication attempt detected")
        
        await self.app(scope, receive, send)