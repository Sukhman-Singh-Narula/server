"""
WebSocket service for managing ESP32 device connections
"""
import asyncio
import time
from datetime import datetime
from typing import Dict, Optional, Callable
from fastapi import WebSocket

from config.settings import get_settings
from models.websocket import ConnectionData, ConnectionStatus, SessionStats, DisconnectionReason
from models.user import User
from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from utils.exceptions import (
    WebSocketConnectionException, UserNotFoundException, 
    SystemPromptNotFoundException, SessionTimeoutException
)
from utils.logger import LoggerMixin, log_websocket_connection, log_websocket_disconnection
from utils.validators import AudioValidator


class WebSocketConnectionManager(LoggerMixin):
    """Manager for ESP32 WebSocket connections"""
    
    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.firebase_service = get_firebase_service()
        self.openai_service = get_openai_service()
        
        # Active connections: device_id -> ConnectionData
        self.connections: Dict[str, ConnectionData] = {}
        
        # Session statistics: device_id -> SessionStats
        self.session_stats: Dict[str, SessionStats] = {}
        
        # Cleanup task (will be started when event loop is available)
        self.cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_started = False
    
    async def _ensure_cleanup_task_started(self):
        """Start cleanup task if not already started"""
        if not self._cleanup_started:
            try:
                self.cleanup_task = asyncio.create_task(self._cleanup_expired_sessions())
                self._cleanup_started = True
                self.log_info("Cleanup task started")
            except Exception as e:
                self.log_error(f"Failed to start cleanup task: {e}")
    
    async def connect_device(self, websocket: WebSocket, device_id: str, 
                           remote_addr: str) -> bool:
        """
        Handle new ESP32 device connection
        
        Args:
            websocket: FastAPI WebSocket connection
            device_id: Unique device identifier
            remote_addr: Client IP address
            
        Returns:
            bool: True if connection successful
        """
        try:
            # Accept WebSocket connection
            await websocket.accept()
            
            # Ensure cleanup task is running
            await self._ensure_cleanup_task_started()
            
            # Check for existing connection
            if device_id in self.connections:
                await self._close_existing_connection(device_id, "duplicate_connection")
            
            # Get user data
            user = await self.firebase_service.get_user(device_id)
            if not user:
                await websocket.close(code=4001, reason="User not registered")
                return False
            
            # Get system prompt for current episode
            system_prompt_obj = await self.firebase_service.get_system_prompt(
                user.progress.season, user.progress.episode
            )
            if not system_prompt_obj:
                await websocket.close(code=4002, reason="System prompt not found")
                return False
            
            # Create connection data
            session_id = f"{device_id}_{int(time.time())}"
            connection_data = ConnectionData(
                device_id=device_id,
                status=ConnectionStatus.CONNECTED,
                session_id=session_id,
                user_data=self.firebase_service._user_to_dict(user),
                system_prompt=system_prompt_obj.prompt
            )
            
            # Store connection
            self.connections[device_id] = connection_data
            self.session_stats[device_id] = SessionStats()
            
            # Create OpenAI connection
            await self._create_openai_connection(device_id, system_prompt_obj.prompt)
            
            # Start handling WebSocket messages
            asyncio.create_task(self._handle_device_messages(websocket, device_id))
            
            # Log connection
            log_websocket_connection(device_id, remote_addr)
            self.log_info(f"Device connected: {device_id} - Season {user.progress.season}, Episode {user.progress.episode}")
            
            return True
            
        except UserNotFoundException:
            await websocket.close(code=4001, reason="User not registered")
            return False
        except SystemPromptNotFoundException:
            await websocket.close(code=4002, reason="System prompt not found")
            return False
        except Exception as e:
            self.log_error(f"Failed to connect device {device_id}: {e}", exc_info=True)
            await websocket.close(code=4003, reason="Connection failed")
            return False
    
    async def _create_openai_connection(self, device_id: str, system_prompt: str):
        """Create OpenAI connection for device"""
        try:
            await self.openai_service.create_connection(
                device_id=device_id,
                system_prompt=system_prompt,
                audio_callback=self._handle_openai_audio,
                completion_callback=self._handle_conversation_completion
            )
            
            # Update connection status
            if device_id in self.connections:
                self.connections[device_id].status = ConnectionStatus.CONNECTED
                
        except Exception as e:
            self.log_error(f"Failed to create OpenAI connection for {device_id}: {e}")
            # Continue without OpenAI connection
    
    async def _handle_device_messages(self, websocket: WebSocket, device_id: str):
        """Handle incoming messages from ESP32 device"""
        connection_data = self.connections.get(device_id)
        if not connection_data:
            return
        
        try:
            while True:
                # Receive audio data from ESP32
                audio_data = await websocket.receive_bytes()
                
                # Update activity and stats
                connection_data.update_activity()
                self.session_stats[device_id].add_sent_data(len(audio_data))
                
                # Validate audio data
                is_valid, error = AudioValidator.validate_audio_data(audio_data)
                if not is_valid:
                    self.log_warning(f"Invalid audio data from {device_id}: {error}")
                    continue
                
                # Forward to OpenAI
                success = await self.openai_service.send_audio(device_id, audio_data)
                if not success:
                    self.log_warning(f"Failed to send audio to OpenAI for {device_id}")
                
        except Exception as e:
            self.log_error(f"Error handling messages for {device_id}: {e}")
        finally:
            await self.disconnect_device(device_id, DisconnectionReason.CLIENT_DISCONNECT)
    
    async def _handle_openai_audio(self, device_id: str, audio_data: bytes):
        """Handle audio response from OpenAI"""
        connection_data = self.connections.get(device_id)
        if not connection_data:
            return
        
        try:
            # Update stats
            self.session_stats[device_id].add_received_data(len(audio_data))
            
            # Send audio to ESP32 device
            # Note: This would need to be implemented based on your WebSocket setup
            # For now, we'll log that audio was received
            self.log_info(f"Received {len(audio_data)} bytes of audio for {device_id}")
            
        except Exception as e:
            self.log_error(f"Error handling OpenAI audio for {device_id}: {e}")
    
    async def _handle_conversation_completion(self, device_id: str):
        """Handle conversation completion from OpenAI"""
        connection_data = self.connections.get(device_id)
        if not connection_data:
            return
        
        try:
            # Get current user data
            user = await self.firebase_service.get_user(device_id)
            
            # Advance episode
            old_progress = user.progress.dict()
            advanced_to_new_season = user.progress.advance_episode(
                self.settings.episodes_per_season
            )
            
            # Update user progress in Firebase
            await self.firebase_service.update_user_progress(device_id, user.progress)
            
            # Log progress update
            from utils.logger import log_user_progress
            log_user_progress(device_id, old_progress, user.progress.dict())
            
            # Close OpenAI connection
            await self.openai_service.close_connection(device_id)
            
            self.log_info(f"Episode completed for {device_id} - Advanced to Season {user.progress.season}, Episode {user.progress.episode}")
            
            # Disconnect device to end session
            await self.disconnect_device(device_id, DisconnectionReason.SESSION_COMPLETE)
            
        except Exception as e:
            self.log_error(f"Error handling conversation completion for {device_id}: {e}")
    
    async def disconnect_device(self, device_id: str, reason: DisconnectionReason):
        """
        Disconnect device and cleanup resources
        
        Args:
            device_id: Unique device identifier
            reason: Reason for disconnection
        """
        if device_id not in self.connections:
            return
        
        connection_data = self.connections[device_id]
        session_duration = connection_data.connection_duration
        
        try:
            # Update session time in Firebase
            await self.firebase_service.increment_user_time(device_id, session_duration)
            
            # Close OpenAI connection
            await self.openai_service.close_connection(device_id)
            
            # Clean up connections
            del self.connections[device_id]
            
            # Get final stats
            final_stats = self.session_stats.pop(device_id, SessionStats())
            
            # Log disconnection
            log_websocket_disconnection(device_id, session_duration, reason.value)
            self.log_info(f"Device disconnected: {device_id} - Duration: {session_duration:.2f}s, Reason: {reason.value}")
            
        except Exception as e:
            self.log_error(f"Error during disconnect for {device_id}: {e}")
    
    async def _close_existing_connection(self, device_id: str, reason: str):
        """Close existing connection for device"""
        if device_id in self.connections:
            self.log_info(f"Closing existing connection for {device_id}: {reason}")
            await self.disconnect_device(device_id, DisconnectionReason.CLIENT_DISCONNECT)
    
    async def _cleanup_expired_sessions(self):
        """Periodically cleanup expired sessions"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                current_time = time.time()
                timeout_seconds = self.settings.session_timeout_minutes * 60
                
                expired_devices = []
                for device_id, connection_data in self.connections.items():
                    if (current_time - connection_data.last_activity.timestamp()) > timeout_seconds:
                        expired_devices.append(device_id)
                
                for device_id in expired_devices:
                    self.log_info(f"Session timeout for device {device_id}")
                    await self.disconnect_device(device_id, DisconnectionReason.TIMEOUT)
                    
            except Exception as e:
                self.log_error(f"Error in cleanup task: {e}")
    
    def get_session_duration(self, device_id: str) -> float:
        """Get current session duration for device"""
        if device_id in self.connections:
            return self.connections[device_id].connection_duration
        return 0.0
    
    def get_connection_info(self, device_id: str) -> Optional[Dict]:
        """Get connection information for device"""
        if device_id not in self.connections:
            return None
        
        connection_data = self.connections[device_id]
        stats = self.session_stats.get(device_id, SessionStats())
        
        return {
            "device_id": device_id,
            "status": connection_data.status.value,
            "session_id": connection_data.session_id,
            "connected_at": connection_data.connected_at.isoformat(),
            "last_activity": connection_data.last_activity.isoformat(),
            "session_duration": connection_data.connection_duration,
            "current_season": connection_data.user_data.get("progress", {}).get("season"),
            "current_episode": connection_data.user_data.get("progress", {}).get("episode"),
            "bytes_sent": stats.bytes_sent,
            "bytes_received": stats.bytes_received,
            "messages_sent": stats.messages_sent,
            "messages_received": stats.messages_received
        }
    
    def get_all_connections(self) -> Dict[str, Dict]:
        """Get information for all active connections"""
        return {
            device_id: self.get_connection_info(device_id)
            for device_id in self.connections.keys()
        }
    
    async def shutdown(self):
        """Shutdown connection manager and cleanup resources"""
        self.log_info("Shutting down WebSocket connection manager")
        
        # Cancel cleanup task
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect all devices
        for device_id in list(self.connections.keys()):
            await self.disconnect_device(device_id, DisconnectionReason.SERVER_SHUTDOWN)
        
        # Close all OpenAI connections
        await self.openai_service.close_all_connections()


# Global WebSocket manager instance
_websocket_manager: Optional[WebSocketConnectionManager] = None


def get_websocket_manager() -> WebSocketConnectionManager:
    """Get WebSocket manager singleton"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketConnectionManager()
    return _websocket_manager