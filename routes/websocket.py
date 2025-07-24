# File: /home/ubuntu/finalMVPserver/server/routes/websocket.py

"""
Updated WebSocket routes for ESP32 device connections
"""
import asyncio
import logging
import base64 # Added for base64 encoding/decoding if used in this file
import time # Added for time.time() in REST endpoints

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any

from services.websocket_service import get_websocket_manager, WebSocketConnectionManager
from services.firebase_service import get_firebase_service, FirebaseService
# CORRECTED: Removed get_openai_service from import. Now import OpenAIService directly.
from services.openai_service import OpenAIService 
from utils.validators import DeviceValidator
from utils.exceptions import ValidationException, handle_validation_error
from utils.security import SecurityValidator
from utils.logger import log_security_event # Assuming log_security_event is a standalone function

router = APIRouter(tags=["WebSocket"])

# Get a logger instance for this module
logger = logging.getLogger(__name__)

# --- Dependency Providers ---
# These functions provide the singleton instances of your services.
# FastAPI's Depends will call these when a route needs them,
# ensuring they are already initialized by the application's lifespan.

def get_websocket_manager_dependency() -> WebSocketConnectionManager:
    """Dependency to get the WebSocket manager singleton."""
    return get_websocket_manager()

def get_firebase_service_dependency() -> FirebaseService:
    """Dependency to get the Firebase service singleton."""
    return get_firebase_service()

# CORRECTED: This dependency now just returns the OpenAIService instance directly.
def get_openai_service_dependency() -> OpenAIService:
    """Dependency to get the OpenAI service singleton."""
    # Since OpenAIService is a singleton, instantiating it returns the existing instance.
    return OpenAIService()

# --- WebSocket Endpoint ---

@router.websocket("/ws/{device_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    device_id: str,
    websocket_manager: WebSocketConnectionManager = Depends(get_websocket_manager_dependency)
    # The openai_service dependency is implicitly used by websocket_manager.handle_connection now
):
    """
    WebSocket endpoint for ESP32 device connections

    This endpoint handles:
    - Device authentication via device ID validation
    - Audio streaming between ESP32 and OpenAI
    - Session management and progress tracking
    - Automatic disconnection on episode completion (logic within manager/services)

    **Device ID Format**: Must be 4 uppercase letters followed by 4 digits (e.g., ABCD1234)

    **Connection Flow**:
    1. Validate device ID format
    2. Verify user registration (will be handled within websocket_manager.handle_connection or a deeper service)
    3. Get current episode system prompt (will be handled within websocket_manager.handle_connection or a deeper service)
    4. Establish OpenAI connection (handled by manager)
    5. Start audio streaming (handled by manager)
    6. Handle episode completion (logic within manager/services)
    """

    # Get client IP for logging
    client_ip = websocket.client.host if websocket.client else "unknown"

    logger.info(f"🔗 WebSocket connection attempt from {client_ip} for device {device_id}")

    # Validate device ID format
    if not DeviceValidator.validate_device_id(device_id):
        error_msg = DeviceValidator.get_device_validation_error(device_id)
        logger.warning(f"❌ Invalid device ID connection attempt: {device_id} from {client_ip}")

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

        # Close the WebSocket connection immediately for invalid device ID
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=f"Invalid device ID format: {error_msg}")
        return

    # Sanitize device ID (additional security measure)
    device_id = SecurityValidator.sanitize_input(device_id)

    # CRITICAL: Accept the WebSocket connection before any send/receive operations
    await websocket.accept()
    logger.info(f"Accepted WebSocket connection for device {device_id}")

    try:
        # Pass the accepted WebSocket and device ID to the manager's central handler.
        # The manager is now solely responsible for setting up and tearing down the
        # client and OpenAI sessions.
        await websocket_manager.handle_connection(
            websocket=websocket,
            device_id=device_id
        )

        # The manager's handle_connection method will only complete when the
        # WebSocket connection effectively closes (either gracefully or due to error).
        # Therefore, this line will only be reached after the connection lifecycle
        # managed by the manager is complete.
        logger.info(f"✅ WebSocket connection handler for {device_id} finished its lifecycle.")

    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket client disconnected: {device_id}")

    except Exception as e:
        logger.error(f"❌ WebSocket error for device {device_id}: {e}", exc_info=True)

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

        # Try to close gracefully if not already closed
        try:
            # Check client_state to avoid RuntimeError if connection is already closed/closing
            if websocket.client_state.name == 'CONNECTED':
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Internal server error")
        except Exception:
            pass  # Connection might already be closed or in closing state

    finally:
        logger.info(f"🔚 WebSocket route completed for {device_id}")

# --- REST Endpoints for WebSocket Management/Info ---

@router.get("/ws/connections",
             summary="Get active WebSocket connections",
             description="Get information about all active WebSocket connections")
async def get_active_websocket_connections(
    websocket_manager: WebSocketConnectionManager = Depends(get_websocket_manager_dependency)
):
    """
    Get information about all currently active WebSocket connections

    Returns connection details including:
    - Device IDs
    - Connection timestamps (based on last activity for now)

    Note: This endpoint would typically require admin authentication in production
    """
    try:
        # Use websocket_manager.clients to get active connections
        active_client_ids = list(websocket_manager.clients.keys())
        logger.info("Active WebSocket connections requested")
        return {
            "timestamp": time.time(), # Use current time for response
            "total_connections": len(active_client_ids),
            "connections": active_client_ids # Return just the device IDs
        }

    except Exception as e:
        logger.error(f"Failed to get active connections: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to retrieve connection information"}
        )


@router.get("/ws/connection/{device_id}",
             summary="Get specific connection info",
             description="Get information about a specific device connection")
