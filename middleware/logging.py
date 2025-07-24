"""
Logging middleware for the ESP32 Audio Streaming Server
"""
import time
import json
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import logging

from utils.logger import LoggerMixin


class RequestLoggingMiddleware(BaseHTTPMiddleware, LoggerMixin):
    """Middleware for logging HTTP requests and responses"""
    
    def __init__(self, app):
        super().__init__(app)
        LoggerMixin.__init__(self)
        
        # Create request logger
        self.request_logger = logging.getLogger('requests')
        
        # Paths to exclude from detailed logging (to reduce noise)
        self.exclude_paths = {
            "/health",
            "/docs", 
            "/redoc",
            "/openapi.json",
            "/favicon.ico"
        }
        
        # Sensitive headers to mask in logs
        self.sensitive_headers = {
            "authorization",
            "cookie",
            "x-api-key",
            "x-auth-token"
        }
    
    async def dispatch(self, request: Request, call_next):
        """Process request and log details"""
        
        # Record start time
        start_time = time.time()
        
        # Generate request ID for tracking
        request_id = self._generate_request_id()
        
        # Get client information
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Skip detailed logging for excluded paths
        should_log_details = not any(
            excluded in str(request.url.path) for excluded in self.exclude_paths
        )
        
        # Log request start
        if should_log_details:
            self._log_request_start(request, request_id, client_ip, user_agent)
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate processing time
            process_time = time.time() - start_time
            
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            
            # Log request completion
            if should_log_details:
                self._log_request_completion(
                    request, response, request_id, client_ip, process_time
                )
            else:
                # Log minimal info for excluded paths
                self.log_info(f"Request: {request.method} {request.url.path} - {response.status_code} ({process_time:.3f}s)")
            
            return response
            
        except Exception as e:
            # Calculate processing time for failed requests
            process_time = time.time() - start_time
            
            # Log request error
            self._log_request_error(request, e, request_id, client_ip, process_time)
            
            # Re-raise the exception
            raise
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address"""
        # Check for forwarded headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fallback to direct connection
        if request.client:
            return request.client.host
        
        return "unknown"
    
    def _mask_sensitive_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Mask sensitive headers for logging"""
        masked_headers = {}
        
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower in self.sensitive_headers:
                # Mask sensitive values
                if len(value) > 8:
                    masked_headers[key] = f"{value[:4]}***{value[-4:]}"
                else:
                    masked_headers[key] = "***"
            else:
                masked_headers[key] = value
        
        return masked_headers
    
    def _log_request_start(self, request: Request, request_id: str, 
                          client_ip: str, user_agent: str):
        """Log request start details"""
        
        # Prepare request headers (masked)
        headers = dict(request.headers)
        masked_headers = self._mask_sensitive_headers(headers)
        
        # Extract query parameters
        query_params = dict(request.query_params) if request.query_params else {}
        
        # Log request start
        self.request_logger.info(
            "Request started",
            extra={
                "event": "request_start",
                "request_id": request_id,
                "method": request.method,
                "url": str(request.url),
                "path": request.url.path,
                "query_params": query_params,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "headers": masked_headers,
                "timestamp": datetime.now().isoformat()
            }
        )
    
    def _log_request_completion(self, request: Request, response: Response,
                              request_id: str, client_ip: str, process_time: float):
        """Log successful request completion"""
        
        # Prepare response headers (masked)
        response_headers = dict(response.headers)
        masked_response_headers = self._mask_sensitive_headers(response_headers)
        
        # Determine log level based on status code
        if response.status_code >= 500:
            log_level = "error"
        elif response.status_code >= 400:
            log_level = "warning"
        else:
            log_level = "info"
        
        # Log completion
        log_method = getattr(self.request_logger, log_level)
        log_method(
            f"Request completed: {request.method} {request.url.path} - {response.status_code}",
            extra={
                "event": "request_completed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "client_ip": client_ip,
                "process_time_seconds": round(process_time, 4),
                "response_headers": masked_response_headers,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        # Log slow requests
        if process_time > 2.0:  # Log requests taking more than 2 seconds
            self.log_warning(f"Slow request detected: {request.method} {request.url.path} took {process_time:.3f}s")
    
    def _log_request_error(self, request: Request, error: Exception,
                          request_id: str, client_ip: str, process_time: float):
        """Log request error details"""
        
        self.request_logger.error(
            f"Request error: {request.method} {request.url.path} - {type(error).__name__}",
            extra={
                "event": "request_error",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client_ip": client_ip,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "process_time_seconds": round(process_time, 4),
                "timestamp": datetime.now().isoformat()
            },
            exc_info=True
        )


class MetricsCollectionMiddleware(BaseHTTPMiddleware, LoggerMixin):
    """Middleware for collecting application metrics"""
    
    def __init__(self, app):
        super().__init__(app)
        LoggerMixin.__init__(self)
        
        # Metrics storage
        self.metrics = {
            "request_count": 0,
            "error_count": 0,
            "total_process_time": 0.0,
            "request_counts_by_path": {},
            "error_counts_by_status": {},
            "response_times": []
        }
        
        # Last metrics log time
        self.last_metrics_log = time.time()
        self.metrics_log_interval = 300  # Log metrics every 5 minutes
    
    async def dispatch(self, request: Request, call_next):
        """Collect metrics during request processing"""
        
        start_time = time.time()
        path = request.url.path
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate processing time
            process_time = time.time() - start_time
            
            # Update metrics
            self._update_success_metrics(path, response.status_code, process_time)
            
            # Log metrics periodically
            self._maybe_log_metrics()
            
            return response
            
        except Exception as e:
            # Calculate processing time for failed requests
            process_time = time.time() - start_time
            
            # Update error metrics
            self._update_error_metrics(path, process_time)
            
            # Log metrics periodically
            self._maybe_log_metrics()
            
            raise
    
    def _update_success_metrics(self, path: str, status_code: int, process_time: float):
        """Update metrics for successful requests"""
        self.metrics["request_count"] += 1
        self.metrics["total_process_time"] += process_time
        
        # Track by path
        if path not in self.metrics["request_counts_by_path"]:
            self.metrics["request_counts_by_path"][path] = 0
        self.metrics["request_counts_by_path"][path] += 1
        
        # Track errors by status code
        if status_code >= 400:
            self.metrics["error_count"] += 1
            status_key = f"{status_code // 100}xx"
            if status_key not in self.metrics["error_counts_by_status"]:
                self.metrics["error_counts_by_status"][status_key] = 0
            self.metrics["error_counts_by_status"][status_key] += 1
        
        # Store response time (keep last 1000)
        self.metrics["response_times"].append(process_time)
        if len(self.metrics["response_times"]) > 1000:
            self.metrics["response_times"].pop(0)
    
    def _update_error_metrics(self, path: str, process_time: float):
        """Update metrics for failed requests"""
        self.metrics["request_count"] += 1
        self.metrics["error_count"] += 1
        self.metrics["total_process_time"] += process_time
        
        # Track by path
        if path not in self.metrics["request_counts_by_path"]:
            self.metrics["request_counts_by_path"][path] = 0
        self.metrics["request_counts_by_path"][path] += 1
        
        # Track 5xx errors
        if "5xx" not in self.metrics["error_counts_by_status"]:
            self.metrics["error_counts_by_status"]["5xx"] = 0
        self.metrics["error_counts_by_status"]["5xx"] += 1
        
        # Store response time
        self.metrics["response_times"].append(process_time)
        if len(self.metrics["response_times"]) > 1000:
            self.metrics["response_times"].pop(0)
    
    def _maybe_log_metrics(self):
        """Log metrics if interval has passed"""
        current_time = time.time()
        
        if current_time - self.last_metrics_log >= self.metrics_log_interval:
            self._log_metrics()
            self.last_metrics_log = current_time
    
    def _log_metrics(self):
        """Log current metrics"""
        if self.metrics["request_count"] == 0:
            return
        
        # Calculate statistics
        avg_response_time = self.metrics["total_process_time"] / self.metrics["request_count"]
        error_rate = (self.metrics["error_count"] / self.metrics["request_count"]) * 100
        
        # Calculate response time percentiles
        response_times = sorted(self.metrics["response_times"])
        percentiles = {}
        if response_times:
            percentiles = {
                "p50": response_times[int(len(response_times) * 0.5)],
                "p95": response_times[int(len(response_times) * 0.95)],
                "p99": response_times[int(len(response_times) * 0.99)]
            }
        
        # Log metrics
        metrics_logger = logging.getLogger('metrics')
        metrics_logger.info(
            "Application metrics",
            extra={
                "event": "metrics_snapshot",
                "request_count": self.metrics["request_count"],
                "error_count": self.metrics["error_count"],
                "error_rate_percent": round(error_rate, 2),
                "avg_response_time_seconds": round(avg_response_time, 4),
                "total_process_time_seconds": round(self.metrics["total_process_time"], 2),
                "response_time_percentiles": percentiles,
                "request_counts_by_path": self.metrics["request_counts_by_path"],
                "error_counts_by_status": self.metrics["error_counts_by_status"],
                "timestamp": datetime.now().isoformat()
            }
        )
        
        # Reset some metrics to avoid memory growth
        if self.metrics["request_count"] > 10000:
            self._reset_metrics()
    
    def _reset_metrics(self):
        """Reset metrics to prevent memory growth"""
        self.log_info("Resetting metrics counters")
        
        self.metrics = {
            "request_count": 0,
            "error_count": 0,
            "total_process_time": 0.0,
            "request_counts_by_path": {},
            "error_counts_by_status": {},
            "response_times": []
        }
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current metrics snapshot"""
        if self.metrics["request_count"] == 0:
            return self.metrics.copy()
        
        # Calculate derived metrics
        avg_response_time = self.metrics["total_process_time"] / self.metrics["request_count"]
        error_rate = (self.metrics["error_count"] / self.metrics["request_count"]) * 100
        
        # Calculate response time percentiles
        response_times = sorted(self.metrics["response_times"])
        percentiles = {}
        if response_times:
            percentiles = {
                "p50": response_times[int(len(response_times) * 0.5)],
                "p95": response_times[int(len(response_times) * 0.95)],
                "p99": response_times[int(len(response_times) * 0.99)]
            }
        
        metrics_copy = self.metrics.copy()
        metrics_copy.update({
            "avg_response_time_seconds": round(avg_response_time, 4),
            "error_rate_percent": round(error_rate, 2),
            "response_time_percentiles": percentiles,
            "timestamp": datetime.now().isoformat()
        })
        
        return metrics_copy


# Global metrics instance for access from routes
_metrics_middleware: Optional[MetricsCollectionMiddleware] = None


def get_metrics_middleware() -> Optional[MetricsCollectionMiddleware]:
    """Get the global metrics middleware instance"""
    return _metrics_middleware


def set_metrics_middleware(middleware: MetricsCollectionMiddleware):
    """Set the global metrics middleware instance"""
    global _metrics_middleware
    _metrics_middleware = middleware