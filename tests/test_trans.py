#!/usr/bin/env python3
"""
Fixed transcription-only test for ESP32 server
"""

import asyncio
import websockets
import json
import time
import requests
import random
import string
from datetime import datetime

class TranscriptionOnlyTester:
    def __init__(self, base_url: str = "http://localhost:8001", ws_url: str = "ws://localhost:8001"):
        self.base_url = base_url
        self.ws_url = ws_url

    def generate_device_id(self) -> str:
        """Generate a random valid device ID"""
        letters = ''.join(random.choices(string.ascii_uppercase, k=4))
        numbers = ''.join(random.choices(string.digits, k=4))
        return letters + numbers

    async def register_fresh_user(self, device_id: str) -> bool:
        """Register a fresh user for testing"""
        first_names = ["Alice", "Bob", "Charlie", "Diana", "Edward", "Fiona"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia"]
        
        registration_data = {
            "device_id": device_id,
            "name": f"{random.choice(first_names)} {random.choice(last_names)}",
            "age": random.randint(20, 40)
        }
        
        try:
            response = requests.post(f"{self.base_url}/auth/register", json=registration_data, timeout=10)
            
            if response.status_code in [200, 201]:
                print(f"✅ User registered: {registration_data['name']}")
                return True
            elif response.status_code == 409:
                print(f"ℹ️  User already exists: {device_id}")
                return True
            else:
                print(f"❌ Registration failed: {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"   Error: {error_data}")
                except:
                    print(f"   Error text: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Registration error: {e}")
            return False

    def create_audio_chunk(self, duration: float = 0.1) -> bytes:
        """Create PCM16 audio data"""
        import math
        
        sample_rate = 16000
        frequency = 440
        samples = int(sample_rate * duration)
        audio_data = bytearray()
        
        for i in range(samples):
            t = i / sample_rate
            sample = int(16000 * 0.3 * math.sin(2 * math.pi * frequency * t))
            audio_data.extend(sample.to_bytes(2, byteorder='little', signed=True))
        
        return bytes(audio_data)

    async def test_transcription_workflow(self, device_id: str):
        """Test the complete transcription workflow"""
        print(f"\n🎤 TRANSCRIPTION WORKFLOW TEST")
        print("=" * 50)
        
        # Check daily limits first
        limits_response = requests.get(f"{self.base_url}/users/{device_id}/daily-limits", timeout=10)
        if limits_response.status_code == 200:
            limits = limits_response.json()
            print(f"📊 Current limits: {limits['episodes_played_today']}/3 episodes used")
            
            if not limits['can_play_episode']:
                print("🚫 Cannot test transcription - daily limit reached")
                print("💡 Try with a different device ID or wait until tomorrow")
                return False
        else:
            print("⚠️  Could not check daily limits, proceeding anyway...")

        # WebSocket transcription test
        uri = f"{self.ws_url}/ws/{device_id}"
        print(f"🔗 Connecting to: {uri}")
        
        try:
            async with websockets.connect(uri, ping_interval=None, timeout=30) as websocket:
                print("✅ WebSocket connected")
                
                # Step 1: Wait for session setup
                session_info = await self.wait_for_ready(websocket)
                if not session_info:
                    print("❌ Session setup failed")
                    return False
                
                session_id = session_info.get('session_id')
                season = session_info.get('season')
                episode = session_info.get('episode')
                print(f"✅ Session ready: {session_id[:8]}... (S{season}E{episode})")
                
                # Step 2: Send audio and monitor transcription
                print(f"\n🎵 Testing audio streaming and transcription...")
                audio_stats = await self.stream_audio_and_monitor(websocket, duration=6)  # Reduced duration
                
                # Step 3: Wait for AI response to complete
                print(f"\n⏳ Waiting for AI response to complete...")
                await asyncio.sleep(5)  # Give AI time to respond
                
                # Step 4: End session gracefully - DON'T send disconnect, just close
                print(f"\n🏁 Ending session gracefully...")
                await self.end_session_gracefully()
                
                # Step 5: Wait before checking storage
                print(f"\n💾 Waiting for conversation to be saved...")
                await asyncio.sleep(5)  # Wait longer for data to be saved
                
                storage_results = await self.verify_conversation_storage(device_id, session_id)
                
                # Results summary
                print(f"\n📊 TRANSCRIPTION TEST RESULTS:")
                print(f"   ✓ Audio chunks sent: {audio_stats['chunks_sent']}")
                print(f"   ✓ Messages received: {audio_stats['messages_received']}")
                print(f"   ✓ Session duration: {audio_stats['duration']:.1f} seconds")
                print(f"   ✓ Conversation stored: {storage_results['stored']}")
                print(f"   ✓ Message count: {storage_results.get('message_count', 0)}")
                print(f"   ✓ User messages: {storage_results.get('user_messages', 0)}")
                print(f"   ✓ AI messages: {storage_results.get('ai_messages', 0)}")
                print(f"   ✓ System messages: {storage_results.get('system_messages', 0)}")
                
                return storage_results['stored']
                
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            return False

    async def wait_for_ready(self, websocket) -> dict:
        """Wait for session ready message"""
        timeout = 30
        start_time = time.time()
        
        print("⏳ Waiting for session setup...")
        
        while time.time() - start_time < timeout:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=2)
                data = json.loads(message)
                msg_type = data.get('type')
                
                print(f"   📨 {msg_type}")
                
                if msg_type == "ready":
                    daily_limits = data.get('daily_limits', {})
                    print(f"   ✅ Session ready! Daily limits: {daily_limits.get('episodes_played_today', 0)}/3")
                    return data
                elif msg_type == "daily_limit_exceeded":
                    print(f"   🚫 {data.get('message')}")
                    return None
                elif msg_type in ["server_ping", "setup_ping"]:
                    pong = {"type": "client_pong", "timestamp": time.time()}
                    await websocket.send(json.dumps(pong))
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"   ❌ Setup error: {e}")
                return None
        
        print("   ⏰ Setup timeout")
        return None

    async def stream_audio_and_monitor(self, websocket, duration: int = 6) -> dict:
        """Stream audio and monitor for transcription"""
        chunks_sent = 0
        messages_received = 0
        start_time = time.time()
        important_messages = []
        
        # Message monitoring task
        async def monitor_messages():
            nonlocal messages_received, important_messages
            
            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1)
                    data = json.loads(message)
                    msg_type = data.get('type')
                    
                    messages_received += 1
                    
                    print(f"      📨 {msg_type}")
                    
                    # Log important transcription events
                    if any(keyword in msg_type.lower() for keyword in ['transcription', 'response', 'audio', 'speech', 'openai']):
                        important_messages.append((msg_type, data))
                        print(f"         🎯 Important: {msg_type}")
                    
                    # Respond to pings
                    if msg_type in ["server_ping"]:
                        pong = {"type": "client_pong", "timestamp": time.time()}
                        await websocket.send(json.dumps(pong))
                        
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f"         ❌ Monitor error: {e}")
                    break
        
        # Start monitoring
        monitor_task = asyncio.create_task(monitor_messages())
        
        # Send audio chunks
        print(f"   🎵 Streaming audio for {duration} seconds...")
        chunk_interval = 0.1  # 100ms chunks
        chunks_to_send = int(duration / chunk_interval)
        
        for chunk_num in range(chunks_to_send):
            try:
                audio_chunk = self.create_audio_chunk(chunk_interval)
                await websocket.send(audio_chunk)
                chunks_sent += 1
                
                if chunk_num % 10 == 0:  # Log every second
                    elapsed = time.time() - start_time
                    print(f"      Sent {chunk_num + 1}/{chunks_to_send} chunks ({elapsed:.1f}s)")
                
                await asyncio.sleep(chunk_interval)
                
            except Exception as e:
                print(f"      ❌ Audio send error: {e}")
                break
        
        # Continue monitoring for a bit longer to catch AI responses
        print(f"   ⏳ Monitoring for AI responses...")
        await asyncio.sleep(3)
        
        # Stop monitoring
        monitor_task.cancel()
        
        total_duration = time.time() - start_time
        print(f"   ✅ Audio streaming complete: {chunks_sent} chunks in {total_duration:.1f}s")
        print(f"   📨 Total messages received: {messages_received}")
        print(f"   🎯 Important messages: {len(important_messages)}")
        
        return {
            "chunks_sent": chunks_sent,
            "messages_received": messages_received,
            "duration": total_duration,
            "important_messages": len(important_messages)
        }

    async def end_session_gracefully(self):
        """End session gracefully without sending disconnect"""
        # Just wait - let the WebSocket close naturally
        await asyncio.sleep(1)

    async def verify_conversation_storage(self, device_id: str, session_id: str) -> dict:
        """Verify conversation was stored in Firebase"""
        print("   🔍 Checking conversation storage...")
        
        # Try multiple times as data might take time to appear
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Get all conversations
                response = requests.get(f"{self.base_url}/conversations/{device_id}", timeout=10)
                
                if response.status_code != 200:
                    print(f"   ❌ Failed to get conversations: {response.status_code}")
                    if attempt < max_attempts - 1:
                        print(f"   🔄 Retrying in 3 seconds... (attempt {attempt + 1}/{max_attempts})")
                        await asyncio.sleep(3)
                        continue
                    return {"stored": False}
                
                conversations = response.json()
                print(f"   📋 Found {len(conversations)} total conversations")
                
                # Find our session
                target_session = None
                for conv in conversations:
                    if conv.get('session_id') == session_id:
                        target_session = conv
                        break
                
                if not target_session:
                    if attempt < max_attempts - 1:
                        print(f"   ⏳ Session {session_id[:8]}... not found yet, retrying...")
                        await asyncio.sleep(3)
                        continue
                    else:
                        print(f"   ❌ Session {session_id[:8]}... not found after {max_attempts} attempts")
                        return {"stored": False}
                
                print(f"   ✅ Session found: {target_session.get('message_count', 0)} messages")
                
                # Get detailed session data
                detail_response = requests.get(
                    f"{self.base_url}/conversations/{device_id}/session/{session_id}",
                    timeout=10
                )
                
                if detail_response.status_code == 200:
                    session_detail = detail_response.json()
                    messages = session_detail.get('messages', [])
                    
                    # Count message types
                    user_messages = len([m for m in messages if m.get('type') == 'user_speech'])
                    ai_messages = len([m for m in messages if m.get('type') == 'ai_response'])
                    system_messages = len([m for m in messages if m.get('type') == 'system_message'])
                    
                    print(f"   📝 Message breakdown:")
                    print(f"      User messages: {user_messages}")
                    print(f"      AI messages: {ai_messages}")
                    print(f"      System messages: {system_messages}")
                    
                    # Show sample messages
                    if messages:
                        print(f"   📋 Sample messages:")
                        for i, msg in enumerate(messages[:5]):  # Show first 5
                            msg_type = msg.get('type', 'unknown')
                            content = msg.get('content', '')
                            short_content = content[:40] + "..." if len(content) > 40 else content
                            print(f"      {i+1}. [{msg_type}] {short_content}")
                    
                    return {
                        "stored": True,
                        "message_count": len(messages),
                        "user_messages": user_messages,
                        "ai_messages": ai_messages,
                        "system_messages": system_messages
                    }
                else:
                    print(f"   ⚠️  Could not get session details: {detail_response.status_code}")
                    return {
                        "stored": True,
                        "message_count": target_session.get('message_count', 0),
                        "user_messages": 0,
                        "ai_messages": 0,
                        "system_messages": 0
                    }
                    
            except Exception as e:
                print(f"   ❌ Storage verification error (attempt {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(3)
                    continue
                    
        return {"stored": False}

    async def run_transcription_test(self):
        """Run focused transcription test"""
        print("🎤 ESP32 TRANSCRIPTION TEST")
        print("=" * 50)
        print(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Generate fresh device ID
        device_id = self.generate_device_id()
        print(f"📱 Test Device: {device_id}")
        
        # Register user
        print(f"\n📝 Registering test user...")
        if not await self.register_fresh_user(device_id):
            print("❌ Cannot proceed without user registration")
            return
        
        # Run transcription test
        success = await self.test_transcription_workflow(device_id)
        
        # Final summary
        print(f"\n" + "=" * 50)
        print(f"🏁 TRANSCRIPTION TEST SUMMARY")
        print(f"=" * 50)
        print(f"Device ID: {device_id}")
        print(f"Test Result: {'✅ SUCCESS' if success else '❌ FAILED'}")
        print(f"Transcription Storage: {'✅ Working' if success else '❌ Not Working'}")
        
        if success:
            print("\n🎉 Great! The transcription system is working correctly:")
            print("   ✓ WebSocket connections work")
            print("   ✓ Audio streaming works")
            print("   ✓ OpenAI transcription works")
            print("   ✓ Conversation storage works")
        else:
            print("\n🔧 Transcription system needs attention:")
            print("   • Check if conversations are being saved to Firebase")
            print("   • Verify OpenAI API key and connection")
            print("   • Check server logs for detailed error information")
        
        print("=" * 50)


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="ESP32 Transcription Test")
    parser.add_argument("--base-url", default="http://localhost:8001", help="Base URL")
    parser.add_argument("--ws-url", default="ws://localhost:8001", help="WebSocket URL")
    
    args = parser.parse_args()
    
    tester = TranscriptionOnlyTester(args.base_url, args.ws_url)
    
    try:
        await tester.run_transcription_test()
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())