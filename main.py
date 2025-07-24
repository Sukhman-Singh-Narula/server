"""
Complete FIXED main.py - Replace your existing main.py with this
"""
import logging
import sys
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('server.log')
    ]
)

logger = logging.getLogger(__name__)

def startup_checks():
    """Perform startup validation before initializing services"""
    logger.info("🔍 Performing startup checks...")
    
    # Check OpenAI API key
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("❌ OPENAI_API_KEY environment variable not set")
        logger.error("Please set your OpenAI API key: export OPENAI_API_KEY='your-key-here'")
        sys.exit(1)
    
    logger.info("✅ OpenAI API key found")
    
    # Test critical imports
    try:
        from services.firebase_service import get_firebase_service
        logger.info("✅ Firebase service import successful")
    except ImportError as e:
        logger.error(f"❌ Firebase service import failed: {e}")
        sys.exit(1)
    
    try:
        from services.openai_service import get_openai_service
        logger.info("✅ OpenAI service import successful")
    except ImportError as e:
        logger.error(f"❌ OpenAI service import failed: {e}")
        sys.exit(1)
    
    try:
        from services.websocket_service import get_websocket_manager
        logger.info("✅ WebSocket service import successful")
    except ImportError as e:
        logger.error(f"❌ WebSocket service import failed: {e}")
        sys.exit(1)
    
    logger.info("🎉 All startup checks passed")

# Perform checks before importing services
startup_checks()

# Now import services after validation
from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from services.websocket_service import get_websocket_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with proper error handling"""
    logger.info("🚀 Starting ESP32 Audio Streaming Server...")
    
    try:
        # Initialize Firebase service
        firebase_service = get_firebase_service()
        logger.info("✅ Firebase service initialized")
        
        # Initialize OpenAI service
        openai_service = get_openai_service()
        logger.info("✅ OpenAI service initialized")
        
        # Initialize WebSocket manager
        websocket_manager = get_websocket_manager()
        logger.info("✅ WebSocket manager initialized")
        
        logger.info("🎉 All services initialized successfully")
        
        yield  # Server is running
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    finally:
        # Cleanup
        logger.info("🛑 Shutting down ESP32 Audio Streaming Server...")
        
        try:
            websocket_manager = get_websocket_manager()
            await websocket_manager.shutdown()
            logger.info("✅ WebSocket connections closed")
        except Exception as e:
            logger.warning(f"⚠ WebSocket shutdown error: {e}")
        
        try:
            openai_service = get_openai_service()
            await openai_service.close_all_connections()
            logger.info("✅ OpenAI connections closed")
        except Exception as e:
            logger.warning(f"⚠ OpenAI shutdown error: {e}")
        
        logger.info("✅ Server shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="ESP32 Audio Streaming Server",
    description="Real-time audio streaming with OpenAI integration",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ESP32 Audio Streaming Server",
        "version": "1.0.0"
    }

# Import and include routers
try:
    from routes.websocket import router as websocket_router
    app.include_router(websocket_router)
    logger.info("✅ WebSocket routes included")
except ImportError as e:
    logger.warning(f"⚠ Could not import WebSocket routes: {e}")

try:
    from routes.api import router as api_router
    app.include_router(api_router, prefix="/api")
    logger.info("✅ API routes included")
except ImportError as e:
    logger.warning(f"⚠ Could not import API routes: {e}")

if __name__ == "__main__":
    import uvicorn
    
    # Print startup banner
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                ESP32 Audio Streaming Server                 ║")
    print("║                        Version 1.0.0                        ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print("║  📋 Documentation: http://0.0.0.0:8001/docs               ║")
    print("║  🔗 WebSocket: ws://0.0.0.0:8001/ws/{device_id}         ║")
    print("║  💡 Health Check: http://0.0.0.0:8001/health              ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    
    # Run server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=False,  # Set to True for development
        log_level="info"
    )