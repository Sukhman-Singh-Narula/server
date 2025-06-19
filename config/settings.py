"""
Configuration management for ESP32 Audio Streaming Server
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
    openai_realtime_url: str = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    openai_voice_model: str = "alloy"
    
    # Audio Configuration
    audio_format: str = "pcm16"
    audio_sample_rate: int = 16000
    audio_buffer_size: int = 1024
    
    # Security Configuration
    device_id_pattern: str = r"^[A-Z]{4}\d{4}$"
    max_connections_per_device: int = 1
    session_timeout_minutes: int = 30
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    
    # Learning Configuration
    episodes_per_season: int = 7
    max_seasons: int = 10
    
    # Logging Configuration
    log_level: str = "INFO"
    log_file: str = "esp32_server.log"
    log_max_size: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 5
    
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
        errors.append("OpenAI API key is required")
    
    if not os.path.exists(settings.firebase_credentials_path):
        errors.append(f"Firebase credentials file not found: {settings.firebase_credentials_path}")
    
    if settings.episodes_per_season < 1 or settings.episodes_per_season > 10:
        errors.append("Episodes per season must be between 1 and 10")
    
    if errors:
        for error in errors:
            print(f"Configuration Error: {error}")
        return False
    
    return True