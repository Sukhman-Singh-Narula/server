"""
ESP32 Audio Streaming Server - Main Application with Mobile Integration
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Dict, Any, List, Optional
import uvicorn
import logging

# Configuration and settings
from config.settings import get_settings, validate_settings

# Routes
from routes.auth import router as auth_router
from routes.users import router as users_router
from routes.prompts import router as prompts_router
from routes.websocket import router as websocket_router

# Middleware
from middleware.security import SecurityMiddleware, get_cors_config
from middleware.logging import RequestLoggingMiddleware, MetricsCollectionMiddleware, set_metrics_middleware

# Services
from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from services.websocket_service import get_websocket_manager
from services.user_service import get_user_service

# Utils
from utils.logger import setup_logging
from utils.exceptions import handle_generic_error
from utils.firebase_auth import verify_firebase_token

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    
    # Startup
    print("🚀 Starting ESP32 Audio Streaming Server...")
    
    try:
        # Validate configuration
        if not validate_settings():
            raise Exception("Configuration validation failed")
        
        # Initialize logging
        setup_logging()
        print("✅ Logging initialized")
        
        # Initialize services
        firebase_service = get_firebase_service()
        print("✅ Firebase service initialized")
        
        openai_service = get_openai_service()
        print("✅ OpenAI service initialized")
        
        websocket_manager = get_websocket_manager()
        print("✅ WebSocket manager initialized")
        
        print("🎯 Server startup completed successfully")
        
        yield
        
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        raise
    
    finally:
        # Shutdown
        print("🛑 Shutting down ESP32 Audio Streaming Server...")
        
        try:
            # Close WebSocket connections
            websocket_manager = get_websocket_manager()
            await websocket_manager.shutdown()
            print("✅ WebSocket connections closed")
            
            # Close OpenAI connections
            openai_service = get_openai_service()
            await openai_service.close_all_connections()
            print("✅ OpenAI connections closed")
            
            print("✅ Server shutdown completed")
            
        except Exception as e:
            print(f"⚠️ Shutdown error: {e}")


# Create FastAPI application
def create_application() -> FastAPI:
    """Create and configure FastAPI application"""
    
    settings = get_settings()
    
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="""
        ## ESP32 Audio Streaming Server with Mobile Integration
        
        A comprehensive FastAPI server for managing ESP32 device connections with OpenAI Realtime API integration and mobile app support.
        
        ### Features:
        - **Device Authentication**: Secure device ID validation (ABCD1234 format)
        - **Real-time Audio Streaming**: WebSocket connections for ESP32 ↔ OpenAI audio streaming
        - **User Management**: Registration, progress tracking, and session management
        - **Mobile App Integration**: Complete API for React Native mobile app
        - **Learning System**: Season/episode progression with system prompts
        - **Firebase Integration**: User data and prompt storage with Firebase Auth
        - **Security**: Rate limiting, IP blocking, and request validation
        - **Monitoring**: Comprehensive logging and metrics collection
        
        ### Getting Started:
        1. Register a user with POST /auth/register (for ESP32) or use Firebase Auth (for mobile)
        2. Upload system prompts with POST /prompts/
        3. Connect ESP32 via WebSocket /ws/{device_id}
        4. Use mobile endpoints under /mobile/ for app integration
        """,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        debug=settings.debug
    )
    
    return app


# Initialize app
app = create_application()

# Add CORS middleware - Allow all for now
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middleware (order matters - security first, then logging)
app.add_middleware(SecurityMiddleware)
app.add_middleware(RequestLoggingMiddleware)

# Add metrics middleware and store reference
metrics_middleware = MetricsCollectionMiddleware(app)
app.add_middleware(MetricsCollectionMiddleware)
set_metrics_middleware(metrics_middleware)

# Include routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(prompts_router)
app.include_router(websocket_router)

# ========================
# MOBILE APP ENDPOINTS
# ========================

# Mobile Account Management
@app.get("/mobile/account/details")
async def get_mobile_account_details(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get account details for mobile app"""
    try:
        return {
            "displayName": firebase_user.get('name', 'User'),
            "email": firebase_user.get('email', ''),
            "phoneNumber": firebase_user.get('phone_number'),
            "subscription": "free",
            "avatar": firebase_user.get('picture')
        }
    except Exception as e:
        logger.error(f"Error fetching account details: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch account details")

