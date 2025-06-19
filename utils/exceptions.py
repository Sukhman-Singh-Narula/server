"""
Custom exceptions for the ESP32 Audio Streaming Server
"""
from typing import Optional, Dict, Any


class ESP32ServerException(Exception):
    """Base exception for ESP32 server errors"""
    
    def __init__(self, message: str, error_code: str = None, details: Dict[str, Any] = None):
        self.message = message
        self.error_code = error_code or "GENERAL_ERROR"
        self.details = details or {}
        super().__init__(self.message)


class ValidationException(ESP32ServerException):
    """Exception raised for validation errors"""
    
    def __init__(self, message: str, field: str = None, value: Any = None):
        super().__init__(message, "VALIDATION_ERROR", {"field": field, "value": value})
        self.field = field
        self.value = value


class DeviceIDException(ValidationException):
    """Exception raised for invalid device IDs"""
    
    def __init__(self, device_id: str, reason: str = None):
        message = f"Invalid device ID: {device_id}"
        if reason:
            message += f" - {reason}"
        super().__init__(message, "device_id", device_id)
        self.device_id = device_id


class UserNotFoundException(ESP32ServerException):
    """Exception raised when user is not found"""
    
    def __init__(self, device_id: str):
        super().__init__(
            f"User not found for device ID: {device_id}",
            "USER_NOT_FOUND",
            {"device_id": device_id}
        )
        self.device_id = device_id


class UserAlreadyExistsException(ESP32ServerException):
    """Exception raised when trying to register an existing user"""
    
    def __init__(self, device_id: str):
        super().__init__(
            f"User already exists for device ID: {device_id}",
            "USER_ALREADY_EXISTS",
            {"device_id": device_id}
        )
        self.device_id = device_id


class SystemPromptNotFoundException(ESP32ServerException):
    """Exception raised when system prompt is not found"""
    
    def __init__(self, season: int, episode: int):
        super().__init__(
            f"System prompt not found for Season {season}, Episode {episode}",
            "SYSTEM_PROMPT_NOT_FOUND",
            {"season": season, "episode": episode}
        )
        self.season = season
        self.episode = episode


class WebSocketConnectionException(ESP32ServerException):
    """Exception raised for WebSocket connection errors"""
    
    def __init__(self, device_id: str, reason: str):
        super().__init__(
            f"WebSocket connection error for {device_id}: {reason}",
            "WEBSOCKET_CONNECTION_ERROR",
            {"device_id": device_id, "reason": reason}
        )
        self.device_id = device_id
        self.reason = reason


class OpenAIConnectionException(ESP32ServerException):
    """Exception raised for OpenAI API connection errors"""
    
    def __init__(self, device_id: str, reason: str, openai_error: str = None):
        message = f"OpenAI connection error for {device_id}: {reason}"
        details = {"device_id": device_id, "reason": reason}
        if openai_error:
            details["openai_error"] = openai_error
        
        super().__init__(message, "OPENAI_CONNECTION_ERROR", details)
        self.device_id = device_id
        self.reason = reason
        self.openai_error = openai_error


class AudioProcessingException(ESP32ServerException):
    """Exception raised for audio processing errors"""
    
    def __init__(self, device_id: str, reason: str, audio_size: int = None):
        details = {"device_id": device_id, "reason": reason}
        if audio_size is not None:
            details["audio_size"] = audio_size
        
        super().__init__(
            f"Audio processing error for {device_id}: {reason}",
            "AUDIO_PROCESSING_ERROR",
            details
        )
        self.device_id = device_id
        self.reason = reason


class RateLimitException(ESP32ServerException):
    """Exception raised when rate limit is exceeded"""
    
    def __init__(self, identifier: str, limit: int, window: int):
        super().__init__(
            f"Rate limit exceeded for {identifier}: {limit} requests per {window} seconds",
            "RATE_LIMIT_EXCEEDED",
            {"identifier": identifier, "limit": limit, "window": window}
        )
        self.identifier = identifier
        self.limit = limit
        self.window = window


