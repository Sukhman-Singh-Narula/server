"""
Device API routes for ESP32 hardware communication
Implements the HTTP endpoints that your ESP32 expects
"""
import json
import base64
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from services.websocket_service import get_websocket_manager
from utils.validators import DeviceValidator
from utils.exceptions import ValidationException, UserNotFoundException, handle_validation_error
from utils.logger import LoggerMixin


router = APIRouter(prefix="/api", tags=["Device API"])


class DeviceAPIRoutes(LoggerMixin):
    """Device API route handlers for ESP32 communication"""
    
    def _init_(self):
        super()._init_()
        self.firebase_service = get_firebase_service()
        self.openai_service = get_openai_service()
        self.websocket_manager = get_websocket_manager()


device_api = DeviceAPIRoutes()


class DeviceConnectRequest(BaseModel):
    """Device connection request model"""
    device_id: str = Field(..., description="Device identifier")
    type: str = Field(default="device_connect", description="Request type")
    capabilities: list = Field(default=["audio_streaming"], description="Device capabilities")
    timestamp: Optional[int] = Field(None, description="Request timestamp")


class AudioProcessRequest(BaseModel):
    """Audio processing request model"""
    device_id: str = Field(..., description="Device identifier")
    type: str = Field(..., description="Request type")
    format: str = Field(default="adpcm", description="Audio format")
    sample_rate: int = Field(default=24000, description="Sample rate")
    channels: int = Field(default=1, description="Audio channels")
    data: str = Field(..., description="Base64 encoded audio data")
    size: int = Field(..., description="Audio data size")
    timestamp: Optional[int] = Field(None, description="Request timestamp")


class EndOfStreamRequest(BaseModel):
    """End of stream request model"""
    device_id: str = Field(..., description="Device identifier")
    type: str = Field(default="end_of_stream", description="Request type")
    frames_sent: int = Field(default=0, description="Number of frames sent")
    timestamp: Optional[int] = Field(None, description="Request timestamp")


# Health endpoint (this one works)
@router.get("/health", 
            summary="Server health check",
            description="Check if the server is running and accessible")
async def health_check():
    """
    Health check endpoint for ESP32 to verify server connectivity
    """
    device_api.log_info("Health check requested")
    
    # Check critical services
    try:
        firebase_healthy = await device_api.firebase_service.health_check()
        openai_healthy = device_api.openai_service is not None
        websocket_healthy = device_api.websocket_manager is not None
        
        health_status = {
            "status": "healthy",
            "services": {
                "firebase": "up" if firebase_healthy else "down",
                "openai": "up" if openai_healthy else "down", 
                "websocket": "up" if websocket_healthy else "down"
            },
            "message": "ESP32 Audio Server Running",
            "version": "1.0.0"
        }
        
        overall_healthy = firebase_healthy and openai_healthy and websocket_healthy
        
        return JSONResponse(
            status_code=200 if overall_healthy else 503,
            content=health_status
        )
        
    except Exception as e:
        device_api.log_error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "message": "Server health check failed"
            }
        )


# Device connection endpoint (this was missing!)
@router.post("/device/connect",
             summary="Connect ESP32 device",
             description="Establish connection between ESP32 and server")
async def connect_device(connect_request: DeviceConnectRequest):
    """
    Connect ESP32 device to server
    This endpoint handles the initial device connection setup
    """
    device_id = connect_request.device_id
    
    device_api.log_info(f"🤝 Device connection request: {device_id}")
    
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            device_api.log_warning(f"Invalid device ID: {device_id}")
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid device ID", "message": error_msg}
            )
        
        # Check if user exists
        try:
            user = await device_api.firebase_service.get_user(device_id)
            device_api.log_info(f"User found: {device_id} - S{user.progress.season}E{user.progress.episode}")
        except UserNotFoundException:
            device_api.log_warning(f"User not found: {device_id}")
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "Device not registered",
                    "message": f"Device {device_id} is not registered. Please register first.",
                    "device_id": device_id
                }
            )
        
        # Get current system prompt
        try:
            system_prompt = await device_api.firebase_service.get_system_prompt(
                user.progress.season, user.progress.episode
            )
            device_api.log_info(f"System prompt loaded for {device_id}")
        except Exception as e:
            device_api.log_error(f"Failed to load system prompt for {device_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail={"error": "System prompt not available", "message": str(e)}
            )
        
        # Check if device is already connected via WebSocket
        active_connections = device_api.websocket_manager.get_active_connections()
        is_websocket_connected = device_id in active_connections
        
        # Respond with connection information
        response = {
            "status": "connected",
            "device_id": device_id,
            "message": "Device connected successfully",
            "user_info": {
                "name": user.name,
                "age": user.age,
                "current_season": user.progress.season,
                "current_episode": user.progress.episode
            },
            "server_info": {
                "websocket_endpoint": f"ws://15.207.43.20:8001/ws/{device_id}",
                "audio_endpoint": "/api/audio/process",
                "websocket_connected": is_websocket_connected
            },
            "capabilities": connect_request.capabilities,
            "timestamp": connect_request.timestamp
        }
        
        device_api.log_info(f"✅ Device connected: {device_id}")
        return JSONResponse(status_code=200, content=response)
        
    except HTTPException:
        raise
    except Exception as e:
        device_api.log_error(f"Device connection failed for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "Connection failed", "message": str(e)}
        )


# Audio processing endpoint
@router.post("/audio/process",
             summary="Process audio data",
             description="Process audio data from ESP32 device")
async def process_audio(audio_request: AudioProcessRequest):
    """
    Process audio data from ESP32
    This handles both individual frames and end-of-stream signals
    """
    device_id = audio_request.device_id
    
    device_api.log_info(f"🎵 Audio processing request: {device_id}, type: {audio_request.type}")
    
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            raise HTTPException(status_code=400, detail="Invalid device ID")
        
        # Handle end of stream
        if audio_request.type == "end_of_stream":
            device_api.log_info(f"🏁 End of stream for {device_id}")
            
            # Trigger response generation if OpenAI is connected
            if device_api.openai_service.is_connected(device_id):
                try:
                    await device_api.openai_service.commit_audio_buffer(device_id)
                    await device_api.openai_service.create_response(device_id)
                    device_api.log_info(f"✅ Response triggered for {device_id}")
                except Exception as e:
                    device_api.log_warning(f"Failed to trigger response for {device_id}: {e}")
            
            return JSONResponse(
                status_code=200,
                content={
                    "status": "stream_ended",
                    "device_id": device_id,
                    "message": "Audio stream processing completed"
                }
            )
        
        # Handle audio data
        if audio_request.type == "audio_data":
            # Decode base64 audio data
            try:
                audio_data = base64.b64decode(audio_request.data)
                device_api.log_info(f"📤 Decoded audio: {len(audio_data)} bytes for {device_id}")
            except Exception as e:
                device_api.log_error(f"Failed to decode audio data for {device_id}: {e}")
                raise HTTPException(
                    status_code=400,
                    detail={"error": "Invalid audio data", "message": "Failed to decode base64 audio"}
                )
            
            # Forward to OpenAI if connected
            if device_api.openai_service.is_connected(device_id):
                try:
                    success = await device_api.openai_service.send_audio(device_id, audio_data)
                    if success:
                        device_api.log_info(f"✅ Audio forwarded to OpenAI for {device_id}")
                        status_msg = "Audio sent to OpenAI"
                    else:
                        device_api.log_warning(f"⚠ Failed to forward audio to OpenAI for {device_id}")
                        status_msg = "Audio received but OpenAI forwarding failed"
                except Exception as e:
                    device_api.log_error(f"Error forwarding audio to OpenAI for {device_id}: {e}")
                    status_msg = f"Audio received but OpenAI error: {str(e)}"
            else:
                device_api.log_info(f"📦 Audio stored locally for {device_id} (no OpenAI connection)")
                status_msg = "Audio received and stored locally"
            
            return JSONResponse(
                status_code=200,
                content={
                    "status": "audio_processed",
                    "device_id": device_id,
                    "bytes_processed": len(audio_data),
                    "format": audio_request.format,
                    "message": status_msg
                }
            )
        
        # Unknown request type
        device_api.log_warning(f"Unknown audio request type: {audio_request.type}")
        raise HTTPException(
            status_code=400,
            detail={"error": "Unknown request type", "message": f"Unsupported type: {audio_request.type}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        device_api.log_error(f"Audio processing failed for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "Audio processing failed", "message": str(e)}
        )


# Device status endpoint
@router.get("/device/{device_id}/status",
            summary="Get device status",
            description="Get current status of a specific device")
async def get_device_status(device_id: str):
    """
    Get current status and connection information for a device
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Check WebSocket connection
        active_connections = device_api.websocket_manager.get_active_connections()
        connection_info = active_connections.get(device_id)
        
        # Check OpenAI connection
        openai_connected = device_api.openai_service.is_connected(device_id)
        
        # Get user info if available
        user_info = None
        try:
            user = await device_api.firebase_service.get_user(device_id)
            user_info = {
                "name": user.name,
                "age": user.age,
                "current_season": user.progress.season,
                "current_episode": user.progress.episode,
                "total_time": user.progress.total_time
            }
        except UserNotFoundException:
            pass
        
        status_info = {
            "device_id": device_id,
            "websocket_connected": connection_info is not None,
            "openai_connected": openai_connected,
            "connection_info": connection_info,
            "user_info": user_info,
            "server_endpoints": {
                "health": "/api/health",
                "connect": "/api/device/connect", 
                "audio": "/api/audio/process",
                "websocket": f"/ws/{device_id}"
            }
        }
        
        return JSONResponse(status_code=200, content=status_info)
        
    except HTTPException:
        raise
    except Exception as e:
        device_api.log_error(f"Failed to get device status for {device_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to get device status", "message": str(e)}
        )


# Device list endpoint
@router.get("/devices",
            summary="List all devices",
            description="Get list of all connected and registered devices")
async def list_devices():
    """
    Get list of all devices with their current status
    """
    try:
        # Get active WebSocket connections
        active_connections = device_api.websocket_manager.get_active_connections()
        
        # Get OpenAI connections
        openai_connections = device_api.openai_service.get_connection_count()
        
        device_list = []
        for device_id, conn_info in active_connections.items():
            try:
                # Try to get user info
                user = await device_api.firebase_service.get_user(device_id, raise_if_not_found=False)
                user_info = None
                if user:
                    user_info = {
                        "name": user.name,
                        "age": user.age,
                        "season": user.progress.season,
                        "episode": user.progress.episode
                    }
                
                device_list.append({
                    "device_id": device_id,
                    "websocket_connected": True,
                    "openai_connected": device_api.openai_service.is_connected(device_id),
                    "session_duration": conn_info.get("duration", 0),
                    "last_activity": conn_info.get("last_activity", 0),
                    "user_info": user_info
                })
            except Exception as e:
                device_api.log_warning(f"Error getting info for device {device_id}: {e}")
        
        return JSONResponse(
            status_code=200,
            content={
                "total_devices": len(device_list),
                "websocket_connections": len(active_connections),
                "openai_connections": openai_connections,
                "devices": device_list
            }
        )
        
    except Exception as e:
        device_api.log_error(f"Failed to list devices: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to list devices", "message": str(e)}
        )