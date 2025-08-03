"""
ESP32 Audio Streaming Server - Updated Main Application
Fixed version with device API routes
"""
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import all route modules
from routes import auth, users, prompts, websocket, device  # Added device routes
from services.websocket_service import get_websocket_manager
from services.openai_service import get_openai_service
from services.firebase_service import get_firebase_service
from utils.logger import LoggerMixin
from config.settings import get_settings


class AppManager(LoggerMixin):
    """Application lifecycle manager"""
    
    def _init_(self):
        super()._init_()
        self.settings = get_settings()
    
    async def startup(self):
        """Initialize services on startup"""
        self.log_info("🚀 Starting ESP32 Audio Streaming Server")
        
        # Initialize services
        firebase_service = get_firebase_service()
        websocket_manager = get_websocket_manager()
        openai_service = get_openai_service()
        
        # Test Firebase connection
        firebase_healthy = await firebase_service.health_check()
        self.log_info(f"Firebase connection: {'✅ Healthy' if firebase_healthy else '❌ Failed'}")
        
        # Log service status
        self.log_info(f"WebSocket manager: {'✅ Ready' if websocket_manager else '❌ Failed'}")
        self.log_info(f"OpenAI service: {'✅ Ready' if openai_service else '❌ Failed'}")
        
        self.log_info("✅ ESP32 Audio Streaming Server started successfully")
        self.log_info(f"🌐 Server listening on: {self.settings.host}:{self.settings.port}")
        self.log_info(f"📚 API documentation: http://{self.settings.host}:{self.settings.port}/docs")
    
    async def shutdown(self):
        """Clean up resources on shutdown"""
        self.log_info("🛑 Shutting down ESP32 Audio Streaming Server")
        
        try:
            # Close WebSocket connections
            websocket_manager = get_websocket_manager()
            await websocket_manager.shutdown()
            
            # Close OpenAI connections
            openai_service = get_openai_service()
            await openai_service.close_all_connections()
            
            self.log_info("✅ Server shutdown completed")
            
        except Exception as e:
            self.log_error(f"❌ Error during shutdown: {e}")


app_manager = AppManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    await app_manager.startup()
    yield
    # Shutdown
    await app_manager.shutdown()


# Create FastAPI application
app = FastAPI(
    title="ESP32 Audio Streaming Server",
    description="""
    *ESP32 Audio Streaming Server* for Real-time Voice Learning

    This server provides:
    - 🎤 Real-time audio streaming from ESP32 devices
    - 🤖 OpenAI GPT-4 Realtime API integration
    - 📚 Educational content management
    - 👥 User progress tracking
    - 🔌 WebSocket connections for low-latency audio

    ## Quick Start for ESP32
    1. *Register Device*: POST /auth/register
    2. *Connect WebSocket*: ws://your-server:8001/ws/{device_id}
    3. *Stream Audio*: Send audio bytes through WebSocket
    4. *Receive Responses*: Get AI audio responses in real-time

    ## Device ID Format
    Must be 4 uppercase letters followed by 4 digits (e.g., ABCD1234)
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors"""
    import logging
    logger = logging.getLogger(_name_)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred",
            "path": str(request.url)
        }
    )


# Include all route modules
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1") 
app.include_router(prompts.router, prefix="/api/v1")
app.include_router(websocket.router)  # No prefix for WebSocket routes
app.include_router(device.router)     # Device API routes (NEW!)


# Root endpoint
@app.get("/", 
         summary="Server Information",
         description="Get basic server information and status")
async def root():
    """
    Root endpoint providing server information and health status
    """
    settings = get_settings()
    
    # Get service status
    try:
        firebase_service = get_firebase_service()
        firebase_healthy = await firebase_service.health_check()
    except Exception:
        firebase_healthy = False
    
    websocket_manager = get_websocket_manager()
    openai_service = get_openai_service()
    
    active_connections = websocket_manager.get_active_connections()
    
    return {
        "service": "ESP32 Audio Streaming Server",
        "version": "1.0.0",
        "status": "running",
        "description": "Real-time audio streaming server for ESP32 educational devices",
        "endpoints": {
            "documentation": "/docs",
            "health": "/api/health",
            "websocket": "/ws/{device_id}",
            "device_api": "/api/device/connect",
            "audio_processing": "/api/audio/process",
            "user_registration": "/api/v1/auth/register"
        },
        "services": {
            "firebase": "healthy" if firebase_healthy else "unhealthy",
            "websocket": "healthy" if websocket_manager else "unhealthy",
            "openai": "healthy" if openai_service else "unhealthy"
        },
        "statistics": {
            "active_connections": len(active_connections),
            "openai_connections": openai_service.get_connection_count() if openai_service else 0
        },
        "device_requirements": {
            "device_id_format": "4 uppercase letters + 4 digits (e.g., ABCD1234)",
            "audio_format": "PCM16, 24kHz, Mono",
            "connection_flow": [
                "1. Register device via /api/v1/auth/register",
                "2. Test connection via /api/health", 
                "3. Connect device via /api/device/connect",
                "4. Open WebSocket to /ws/{device_id}",
                "5. Start audio streaming"
            ]
        }
    }


# Additional health endpoint (for compatibility)
@app.get("/health",
         summary="Health Check", 
         description="Simple health check endpoint")
async def health():
    """Simple health check for load balancers"""
    return {"status": "healthy", "service": "ESP32 Audio Streaming Server"}


if _name_ == "_main_":
    # Run the server
    settings = get_settings()
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info" if not settings.debug else "debug"
    )