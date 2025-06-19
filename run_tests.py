#!/usr/bin/env python3
"""
Simple test runner script for ESP32 Audio Streaming Server
Provides easy-to-use interface for running tests with different configurations
"""

import subprocess
import sys
import time
import requests
from pathlib import Path

def check_server_running(url: str = "http://localhost:8000", timeout: int = 5) -> bool:
    """Check if server is running and healthy"""
    try:
        # First check if server responds at all
        response = requests.get(f"{url}/", timeout=timeout)
        if response.status_code == 200:
            print(f"✅ Server is responding at {url}")
            
            # Check health endpoint
            health_response = requests.get(f"{url}/health", timeout=timeout)
            if health_response.status_code == 200:
                print("✅ Server is healthy")
                return True
            else:
                print(f"⚠️  Server responding but health check failed: {health_response.status_code}")
                print("   This might be due to missing Firebase configuration.")
                
                # Ask user if they want to continue anyway
                response = input("   Continue with tests anyway? [y/N]: ")
                return response.lower() in ['y', 'yes']
        else:
            return False
            
    except requests.exceptions.ConnectionError:
        return False
    except Exception as e:
        print(f"   Error checking server: {e}")
        return False

def wait_for_server(url: str = "http://localhost:8000", max_wait: int = 30):
    """Wait for server to start"""
    print(f"⏳ Waiting for server at {url}...")
    
    for i in range(max_wait):
        if check_server_running(url):
            print(f"✅ Server is running!")
            return True
        
        print(f"   Attempt {i+1}/{max_wait}... ", end="", flush=True)
        time.sleep(1)
        print("❌")
    
    print(f"❌ Server not responding after {max_wait} seconds")
    return False

def run_test_command(command: list):
    """Run test command and return success status"""
    try:
        print(f"🚀 Running: {' '.join(command)}")
        result = subprocess.run(command, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Test failed with exit code: {e.returncode}")
        return False
    except FileNotFoundError:
        print("❌ test_endpoints.py not found. Make sure you're in the correct directory.")
        return False

def main():
    """Main test runner"""
    print("🧪 ESP32 Audio Streaming Server - Test Runner")
    print("=" * 50)
    
    # Check if test file exists
    if not Path("test_endpoints.py").exists():
        print("❌ test_endpoints.py not found!")
        print("   Make sure you're running this from the project root directory.")
        sys.exit(1)
    
    # Check for different ports
    ports_to_check = [8001]
    server_url = None
    
    for port in ports_to_check:
        test_url = f"http://localhost:{port}"
        print(f"🔍 Checking {test_url}...")
        
        if check_server_running(test_url):
            server_url = test_url
            break
    
    if not server_url:
        print("❌ No server found on common ports!")
        print("   Checked ports: 8000, 8001, 8002, 3000")
        print()
        print("💡 Solutions:")
        print("   1. Start the server:")
        print("      python main.py")
        print("      python main_fixed.py")
        print()
        print("   2. Or run the health diagnostic:")
        print("      python debug_health.py")
        
        # Ask for custom URL
        custom_url = input("\n🔧 Enter custom server URL (or press Enter to exit): ").strip()
        if custom_url:
            if check_server_running(custom_url):
                server_url = custom_url
            else:
                print(f"❌ Server not responding at {custom_url}")
                sys.exit(1)
        else:
            sys.exit(1)
    
    print(f"✅ Using server at: {server_url}")
    
    # Extract WebSocket URL
    ws_url = server_url.replace('http://', 'ws://').replace('https://', 'wss://')
    
    # Test menu
    while True:
        print("\n🎯 Test Options:")
        print("1. 🏃 Quick Test (basic functionality)")
        print("2. 🔍 Full Test Suite (comprehensive)")
        print("3. 🧪 Basic Server Tests")
        print("4. 🔐 Authentication Tests")
        print("5. 👥 User Management Tests")
        print("6. 📝 System Prompt Tests")
        print("7. 🌐 WebSocket Tests")
        print("8. 🛡️  Security Tests")
        print("9. ⚡ Performance Tests")
        print("10. 🔧 Custom Test")
        print("0. ❌ Exit")
        
        choice = input("\n📋 Select test option (0-10): ").strip()
        
        if choice == "0":
            print("👋 Goodbye!")
            break
        
        elif choice == "1":
            # Quick test
            success = run_test_command(["python", "test_endpoints.py", "--quick", "--url", server_url])
            
        elif choice == "2":
            # Full test suite
            print("⚠️  This will run all tests including WebSocket and concurrent tests.")
            print("   This may take several minutes.")
            confirm = input("Continue? [y/N]: ")
            if confirm.lower() in ['y', 'yes']:
                success = run_test_command(["python", "test_endpoints.py", "--url", server_url, "--ws-url", ws_url])
            else:
                continue
                
        elif choice == "3":
            # Basic tests
            success = run_test_command(["python", "test_endpoints.py", "--category", "basic", "--url", server_url])
            
        elif choice == "4":
            # Auth tests
            success = run_test_command(["python", "test_endpoints.py", "--category", "auth", "--url", server_url])
            
        elif choice == "5":
            # User tests
            success = run_test_command(["python", "test_endpoints.py", "--category", "users", "--url", server_url])
            
        elif choice == "6":
            # Prompt tests
            success = run_test_command(["python", "test_endpoints.py", "--category", "prompts", "--url", server_url])
            
        elif choice == "7":
            # WebSocket tests
            success = run_test_command(["python", "test_endpoints.py", "--category", "websocket", "--url", server_url, "--ws-url", ws_url])
            
        elif choice == "8":
            # Security tests
            success = run_test_command(["python", "test_endpoints.py", "--category", "security", "--url", server_url])
            
        elif choice == "9":
            # Performance tests (run basic + performance)
            print("🏃 Running performance-focused tests...")
            success = run_test_command(["python", "test_endpoints.py", "--category", "basic", "--url", server_url])
            
        elif choice == "10":
            # Custom test
            print("\n🔧 Custom Test Options:")
            print("Available flags:")
            print("  --url <URL>          Server URL")
            print("  --ws-url <URL>       WebSocket URL")
            print("  --no-websocket       Skip WebSocket tests")
            print("  --no-concurrent      Skip concurrent tests")
            print("  --quick              Run only basic tests")
            print("  --category <cat>     Run specific category")
            
            custom_args = input("\nEnter additional arguments: ").strip()
            cmd = ["python", "test_endpoints.py", "--url", server_url, "--ws-url", ws_url]
            if custom_args:
                cmd.extend(custom_args.split())
            success = run_test_command(cmd)
                
        else:
            print("❌ Invalid choice. Please select 0-10.")
            continue
        
        # Show result
        if success:
            print(f"\n✅ Tests completed successfully!")
        else:
            print(f"\n❌ Some tests failed. Check the output above for details.")
        
        # Ask to continue
        if choice != "0":
            input("\n⏎ Press Enter to continue...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Test runner interrupted. Goodbye!")
    except Exception as e:
        print(f"\n❌ Test runner error: {e}")
        sys.exit(1)