class SessionTimeoutException(ESP32ServerException):
    """Exception raised when session times out"""
    
    def __init__(self, device_id: str, duration: float, timeout: float):
        super().__init__(
            f"Session timeout for {device_id}: {duration}s (limit: {timeout}s)",
            "SESSION_TIMEOUT",
            {"device_id": device_id, "duration": duration, "timeout": timeout}
        )
        self.device_id = device_id
        self.duration = duration
        self.timeout = timeout


class FirebaseException(ESP32ServerException):
    """Exception raised for Firebase-related errors"""
    
    def __init__(self, operation: str, reason: str, collection: str = None, 
                 document_id: str = None):
        details = {"operation": operation, "reason": reason}
        if collection:
            details["collection"] = collection
        if document_id:
            details["document_id"] = document_id
        
        super().__init__(
            f"Firebase {operation} error: {reason}",
            "FIREBASE_ERROR",
            details
        )
        self.operation = operation
        self.reason = reason


class ConfigurationException(ESP32ServerException):
    """Exception raised for configuration errors"""
    
    def __init__(self, setting: str, value: Any = None, reason: str = None):
        message = f"Configuration error for setting '{setting}'"
        if reason:
            message += f": {reason}"
        
        super().__init__(
            message,
            "CONFIGURATION_ERROR",
            {"setting": setting, "value": value, "reason": reason}
        )
        self.setting = setting
        self.value = value


class SecurityException(ESP32ServerException):
    """Exception raised for security violations"""
    
    def __init__(self, violation_type: str, identifier: str = None, 
                 details: Dict[str, Any] = None):
        message = f"Security violation: {violation_type}"
        if identifier:
            message += f" (identifier: {identifier})"
        
        security_details = {"violation_type": violation_type}
        if identifier:
            security_details["identifier"] = identifier
        if details:
            security_details.update(details)
        
        super().__init__(message, "SECURITY_VIOLATION", security_details)
        self.violation_type = violation_type
        self.identifier = identifier


# Exception handling utilities
def handle_validation_error(error: ValidationException) -> Dict[str, Any]:
    """Convert validation exception to API response format"""
    return {
        "error": "Validation Error",
        "message": error.message,
        "field": error.field,
        "value": str(error.value) if error.value is not None else None,
        "code": error.error_code
    }


def handle_user_error(error: ESP32ServerException) -> Dict[str, Any]:
    """Convert user-related exception to API response format"""
    return {
        "error": "User Error",
        "message": error.message,
        "code": error.error_code,
        "details": error.details
    }


def handle_websocket_error(error: WebSocketConnectionException) -> Dict[str, Any]:
    """Convert WebSocket exception to response format"""
    return {
        "error": "WebSocket Error",
        "message": error.message,
        "device_id": error.device_id,
        "reason": error.reason,
        "code": error.error_code
    }


def handle_generic_error(error: Exception) -> Dict[str, Any]:
    """Convert generic exception to API response format"""
    if isinstance(error, ESP32ServerException):
        return {
            "error": "Server Error",
            "message": error.message,
            "code": error.error_code,
            "details": error.details
        }
    else:
        return {
            "error": "Internal Server Error",
            "message": str(error),
            "code": "INTERNAL_ERROR"
        }


# Context managers for exception handling
class ExceptionContext:
    """Context manager for handling specific exceptions"""
    
    def __init__(self, operation: str, device_id: str = None):
        self.operation = operation
        self.device_id = device_id
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            # Log the exception with context
            from utils.logger import log_security_event
            
            if isinstance(exc_val, SecurityException):
                log_security_event(
                    exc_val.violation_type,
                    self.device_id,
                    {
                        "operation": self.operation,
                        "error": str(exc_val)
                    }
                )
            elif isinstance(exc_val, ESP32ServerException):
                # Log other server exceptions
                import logging
                logger = logging.getLogger(__name__)
                logger.error(
                    f"Exception in {self.operation}: {exc_val.message}",
                    extra={
                        "device_id": self.device_id,
                        "error_code": exc_val.error_code,
                        "details": exc_val.details
                    }
                )
        
        return False  # Don't suppress exceptions