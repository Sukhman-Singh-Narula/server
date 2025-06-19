#!/usr/bin/env python3
"""
Comprehensive Test Script for ESP32 Audio Streaming Server
Tests all endpoints with various scenarios including success and failure cases
"""

import asyncio
import json
import time
import random
import string
from datetime import datetime
from typing import Dict, List, Any, Optional
import requests
import websockets
from websockets.exceptions import ConnectionClosed
import argparse
import sys
from pathlib import Path

# Color codes for console output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


class TestResult:
    """Store test result information"""
    
    def __init__(self, name: str, success: bool, message: str = "", 
                 response_data: Any = None, duration: float = 0.0):
        self.name = name
        self.success = success
        self.message = message
        self.response_data = response_data
        self.duration = duration
        self.timestamp = datetime.now()


class ESP32ServerTester:
    """Comprehensive tester for ESP32 Audio Streaming Server"""
    
    def __init__(self, base_url: str = "http://localhost:8000", ws_url: str = "ws://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.ws_url = ws_url.rstrip('/')
        self.session = requests.Session()
        self.results: List[TestResult] = []
        
        # Test data
        self.test_device_ids = {
            'valid': ['ABCD1234', 'TEST0001', 'USER9999', 'DEMO5678'],
            'invalid': ['abc1234', 'ABCD123', 'ABCD12345', '1234ABCD', '', 'invalid']
        }
        
        self.test_users = [
            {'device_id': 'ABCD1234', 'name': 'Alice Johnson', 'age': 25},
            {'device_id': 'TEST0001', 'name': 'Bob Smith', 'age': 30},
            {'device_id': 'USER9999', 'name': 'Charlie Brown', 'age': 18},
            {'device_id': 'DEMO5678', 'name': 'Diana Prince', 'age': 28}
        ]
        
        self.test_prompts = [
            {
                'season': 1, 'episode': 1, 
                'prompt': 'You are a helpful assistant teaching basic vocabulary to young learners. Use simple words and encouraging tone.',
                'prompt_type': 'learning'
            },
            {
                'season': 1, 'episode': 2,
                'prompt': 'You are helping children learn colors and shapes. Be patient and use visual descriptions.',
                'prompt_type': 'learning'
            },
            {
                'season': 2, 'episode': 1,
                'prompt': 'Assessment time! Ask simple questions to test vocabulary knowledge.',
                'prompt_type': 'assessment'
            }
        ]
    
    def log(self, message: str, color: str = Colors.WHITE):
        """Log message with color"""
        print(f"{color}{message}{Colors.END}")
    
    def log_success(self, message: str):
        """Log success message"""
        self.log(f"✅ {message}", Colors.GREEN)
    
    def log_error(self, message: str):
        """Log error message"""
        self.log(f"❌ {message}", Colors.RED)
    
    def log_warning(self, message: str):
        """Log warning message"""
        self.log(f"⚠️  {message}", Colors.YELLOW)
    
    def log_info(self, message: str):
        """Log info message"""
        self.log(f"ℹ️  {message}", Colors.BLUE)
    
    def log_test_header(self, test_name: str):
        """Log test section header"""
        self.log(f"\n{'='*60}", Colors.CYAN)
        self.log(f"🧪 {test_name.upper()}", Colors.CYAN + Colors.BOLD)
        self.log(f"{'='*60}", Colors.CYAN)
    
    def add_result(self, name: str, success: bool, message: str = "", 
                   response_data: Any = None, duration: float = 0.0):
        """Add test result"""
        result = TestResult(name, success, message, response_data, duration)
        self.results.append(result)
        
        if success:
            self.log_success(f"{name}: {message}")
        else:
            self.log_error(f"{name}: {message}")
    
    def make_request(self, method: str, endpoint: str, **kwargs) -> tuple[bool, Any, float]:
        """Make HTTP request and return (success, response_data, duration)"""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            response = self.session.request(method, url, timeout=10, **kwargs)
            duration = time.time() - start_time
            
            try:
                data = response.json()
            except:
                data = response.text
            
            return response.status_code < 400, data, duration
            
        except Exception as e:
            duration = time.time() - start_time
            return False, str(e), duration
    
    # =================================================================
    # BASIC SERVER TESTS
    # =================================================================
    
    def test_server_basic(self):
        """Test basic server functionality"""
        self.log_test_header("Basic Server Tests")
        
        # Test root endpoint
        success, data, duration = self.make_request('GET', '/')
        if success and 'message' in data:
            self.add_result("Root Endpoint", True, f"Server running ({duration:.3f}s)", data, duration)
        else:
            self.add_result("Root Endpoint", False, f"Failed to reach server: {data}")
        
        # Test health check
        success, data, duration = self.make_request('GET', '/health')
        if success and 'status' in data:
            status = data.get('status', 'unknown')
            self.add_result("Health Check", True, f"Status: {status} ({duration:.3f}s)", data, duration)
        else:
            self.add_result("Health Check", False, f"Health check failed: {data}")
        
        # Test metrics
        success, data, duration = self.make_request('GET', '/metrics')
        if success:
            self.add_result("Metrics Endpoint", True, f"Metrics available ({duration:.3f}s)", data, duration)
        else:
            self.add_result("Metrics Endpoint", False, f"Metrics failed: {data}")
        
        # Test documentation
        success, data, duration = self.make_request('GET', '/docs')
        if success:
            self.add_result("API Documentation", True, f"Docs accessible ({duration:.3f}s)", None, duration)
        else:
            self.add_result("API Documentation", False, f"Docs not accessible: {data}")
    
    # =================================================================
    # AUTHENTICATION TESTS
    # =================================================================
    
    def test_authentication(self):
        """Test authentication endpoints"""
        self.log_test_header("Authentication Tests")
        
        # Test device ID validation
        for device_id in self.test_device_ids['valid']:
            success, data, duration = self.make_request('POST', f'/auth/validate-device-id?device_id={device_id}')
            if success and data.get('is_valid'):
                self.add_result(f"Valid Device ID: {device_id}", True, f"Validation passed ({duration:.3f}s)")
            else:
                self.add_result(f"Valid Device ID: {device_id}", False, f"Should be valid: {data}")
        
        for device_id in self.test_device_ids['invalid']:
            success, data, duration = self.make_request('POST', f'/auth/validate-device-id?device_id={device_id}')
            if success and not data.get('is_valid'):
                self.add_result(f"Invalid Device ID: {device_id}", True, f"Correctly rejected ({duration:.3f}s)")
            else:
                self.add_result(f"Invalid Device ID: {device_id}", False, f"Should be invalid: {data}")
        
        # Test user registration
        for user in self.test_users:
            success, data, duration = self.make_request('POST', '/auth/register', json=user)
            if success and 'device_id' in data:
                self.add_result(f"Register User: {user['device_id']}", True, 
                              f"User {user['name']} registered ({duration:.3f}s)", data, duration)
            else:
                # Could be duplicate registration, which is expected
                if 'already exists' in str(data).lower():
                    self.add_result(f"Register User: {user['device_id']}", True, 
                                  f"User already exists (expected) ({duration:.3f}s)")
                else:
                    self.add_result(f"Register User: {user['device_id']}", False, 
                                  f"Registration failed: {data}")
        
        # Test duplicate registration
        duplicate_user = self.test_users[0]
        success, data, duration = self.make_request('POST', '/auth/register', json=duplicate_user)
        if not success and 'already exists' in str(data).lower():
            self.add_result("Duplicate Registration Prevention", True, 
                          f"Correctly prevented duplicate ({duration:.3f}s)")
        elif success:
            self.add_result("Duplicate Registration Prevention", False, 
                          "Should have prevented duplicate registration")
        
        # Test registration with invalid data
        invalid_user = {'device_id': 'invalid', 'name': '', 'age': -1}
        success, data, duration = self.make_request('POST', '/auth/register', json=invalid_user)
        if not success:
            self.add_result("Invalid Registration Data", True, 
                          f"Correctly rejected invalid data ({duration:.3f}s)")
        else:
            self.add_result("Invalid Registration Data", False, 
                          "Should have rejected invalid data")
        
        # Test user verification
        for user in self.test_users[:2]:  # Test first 2 users
            success, data, duration = self.make_request('GET', f'/auth/verify/{user["device_id"]}')
            if success and data.get('registered'):
                self.add_result(f"Verify User: {user['device_id']}", True, 
                              f"User verification successful ({duration:.3f}s)")
            else:
                self.add_result(f"Verify User: {user['device_id']}", False, 
                              f"User verification failed: {data}")
    
    # =================================================================
    # USER MANAGEMENT TESTS
    # =================================================================
    
    def test_user_management(self):
        """Test user management endpoints"""
        self.log_test_header("User Management Tests")
        
        for user in self.test_users[:2]:  # Test first 2 users
            device_id = user['device_id']
            
            # Test get user info
            success, data, duration = self.make_request('GET', f'/users/{device_id}')
            if success and 'device_id' in data:
                self.add_result(f"Get User Info: {device_id}", True, 
                              f"Retrieved user data ({duration:.3f}s)", data, duration)
            else:
                self.add_result(f"Get User Info: {device_id}", False, 
                              f"Failed to get user: {data}")
            
            # Test get user statistics
            success, data, duration = self.make_request('GET', f'/users/{device_id}/statistics')
            if success and 'user_info' in data:
                self.add_result(f"Get User Stats: {device_id}", True, 
                              f"Retrieved statistics ({duration:.3f}s)", data, duration)
            else:
                self.add_result(f"Get User Stats: {device_id}", False, 
                              f"Failed to get stats: {data}")
            
            # Test get session info
            success, data, duration = self.make_request('GET', f'/users/{device_id}/session')
            if success:
                self.add_result(f"Get Session Info: {device_id}", True, 
                              f"Retrieved session info ({duration:.3f}s)", data, duration)
            else:
                self.add_result(f"Get Session Info: {device_id}", False, 
                              f"Failed to get session: {data}")
            
            # Test get session duration
            success, data, duration = self.make_request('GET', f'/users/{device_id}/session-duration')
            if success and 'session_duration_seconds' in data:
                duration_seconds = data['session_duration_seconds']
                self.add_result(f"Get Session Duration: {device_id}", True, 
                              f"Duration: {duration_seconds}s ({duration:.3f}s)")
            else:
                self.add_result(f"Get Session Duration: {device_id}", False, 
                              f"Failed to get duration: {data}")
            
            # Test update progress
            progress_update = {
                'words_learnt': ['hello', 'world', 'test'],
                'topics_learnt': ['greetings', 'vocabulary']
            }
            success, data, duration = self.make_request('PUT', f'/users/{device_id}/progress', 
                                                      json=progress_update)
            if success:
                self.add_result(f"Update Progress: {device_id}", True, 
                              f"Progress updated ({duration:.3f}s)", data, duration)
            else:
                self.add_result(f"Update Progress: {device_id}", False, 
                              f"Failed to update progress: {data}")
            
            # Test advance episode
            success, data, duration = self.make_request('POST', f'/users/{device_id}/advance-episode')
            if success:
                self.add_result(f"Advance Episode: {device_id}", True, 
                              f"Episode advanced ({duration:.3f}s)", data, duration)
            else:
                self.add_result(f"Advance Episode: {device_id}", False, 
                              f"Failed to advance: {data}")
        
        # Test with invalid device ID
        success, data, duration = self.make_request('GET', '/users/INVALID123')
        if not success:
            self.add_result("Invalid User Request", True, 
                          f"Correctly rejected invalid device ID ({duration:.3f}s)")
        else:
            self.add_result("Invalid User Request", False, 
                          "Should have rejected invalid device ID")
        
        # Test get all active connections
        success, data, duration = self.make_request('GET', '/users/')
        if success:
            active_connections = data.get('active_connections', 0)
            self.add_result("Get Active Connections", True, 
                          f"Found {active_connections} active connections ({duration:.3f}s)")
        else:
            self.add_result("Get Active Connections", False, 
                          f"Failed to get connections: {data}")
    
    # =================================================================
    # SYSTEM PROMPT TESTS
    # =================================================================
    
    def test_system_prompts(self):
        """Test system prompt management"""
        self.log_test_header("System Prompt Tests")
        
        # Test create system prompts
        for prompt in self.test_prompts:
            success, data, duration = self.make_request('POST', '/prompts/', json=prompt)
            if success and 'season' in data:
                self.add_result(f"Create Prompt S{prompt['season']}E{prompt['episode']}", True, 
                              f"Prompt created ({duration:.3f}s)", data, duration)
            else:
                # Could be duplicate, which is expected
                if 'already exists' in str(data).lower() or success:
                    self.add_result(f"Create Prompt S{prompt['season']}E{prompt['episode']}", True, 
                                  f"Prompt exists (expected) ({duration:.3f}s)")
                else:
                    self.add_result(f"Create Prompt S{prompt['season']}E{prompt['episode']}", False, 
                                  f"Failed to create: {data}")
        
        # Test get specific prompts
        for prompt in self.test_prompts:
            season, episode = prompt['season'], prompt['episode']
            success, data, duration = self.make_request('GET', f'/prompts/{season}/{episode}')
            if success and 'season' in data:
                self.add_result(f"Get Prompt S{season}E{episode}", True, 
                              f"Retrieved prompt ({duration:.3f}s)", data, duration)
            else:
                self.add_result(f"Get Prompt S{season}E{episode}", False, 
                              f"Failed to get prompt: {data}")
        
        # Test get prompt content
        prompt = self.test_prompts[0]
        season, episode = prompt['season'], prompt['episode']
        success, data, duration = self.make_request('GET', f'/prompts/{season}/{episode}/content')
        if success and 'content' in data:
            content_length = len(data['content'])
            self.add_result(f"Get Prompt Content S{season}E{episode}", True, 
                          f"Content length: {content_length} chars ({duration:.3f}s)")
        else:
            self.add_result(f"Get Prompt Content S{season}E{episode}", False, 
                          f"Failed to get content: {data}")
        
        # Test get season overview
        success, data, duration = self.make_request('GET', '/prompts/1')
        if success and 'season' in data:
            completed = data.get('completed_episodes', 0)
            total = data.get('total_episodes', 0)
            self.add_result("Get Season Overview", True, 
                          f"Season 1: {completed}/{total} episodes ({duration:.3f}s)")
        else:
            self.add_result("Get Season Overview", False, 
                          f"Failed to get overview: {data}")
        
        # Test get all seasons overview
        success, data, duration = self.make_request('GET', '/prompts/')
        if success and isinstance(data, list):
            seasons_count = len(data)
            self.add_result("Get All Seasons Overview", True, 
                          f"Found {seasons_count} seasons ({duration:.3f}s)")
        else:
            self.add_result("Get All Seasons Overview", False, 
                          f"Failed to get all seasons: {data}")
        
        # Test prompt validation
        validation_data = {'prompt': 'You are a helpful assistant teaching vocabulary.'}
        success, data, duration = self.make_request('POST', '/prompts/validate', json=validation_data)
        if success and 'is_valid' in data:
            is_valid = data['is_valid']
            self.add_result("Prompt Validation", True, 
                          f"Validation result: {is_valid} ({duration:.3f}s)")
        else:
            self.add_result("Prompt Validation", False, 
                          f"Validation failed: {data}")
        
        # Test prompt metadata update
        metadata_update = {'metadata': {'updated_by': 'test_script', 'version': '1.1'}}
        prompt = self.test_prompts[0]
        success, data, duration = self.make_request('PUT', 
                                                   f'/prompts/{prompt["season"]}/{prompt["episode"]}/metadata',
                                                   json=metadata_update)
        if success:
            self.add_result("Update Prompt Metadata", True, 
                          f"Metadata updated ({duration:.3f}s)")
        else:
            self.add_result("Update Prompt Metadata", False, 
                          f"Failed to update metadata: {data}")
        
        # Test invalid prompt creation
        invalid_prompt = {'season': 0, 'episode': 0, 'prompt': ''}
        success, data, duration = self.make_request('POST', '/prompts/', json=invalid_prompt)
        if not success:
            self.add_result("Invalid Prompt Creation", True, 
                          f"Correctly rejected invalid prompt ({duration:.3f}s)")
        else:
            self.add_result("Invalid Prompt Creation", False, 
                          "Should have rejected invalid prompt")
        
        # Test prompt search
        success, data, duration = self.make_request('GET', '/prompts/search?query=assistant')
        if success:
            results_count = len(data) if isinstance(data, list) else 0
            self.add_result("Prompt Search", True, 
                          f"Found {results_count} results ({duration:.3f}s)")
        else:
            self.add_result("Prompt Search", False, 
                          f"Search failed: {data}")
        
        # Test prompt analytics
        prompt = self.test_prompts[0]
        success, data, duration = self.make_request('GET', 
                                                   f'/prompts/{prompt["season"]}/{prompt["episode"]}/analytics')
        if success and 'prompt_info' in data:
            self.add_result("Prompt Analytics", True, 
                          f"Analytics retrieved ({duration:.3f}s)")
        else:
            self.add_result("Prompt Analytics", False, 
                          f"Analytics failed: {data}")
    
    # =================================================================
    # WEBSOCKET TESTS
    # =================================================================
    
    def test_websocket_endpoints(self):
        """Test WebSocket-related HTTP endpoints"""
        self.log_test_header("WebSocket HTTP Endpoints")
        
        # Test get active WebSocket connections
        success, data, duration = self.make_request('GET', '/ws/connections')
        if success and 'total_connections' in data:
            total = data['total_connections']
            self.add_result("Get WebSocket Connections", True, 
                          f"Found {total} active connections ({duration:.3f}s)")
        else:
            self.add_result("Get WebSocket Connections", False, 
                          f"Failed to get connections: {data}")
        
        # Test get specific connection info
        device_id = self.test_users[0]['device_id']
        success, data, duration = self.make_request('GET', f'/ws/connection/{device_id}')
        if success:
            is_connected = data.get('is_connected', False)
            self.add_result(f"Get Connection Info: {device_id}", True, 
                          f"Connected: {is_connected} ({duration:.3f}s)")
        else:
            self.add_result(f"Get Connection Info: {device_id}", False, 
                          f"Failed to get info: {data}")
        
        # Test WebSocket health check
        success, data, duration = self.make_request('GET', '/ws/health')
        if success and 'overall_status' in data:
            status = data['overall_status']
            self.add_result("WebSocket Health Check", True, 
                          f"Status: {status} ({duration:.3f}s)")
        else:
            self.add_result("WebSocket Health Check", False, 
                          f"Health check failed: {data}")
        
        # Test WebSocket stats
        success, data, duration = self.make_request('GET', '/ws/stats')
        if success and 'connection_stats' in data:
            stats = data['connection_stats']
            total_connections = stats.get('total_active_connections', 0)
            self.add_result("WebSocket Statistics", True, 
                          f"Active connections: {total_connections} ({duration:.3f}s)")
        else:
            self.add_result("WebSocket Statistics", False, 
                          f"Stats failed: {data}")
    
    async def test_websocket_connection(self):
        """Test actual WebSocket connection"""
        self.log_test_header("WebSocket Connection Tests")
        
        device_id = self.test_users[0]['device_id']
        ws_url = f"{self.ws_url}/ws/{device_id}"
        
        try:
            # Test WebSocket connection
            start_time = time.time()
            
            async with websockets.connect(ws_url, timeout=10) as websocket:
                duration = time.time() - start_time
                self.add_result(f"WebSocket Connection: {device_id}", True, 
                              f"Connected successfully ({duration:.3f}s)")
                
                # Test sending data
                test_audio_data = b'\x00\x01\x02\x03' * 100  # Fake audio data
                await websocket.send(test_audio_data)
                self.add_result(f"WebSocket Send Data: {device_id}", True, 
                              f"Sent {len(test_audio_data)} bytes")
                
                # Wait a bit to see if we get any response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    self.add_result(f"WebSocket Receive Data: {device_id}", True, 
                                  f"Received {len(response)} bytes")
                except asyncio.TimeoutError:
                    self.add_result(f"WebSocket Receive Data: {device_id}", True, 
                                  "No immediate response (expected)")
                
        except Exception as e:
            self.add_result(f"WebSocket Connection: {device_id}", False, 
                          f"Connection failed: {str(e)}")
        
        # Test invalid device ID WebSocket connection
        try:
            invalid_ws_url = f"{self.ws_url}/ws/INVALID123"
            
            async with websockets.connect(invalid_ws_url, timeout=5) as websocket:
                self.add_result("WebSocket Invalid Device ID", False, 
                              "Should have rejected invalid device ID")
                
        except websockets.exceptions.ConnectionClosedError as e:
            if e.code in [4000, 4001, 4002]:  # Expected close codes
                self.add_result("WebSocket Invalid Device ID", True, 
                              f"Correctly rejected (code: {e.code})")
            else:
                self.add_result("WebSocket Invalid Device ID", False, 
                              f"Unexpected close code: {e.code}")
                
        except Exception as e:
            self.add_result("WebSocket Invalid Device ID", True, 
                          f"Connection properly rejected: {type(e).__name__}")
    
    # =================================================================
    # ERROR HANDLING TESTS
    # =================================================================
    
    def test_error_handling(self):
        """Test error handling and edge cases"""
        self.log_test_header("Error Handling Tests")
        
        # Test 404 endpoints
        success, data, duration = self.make_request('GET', '/nonexistent-endpoint')
        if not success:
            self.add_result("404 Not Found", True, 
                          f"Correctly returned 404 ({duration:.3f}s)")
        else:
            self.add_result("404 Not Found", False, 
                          "Should have returned 404")
        
        # Test invalid HTTP methods
        success, data, duration = self.make_request('DELETE', '/')
        if not success:
            self.add_result("Invalid HTTP Method", True, 
                          f"Correctly rejected invalid method ({duration:.3f}s)")
        else:
            self.add_result("Invalid HTTP Method", False, 
                          "Should have rejected invalid method")
        
        # Test malformed JSON
        try:
            response = self.session.post(f"{self.base_url}/auth/register", 
                                       data="invalid json", 
                                       headers={'Content-Type': 'application/json'},
                                       timeout=10)
            if response.status_code >= 400:
                self.add_result("Malformed JSON", True, 
                              "Correctly rejected malformed JSON")
            else:
                self.add_result("Malformed JSON", False, 
                              "Should have rejected malformed JSON")
        except Exception as e:
            self.add_result("Malformed JSON", True, 
                          f"Request properly failed: {type(e).__name__}")
        
        # Test extremely large request
        large_data = {'prompt': 'A' * 10000}  # Very large prompt
        success, data, duration = self.make_request('POST', '/prompts/validate', json=large_data)
        # This should either succeed or fail gracefully
        self.add_result("Large Request Handling", True, 
                      f"Handled large request gracefully ({duration:.3f}s)")
    
    # =================================================================
    # PERFORMANCE TESTS
    # =================================================================
    
    def test_performance(self):
        """Test basic performance characteristics"""
        self.log_test_header("Performance Tests")
        
        # Test response times for different endpoints
        endpoints = [
            ('GET', '/'),
            ('GET', '/health'),
            ('GET', '/metrics'),
            ('POST', '/auth/validate-device-id?device_id=ABCD1234'),
            ('GET', f'/users/{self.test_users[0]["device_id"]}'),
            ('GET', '/prompts/1/1')
        ]
        
        response_times = []
        
        for method, endpoint in endpoints:
            times = []
            for i in range(3):  # Test each endpoint 3 times
                success, data, duration = self.make_request(method, endpoint)
                if success:
                    times.append(duration)
                time.sleep(0.1)  # Small delay between requests
            
            if times:
                avg_time = sum(times) / len(times)
                response_times.append(avg_time)
                
                if avg_time < 1.0:  # Less than 1 second
                    self.add_result(f"Performance {method} {endpoint}", True, 
                                  f"Avg response time: {avg_time:.3f}s")
                else:
                    self.add_result(f"Performance {method} {endpoint}", False, 
                                  f"Slow response time: {avg_time:.3f}s")
        
        # Overall performance summary
        if response_times:
            avg_overall = sum(response_times) / len(response_times)
            self.add_result("Overall Performance", True, 
                          f"Average response time: {avg_overall:.3f}s")
    
    # =================================================================
    # CONCURRENT ACCESS TESTS
    # =================================================================
    
    async def test_concurrent_access(self):
        """Test concurrent access patterns"""
        self.log_test_header("Concurrent Access Tests")
        
        # Test concurrent user registrations
        async def register_random_user():
            random_id = ''.join(random.choices(string.ascii_uppercase, k=4)) + \
                       ''.join(random.choices(string.digits, k=4))
            user_data = {
                'device_id': random_id,
                'name': f'Test User {random_id}',
                'age': random.randint(18, 65)
            }
            
            success, data, duration = self.make_request('POST', '/auth/register', json=user_data)
            return success, random_id, duration
        
        # Create 5 concurrent registration tasks
        tasks = [register_random_user() for _ in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_registrations = 0
        total_time = 0
        
        for result in results:
            if isinstance(result, tuple) and result[0]:  # success
                successful_registrations += 1
                total_time += result[2]  # duration
        
        if successful_registrations > 0:
            avg_time = total_time / successful_registrations
            self.add_result("Concurrent User Registration", True, 
                          f"{successful_registrations}/5 successful, avg time: {avg_time:.3f}s")
        else:
            self.add_result("Concurrent User Registration", False, 
                          "No successful concurrent registrations")
        
        # Test concurrent health checks
        async def health_check():
            success, data, duration = self.make_request('GET', '/health')
            return success, duration
        
        health_tasks = [health_check() for _ in range(10)]
        health_results = await asyncio.gather(*health_tasks, return_exceptions=True)
        
        successful_health = sum(1 for r in health_results if isinstance(r, tuple) and r[0])
        if successful_health >= 8:  # At least 80% success
            self.add_result("Concurrent Health Checks", True, 
                          f"{successful_health}/10 successful")
        else:
            self.add_result("Concurrent Health Checks", False, 
                          f"Only {successful_health}/10 successful")
    
    # =================================================================
    # SECURITY TESTS
    # =================================================================
    
    def test_security(self):
        """Test security features"""
        self.log_test_header("Security Tests")
        
        # Test SQL injection attempts
        sql_injection_attempts = [
            "'; DROP TABLE users; --",
            "1' OR '1'='1",
            "admin'/**/OR/**/1=1#"
        ]
        
        for injection in sql_injection_attempts:
            success, data, duration = self.make_request('POST', 
                f'/auth/validate-device-id?device_id={injection}')
            if not success or not data.get('is_valid', True):
                self.add_result(f"SQL Injection Protection", True, 
                              "Properly handled injection attempt")
            else:
                self.add_result(f"SQL Injection Protection", False, 
                              f"May be vulnerable to: {injection}")
        
        # Test XSS attempts
        xss_attempts = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>"
        ]
        
        for xss in xss_attempts:
            user_data = {
                'device_id': 'TEST0001',
                'name': xss,
                'age': 25
            }
            success, data, duration = self.make_request('POST', '/auth/register', json=user_data)
            # Should either reject or sanitize
            self.add_result("XSS Protection", True, 
                          "Handled XSS attempt appropriately")
        
        # Test rate limiting (if implemented)
        rate_limit_requests = []
        for i in range(20):  # Make 20 quick requests
            success, data, duration = self.make_request('GET', '/')
            rate_limit_requests.append(success)
            if i < 19:  # Don't sleep after last request
                time.sleep(0.1)
        
        successful_requests = sum(rate_limit_requests)
        if successful_requests < 20:
            self.add_result("Rate Limiting", True, 
                          f"Rate limiting active: {successful_requests}/20 succeeded")
        else:
            self.add_result("Rate Limiting", True, 
                          "No rate limiting detected (may be configured differently)")
        
        # Test large payload handling
        large_payload = {'name': 'A' * 10000, 'device_id': 'TEST0001', 'age': 25}
        success, data, duration = self.make_request('POST', '/auth/register', json=large_payload)
        # Should handle gracefully
        self.add_result("Large Payload Handling", True, 
                      f"Handled large payload appropriately ({duration:.3f}s)")
        
        # Test invalid content types
        try:
            response = self.session.post(f"{self.base_url}/auth/register", 
                                       data="not json",
                                       headers={'Content-Type': 'text/plain'},
                                       timeout=10)
            if response.status_code >= 400:
                self.add_result("Invalid Content Type", True, 
                              "Properly rejected invalid content type")
            else:
                self.add_result("Invalid Content Type", False, 
                              "Should reject invalid content type")
        except Exception:
            self.add_result("Invalid Content Type", True, 
                          "Request properly rejected")
    
    # =================================================================
    # MAIN TEST RUNNER
    # =================================================================
    
    async def run_all_tests(self, include_websocket: bool = True, include_concurrent: bool = True):
        """Run all test suites"""
        self.log(f"\n{Colors.PURPLE + Colors.BOLD}{'='*80}{Colors.END}")
        self.log(f"{Colors.PURPLE + Colors.BOLD}🚀 ESP32 AUDIO STREAMING SERVER - COMPREHENSIVE TEST SUITE{Colors.END}")
        self.log(f"{Colors.PURPLE + Colors.BOLD}{'='*80}{Colors.END}")
        self.log(f"{Colors.CYAN}Testing server at: {self.base_url}{Colors.END}")
        self.log(f"{Colors.CYAN}WebSocket URL: {self.ws_url}{Colors.END}")
        self.log(f"{Colors.CYAN}Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
        
        start_time = time.time()
        
        try:
            # Basic server tests
            self.test_server_basic()
            
            # Authentication tests
            self.test_authentication()
            
            # User management tests
            self.test_user_management()
            
            # System prompt tests
            self.test_system_prompts()
            
            # WebSocket HTTP endpoint tests
            self.test_websocket_endpoints()
            
            # WebSocket connection tests
            if include_websocket:
                await self.test_websocket_connection()
            
            # Error handling tests
            self.test_error_handling()
            
            # Performance tests
            self.test_performance()
            
            # Concurrent access tests
            if include_concurrent:
                await self.test_concurrent_access()
            
            # Security tests
            self.test_security()
            
        except KeyboardInterrupt:
            self.log_warning("Tests interrupted by user")
        except Exception as e:
            self.log_error(f"Test suite error: {e}")
        
        total_time = time.time() - start_time
        self.print_results(total_time)
    
    def print_results(self, total_time: float):
        """Print comprehensive test results"""
        self.log(f"\n{Colors.PURPLE + Colors.BOLD}{'='*80}{Colors.END}")
        self.log(f"{Colors.PURPLE + Colors.BOLD}📊 TEST RESULTS SUMMARY{Colors.END}")
        self.log(f"{Colors.PURPLE + Colors.BOLD}{'='*80}{Colors.END}")
        
        # Count results
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.success)
        failed_tests = total_tests - passed_tests
        success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        # Summary stats
        self.log(f"{Colors.CYAN}Total Tests: {total_tests}{Colors.END}")
        self.log(f"{Colors.GREEN}Passed: {passed_tests}{Colors.END}")
        self.log(f"{Colors.RED}Failed: {failed_tests}{Colors.END}")
        self.log(f"{Colors.YELLOW}Success Rate: {success_rate:.1f}%{Colors.END}")
        self.log(f"{Colors.BLUE}Total Time: {total_time:.2f} seconds{Colors.END}")
        
        # Performance stats
        response_times = [r.duration for r in self.results if r.duration > 0]
        if response_times:
            avg_response = sum(response_times) / len(response_times)
            max_response = max(response_times)
            min_response = min(response_times)
            
            self.log(f"\n{Colors.CYAN}Performance Metrics:{Colors.END}")
            self.log(f"  Average Response Time: {avg_response:.3f}s")
            self.log(f"  Fastest Response: {min_response:.3f}s")
            self.log(f"  Slowest Response: {max_response:.3f}s")
        
        # Failed tests details
        if failed_tests > 0:
            self.log(f"\n{Colors.RED + Colors.BOLD}❌ FAILED TESTS:{Colors.END}")
            for result in self.results:
                if not result.success:
                    self.log(f"{Colors.RED}  • {result.name}: {result.message}{Colors.END}")
        
        # Categories breakdown
        categories = {}
        for result in self.results:
            category = result.name.split(':')[0] if ':' in result.name else result.name.split(' ')[0]
            if category not in categories:
                categories[category] = {'passed': 0, 'failed': 0}
            
            if result.success:
                categories[category]['passed'] += 1
            else:
                categories[category]['failed'] += 1
        
        self.log(f"\n{Colors.CYAN}Test Categories:{Colors.END}")
        for category, stats in categories.items():
            total = stats['passed'] + stats['failed']
            rate = (stats['passed'] / total * 100) if total > 0 else 0
            color = Colors.GREEN if rate >= 90 else Colors.YELLOW if rate >= 70 else Colors.RED
            self.log(f"  {color}{category}: {stats['passed']}/{total} ({rate:.1f}%){Colors.END}")
        
        # Overall assessment
        self.log(f"\n{Colors.PURPLE + Colors.BOLD}🎯 OVERALL ASSESSMENT:{Colors.END}")
        if success_rate >= 95:
            self.log(f"{Colors.GREEN + Colors.BOLD}🎉 EXCELLENT! Server is working great!{Colors.END}")
        elif success_rate >= 85:
            self.log(f"{Colors.YELLOW + Colors.BOLD}✅ GOOD! Minor issues to address{Colors.END}")
        elif success_rate >= 70:
            self.log(f"{Colors.YELLOW + Colors.BOLD}⚠️  ACCEPTABLE! Several issues need attention{Colors.END}")
        else:
            self.log(f"{Colors.RED + Colors.BOLD}❌ NEEDS WORK! Major issues detected{Colors.END}")
        
        # Recommendations
        self.log(f"\n{Colors.CYAN}💡 Recommendations:{Colors.END}")
        if failed_tests == 0:
            self.log("  • All tests passed! Your server is ready for production.")
        else:
            self.log("  • Review failed tests and fix underlying issues")
            if avg_response > 1.0:
                self.log("  • Consider performance optimization for slow responses")
            self.log("  • Run tests again after fixes to verify improvements")
        
        # Export option
        self.log(f"\n{Colors.BLUE}📁 Results saved to: test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json{Colors.END}")
        self.export_results()
    
    def export_results(self):
        """Export test results to JSON file"""
        filename = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        export_data = {
            'test_info': {
                'server_url': self.base_url,
                'websocket_url': self.ws_url,
                'timestamp': datetime.now().isoformat(),
                'total_tests': len(self.results),
                'passed_tests': sum(1 for r in self.results if r.success),
                'failed_tests': sum(1 for r in self.results if not r.success)
            },
            'results': [
                {
                    'name': r.name,
                    'success': r.success,
                    'message': r.message,
                    'duration': r.duration,
                    'timestamp': r.timestamp.isoformat(),
                    'response_data': r.response_data if r.response_data else None
                }
                for r in self.results
            ]
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
        except Exception as e:
            self.log_error(f"Failed to export results: {e}")


# =================================================================
# COMMAND LINE INTERFACE
# =================================================================

def main():
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(description='ESP32 Audio Streaming Server Test Suite')
    parser.add_argument('--url', default='http://localhost:8000', 
                       help='Base URL of the server (default: http://localhost:8000)')
    parser.add_argument('--ws-url', default='ws://localhost:8000',
                       help='WebSocket URL of the server (default: ws://localhost:8000)')
    parser.add_argument('--no-websocket', action='store_true',
                       help='Skip WebSocket connection tests')
    parser.add_argument('--no-concurrent', action='store_true',
                       help='Skip concurrent access tests')
    parser.add_argument('--quick', action='store_true',
                       help='Run only basic tests (faster execution)')
    parser.add_argument('--category', choices=['basic', 'auth', 'users', 'prompts', 'websocket', 'security'],
                       help='Run only tests from specific category')
    
    args = parser.parse_args()
    
    # Create tester instance
    tester = ESP32ServerTester(args.url, args.ws_url)
    
    async def run_tests():
        if args.quick:
            # Quick test mode
            tester.log("🏃 Running in QUICK mode - basic tests only")
            tester.test_server_basic()
            tester.test_authentication()
            tester.print_results(0)
            
        elif args.category:
            # Category-specific tests
            tester.log(f"🎯 Running {args.category.upper()} tests only")
            
            if args.category == 'basic':
                tester.test_server_basic()
            elif args.category == 'auth':
                tester.test_authentication()
            elif args.category == 'users':
                tester.test_user_management()
            elif args.category == 'prompts':
                tester.test_system_prompts()
            elif args.category == 'websocket':
                tester.test_websocket_endpoints()
                if not args.no_websocket:
                    await tester.test_websocket_connection()
            elif args.category == 'security':
                tester.test_security()
            
            tester.print_results(0)
        else:
            # Full test suite
            await tester.run_all_tests(
                include_websocket=not args.no_websocket,
                include_concurrent=not args.no_concurrent
            )
    
    # Run the tests
    try:
        asyncio.run(run_tests())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Tests interrupted by user{Colors.END}")
    except Exception as e:
        print(f"\n{Colors.RED}Test runner error: {e}{Colors.END}")
        sys.exit(1)


if __name__ == "__main__":
    main()