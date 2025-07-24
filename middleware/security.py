"""
Security middleware for the ESP32 Audio Streaming Server
"""
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import get_settings
from utils.logger import LoggerMixin, log_security_event
from utils.exceptions import RateLimitException, SecurityException


class SecurityMiddleware(BaseHTTPMiddleware, LoggerMixin):
    """Security middleware for rate limiting and basic security checks"""
    
    def __init__(self, app):
        super().__init__(app)
        LoggerMixin.__init__(self)
        self.settings = get_settings()
        
        # Rate limiting storage: IP -> list of request timestamps
        self.rate_limit_storage: Dict[str, list] = {}
        
        # Failed authentication attempts: IP -> count
        self.failed_attempts: Dict[str, int] = {}
        
        # Blocked IPs: IP -> blocked_until timestamp
        self.blocked_ips: Dict[str, datetime] = {}
        
        # Last cleanup time
        self.last_cleanup = datetime.now()
    
    async def dispatch(self, request: Request, call_next):
        """Process request through security checks"""
        
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Cleanup expired data periodically
        await self._cleanup_expired_data()
        
        try:
            # Check if IP is blocked
            if self._is_ip_blocked(client_ip):
                log_security_event("blocked_ip_access", details={
                    "client_ip": client_ip,
                    "path": str(request.url.path),
                    "method": request.method
                })
                
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": "Access Denied",
                        "message": "IP temporarily blocked due to security violations",
                        "code": "IP_BLOCKED"
                    }
                )
            
            # Rate limiting check
            if not self._check_rate_limit(client_ip, request):
                log_security_event("rate_limit_exceeded", details={
                    "client_ip": client_ip,
                    "path": str(request.url.path),
                    "method": request.method,
                    "rate_limit": self.settings.rate_limit_requests,
                    "time_window": self.settings.rate_limit_window_seconds
                })
                
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": "Rate Limit Exceeded",
                        "message": f"Too many requests. Limit: {self.settings.rate_limit_requests} per {self.settings.rate_limit_window_seconds} seconds",
                        "code": "RATE_LIMIT_EXCEEDED",
                        "retry_after": self.settings.rate_limit_window_seconds
                    }
                )
            
            # Security headers check
            security_violation = self._check_security_headers(request)
            if security_violation:
                log_security_event("security_header_violation", details={
                    "client_ip": client_ip,
                    "violation": security_violation,
                    "user_agent": request.headers.get("user-agent", "unknown")
                })
                
                # Don't block for header violations, just log
                self.log_warning(f"Security header violation from {client_ip}: {security_violation}")
            
            # Suspicious path check
            if self._is_suspicious_path(request.url.path):
                log_security_event("suspicious_path_access", details={
                    "client_ip": client_ip,
                    "path": str(request.url.path),
                    "user_agent": request.headers.get("user-agent", "unknown")
                })
                
                # Increase failed attempts for suspicious behavior
                self._record_failed_attempt(client_ip)
                
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={
                        "error": "Not Found",
                        "message": "The requested resource was not found",
                        "code": "NOT_FOUND"
                    }
                )
            
            # Process request
            start_time = time.time()
            response = await call_next(request)
            process_time = time.time() - start_time
            
            # Add security headers to response
            response = self._add_security_headers(response)
            
            # Add processing time header
            response.headers["X-Process-Time"] = str(process_time)
            
            # Log successful request
            self.log_info(f"Request processed: {request.method} {request.url.path} - {response.status_code} ({process_time:.3f}s)")
            
            return response
            
        except Exception as e:
            self.log_error(f"Security middleware error: {e}", exc_info=True)
            
            log_security_event("middleware_error", details={
                "client_ip": client_ip,
                "error": str(e),
                "path": str(request.url.path)
            })
            
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                    "code": "INTERNAL_ERROR"
                }
            )
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request"""
        # Check for forwarded headers (proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fallback to direct connection IP
        if request.client:
            return request.client.host
        
        return "unknown"
    
    def _check_rate_limit(self, client_ip: str, request: Request) -> bool:
        """Check if request is within rate limits"""
        now = datetime.now()
        
        if client_ip not in self.rate_limit_storage:
            self.rate_limit_storage[client_ip] = []
        
        # Clean old requests outside the window
        window_start = now - timedelta(seconds=self.settings.rate_limit_window_seconds)
        self.rate_limit_storage[client_ip] = [
            req_time for req_time in self.rate_limit_storage[client_ip]
            if req_time > window_start
        ]
        
        # Check if limit exceeded
        if len(self.rate_limit_storage[client_ip]) >= self.settings.rate_limit_requests:
            self._record_failed_attempt(client_ip)
            return False
        
        # Add current request
        self.rate_limit_storage[client_ip].append(now)
        return True
    
    def _is_ip_blocked(self, client_ip: str) -> bool:
        """Check if IP is currently blocked"""
        if client_ip not in self.blocked_ips:
            return False
        
        blocked_until = self.blocked_ips[client_ip]
        if datetime.now() > blocked_until:
            # Block expired, remove it
            del self.blocked_ips[client_ip]
            if client_ip in self.failed_attempts:
                del self.failed_attempts[client_ip]
            return False
        
        return True
    
    def _record_failed_attempt(self, client_ip: str):
        """Record a failed/suspicious attempt from IP"""
        if client_ip not in self.failed_attempts:
            self.failed_attempts[client_ip] = 0
        
        self.failed_attempts[client_ip] += 1
        
        # Block IP if too many failed attempts
        if self.failed_attempts[client_ip] >= 5:  # Block after 5 violations
            block_duration = timedelta(minutes=30)  # Block for 30 minutes
            self.blocked_ips[client_ip] = datetime.now() + block_duration
            
            log_security_event("ip_blocked", details={
                "client_ip": client_ip,
                "failed_attempts": self.failed_attempts[client_ip],
                "block_duration_minutes": 30
            })
            
            self.log_warning(f"IP blocked for 30 minutes: {client_ip} (failed attempts: {self.failed_attempts[client_ip]})")
    
    def _check_security_headers(self, request: Request) -> Optional[str]:
        """Check for suspicious security headers"""
        user_agent = request.headers.get("user-agent", "").lower()
        
        # Check for common attack tools
        suspicious_agents = [
            "sqlmap", "nikto", "nmap", "masscan", "zap", "burp",
            "w3af", "skipfish", "grabber", "whatweb"
        ]
        
        for agent in suspicious_agents:
            if agent in user_agent:
                return f"Suspicious user agent: {agent}"
        
        # Check for missing user agent (common in automated attacks)
        if not user_agent or user_agent == "unknown":
            return "Missing or invalid user agent"
        
        # Check for suspicious headers
        if request.headers.get("X-Forwarded-For") and "script" in request.headers.get("X-Forwarded-For", "").lower():
            return "Suspicious X-Forwarded-For header"
        
        return None
    
    def _is_suspicious_path(self, path: str) -> bool:
        """Check for suspicious URL paths"""
        path_lower = path.lower()
        
        # Common attack paths
        suspicious_paths = [
            "/admin", "/wp-admin", "/wp-login", "/phpMyAdmin",
            "/config", "/.env", "/backup", "/db", "/database",
            "/phpmyadmin", "/mysql", "/temp", "/tmp",
            "/.git", "/.svn", "/config.php", "/wp-config.php",
            "/etc/passwd", "/proc/version", "/bin/bash"
        ]
        
        for suspicious in suspicious_paths:
            if suspicious in path_lower:
                return True
        
        # Check for directory traversal attempts
        if "../" in path or "..%2f" in path_lower or "..%5c" in path_lower:
            return True
        
        # Check for SQL injection attempts in path - but exclude legitimate device IDs
        sql_indicators = ["union", "select", "insert", "delete", "drop", "alter"]
        for indicator in sql_indicators:
            if indicator in path_lower:
                return True
        
        # Don't flag legitimate device ID patterns in auth routes
        if "/auth/verify/" in path_lower:
            device_id_part = path_lower.split("/auth/verify/")[-1]
            # Allow valid device ID patterns (4 letters + 4 digits)
            import re
            if re.match(r'^[a-z0-9]{4,8}$', device_id_part):
                return False

    
    def _add_security_headers(self, response: Response) -> Response:
        """Add security headers to response"""
        security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }
        
        for header, value in security_headers.items():
            response.headers[header] = value
        
        return response
    
    async def _cleanup_expired_data(self):
        """Cleanup expired rate limiting and blocking data"""
        now = datetime.now()
        
        # Only cleanup every 5 minutes
        if (now - self.last_cleanup).total_seconds() < 300:
            return
        
        self.last_cleanup = now
        
        # Cleanup expired blocked IPs
        expired_blocks = [
            ip for ip, blocked_until in self.blocked_ips.items()
            if now > blocked_until
        ]
        
        for ip in expired_blocks:
            del self.blocked_ips[ip]
            if ip in self.failed_attempts:
                del self.failed_attempts[ip]
        
        # Cleanup old rate limit data
        window_start = now - timedelta(seconds=self.settings.rate_limit_window_seconds * 2)
        
        for ip in list(self.rate_limit_storage.keys()):
            self.rate_limit_storage[ip] = [
                req_time for req_time in self.rate_limit_storage[ip]
                if req_time > window_start
            ]
            
            # Remove empty entries
            if not self.rate_limit_storage[ip]:
                del self.rate_limit_storage[ip]
        
        self.log_info(f"Security cleanup completed: {len(expired_blocks)} expired blocks removed")


class SecurityValidator:
    """Utility class for security validation"""
    
    @staticmethod
    def sanitize_input(input_data: str) -> str:
        """Sanitize user input to prevent XSS and injection attacks"""
        if not input_data:
            return ""
        
        import re
        
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
        """Validate request content size"""
        if content_length is None:
            return True
        
        return content_length <= max_size
    
    @staticmethod
    def is_safe_filename(filename: str) -> bool:
        """Check if filename is safe (no directory traversal)"""
        import os
        
        # Normalize path and check for traversal
        normalized = os.path.normpath(filename)
        return not (normalized.startswith('/') or normalized.startswith('\\') or '..' in normalized)


# CORS Security Configuration
def get_cors_config():
    """Get CORS configuration with security considerations"""
    settings = get_settings()
    
    if settings.debug:
        # Development: Allow all origins
        return {
            "allow_origins": ["*"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    else:
        # Production: Restrict origins
        return {
            "allow_origins": [
                "https://yourdomain.com",  # Replace with your domain
                "https://api.yourdomain.com",
            ],
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": [
                "Accept",
                "Accept-Language",
                "Content-Language",
                "Content-Type",
                "Authorization"
            ],
        }
      
        return False
    
    def _add_security_headers(self, response: Response) -> Response:
        """Add security headers to response"""
        security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }
        
        for header, value in security_headers.items():
            response.headers[header] = value
        
        return response
    
    async def _cleanup_expired_data(self):
        """Cleanup expired rate limiting and blocking data"""
        now = datetime.now()
        
        # Only cleanup every 5 minutes
        if (now - self.last_cleanup).total_seconds() < 300:
            return
        
        self.last_cleanup = now
        
        # Cleanup expired blocked IPs
        expired_blocks = [
            ip for ip, blocked_until in self.blocked_ips.items()
            if now > blocked_until
        ]
        
        for ip in expired_blocks:
            del self.blocked_ips[ip]
            if ip in self.failed_attempts:
                del self.failed_attempts[ip]
        
        # Cleanup old rate limit data
        window_start = now - timedelta(seconds=self.settings.rate_limit_window_seconds * 2)
        
        for ip in list(self.rate_limit_storage.keys()):
            self.rate_limit_storage[ip] = [
                req_time for req_time in self.rate_limit_storage[ip]
                if req_time > window_start
            ]
            
            # Remove empty entries
            if not self.rate_limit_storage[ip]:
                del self.rate_limit_storage[ip]
        
        self.log_info(f"Security cleanup completed: {len(expired_blocks)} expired blocks removed")


class SecurityValidator:
    """Utility class for security validation"""
    
    @staticmethod
    def sanitize_input(input_data: str) -> str:
        """Sanitize user input to prevent XSS and injection attacks"""
        if not input_data:
            return ""
        
        import re
        
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
        """Validate request content size"""
        if content_length is None:
            return True
        
        return content_length <= max_size
    
    @staticmethod
    def is_safe_filename(filename: str) -> bool:
        """Check if filename is safe (no directory traversal)"""
        import os
        
        # Normalize path and check for traversal
        normalized = os.path.normpath(filename)
        return not (normalized.startswith('/') or normalized.startswith('\\') or '..' in normalized)


# CORS Security Configuration
def get_cors_config():
    """Get CORS configuration with security considerations"""
    settings = get_settings()
    
    if settings.debug:
        # Development: Allow all origins
        return {
            "allow_origins": ["*"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    else:
        # Production: Restrict origins
        return {
            "allow_origins": [
                "https://yourdomain.com",  # Replace with your domain
                "https://api.yourdomain.com",
            ],
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": [
                "Accept",
                "Accept-Language",
                "Content-Language",
                "Content-Type",
                "Authorization"
            ],
        }
    
    def _add_security_headers(self, response: Response) -> Response:
        """Add security headers to response"""
        security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }
        
        for header, value in security_headers.items():
            response.headers[header] = value
        
        return response
    
    async def _cleanup_expired_data(self):
        """Cleanup expired rate limiting and blocking data"""
        now = datetime.now()
        
        # Only cleanup every 5 minutes
        if (now - self.last_cleanup).total_seconds() < 300:
            return
        
        self.last_cleanup = now
        
        # Cleanup expired blocked IPs
        expired_blocks = [
            ip for ip, blocked_until in self.blocked_ips.items()
            if now > blocked_until
        ]
        
        for ip in expired_blocks:
            del self.blocked_ips[ip]
            if ip in self.failed_attempts:
                del self.failed_attempts[ip]
        
        # Cleanup old rate limit data
        window_start = now - timedelta(seconds=self.settings.rate_limit_window_seconds * 2)
        
        for ip in list(self.rate_limit_storage.keys()):
            self.rate_limit_storage[ip] = [
                req_time for req_time in self.rate_limit_storage[ip]
                if req_time > window_start
            ]
            
            # Remove empty entries
            if not self.rate_limit_storage[ip]:
                del self.rate_limit_storage[ip]
        
        self.log_info(f"Security cleanup completed: {len(expired_blocks)} expired blocks removed")


class SecurityValidator:
    """Utility class for security validation"""
    
    @staticmethod
    def sanitize_input(input_data: str) -> str:
        """Sanitize user input to prevent XSS and injection attacks"""
        if not input_data:
            return ""
        
        import re
        
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
        """Validate request content size"""
        if content_length is None:
            return True
        
        return content_length <= max_size
    
    @staticmethod
    def is_safe_filename(filename: str) -> bool:
        """Check if filename is safe (no directory traversal)"""
        import os
        
        # Normalize path and check for traversal
        normalized = os.path.normpath(filename)
        return not (normalized.startswith('/') or normalized.startswith('\\') or '..' in normalized)


# CORS Security Configuration
def get_cors_config():
    """Get CORS configuration with security considerations"""
    settings = get_settings()
    
    if settings.debug:
        # Development: Allow all origins
        return {
            "allow_origins": ["*"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    else:
        # Production: Restrict origins
        return {
            "allow_origins": [
                "https://yourdomain.com",  # Replace with your domain
                "https://api.yourdomain.com",
            ],
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": [
                "Accept",
                "Accept-Language",
                "Content-Language",
                "Content-Type",
                "Authorization"
            ],
        }
        
        return False
    
    def _add_security_headers(self, response: Response) -> Response:
        """Add security headers to response"""
        security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }
        
        for header, value in security_headers.items():
            response.headers[header] = value
        
        return response
    
    async def _cleanup_expired_data(self):
        """Cleanup expired rate limiting and blocking data"""
        now = datetime.now()
        
        # Only cleanup every 5 minutes
        if (now - self.last_cleanup).total_seconds() < 300:
            return
        
        self.last_cleanup = now
        
        # Cleanup expired blocked IPs
        expired_blocks = [
            ip for ip, blocked_until in self.blocked_ips.items()
            if now > blocked_until
        ]
        
        for ip in expired_blocks:
            del self.blocked_ips[ip]
            if ip in self.failed_attempts:
                del self.failed_attempts[ip]
        
        # Cleanup old rate limit data
        window_start = now - timedelta(seconds=self.settings.rate_limit_window_seconds * 2)
        
        for ip in list(self.rate_limit_storage.keys()):
            self.rate_limit_storage[ip] = [
                req_time for req_time in self.rate_limit_storage[ip]
                if req_time > window_start
            ]
            
            # Remove empty entries
            if not self.rate_limit_storage[ip]:
                del self.rate_limit_storage[ip]
        
        self.log_info(f"Security cleanup completed: {len(expired_blocks)} expired blocks removed")


class SecurityValidator:
    """Utility class for security validation"""
    
    @staticmethod
    def sanitize_input(input_data: str) -> str:
        """Sanitize user input to prevent XSS and injection attacks"""
        if not input_data:
            return ""
        
        import re
        
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
        """Validate request content size"""
        if content_length is None:
            return True
        
        return content_length <= max_size
    
    @staticmethod
    def is_safe_filename(filename: str) -> bool:
        """Check if filename is safe (no directory traversal)"""
        import os
        
        # Normalize path and check for traversal
        normalized = os.path.normpath(filename)
        return not (normalized.startswith('/') or normalized.startswith('\\') or '..' in normalized)


# CORS Security Configuration
def get_cors_config():
    """Get CORS configuration with security considerations"""
    settings = get_settings()
    
    if settings.debug:
        # Development: Allow all origins
        return {
            "allow_origins": ["*"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    else:
        # Production: Restrict origins
        return {
            "allow_origins": [
                "https://yourdomain.com",  # Replace with your domain
                "https://api.yourdomain.com",
            ],
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": [
                "Accept",
                "Accept-Language",
                "Content-Language",
                "Content-Type",
                "Authorization"
            ],
        }