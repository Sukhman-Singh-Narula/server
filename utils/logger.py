"""
Logging configuration and utilities for the ESP32 Audio Streaming Server
"""
import logging
import logging.handlers
import json
import sys
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
from config.settings import get_settings


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record):
        """Format log record as JSON"""
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, 'device_id'):
            log_entry['device_id'] = record.device_id
        
        if hasattr(record, 'session_id'):
            log_entry['session_id'] = record.session_id
        
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        
        if hasattr(record, 'duration'):
            log_entry['duration'] = record.duration
        
        return json.dumps(log_entry)


class ApplicationLogger:
    """Main application logger with structured logging capabilities"""
    
    def __init__(self):
        self.settings = get_settings()
        self._setup_loggers()
    
    def _setup_loggers(self):
        """Setup all application loggers"""
        # Create logs directory
        Path("logs").mkdir(exist_ok=True)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.settings.log_level.upper()))
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            f"logs/{self.settings.log_file}",
            maxBytes=self.settings.log_max_size,
            backupCount=self.settings.log_backup_count
        )
        file_handler.setLevel(getattr(logging, self.settings.log_level.upper()))
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)
        
        # Setup specific loggers
        self._setup_audio_logger()
        self._setup_user_logger()
        self._setup_websocket_logger()
        self._setup_security_logger()
    
    def _setup_audio_logger(self):
        """Setup audio session logger"""
        audio_logger = logging.getLogger('audio')
        audio_handler = logging.handlers.RotatingFileHandler(
            "logs/audio_sessions.log",
            maxBytes=self.settings.log_max_size,
            backupCount=self.settings.log_backup_count
        )
        audio_handler.setFormatter(JSONFormatter())
        audio_logger.addHandler(audio_handler)
        audio_logger.setLevel(logging.INFO)
    
    def _setup_user_logger(self):
        """Setup user activity logger"""
        user_logger = logging.getLogger('user')
        user_handler = logging.handlers.RotatingFileHandler(
            "logs/user_activity.log",
            maxBytes=self.settings.log_max_size,
            backupCount=self.settings.log_backup_count
        )
        user_handler.setFormatter(JSONFormatter())
        user_logger.addHandler(user_handler)
        user_logger.setLevel(logging.INFO)
    
    def _setup_websocket_logger(self):
        """Setup WebSocket connection logger"""
        ws_logger = logging.getLogger('websocket')
        ws_handler = logging.handlers.RotatingFileHandler(
            "logs/websocket.log",
            maxBytes=self.settings.log_max_size,
            backupCount=self.settings.log_backup_count
        )
        ws_handler.setFormatter(JSONFormatter())
        ws_logger.addHandler(ws_handler)
        ws_logger.setLevel(logging.INFO)
    
    def _setup_security_logger(self):
        """Setup security events logger"""
        security_logger = logging.getLogger('security')
        security_handler = logging.handlers.RotatingFileHandler(
            "logs/security.log",
            maxBytes=self.settings.log_max_size,
            backupCount=self.settings.log_backup_count
        )
        security_handler.setFormatter(JSONFormatter())
        security_logger.addHandler(security_handler)
        security_logger.setLevel(logging.WARNING)


class LoggerMixin:
    """Mixin class to add logging capabilities to other classes"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def log_info(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log info message with optional extra data"""
        self.logger.info(message, extra=extra or {})
    
    def log_warning(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log warning message with optional extra data"""
        self.logger.warning(message, extra=extra or {})
    
    def log_error(self, message: str, exc_info: bool = False, 
                  extra: Optional[Dict[str, Any]] = None):
        """Log error message with optional exception info"""
        self.logger.error(message, exc_info=exc_info, extra=extra or {})


# Specific logging functions for common use cases
def log_user_registration(device_id: str, user_name: str, age: int):
    """Log user registration event"""
    logger = logging.getLogger('user')
    logger.info(
        "User registered",
        extra={
            'event': 'user_registration',
            'device_id': device_id,
            'user_name': user_name,  # Changed from 'name' to 'user_name'
            'age': age
        }
    )


def log_websocket_connection(device_id: str, remote_addr: str):
    """Log WebSocket connection event"""
    logger = logging.getLogger('websocket')
    logger.info(
        "WebSocket connection established",
        extra={
            'event': 'websocket_connect',
            'device_id': device_id,
            'remote_addr': remote_addr
        }
    )


def log_websocket_disconnection(device_id: str, duration: float, reason: str):
    """Log WebSocket disconnection event"""
    logger = logging.getLogger('websocket')
    logger.info(
        "WebSocket connection closed",
        extra={
            'event': 'websocket_disconnect',
            'device_id': device_id,
            'duration': duration,
            'reason': reason
        }
    )


def log_audio_session(device_id: str, session_data: Dict[str, Any]):
    """Log audio session statistics"""
    logger = logging.getLogger('audio')
    logger.info(
        "Audio session completed",
        extra={
            'event': 'audio_session',
            'device_id': device_id,
            **session_data
        }
    )


def log_user_progress(device_id: str, old_progress: Dict[str, Any], 
                     new_progress: Dict[str, Any]):
    """Log user progress update"""
    logger = logging.getLogger('user')
    logger.info(
        "User progress updated",
        extra={
            'event': 'progress_update',
            'device_id': device_id,
            'old_season': old_progress.get('season'),
            'new_season': new_progress.get('season'),
            'old_episode': old_progress.get('episode'),
            'new_episode': new_progress.get('episode'),
            'episodes_completed': new_progress.get('episodes_completed')
        }
    )


def log_security_event(event_type: str, device_id: str = None, 
                      details: Dict[str, Any] = None):
    """Log security event"""
    logger = logging.getLogger('security')
    logger.warning(
        f"Security event: {event_type}",
        extra={
            'event': 'security_event',
            'event_type': event_type,
            'device_id': device_id,
            **(details or {})
        }
    )


def log_openai_interaction(device_id: str, action: str, status: str, 
                          details: Dict[str, Any] = None):
    """Log OpenAI API interaction"""
    logger = logging.getLogger('openai')
    logger.info(
        f"OpenAI {action}: {status}",
        extra={
            'event': 'openai_interaction',
            'device_id': device_id,
            'action': action,
            'status': status,
            **(details or {})
        }
    )


def log_system_prompt_upload(season: int, episode: int, prompt_length: int):
    """Log system prompt upload"""
    logger = logging.getLogger('user')
    logger.info(
        "System prompt uploaded",
        extra={
            'event': 'system_prompt_upload',
            'season': season,
            'episode': episode,
            'prompt_length': prompt_length
        }
    )


# Initialize application logger
def setup_logging():
    """Initialize application logging"""
    return ApplicationLogger()