async def get_websocket_connection_info(
    device_id: str,
    websocket_manager: WebSocketConnectionManager = Depends(get_websocket_manager_dependency)
):
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

        # Check if device is connected using websocket_manager.clients
        client_instance = websocket_manager.clients.get(device_id)
        connection_present = client_instance is not None and client_instance.connected

        connection_info = {}
        if connection_present:
            connection_info = {
                "is_connected": True,
                "connection_timestamp": websocket_manager.last_activity.get(device_id, "N/A"), # Assuming last_activity tracks start time or is updated often
                "last_activity_timestamp": websocket_manager.last_activity.get(device_id, "N/A"),
                "client_ip": client_instance.websocket.client.host if client_instance.websocket.client else "unknown",
                "openai_session_active": device_id in websocket_manager.openai_sessions,
                # Add more relevant details from ESP32Client instance if needed
            }
        else:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "device_id": device_id,
                    "is_connected": False,
                    "message": "Device not currently connected or found"
                }
            )

        logger.info(f"Connection info retrieved for device: {device_id}")
        return {
            "device_id": device_id,
            **connection_info
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Failed to get connection info for {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to retrieve connection information"}
        )


@router.post("/ws/disconnect/{device_id}",
              summary="Disconnect device",
              description="Manually disconnect a specific device")
async def disconnect_device(
    device_id: str,
    websocket_manager: WebSocketConnectionManager = Depends(get_websocket_manager_dependency)
):
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

        # Check if device is connected using websocket_manager.clients
        if device_id not in websocket_manager.clients or not websocket_manager.clients[device_id].connected:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "device_id": device_id,
                    "message": "Device not currently connected, no action needed",
                    "action": "none"
                }
            )

        # Disconnect the device using the manager's cleanup method
        # _cleanup handles closing WebSocket, OpenAI connections, and removing from tracking
        await websocket_manager._cleanup(device_id)

        logger.info(f"Device manually disconnected: {device_id}")

        return {
            "device_id": device_id,
            "message": "Device disconnected successfully",
            "action": "disconnected",
            "session_duration": 0 # Duration is not readily available here without more logic in manager
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Failed to disconnect device {device_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to disconnect device"}
        )


@router.get("/ws/stats",
             summary="Get WebSocket statistics",
             description="Get overall WebSocket connection statistics")
async def get_websocket_stats(
    websocket_manager: WebSocketConnectionManager = Depends(get_websocket_manager_dependency)
):
    """
    Get overall statistics about WebSocket connections

    Returns metrics such as:
    - Total active connections
    - Average session duration (placeholder for now)
    - Connection success rate (placeholder for now)
    - Error statistics (placeholder for now)
    """
    try:
        total_active_connections = len(websocket_manager.clients)

        # You would need to implement more sophisticated stats collection within your
        # WebSocketConnectionManager if you want average session duration, etc.
        # For now, providing basic stats based on available info.
        total_session_time = 0 # Placeholder if not tracked in manager
        avg_session_duration = 0 # Placeholder

        active_seasons = set() # Placeholders for actual learning progress tracking
        active_episodes = set() # Placeholders

        stats: Dict[str, Any] = {
            "connection_stats": {
                "total_active_connections": total_active_connections,
                "average_session_duration_seconds": round(avg_session_duration, 2),
                "total_session_time_seconds": round(total_session_time, 2)
            },
            "learning_stats": { # These would need to be populated from user/device state in Firebase
                "active_seasons": sorted(list(active_seasons)),
                "active_episodes": sorted(list(active_episodes)),
                "unique_seasons_accessed": len(active_seasons),
                "unique_episodes_accessed": len(active_episodes)
            },
            "timestamp": time.time() # Use current time for response
        }

        logger.info("WebSocket statistics requested")
        return stats

    except Exception as e:
        logger.error(f"Failed to get WebSocket stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to retrieve WebSocket statistics"}
        )


# Health check for WebSocket service
@router.get("/ws/health",
             summary="WebSocket service health check",
             description="Check the health of the WebSocket service")
async def websocket_health_check(
    websocket_manager: WebSocketConnectionManager = Depends(get_websocket_manager_dependency),
    firebase_service: FirebaseService = Depends(get_firebase_service_dependency),
    openai_service: OpenAIService = Depends(get_openai_service_dependency) # This dependency will now get the instance directly
):
    """
    Check the health of the WebSocket service and its dependencies
    """
    try:
        manager_healthy = websocket_manager is not None # True if singleton is set
        firebase_healthy = await firebase_service.health_check() # Calls Firebase health check
        
        # For OpenAI service, a simple check if the object exists.
        # If OpenAIService had a .health_check() method (e.g., pinging OpenAI API), use that.
        openai_healthy = await openai_service.health_check() # Call health_check on the instance

        overall_status = "healthy"
        if not all([manager_healthy, firebase_healthy, openai_healthy]):
            overall_status = "degraded"
            if not manager_healthy: logger.error("WebSocketManager not healthy")
            if not firebase_healthy: logger.error("FirebaseService not healthy")
            if not openai_healthy: logger.error("OpenAIService not healthy")


        health_status: Dict[str, Any] = {
            "websocket_manager": "healthy" if manager_healthy else "unhealthy",
            "firebase_connection": "healthy" if firebase_healthy else "unhealthy",
            "openai_service": "healthy" if openai_healthy else "unhealthy",
            "overall_status": overall_status,
            "timestamp": time.time() # Add timestamp
        }

        status_code = status.HTTP_200_OK if health_status["overall_status"] == "healthy" else status.HTTP_503_SERVICE_UNAVAILABLE

        return JSONResponse(
            status_code=status_code,
            content=health_status
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "websocket_manager": "error",
                "firebase_connection": "error",
                "openai_service": "error",
                "overall_status": "unhealthy",
                "error": str(e),
                "timestamp": time.time()
            }
        )