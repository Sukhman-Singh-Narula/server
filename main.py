"""
ESP32 Audio Streaming Server - Main Application (Fixed)
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
import uvicorn

# Configuration and settings
from config.settings import get_settings, validate_settings

# Routes
from routes.auth import router as auth_router
from routes.users import router as users_router
from routes.prompts import router as prompts_router
from routes.websocket import router as websocket_router
from routes.conversations import router as conversations_router

# Middleware
from middleware.security import SecurityMiddleware, get_cors_config
from middleware.logging import RequestLoggingMiddleware, MetricsCollectionMiddleware, set_metrics_middleware

# Services
from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from services.websocket_service import get_websocket_manager

# Utils
from utils.logger import setup_logging
from utils.exceptions import handle_generic_error


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
        ## ESP32 Audio Streaming Server
        
        A comprehensive FastAPI server for managing ESP32 device connections with OpenAI Realtime API integration.
        
        ### Features:
        - **Device Authentication**: Secure device ID validation (ABCD1234 format)
        - **Real-time Audio Streaming**: WebSocket connections for ESP32 ↔ OpenAI audio streaming
        - **User Management**: Registration, progress tracking, and session management
        - **Learning System**: Season/episode progression with system prompts
        - **Firebase Integration**: User data and prompt storage
        - **Security**: Rate limiting, IP blocking, and request validation
        - **Monitoring**: Comprehensive logging and metrics collection
        
        ### Getting Started:
        1. Register a user with POST /auth/register
        2. Upload system prompts with POST /prompts/
        3. Connect ESP32 via WebSocket /ws/{device_id}
        4. Monitor progress with GET /users/{device_id}
        """,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        debug=settings.debug
    )
    
    return app


# Initialize app
app = create_application()

# Add CORS middleware
cors_config = get_cors_config()
app.add_middleware(CORSMiddleware, **cors_config)

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
app.include_router(conversations_router)

# Root endpoint
@app.get("/", 
         summary="Server status",
         description="Get server status and basic information")
async def root():
    """Root endpoint returning server status"""
    settings = get_settings()
    
    return {
        "message": "ESP32 Audio Streaming Server is running",
        "version": settings.app_version,
        "status": "healthy",
        "documentation": "/docs",
        "websocket_endpoint": "/ws/{device_id}",
        "features": [
            "ESP32 WebSocket connections",
            "OpenAI Realtime API integration", 
            "User registration and management",
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
        # Check Firebase health
        firebase_service = get_firebase_service()
        firebase_healthy = await firebase_service.health_check()
        health_status["services"]["firebase"] = "healthy" if firebase_healthy else "unhealthy"
        
        # Check WebSocket manager
        websocket_manager = get_websocket_manager()
        active_connections = len(websocket_manager.connections)
        health_status["services"]["websocket"] = {
            "status": "healthy",
            "active_connections": active_connections
        }
        
        # Check OpenAI service
        openai_service = get_openai_service()
        openai_connections = len(openai_service.active_connections)
        health_status["services"]["openai"] = {
            "status": "healthy",
            "active_connections": openai_connections
        }
        
        # Overall status - check if all services are healthy
        all_healthy = True
        for service_name, service_status in health_status["services"].items():
            if isinstance(service_status, dict):
                if service_status.get("status") != "healthy":
                    all_healthy = False
                    break
            elif service_status != "healthy":
                all_healthy = False
                break
        
        health_status["status"] = "healthy" if all_healthy else "degraded"
        
        # Return appropriate status code
        status_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        
        return JSONResponse(
            status_code=status_code,
            content=health_status
        )
        
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["error"] = str(e)
        
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status
        )


# Metrics endpoint
@app.get("/metrics",
         summary="Application metrics",
         description="Get application performance metrics")
async def get_metrics():
    """Get application metrics"""
    try:
        from middleware.logging import get_metrics_middleware
        
        metrics_middleware = get_metrics_middleware()
        if metrics_middleware:
            metrics = metrics_middleware.get_current_metrics()
            return {
                "metrics": metrics,
                "note": "Metrics are collected automatically and reset periodically"
            }
        else:
            return {
                "message": "Metrics collection not available",
                "metrics": {}
            }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


# Global exception handlers
from utils.exceptions import (
    ValidationException, UserNotFoundException, UserAlreadyExistsException,
    SystemPromptNotFoundException, WebSocketConnectionException, 
    RateLimitException, SecurityException, handle_validation_error, 
    handle_user_error, handle_generic_error
)

@app.exception_handler(ValidationException)
async def validation_exception_handler(request, exc: ValidationException):
    """Handle validation exceptions globally"""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=handle_validation_error(exc)
    )

@app.exception_handler(UserNotFoundException)
async def user_not_found_handler(request, exc: UserNotFoundException):
    """Handle user not found exceptions"""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=handle_user_error(exc)
    )

@app.exception_handler(UserAlreadyExistsException)
async def user_exists_handler(request, exc: UserAlreadyExistsException):
    """Handle user already exists exceptions"""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=handle_user_error(exc)
    )

@app.exception_handler(SystemPromptNotFoundException)
async def prompt_not_found_handler(request, exc: SystemPromptNotFoundException):
    """Handle system prompt not found exceptions"""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "System Prompt Not Found",
            "message": exc.message,
            "season": exc.season,
            "episode": exc.episode,
            "code": exc.error_code
        }
    )

@app.exception_handler(RateLimitException)
async def rate_limit_handler(request, exc: RateLimitException):
    """Handle rate limit exceptions"""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "Rate Limit Exceeded",
            "message": exc.message,
            "limit": exc.limit,
            "window_seconds": exc.window,
            "code": exc.error_code
        }
    )

@app.exception_handler(SecurityException)
async def security_exception_handler(request, exc: SecurityException):
    """Handle security violations"""
    # Log security event
    from utils.logger import log_security_event
    log_security_event(
        exc.violation_type,
        exc.identifier,
        {
            "path": str(request.url.path),
            "method": request.method,
            "details": exc.details
        }
    )
    
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error": "Security Violation",
            "message": "Access denied due to security policy",
            "code": exc.error_code
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """Global exception handler for unhandled errors"""
    import logging
    
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred",
            "request_id": request.headers.get("X-Request-ID", "unknown")
        }
    )


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Custom 404 handler"""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "Not Found",
            "message": f"The requested endpoint {request.url.path} was not found",
            "available_endpoints": [
                "/docs - API documentation",
                "/health - Health check",
                "/auth/register - User registration", 
                "/users/{device_id} - User management",
                "/prompts/ - System prompt management",
                "/ws/{device_id} - WebSocket connection"
            ]
        }
    )


# Development server startup
if __name__ == "__main__":
    settings = get_settings()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                ESP32 Audio Streaming Server                 ║
║                        Version {settings.app_version}                        ║
╠══════════════════════════════════════════════════════════════╣
║  📋 Documentation: http://{settings.host}:{settings.port}/docs               ║
║  🔗 WebSocket: ws://{settings.host}:{settings.port}/ws/{{device_id}}         ║
║  💡 Health Check: http://{settings.host}:{settings.port}/health              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=True,
        server_header=False,  # Security: hide server info
        date_header=False     # Security: hide date header
    )