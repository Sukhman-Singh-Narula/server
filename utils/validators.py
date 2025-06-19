"""
Validation utilities for the ESP32 Audio Streaming Server
"""
import re
from typing import Optional, Tuple
from config.settings import get_settings


class DeviceValidator:
    """Device ID validation utilities"""
    
    @staticmethod
    def validate_device_id(device_id: str) -> bool:
        """
        Validate device ID format (4 uppercase letters + 4 digits)
        
        Args:
            device_id: Device ID to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        if not device_id:
            return False
        
        settings = get_settings()
        pattern = settings.device_id_pattern
        return bool(re.match(pattern, device_id))
    
    @staticmethod
    def get_device_validation_error(device_id: str) -> Optional[str]:
        """
        Get detailed validation error message for device ID
        
        Args:
            device_id: Device ID to validate
            
        Returns:
            Optional[str]: Error message if invalid, None if valid
        """
        if not device_id:
            return "Device ID cannot be empty"
        
        if len(device_id) != 8:
            return "Device ID must be exactly 8 characters long"
        
        if not device_id[:4].isupper() or not device_id[:4].isalpha():
            return "First 4 characters must be uppercase letters"
        
        if not device_id[4:].isdigit():
            return "Last 4 characters must be digits"
        
        return None


class AudioValidator:
    """Audio data validation utilities"""
    
    @staticmethod
    def validate_audio_data(audio_data: bytes) -> Tuple[bool, Optional[str]]:
        """
        Validate audio data
        
        Args:
            audio_data: Raw audio bytes
            
        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        if not audio_data:
            return False, "Audio data cannot be empty"
        
        # Check minimum size (at least 100 bytes for meaningful audio)
        if len(audio_data) < 100:
            return False, "Audio data too small (minimum 100 bytes)"
        
        # Check maximum size (10MB limit)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(audio_data) > max_size:
            return False, f"Audio data too large (maximum {max_size} bytes)"
        
        return True, None
    
    @staticmethod
    def calculate_audio_duration(audio_data: bytes, sample_rate: int = 16000, 
                               bits_per_sample: int = 16, channels: int = 1) -> float:
        """
        Calculate audio duration in seconds
        
        Args:
            audio_data: Raw audio bytes
            sample_rate: Audio sample rate (default: 16000)
            bits_per_sample: Bits per sample (default: 16)
            channels: Number of channels (default: 1)
            
        Returns:
            float: Duration in seconds
        """
        bytes_per_sample = (bits_per_sample // 8) * channels
        total_samples = len(audio_data) // bytes_per_sample
        return total_samples / sample_rate


class UserValidator:
    """User data validation utilities"""
    
    @staticmethod
    def validate_user_name(name: str) -> Tuple[bool, Optional[str]]:
        """
        Validate user name
        
        Args:
            name: User name to validate
            
        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        if not name or not name.strip():
            return False, "Name cannot be empty"
        
        name = name.strip()
        
        if len(name) < 1:
            return False, "Name must be at least 1 character long"
        
        if len(name) > 100:
            return False, "Name cannot exceed 100 characters"
        
        # Check for valid characters (letters, spaces, common punctuation)
        if not re.match(r"^[a-zA-Z\s\-'.]+$", name):
            return False, "Name contains invalid characters"
        
        return True, None
    
    @staticmethod
    def validate_user_age(age: int) -> Tuple[bool, Optional[str]]:
        """
        Validate user age
        
        Args:
            age: User age to validate
            
        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        if age < 1:
            return False, "Age must be at least 1"
        
        if age > 120:
            return False, "Age cannot exceed 120"
        
        return True, None


class PromptValidator:
    """System prompt validation utilities"""
    
    @staticmethod
    def validate_season_episode(season: int, episode: int) -> Tuple[bool, Optional[str]]:
        """
        Validate season and episode numbers
        
        Args:
            season: Season number
            episode: Episode number
            
        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        settings = get_settings()
        
        if season < 1:
            return False, "Season must be at least 1"
        
        if season > settings.max_seasons:
            return False, f"Season cannot exceed {settings.max_seasons}"
        
        if episode < 1:
            return False, "Episode must be at least 1"
        
        if episode > settings.episodes_per_season:
            return False, f"Episode cannot exceed {settings.episodes_per_season}"
        
        return True, None
    
    @staticmethod
    def validate_prompt_content(prompt: str) -> Tuple[bool, list[str]]:
        """
        Validate system prompt content and provide suggestions
        
        Args:
            prompt: System prompt content
            
        Returns:
            Tuple[bool, list[str]]: (is_valid, list of issues/suggestions)
        """
        issues = []
        
        if not prompt or not prompt.strip():
            issues.append("Prompt cannot be empty")
            return False, issues
        
        prompt = prompt.strip()
        
        if len(prompt) < 10:
            issues.append("Prompt should be at least 10 characters long")
        
        if len(prompt) > 5000:
            issues.append("Prompt should not exceed 5000 characters")
        
        # Check for common prompt best practices
        if not any(word in prompt.lower() for word in ['you are', 'your role', 'assistant']):
            issues.append("Consider starting with role definition (e.g., 'You are...')")
        
        if '{{' in prompt or '}}' in prompt:
            issues.append("Prompt contains template placeholders that should be filled")
        
        # Check for potentially problematic content
        problematic_words = ['kill', 'harm', 'illegal', 'violence']
        if any(word in prompt.lower() for word in problematic_words):
            issues.append("Prompt may contain inappropriate content")
        
        return len(issues) == 0, issues


class SecurityValidator:
    """Security validation utilities"""
    
    @staticmethod
    def validate_request_rate(identifier: str, requests: dict, 
                            max_requests: int = 100, window_seconds: int = 60) -> bool:
        """
        Validate request rate for rate limiting
        
        Args:
            identifier: Unique identifier (IP, device_id, etc.)
            requests: Dictionary tracking requests per identifier
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
            
        Returns:
            bool: True if within rate limit, False otherwise
        """
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        if identifier not in requests:
            requests[identifier] = []
        
        # Clean old requests
        cutoff_time = now - timedelta(seconds=window_seconds)
        requests[identifier] = [
            req_time for req_time in requests[identifier] 
            if req_time > cutoff_time
        ]
        
        # Check if limit exceeded
        if len(requests[identifier]) >= max_requests:
            return False
        
        # Add current request
        requests[identifier].append(now)
        return True
    
    @staticmethod
    def sanitize_input(input_data: str) -> str:
        """
        Sanitize user input to prevent XSS and injection attacks
        
        Args:
            input_data: Raw input string
            
        Returns:
            str: Sanitized input
        """
        if not input_data:
            return ""
        
        # Remove potential HTML/script tags
        input_data = re.sub(r'<[^>]*>', '', input_data)
        
        # Remove potential SQL injection patterns
        sql_patterns = [
            r';\s*drop\s+table',
            r';\s*delete\s+from',
            r';\s*insert\s+into',
            r';\s*update\s+',
            r'union\s+select',
            r'--',
            r'/\*.*\*/'
        ]
        
        for pattern in sql_patterns:
            input_data = re.sub(pattern, '', input_data, flags=re.IGNORECASE)
        
        return input_data.strip()