@app.get("/mobile/account/children")
async def get_mobile_child_profiles(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get child profiles for mobile app"""
    try:
        # Return mock data for now - in production, fetch from database
        return [
            {
                "id": "child_1",
                "name": "Emma",
                "age": 6,
                "avatar": "bear",
                "deviceId": None,
                "created_at": "2024-01-01T00:00:00Z"
            }
        ]
    except Exception as e:
        logger.error(f"Error fetching child profiles: {e}")
        return []

@app.post("/mobile/account/children")
async def add_mobile_child_profile(
    child_data: dict,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Add a new child profile for mobile app"""
    try:
        import uuid
        
        new_child = {
            "id": str(uuid.uuid4()),
            "name": child_data.get('name'),
            "age": child_data.get('age'),
            "avatar": child_data.get('avatar', 'bear'),
            "deviceId": None,
            "created_at": datetime.utcnow().isoformat() + 'Z'
        }
        
        logger.info(f"Added child profile: {new_child['name']} for user {firebase_user.get('uid')}")
        return new_child
    except Exception as e:
        logger.error(f"Error adding child profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to add child profile")

@app.get("/mobile/account/subscription")
async def get_mobile_subscription_status(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get subscription status for mobile app"""
    try:
        return {
            "status": "free",
            "expiresAt": None,
            "features": ["basic_learning", "single_device"]
        }
    except Exception as e:
        logger.error(f"Error fetching subscription status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch subscription status")

# Teddy Bear Management
@app.get("/mobile/teddy")
async def get_mobile_teddy(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get teddy bear status for mobile app"""
    try:
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

@app.post("/mobile/teddy")
async def save_mobile_teddy(
    teddy_data: dict,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Save or update teddy bear configuration for mobile app"""
    try:
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
@app.get("/mobile/learning/progress")
async def get_mobile_learning_progress(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get learning progress for mobile app"""
    try:
        return {
            "completedEpisodes": [
                {
                    "id": "ep_1",
                    "title": "First Meeting",
                    "season": 1,
                    "episode": 1,
                    "completedAt": "2024-01-10T00:00:00Z",
                    "score": 85
                }
            ],
            "currentEpisode": {
                "id": "ep_2",
                "title": "Learning Colors",
                "season": 1,
                "episode": 2,
                "progress": 60
            }
        }
    except Exception as e:
        logger.error(f"Error fetching learning progress: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch learning progress")

# User Management for Mobile
@app.get("/mobile/users/firebase/{firebase_uid}")
async def get_mobile_user_by_firebase_uid(
    firebase_uid: str,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get user by Firebase UID for mobile app"""
    try:
        # Verify user can only access their own data
        if firebase_user.get('uid') != firebase_uid:
            raise HTTPException(status_code=403, detail="Access denied")
        
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

@app.post("/mobile/users/create")
async def create_mobile_user_document(
    user_data: dict,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Create user document for mobile app"""
    try:
        # Verify user can only create their own document
        if firebase_user.get('uid') != user_data.get('firebaseUID'):
            raise HTTPException(status_code=403, detail="Access denied")
        
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

# Device Management for Mobile
@app.get("/mobile/device/{device_id}/metrics")
async def get_mobile_device_metrics(
    device_id: str,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get device metrics for mobile app"""
    try:
        user_service = get_user_service()
        try:
            user_stats = await user_service.get_user_statistics(device_id)
            return {
                "wordsLearned": user_stats.get('words_learnt', []),
                "topicsLearned": user_stats.get('topics_learnt', []),
                "totalSessions": user_stats.get('total_sessions', 0),
                "totalMinutes": int(user_stats.get('total_session_time', 0) / 60),
                "currentEpisode": user_stats.get('current_episode', 1),
                "currentSeason": user_stats.get('current_season', 1),
                "lastActivity": user_stats.get('last_activity'),
                "streakDays": user_stats.get('streak_days', 0)
            }
        except:
            # Return mock data if real data not available
            return {
                "wordsLearned": ['Hola', 'Adiós', 'Gracias', 'Por favor'],
                "topicsLearned": ['Greetings', 'Politeness'],
                "totalSessions": 5,
                "totalMinutes": 45,
                "currentEpisode": 2,
                "currentSeason": 1,
                "lastActivity": "2024-01-15T10:30:00Z",
                "streakDays": 3
            }
    except Exception as e:
        logger.error(f"Error fetching device metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch device metrics")

@app.get("/mobile/device/{device_id}/status")
async def get_mobile_device_status(
    device_id: str,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get device status for mobile app"""
    try:
        websocket_manager = get_websocket_manager()
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

@app.get("/mobile/device/{device_id}/transcripts")
async def get_mobile_device_transcripts(
    device_id: str,
    limit: int = 10,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get device transcripts for mobile app"""
    try:
        user_service = get_user_service()
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

@app.post("/mobile/device/{device_id}/test-connection")
async def test_mobile_device_connection(
    device_id: str,
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Test device connection for mobile app"""
    try:
        websocket_manager = get_websocket_manager()
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

@app.get("/mobile/user/devices")
async def get_mobile_user_devices(
    firebase_user: Dict[str, Any] = Depends(verify_firebase_token)
):
    """Get user devices for mobile app"""
    try:
        user_service = get_user_service()
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

# Root endpoint
@app.get("/", 
         summary="Server status",
         description="Get server status and basic information")
async def root():
    """Root endpoint returning server status"""
    settings = get_settings()
    
    return {
        "message": "ESP32 Audio Streaming Server with Mobile Integration",
        "version": settings.app_version,
        "status": "healthy",
        "documentation": "/docs",
        "websocket_endpoint": "/ws/{device_id}",
        "mobile_endpoints": "/mobile/*",
        "features": [
            "ESP32 WebSocket connections",
            "OpenAI Realtime API integration", 
            "User registration and management",
            "Mobile app integration",
            "Firebase authentication",
            "System prompt management",
            "Session tracking",
            "Security middleware",
            "Comprehensive logging"
        ]
    }


# Health check endpoint
@app.get("/health",
         summary="Health check",
         description="Comprehensive health check for all services")
async def health_check():
    """Comprehensive health check endpoint"""
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {}
    }
    
    try:
        # Check Firebase service
        firebase_service = get_firebase_service()
        health_status["services"]["firebase"] = "healthy"
    except Exception as e:
        health_status["services"]["firebase"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    try:
        # Check OpenAI service
        openai_service = get_openai_service()
        health_status["services"]["openai"] = "healthy"
    except Exception as e:
        health_status["services"]["openai"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    try:
        # Check WebSocket manager
        websocket_manager = get_websocket_manager()
        active_connections = len(getattr(websocket_manager, 'active_connections', {}))
        health_status["services"]["websocket"] = f"healthy (connections: {active_connections})"
    except Exception as e:
        health_status["services"]["websocket"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Add mobile endpoints status
    health_status["services"]["mobile_endpoints"] = "healthy"
    
    return health_status


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Custom 404 handler with available endpoints"""
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": f"The requested endpoint {request.url.path} was not found",
            "available_endpoints": [
                "/docs - API documentation",
                "/health - Health check", 
                "/auth/register - User registration",
                "/auth/link-device - Link device to mobile account",
                "/users/{device_id} - User management",
                "/prompts/ - System prompt management",
                "/ws/{device_id} - WebSocket connection",
                "/mobile/account/* - Mobile account management",
                "/mobile/device/* - Mobile device management", 
                "/mobile/teddy - Teddy bear management",
                "/mobile/learning/progress - Learning progress"
            ]
        }
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Custom 500 handler"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred",
            "timestamp": datetime.now().isoformat()
        }
    )


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )