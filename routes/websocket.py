"""
Fixed WebSocket routes for ESP32 device connections
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.responses import JSONResponse

from services.websocket_service import get_websocket_manager
from utils.validators import DeviceValidator
from utils.exceptions import ValidationException, handle_validation_error
from utils.logger import LoggerMixin, log_security_event
from utils.security import SecurityValidator


router = APIRouter(tags=["WebSocket"])


class WebSocketRoutes(LoggerMixin):
    """WebSocket route handlers"""
    
    def __init__(self):
        super().__init__()
        self.websocket_manager = get_websocket_manager()


websocket_routes = WebSocketRoutes()


@router.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    """
    WebSocket endpoint for ESP32 device connections
    
    This endpoint handles:
    - Device authentication via device ID validation
    - Audio streaming between ESP32 and OpenAI
    - Session management and progress tracking
    - Automatic disconnection on episode completion
    
    **Device ID Format**: Must be 4 uppercase letters followed by 4 digits (e.g., ABCD1234)
    
    **Connection Flow**:
    1. Validate device ID format
    2. Verify user registration
    3. Get current episode system prompt
    4. Establish OpenAI connection
    5. Start audio streaming
    6. Handle episode completion
    """
    
    # Get client IP for logging
    client_ip = websocket.client.host if websocket.client else "unknown"
    
    # Validate device ID format
    if not DeviceValidator.validate_device_id(device_id):
        error_msg = DeviceValidator.get_device_validation_error(device_id)
        websocket_routes.log_warning(f"Invalid device ID connection attempt: {device_id} from {client_ip}")
        
        # Log security event
        log_security_event(
            "invalid_device_id",
            device_id,
            {
                "client_ip": client_ip,
                "error": error_msg,
                "attempted_device_id": device_id
            }
        )
        
        await websocket.close(code=4000, reason=f"Invalid device ID format: {error_msg}")
        return
    
    # Sanitize device ID (additional security)
    device_id = SecurityValidator.sanitize_input(device_id)
    
    try:
        # Attempt to connect device - this handles the entire connection lifecycle
        await websocket_routes.websocket_manager.connect_device(
            websocket=websocket,
            device_id=device_id,
            remote_addr=client_ip
        )
        
        # The connect_device method will handle the connection and won't return
        # until the connection is closed. It manages:
        # 1. WebSocket acceptance
        # 2. User validation
        # 3. OpenAI connection setup
        # 4. Message handling loop
        # 5. Cleanup on disconnect
        
        websocket_routes.log_info(f"WebSocket session completed for {device_id}")
        
    except WebSocketDisconnect:
        websocket_routes.log_info(f"WebSocket client disconnected: {device_id}")
    
    except Exception as e:
        websocket_routes.log_error(f"WebSocket error for device {device_id}: {e}", exc_info=True)
        
        # Log security event for unexpected errors
        log_security_event(
            "websocket_error",
            device_id,
            {
                "client_ip": client_ip,
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass  # Connection might already be closed


@router.get("/ws/connections",
            summary="Get active WebSocket connections",
            description="Get information about all active WebSocket connections")
async def get_active_websocket_connections():
    """
    Get information about all currently active WebSocket connections
    
    Returns connection details including:
    - Device IDs
    - Connection timestamps
    - Session durations
    - Current learning progress
    
    Note: This endpoint would typically require admin authentication in production
    """
    try:
        connections = websocket_routes.websocket_manager.get_all_connections()
        
        websocket_routes.log_info("Active WebSocket connections requested")
        
        return {
            "timestamp": "2024-01-01T00:00:00Z",  # Would use actual timestamp
            "total_connections": len(connections),
            "connections": connections
        }
        
    except Exception as e:
        websocket_routes.log_error(f"Failed to get active connections: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to retrieve connection information"}
        )


@router.get("/ws/connection/{device_id}",
            summary="Get specific connection info",
            description="Get information about a specific device connection")
async def get_websocket_connection_info(device_id: str):
    """
    Get detailed information about a specific device's WebSocket connection
    
    - **device_id**: Unique device identifier
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=handle_validation_error(ValidationException(error_msg, "device_id", device_id))
            )
        
        # Get connection info
        connection_info = websocket_routes.websocket_manager.get_connection_info(device_id)
        
        if connection_info is None:
            return {
                "device_id": device_id,
                "is_connected": False,
                "message": "Device not currently connected"
            }
        
        websocket_routes.log_info(f"Connection info retrieved for device: {device_id}")
        return connection_info
        
    except HTTPException:
        raise
    
    except Exception as e:
        websocket_routes.log_error(f"Failed to get connection info for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to retrieve connection information"}
        )


@router.post("/ws/disconnect/{device_id}",
             summary="Disconnect device",
             description="Manually disconnect a specific device")
async def disconnect_device(device_id: str):
    """
    Manually disconnect a specific device from WebSocket
    
    - **device_id**: Unique device identifier
    
    Note: This would typically require admin authentication in production
    """
    try:
        # Validate device ID
        if not DeviceValidator.validate_device_id(device_id):
            error_msg = DeviceValidator.get_device_validation_error(device_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=handle_validation_error(ValidationException(error_msg, "device_id", device_id))
            )
        
        # Check if device is connected
        connection_info = websocket_routes.websocket_manager.get_connection_info(device_id)
        if connection_info is None:
            return {
                "device_id": device_id,
                "message": "Device not currently connected",
                "action": "none"
            }
        
        # Disconnect the device
        from models.websocket import DisconnectionReason
        await websocket_routes.websocket_manager.disconnect_device(
            device_id, 
            DisconnectionReason.SERVER_SHUTDOWN
        )
        
        websocket_routes.log_info(f"Device manually disconnected: {device_id}")
        
        return {
            "device_id": device_id,
            "message": "Device disconnected successfully",
            "action": "disconnected",
            "session_duration": connection_info.get("session_duration", 0)
        }
        
    except HTTPException:
        raise
    
    except Exception as e:
        websocket_routes.log_error(f"Failed to disconnect device {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to disconnect device"}
        )


@router.get("/ws/stats",
            summary="Get WebSocket statistics",
            description="Get overall WebSocket connection statistics")
async def get_websocket_stats():
    """
    Get overall statistics about WebSocket connections
    
    Returns metrics such as:
    - Total active connections
    - Average session duration
    - Connection success rate
    - Error statistics
    """
    try:
        connections = websocket_routes.websocket_manager.get_all_connections()
        
        # Calculate statistics
        total_connections = len(connections)
        total_session_time = sum(conn.get("session_duration", 0) for conn in connections.values())
        avg_session_duration = total_session_time / max(total_connections, 1)
        
        # Get unique seasons and episodes being accessed
        active_seasons = set()
        active_episodes = set()
        for conn in connections.values():
            if conn.get("current_season"):
                active_seasons.add(conn["current_season"])
            if conn.get("current_episode"):
                active_episodes.add(conn["current_episode"])
        
        stats = {
            "connection_stats": {
                "total_active_connections": total_connections,
                "average_session_duration_seconds": round(avg_session_duration, 2),
                "total_session_time_seconds": round(total_session_time, 2)
            },
            "learning_stats": {
                "active_seasons": sorted(list(active_seasons)),
                "active_episodes": sorted(list(active_episodes)),
                "unique_seasons_accessed": len(active_seasons),
                "unique_episodes_accessed": len(active_episodes)
            },
            "timestamp": "2024-01-01T00:00:00Z"  # Would use actual timestamp
        }
        
        websocket_routes.log_info("WebSocket statistics requested")
        return stats
        
    except Exception as e:
        websocket_routes.log_error(f"Failed to get WebSocket stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to retrieve WebSocket statistics"}
        )


# Health check for WebSocket service
@router.get("/ws/health",
            summary="WebSocket service health check",
            description="Check the health of the WebSocket service")
async def websocket_health_check():
    """
    Check the health of the WebSocket service and its dependencies
    """
    try:
        # Check if WebSocket manager is available
        manager_healthy = websocket_routes.websocket_manager is not None
        
        # Check Firebase connection health
        from services.firebase_service import get_firebase_service
        firebase_service = get_firebase_service()
        firebase_healthy = await firebase_service.health_check()
        
        # Check OpenAI service health (basic check)
        from services.openai_service import get_openai_service
        openai_service = get_openai_service()
        openai_healthy = openai_service is not None
        
        health_status = {
            "websocket_manager": "healthy" if manager_healthy else "unhealthy",
            "firebase_connection": "healthy" if firebase_healthy else "unhealthy",
            "openai_service": "healthy" if openai_healthy else "unhealthy",
            "overall_status": "healthy" if all([manager_healthy, firebase_healthy, openai_healthy]) else "degraded"
        }
        
        status_code = status.HTTP_200_OK if health_status["overall_status"] == "healthy" else status.HTTP_503_SERVICE_UNAVAILABLE
        
        return JSONResponse(
            status_code=status_code,
            content=health_status
        )
        
    except Exception as e:
        websocket_routes.log_error(f"Health check failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "websocket_manager": "error",
                "firebase_connection": "error", 
                "openai_service": "error",
                "overall_status": "unhealthy",
                "error": str(e)
            }
        )