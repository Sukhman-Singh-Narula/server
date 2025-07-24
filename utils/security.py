"""
Security utilities for the ESP32 Audio Streaming Server
"""
import re
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from utils.logger import LoggerMixin


class SecurityValidator(LoggerMixin):
    """Security validation utilities"""
    
    def __init__(self):
        super().__init__()
    
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
        
        # Remove control characters except newlines and tabs
        input_data = ''.join(char for char in input_data if ord(char) >= 32 or char in '\n\t')
        
        return input_data.strip()
    
    @staticmethod
    def validate_request_size(content_length: Optional[int], max_size: int = 10 * 1024 * 1024) -> bool:
        """
        Validate request content size
        
        Args:
            content_length: Content length in bytes
            max_size: Maximum allowed size in bytes
            
        Returns:
            bool: True if within limits
        """
        if content_length is None:
            return True
        
        return content_length <= max_size
    
    @staticmethod
    def is_safe_filename(filename: str) -> bool:
        """
        Check if filename is safe (no directory traversal)
        
        Args:
            filename: Filename to check
            
        Returns:
            bool: True if safe
        """
        import os
        
        # Normalize path and check for traversal
        normalized = os.path.normpath(filename)
        return not (normalized.startswith('/') or normalized.startswith('\\') or '..' in normalized)
    
    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """
        Generate a cryptographically secure random token
        
        Args:
            length: Token length in bytes
            
        Returns:
            str: Secure token
        """
        return secrets.token_urlsafe(length)
    
    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
        """
        Hash a password with salt
        
        Args:
            password: Plain text password
            salt: Optional salt (will generate if not provided)
            
        Returns:
            tuple: (hashed_password, salt)
        """
        if salt is None:
            salt = secrets.token_hex(32)
        
        # Use PBKDF2 for password hashing
        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000  # iterations
        )
        
        return password_hash.hex(), salt
    
    @staticmethod
    def verify_password(password: str, hashed_password: str, salt: str) -> bool:
        """
        Verify a password against its hash
        
        Args:
            password: Plain text password
            hashed_password: Stored hash
            salt: Salt used for hashing
            
        Returns:
            bool: True if password matches
        """
        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        
        return password_hash.hex() == hashed_password


class RateLimiter(LoggerMixin):
    """Rate limiting utility with multiple strategies"""
    
    def __init__(self, max_requests: int = 100, time_window: int = 60):
        super().__init__()
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: Dict[str, List[float]] = {}
        self.blocked_until: Dict[str, float] = {}
    
    def is_allowed(self, identifier: str) -> bool:
        """
        Check if request is allowed for given identifier
        
        Args:
            identifier: Unique identifier (IP, user ID, etc.)
            
        Returns:
            bool: True if request is allowed
        """
        current_time = time.time()
        
        # Check if identifier is blocked
        if identifier in self.blocked_until:
            if current_time < self.blocked_until[identifier]:
                return False
            else:
                # Block expired, remove it
                del self.blocked_until[identifier]
        
        # Initialize request list if not exists
        if identifier not in self.requests:
            self.requests[identifier] = []
        
        # Clean old requests outside the window
        cutoff_time = current_time - self.time_window
        self.requests[identifier] = [
            req_time for req_time in self.requests[identifier]
            if req_time > cutoff_time
        ]
        
        # Check if limit exceeded
        if len(self.requests[identifier]) >= self.max_requests:
            # Block for additional time as penalty
            self.blocked_until[identifier] = current_time + (self.time_window * 2)
            self.log_warning(f"Rate limit exceeded for {identifier}, blocked for {self.time_window * 2}s")
            return False
        
        # Add current request
        self.requests[identifier].append(current_time)
        return True
    
    def get_remaining_requests(self, identifier: str) -> int:
        """Get remaining requests for identifier"""
        if identifier not in self.requests:
            return self.max_requests
        
        current_time = time.time()
        cutoff_time = current_time - self.time_window
        
        # Count requests in current window
        current_requests = len([
            req_time for req_time in self.requests[identifier]
            if req_time > cutoff_time
        ])
        
        return max(0, self.max_requests - current_requests)
    
    def reset_identifier(self, identifier: str):
        """Reset rate limit for specific identifier"""
        if identifier in self.requests:
            del self.requests[identifier]
        if identifier in self.blocked_until:
            del self.blocked_until[identifier]
        
        self.log_info(f"Rate limit reset for {identifier}")


