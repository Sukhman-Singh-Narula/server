"""
Updated configuration management for ESP32 Audio Streaming Server
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # Server Configuration
    app_name: str = "ESP32 Audio Streaming Server"
    app_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    
    # Firebase Configuration
    firebase_credentials_path: str = "serviceAccountKey.json"
    firebase_project_id: Optional[str] = None
    
    # OpenAI Configuration
    openai_api_key: str = ""
    openai_realtime_url: str = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"
    openai_voice_model: str = "alloy"  # Options: alloy, ash, ballad, coral, echo, sage, shimmer, verse
    
    # Audio Configuration
    audio_format: str = "pcm16"
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_bits_per_sample: int = 16
    audio_buffer_size: int = 1024
    audio_chunk_duration_ms: int = 100  # 100ms chunks
    
    # Voice Activity Detection
    vad_enabled: bool = True
    vad_threshold: float = 0.5
    vad_prefix_padding_ms: int = 300
    vad_silence_duration_ms: int = 200
    
    # Security Configuration
    device_id_pattern: str = r"^[A-Z]{4}\d{4}$"
    max_connections_per_device: int = 1
    session_timeout_minutes: int = 30
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    
    # Learning Configuration
    episodes_per_season: int = 7
    max_seasons: int = 10
    
    # WebSocket Configuration
    websocket_ping_interval: int = 30
    websocket_ping_timeout: int = 10
    websocket_close_timeout: int = 10
    websocket_max_message_size: int = 10 * 1024 * 1024  # 10MB
    
    # OpenAI Realtime API Configuration
    openai_temperature: float = 0.8
    openai_max_tokens: int = 4096
    openai_model: str = "gpt-4o-realtime-preview-2024-12-17"
    
    # Logging Configuration
    log_level: str = "INFO"
    log_file: str = "esp32_server.log"
    log_max_size: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 5
    log_json_format: bool = True
    
    # Performance Configuration
    max_concurrent_connections: int = 100
    connection_pool_size: int = 10
    request_timeout_seconds: int = 30
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings"""
    return settings


def validate_settings() -> bool:
    """Validate critical settings"""
    errors = []
    
    if not settings.openai_api_key:
        errors.append("OpenAI API key is required (OPENAI_API_KEY)")
    
    if not os.path.exists(settings.firebase_credentials_path):
        errors.append(f"Firebase credentials file not found: {settings.firebase_credentials_path}")
    
    if settings.episodes_per_season < 1 or settings.episodes_per_season > 10:
        errors.append("Episodes per season must be between 1 and 10")
    
    if settings.audio_sample_rate not in [8000, 16000, 24000, 44100, 48000]:
        errors.append("Audio sample rate must be one of: 8000, 16000, 24000, 44100, 48000")
    
    if settings.audio_bits_per_sample not in [8, 16, 24, 32]:
        errors.append("Audio bits per sample must be one of: 8, 16, 24, 32")
    
    if settings.vad_threshold < 0.0 or settings.vad_threshold > 1.0:
        errors.append("VAD threshold must be between 0.0 and 1.0")
    
    # Validate OpenAI voice model
    valid_voices = ["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]
    if settings.openai_voice_model not in valid_voices:
        errors.append(f"OpenAI voice model must be one of: {', '.join(valid_voices)}")
    
    if errors:
        for error in errors:
            print(f"Configuration Error: {error}")
        return False
    
    return True


def get_audio_config():
    """Get audio configuration for processing"""
    return {
        "sample_rate": settings.audio_sample_rate,
        "channels": settings.audio_channels,
        "bits_per_sample": settings.audio_bits_per_sample,
        "format": settings.audio_format,
        "chunk_duration_ms": settings.audio_chunk_duration_ms,
        "buffer_size": settings.audio_buffer_size
    }


def get_openai_config():
    """Get OpenAI Realtime API configuration"""
    return {
        "model": settings.openai_model,
        "voice": settings.openai_voice_model,
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "temperature": settings.openai_temperature,
        "max_response_output_tokens": settings.openai_max_tokens,
        "modalities": ["text", "audio"],
        "turn_detection": {
            "type": "server_vad" if settings.vad_enabled else None,
            "threshold": settings.vad_threshold,
            "prefix_padding_ms": settings.vad_prefix_padding_ms,
            "silence_duration_ms": settings.vad_silence_duration_ms
        } if settings.vad_enabled else None
    }


def get_websocket_config():
    """Get WebSocket configuration"""
    return {
        "ping_interval": settings.websocket_ping_interval,
        "ping_timeout": settings.websocket_ping_timeout,
        "close_timeout": settings.websocket_close_timeout,
        "max_size": settings.websocket_max_message_size
    }