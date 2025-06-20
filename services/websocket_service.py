"""
Streamlined WebSocket service for ESP32 connections
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect

from services.firebase_service import get_firebase_service
from services.openai_service import get_openai_service
from utils.logger import LoggerMixin


class WebSocketConnectionManager(LoggerMixin):
    """Simplified WebSocket connection manager"""
    
    def __init__(self):
        super().__init__()
        self.firebase_service = get_firebase_service()
        self.openai_service = get_openai_service()
        
        # Active connections: device_id -> WebSocket
        self.connections: Dict[str, WebSocket] = {}
        self.connection_times: Dict[str, float] = {}
        
        # Audio buffering for minimum chunk size
        self.audio_buffers: Dict[str, bytearray] = {}
        self.buffer_timers: Dict[str, asyncio.Task] = {}
    
    async def connect_device(self, websocket: WebSocket, device_id: str, remote_addr: str):
        """Handle ESP32 device connection"""
        try:
            # Accept WebSocket connection
            await websocket.accept()
            self.log_info(f"WebSocket accepted for {device_id}")
            
            # Get user and system prompt
            user = await self.firebase_service.get_user(device_id)
            system_prompt_obj = await self.firebase_service.get_system_prompt(
                user.progress.season, user.progress.episode
            )
            
            # Store connection
            self.connections[device_id] = websocket
            self.connection_times[device_id] = time.time()
            self.audio_buffers[device_id] = bytearray()
            
            # Create OpenAI connection
            await self.openai_service.create_connection(
                device_id=device_id,
                system_prompt=system_prompt_obj.prompt,
                audio_callback=self._send_audio_to_esp32
            )
            
            # Send ready message
            await websocket.send_text(json.dumps({
                "type": "ready",
                "device_id": device_id,
                "season": user.progress.season,
                "episode": user.progress.episode
            }))
            
            self.log_info(f"Device ready: {device_id}")
            
            # Handle messages
            await self._handle_messages(websocket, device_id)
            
        except Exception as e:
            self.log_error(f"Connection error for {device_id}: {e}")
        finally:
            await self._cleanup_device(device_id)
    
    async def _handle_messages(self, websocket: WebSocket, device_id: str):
        """Handle incoming messages from ESP32"""
        try:
            while True:
                message = await websocket.receive()
                self.log_info(f"📥 Raw message from {device_id}: type={message.get('type')}")
                
                if message["type"] == "websocket.receive":
                    if "bytes" in message:
                        # Handle audio data
                        audio_data = message["bytes"]
                        self.log_info(f"🎵 Received binary audio from {device_id}: {len(audio_data)} bytes")
                        await self._handle_audio_data(device_id, audio_data)
                    
                    elif "text" in message:
                        # Handle text messages
                        text_content = message["text"]
                        self.log_info(f"💬 Received text from {device_id}: {text_content[:100]}...")
                        try:
                            text_data = json.loads(text_content)
                            await self._handle_text_message(device_id, text_data)
                        except json.JSONDecodeError:
                            # Simple text command
                            await self._handle_simple_command(device_id, text_content)
                
                elif message["type"] == "websocket.disconnect":
                    self.log_info(f"🔌 Disconnect message received for {device_id}")
                    break
                    
        except WebSocketDisconnect:
            self.log_info(f"🔌 Client disconnected: {device_id}")
        except Exception as e:
            self.log_error(f"❌ Message handling error for {device_id}: {e}", exc_info=True)
    
    async def _handle_audio_data(self, device_id: str, audio_data: bytes):
        """Handle audio data with buffering for minimum chunk size"""
        self.log_info(f"📤 Received audio chunk from ESP32 {device_id}: {len(audio_data)} bytes")
        
        # Add to buffer
        self.audio_buffers[device_id].extend(audio_data)
        buffer_size = len(self.audio_buffers[device_id])
        
        self.log_info(f"📊 Buffer size for {device_id}: {buffer_size} bytes")
        
        # Cancel existing timer if any
        if device_id in self.buffer_timers:
            self.buffer_timers[device_id].cancel()
        
        # Send if buffer is large enough (at least 1600 bytes for 100ms at 16kHz PCM16)
        if buffer_size >= 3200:  # 200ms of audio
            self.log_info(f"🚀 Buffer full, sending audio for {device_id}")
            await self._send_buffered_audio(device_id)
        else:
            # Set timer to send after 100ms if no more audio comes
            self.log_info(f"⏰ Setting timer for {device_id} (buffer: {buffer_size} bytes)")
            self.buffer_timers[device_id] = asyncio.create_task(
                self._send_audio_after_delay(device_id, 0.1)
            )
    
    async def _send_audio_after_delay(self, device_id: str, delay: float):
        """Send buffered audio after delay"""
        self.log_info(f"⏰ Timer triggered for {device_id} after {delay}s delay")
        await asyncio.sleep(delay)
        if device_id in self.audio_buffers and len(self.audio_buffers[device_id]) > 0:
            self.log_info(f"🚀 Timer sending buffered audio for {device_id}")
            await self._send_buffered_audio(device_id)
        else:
            self.log_info(f"🤷 Timer triggered but no audio to send for {device_id}")
    
    async def _send_buffered_audio(self, device_id: str):
        """Send buffered audio to OpenAI"""
        if device_id not in self.audio_buffers:
            self.log_warning(f"❌ No audio buffer found for {device_id}")
            return
        
        buffer = self.audio_buffers[device_id]
        if len(buffer) == 0:
            self.log_warning(f"❌ Empty audio buffer for {device_id}")
            return
        
        self.log_info(f"🎵 Sending {len(buffer)} bytes to OpenAI for {device_id}")
        
        # Send to OpenAI
        success = await self.openai_service.send_audio(device_id, bytes(buffer))
        
        if success:
            self.log_info(f"✅ Successfully sent {len(buffer)} bytes to OpenAI for {device_id}")
            # Clear buffer
            self.audio_buffers[device_id].clear()
            self.log_info(f"🧹 Cleared audio buffer for {device_id}")
        else:
            self.log_error(f"❌ Failed to send audio to OpenAI for {device_id}")
            # Don't clear buffer on failure - maybe retry logic could be added
    
    async def _handle_text_message(self, device_id: str, data: dict):
        """Handle JSON text messages"""
        msg_type = data.get("type")
        self.log_info(f"📝 Text message from {device_id}: {msg_type}")
        
        if msg_type == "ping":
            # Respond with pong
            if device_id in self.connections:
                pong_response = {"type": "pong", "timestamp": time.time()}
                await self.connections[device_id].send_text(json.dumps(pong_response))
                self.log_info(f"🏓 Sent pong to {device_id}")
        
        elif msg_type == "start_recording":
            self.log_info(f"🎤 Recording started for {device_id}")
            
        elif msg_type == "stop_recording":
            # Send any remaining buffered audio
            self.log_info(f"🛑 Recording stopped for {device_id}, flushing buffer")
            await self._send_buffered_audio(device_id)
        
        else:
            self.log_info(f"🤔 Unknown text message type from {device_id}: {msg_type}")
    
    async def _handle_simple_command(self, device_id: str, command: str):
        """Handle simple text commands"""
        command = command.strip().lower()
        self.log_info(f"📢 Simple command from {device_id}: '{command}'")
        
        if command in ["ping", "heartbeat"]:
            if device_id in self.connections:
                pong_response = {"type": "pong", "timestamp": time.time()}
                await self.connections[device_id].send_text(json.dumps(pong_response))
                self.log_info(f"🏓 Sent pong to {device_id}")
        else:
            self.log_info(f"🤷 Unknown simple command from {device_id}: '{command}'")
    
    async def _send_audio_to_esp32(self, device_id: str, audio_data: bytes):
        """Send audio response from OpenAI to ESP32"""
        if device_id in self.connections:
            try:
                self.log_info(f"🔊 Forwarding {len(audio_data)} bytes of audio to ESP32 {device_id}")
                await self.connections[device_id].send_bytes(audio_data)
                self.log_info(f"✅ Successfully sent {len(audio_data)} bytes to ESP32 {device_id}")
            except Exception as e:
                self.log_error(f"❌ Failed to send audio to ESP32 {device_id}: {e}")
        else:
            self.log_warning(f"⚠️ No WebSocket connection found for device {device_id}")
    
    async def _cleanup_device(self, device_id: str):
        """Clean up device connection"""
        # Cancel timer
        if device_id in self.buffer_timers:
            self.buffer_timers[device_id].cancel()
            del self.buffer_timers[device_id]
        
        # Close OpenAI connection
        await self.openai_service.close_connection(device_id)
        
        # Update session time if user exists
        if device_id in self.connection_times:
            session_duration = time.time() - self.connection_times[device_id]
            try:
                await self.firebase_service.increment_user_time(device_id, session_duration)
            except:
                pass  # Don't fail cleanup on Firebase error
            del self.connection_times[device_id]
        
        # Clean up connection data
        if device_id in self.connections:
            del self.connections[device_id]
        if device_id in self.audio_buffers:
            del self.audio_buffers[device_id]
        
        self.log_info(f"Cleaned up connection for {device_id}")
    
    def get_active_connections(self) -> Dict[str, dict]:
        """Get active connection info"""
        return {
            device_id: {
                "device_id": device_id,
                "connected_at": self.connection_times.get(device_id, 0),
                "duration": time.time() - self.connection_times.get(device_id, time.time())
            }
            for device_id in self.connections.keys()
        }
    
    async def disconnect_device(self, device_id: str):
        """Manually disconnect a device"""
        if device_id in self.connections:
            try:
                await self.connections[device_id].close()
            except:
                pass
            await self._cleanup_device(device_id)
    
    async def shutdown(self):
        """Shutdown manager"""
        for device_id in list(self.connections.keys()):
            await self.disconnect_device(device_id)


# Global instance
_websocket_manager: Optional[WebSocketConnectionManager] = None

def get_websocket_manager() -> WebSocketConnectionManager:
    """Get WebSocket manager singleton"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketConnectionManager()
    return _websocket_manager