class IPBlocker(LoggerMixin):
    """IP blocking utility for security violations"""
    
    def __init__(self):
        super().__init__()
        self.violations: Dict[str, List[Dict[str, Any]]] = {}
        self.blocked_ips: Dict[str, Dict[str, Any]] = {}
        
        # Violation thresholds
        self.violation_thresholds = {
            "suspicious_activity": 3,    # Block after 3 suspicious activities
            "invalid_requests": 5,       # Block after 5 invalid requests
            "rate_limit_exceeded": 3,    # Block after 3 rate limit violations
            "authentication_failed": 5   # Block after 5 auth failures
        }
        
        # Block durations (in seconds)
        self.block_durations = {
            "suspicious_activity": 1800,    # 30 minutes
            "invalid_requests": 3600,       # 1 hour
            "rate_limit_exceeded": 1800,    # 30 minutes
            "authentication_failed": 3600   # 1 hour
        }
    
    def record_violation(self, ip: str, violation_type: str, details: Dict[str, Any] = None):
        """
        Record a security violation for an IP
        
        Args:
            ip: IP address
            violation_type: Type of violation
            details: Additional details about the violation
        """
        current_time = time.time()
        
        if ip not in self.violations:
            self.violations[ip] = []
        
        violation = {
            "type": violation_type,
            "timestamp": current_time,
            "details": details or {}
        }
        
        self.violations[ip].append(violation)
        
        # Clean old violations (older than 24 hours)
        cutoff_time = current_time - 86400  # 24 hours
        self.violations[ip] = [
            v for v in self.violations[ip]
            if v["timestamp"] > cutoff_time
        ]
        
        # Check if IP should be blocked
        self._check_for_blocking(ip, violation_type)
    
    def _check_for_blocking(self, ip: str, violation_type: str):
        """Check if IP should be blocked based on violations"""
        if violation_type not in self.violation_thresholds:
            return
        
        threshold = self.violation_thresholds[violation_type]
        recent_violations = [
            v for v in self.violations[ip]
            if v["type"] == violation_type and
            v["timestamp"] > (time.time() - 3600)  # Last hour
        ]
        
        if len(recent_violations) >= threshold:
            self._block_ip(ip, violation_type)
    
    def _block_ip(self, ip: str, reason: str):
        """Block an IP address"""
        duration = self.block_durations.get(reason, 3600)  # Default 1 hour
        
        self.blocked_ips[ip] = {
            "reason": reason,
            "blocked_at": time.time(),
            "blocked_until": time.time() + duration,
            "duration": duration
        }
        
        self.log_warning(f"IP blocked: {ip} for {duration}s due to {reason}")
    
    def is_blocked(self, ip: str) -> bool:
        """Check if IP is currently blocked"""
        if ip not in self.blocked_ips:
            return False
        
        block_info = self.blocked_ips[ip]
        if time.time() > block_info["blocked_until"]:
            # Block expired
            del self.blocked_ips[ip]
            self.log_info(f"IP block expired: {ip}")
            return False
        
        return True
    
    def unblock_ip(self, ip: str):
        """Manually unblock an IP"""
        if ip in self.blocked_ips:
            del self.blocked_ips[ip]
            self.log_info(f"IP manually unblocked: {ip}")
    
    def get_block_info(self, ip: str) -> Optional[Dict[str, Any]]:
        """Get block information for an IP"""
        return self.blocked_ips.get(ip)
    
    def cleanup_expired_blocks(self):
        """Clean up expired blocks"""
        current_time = time.time()
        expired_ips = [
            ip for ip, block_info in self.blocked_ips.items()
            if current_time > block_info["blocked_until"]
        ]
        
        for ip in expired_ips:
            del self.blocked_ips[ip]
        
        if expired_ips:
            self.log_info(f"Cleaned up {len(expired_ips)} expired IP blocks")


class SecurityHeaders:
    """Security headers management"""
    
    @staticmethod
    def get_security_headers() -> Dict[str, str]:
        """Get standard security headers"""
        return {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }
    
    @staticmethod
    def get_cors_headers(allowed_origins: List[str] = None) -> Dict[str, str]:
        """Get CORS headers"""
        if allowed_origins is None:
            allowed_origins = ["*"]
        
        return {
            "Access-Control-Allow-Origin": ",".join(allowed_origins),
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            "Access-Control-Max-Age": "3600"
        }


class InputValidator:
    """Input validation utilities"""
    
    @staticmethod
    def validate_json_input(data: str, max_size: int = 1024 * 1024) -> bool:
        """Validate JSON input"""
        import json
        
        try:
            if len(data) > max_size:
                return False
            
            json.loads(data)
            return True
        except (json.JSONDecodeError, ValueError):
            return False
    
    @staticmethod
    def validate_file_upload(filename: str, content: bytes, 
                           allowed_extensions: List[str] = None,
                           max_size: int = 10 * 1024 * 1024) -> tuple[bool, str]:
        """Validate file upload"""
        if not filename:
            return False, "Filename is required"
        
        if not SecurityValidator.is_safe_filename(filename):
            return False, "Unsafe filename"
        
        if len(content) > max_size:
            return False, f"File too large (max {max_size} bytes)"
        
        if allowed_extensions:
            extension = filename.split('.')[-1].lower()
            if extension not in allowed_extensions:
                return False, f"File type not allowed. Allowed: {', '.join(allowed_extensions)}"
        
        return True, "Valid"
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format"""
        import re
        
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        
        return bool(url_pattern.match(url))


# Global security instances
_rate_limiter: Optional[RateLimiter] = None
_ip_blocker: Optional[IPBlocker] = None


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter instance"""
    global _rate_limiter
    if _rate_limiter is None:
        from config.settings import get_settings
        settings = get_settings()
        _rate_limiter = RateLimiter(
            max_requests=settings.rate_limit_requests,
            time_window=settings.rate_limit_window_seconds
        )
    return _rate_limiter


def get_ip_blocker() -> IPBlocker:
    """Get global IP blocker instance"""
    global _ip_blocker
    if _ip_blocker is None:
        _ip_blocker = IPBlocker()
    return _ip_blocker