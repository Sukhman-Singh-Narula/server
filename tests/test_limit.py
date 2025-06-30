#!/usr/bin/env python3
"""
Enhanced test specifically for transcription and daily limits
"""

import asyncio
import websockets
import json
import time
import requests
import wave
import io
from typing import Dict, List, Optional
from datetime import datetime, date

class TranscriptionAndLimitTester:
    def __init__(self, base_url: str = "http://localhost:8001", ws_url: str = "ws://localhost:8001"):
        self.base_url = base_url
        self.ws_url = ws_url
        
    def create_real_audio_data(self, duration: float = 0.1, text_to_speak: str = "Hello, this is a test message") -> bytes:
        """Create actual PCM16 audio data (sine wave simulation)"""
        import math
        
        # This creates a sine wave with multiple frequencies to simulate speech
        sample_rate = 16000
        frequency = 440  # A4 note
        
        samples = int(sample_rate * duration)
        audio_data = bytearray()
        
        for i in range(samples):
            # Create sine wave with some variation to simulate speech
            t = i / sample_rate
            # Multiple frequencies to simulate speech complexity
            sample = int(16000 * (
                0.3 * math.sin(2 * math.pi * frequency * t) +
                0.2 * math.sin(2 * math.pi * (frequency * 1.5) * t) +
                0.1 * math.sin(2 * math.pi * (frequency * 0.5) * t)
            ))
            audio_data.extend(sample.to_bytes(2, byteorder='little', signed=True))
        
        return bytes(audio_data)

    async def test_daily_limits_comprehensive(self, device_id: str):
        """Comprehensive daily limit testing"""
        print(f"\n🔍 DAILY LIMITS TEST for {device_id}")
        print("=" * 50)
        
        # Step 1: Check initial state
        print("1️⃣ Checking initial daily limits...")
        initial_limits = await self.get_daily_limits(device_id)
        print(f"   Initial episodes played: {initial_limits.get('episodes_played_today', 0)}")
        print(f"   Can play episode: {initial_limits.get('can_play_episode', False)}")
        
        # Step 2: Test episode advancement loop
        print("\n2️⃣ Testing episode advancement until limit...")
        advancement_count = 0
        max_attempts = 5
        
        for attempt in range(max_attempts):
            print(f"\n   Attempt {attempt + 1}: Advancing episode...")
            
            # Check limits before attempt
            current_limits = await self.get_daily_limits(device_id)
            can_play = current_limits.get('can_play_episode', False)
            episodes_today = current_limits.get('episodes_played_today', 0)
            
            print(f"      Before: {episodes_today}/3 episodes, can_play={can_play}")
            
            if not can_play:
                print(f"      🚫 Cannot play more episodes (limit reached)")
                break
            
            # Try to advance
            success, response_code = await self.advance_episode(device_id)
            
            if success:
                advancement_count += 1
                print(f"      ✅ Episode advanced successfully ({advancement_count})")
            elif response_code == 429:
                print(f"      🚫 Daily limit exceeded (HTTP 429)")
                break
            else:
                print(f"      ❌ Episode advancement failed (HTTP {response_code})")
                break
            
            # Verify the change
            new_limits = await self.get_daily_limits(device_id)
            new_episodes = new_limits.get('episodes_played_today', 0)
            print(f"      After: {new_episodes}/3 episodes")
            
            # Small delay between attempts
            await asyncio.sleep(1)
        
        # Step 3: Verify final state
        print(f"\n3️⃣ Final verification...")
        final_limits = await self.get_daily_limits(device_id)
        final_episodes = final_limits.get('episodes_played_today', 0)
        final_can_play = final_limits.get('can_play_episode', False)
        
        print(f"   Total advancements: {advancement_count}")
        print(f"   Final episodes today: {final_episodes}/3")
        print(f"   Can still play: {final_can_play}")
        
        # Step 4: Test limit enforcement
        print(f"\n4️⃣ Testing limit enforcement...")
        if final_episodes >= 3:
            print("   Attempting to advance beyond limit...")
            success, response_code = await self.advance_episode(device_id)
            
            if response_code == 429:
                print("   ✅ Limit properly enforced (HTTP 429)")
            elif not success:
                print(f"   ✅ Limit enforced (failed with HTTP {response_code})")
            else:
                print("   ❌ Limit NOT enforced (advancement succeeded when it shouldn't)")
        
        # Test results summary
        print(f"\n📊 DAILY LIMITS TEST RESULTS:")
        print(f"   ✓ Episodes advanced: {advancement_count}")
        print(f"   ✓ Final count: {final_episodes}/3")
        print(f"   ✓ Limit enforced: {final_episodes <= 3}")
        
        return {
            "advancement_count": advancement_count,
            "final_episodes": final_episodes,
            "limit_enforced": final_episodes <= 3
        }

    async def test_transcription_comprehensive(self, device_id: str):
        """Comprehensive transcription testing"""
        print(f"\n🎤 TRANSCRIPTION TEST for {device_id}")
        print("=" * 50)
        
        # Step 1: Establish WebSocket connection
        print("1️⃣ Establishing WebSocket connection...")
        uri = f"{self.ws_url}/ws/{device_id}"
        
        try:
            async with websockets.connect(uri, ping_interval=None) as websocket:
                print("   ✅ WebSocket connected")
                
                # Step 2: Wait for setup
                print("\n2️⃣ Waiting for session setup...")
                session_info = await self.wait_for_session_setup(websocket)
                
                if not session_info:
                    print("   ❌ Session setup failed")
                    return {"success": False, "error": "Session setup failed"}
                
                print(f"   ✅ Session ready: S{session_info.get('season')}E{session_info.get('episode')}")
                session_id = session_info.get('session_id')
                
                # Step 3: Send audio and monitor transcription
                print("\n3️⃣ Sending audio data and monitoring transcription...")
                transcription_data = await self.send_audio_and_monitor(websocket, device_id)
                
                # Step 4: End session and verify storage
                print("\n4️⃣ Ending session and verifying storage...")
                await self.end_session_gracefully(websocket)
                
                # Wait for data to be saved
                await asyncio.sleep(3)
                
                # Step 5: Verify conversation storage
                print("\n5️⃣ Verifying conversation storage...")
                conversation_data = await self.verify_conversation_storage(device_id, session_id)
                
                # Test results
                print(f"\n📊 TRANSCRIPTION TEST RESULTS:")
                print(f"   ✓ Audio chunks sent: {transcription_data.get('audio_chunks_sent', 0)}")
                print(f"   ✓ Messages received: {transcription_data.get('messages_received', 0)}")
                print(f"   ✓ Conversation saved: {conversation_data.get('found', False)}")
                print(f"   ✓ Message count: {conversation_data.get('message_count', 0)}")
                print(f"   ✓ Session duration: {conversation_data.get('duration_minutes', 0)} minutes")
                
                return {
                    "success": True,
                    "audio_chunks_sent": transcription_data.get('audio_chunks_sent', 0),
                    "conversation_saved": conversation_data.get('found', False),
                    "message_count": conversation_data.get('message_count', 0)
                }
                
        except Exception as e:
            print(f"   ❌ WebSocket error: {e}")
            return {"success": False, "error": str(e)}

    async def wait_for_session_setup(self, websocket) -> Optional[Dict]:
        """Wait for session setup completion"""
        timeout = 30  # 30 seconds timeout
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=2)
                data = json.loads(message)
                msg_type = data.get('type')
                
                print(f"      📨 {msg_type}")
                
                if msg_type == "ready":
                    return data
                elif msg_type == "daily_limit_exceeded":
                    print(f"      🚫 {data.get('message')}")
                    return None
                elif msg_type in ["server_ping", "setup_ping"]:
                    # Respond to pings
                    pong = {"type": "client_pong", "timestamp": time.time()}
                    await websocket.send(json.dumps(pong))
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"      ❌ Setup error: {e}")
                return None
        
        print("      ⏰ Setup timeout")
        return None

    async def send_audio_and_monitor(self, websocket, device_id: str) -> Dict:
        """Send audio data and monitor for transcription responses"""
        import math
        
        audio_chunks_sent = 0
        messages_received = 0
        transcription_events = []
        
        # Create monitoring task
        async def monitor_messages():
            nonlocal messages_received, transcription_events
            
            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1)
                    data = json.loads(message)
                    msg_type = data.get('type')
                    
                    messages_received += 1
                    print(f"         📨 {msg_type}")
                    
                    # Log transcription-related messages
                    if 'transcription' in msg_type.lower() or 'response' in msg_type.lower():
                        transcription_events.append(data)
                        print(f"         🎯 Transcription event: {msg_type}")
                    
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
        
        # Send audio data
        print("      🎵 Sending audio chunks...")
        audio_duration = 10  # 10 seconds of audio
        chunk_interval = 0.1  # 100ms chunks
        chunks_to_send = int(audio_duration / chunk_interval)
        
        for chunk_num in range(chunks_to_send):
            try:
                # Create audio chunk (100ms of PCM16 data)
                audio_chunk = self.create_real_audio_data(duration=0.1)  # 100ms chunks
                
                await websocket.send(audio_chunk)
                audio_chunks_sent += 1
                
                if chunk_num % 10 == 0:  # Log every second
                    print(f"         Sent {chunk_num + 1}/{chunks_to_send} chunks...")
                
                await asyncio.sleep(chunk_interval)
                
            except Exception as e:
                print(f"         ❌ Audio send error: {e}")
                break
        
        # Stop monitoring
        monitor_task.cancel()
        
        print(f"      ✅ Audio sending complete: {audio_chunks_sent} chunks")
        print(f"      📨 Total messages received: {messages_received}")
        print(f"      🎯 Transcription events: {len(transcription_events)}")
        
        return {
            "audio_chunks_sent": audio_chunks_sent,
            "messages_received": messages_received,
            "transcription_events": len(transcription_events)
        }

    async def end_session_gracefully(self, websocket):
        """End session gracefully"""
        print("      🎯 Sending episode completion...")
        
        completion_message = {
            "type": "episode_complete",
            "current_season": 1,
            "current_episode": 1,
            "completion_reason": "transcription_test"
        }
        
        try:
            await websocket.send(json.dumps(completion_message))
            # Wait for response
            await asyncio.sleep(2)
        except Exception as e:
            print(f"      ❌ Completion error: {e}")

    async def verify_conversation_storage(self, device_id: str, session_id: str) -> Dict:
        """Verify that conversation was properly stored"""
        print("      🔍 Checking conversation storage...")
        
        try:
            # Get all conversations for device
            response = requests.get(f"{self.base_url}/conversations/{device_id}", timeout=10)
            
            if response.status_code != 200:
                print(f"      ❌ Failed to get conversations: {response.status_code}")
                return {"found": False}
            
            conversations = response.json()
            print(f"      📋 Found {len(conversations)} conversation sessions")
            
            # Look for our specific session
            target_session = None
            for conv in conversations:
                if conv.get('session_id') == session_id:
                    target_session = conv
                    break
            
            if not target_session:
                print(f"      ❌ Session {session_id[:8]}... not found in conversations")
                return {"found": False}
            
            print(f"      ✅ Session found: {target_session['message_count']} messages, "
                  f"{target_session['duration_minutes']} minutes")
            
            # Get detailed session data
            detail_response = requests.get(
                f"{self.base_url}/conversations/{device_id}/session/{session_id}", 
                timeout=10
            )
            
            if detail_response.status_code == 200:
                session_detail = detail_response.json()
                messages = session_detail.get('messages', [])
                
                print(f"      📝 Session details:")
                print(f"         Total messages: {len(messages)}")
                print(f"         User messages: {session_detail.get('user_message_count', 0)}")
                print(f"         AI messages: {session_detail.get('ai_message_count', 0)}")
                print(f"         System messages: {len([m for m in messages if m.get('type') == 'system_message'])}")
                
                # Show sample messages
                if messages:
                    print(f"      📋 Sample messages:")
                    for i, msg in enumerate(messages[:3]):
                        msg_type = msg.get('type', 'unknown')
                        content = msg.get('content', '')[:50] + "..." if len(msg.get('content', '')) > 50 else msg.get('content', '')
                        print(f"         {i+1}. {msg_type}: {content}")
                
                return {
                    "found": True,
                    "message_count": len(messages),
                    "duration_minutes": target_session['duration_minutes'],
                    "user_messages": session_detail.get('user_message_count', 0),
                    "ai_messages": session_detail.get('ai_message_count', 0)
                }
            else:
                print(f"      ⚠️ Could not get session details: {detail_response.status_code}")
                return {
                    "found": True,
                    "message_count": target_session['message_count'],
                    "duration_minutes": target_session['duration_minutes']
                }
                
        except Exception as e:
            print(f"      ❌ Storage verification error: {e}")
            return {"found": False, "error": str(e)}

    async def get_daily_limits(self, device_id: str) -> Dict:
        """Get current daily limits"""
        try:
            response = requests.get(f"{self.base_url}/users/{device_id}/daily-limits", timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to get daily limits: {response.status_code}")
                return {}
        except Exception as e:
            print(f"Daily limits error: {e}")
            return {}

    async def advance_episode(self, device_id: str) -> tuple[bool, int]:
        """Advance episode and return (success, status_code)"""
        try:
            response = requests.post(f"{self.base_url}/users/{device_id}/advance-episode", timeout=10)
            return response.status_code == 200, response.status_code
        except Exception as e:
            print(f"Episode advancement error: {e}")
            return False, 500



    async def register_test_user(self, device_id: str) -> bool:
        """Register a test user"""
        print(f"📝 Registering test user: {device_id}")
        
        registration_data = {
            "device_id": device_id,
            "name": "Sukh",
            "age": 25
        }
        
        try:
            response = requests.post(f"{self.base_url}/auth/register", json=registration_data, timeout=10)
            
            if response.status_code in [200, 201]:
                print("   ✅ User registered successfully")
                return True
            elif response.status_code == 409:
                print("   ℹ️ User already exists")
                return True
            else:
                print(f"   ❌ Registration failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"   ❌ Registration error: {e}")
            return False

    async def run_focused_tests(self, device_id: str = None):
        """Run focused tests on transcription and daily limits"""
        if device_id is None:
            import random
            import string
            device_id = ''.join(random.choices(string.ascii_uppercase, k=4)) + ''.join(random.choices(string.digits, k=4))
        
        print("🎯 FOCUSED TRANSCRIPTION & DAILY LIMITS TEST")
        print("=" * 60)
        print(f"Device ID: {device_id}")
        print(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        # Register user
        if not await self.register_test_user(device_id):
            print("❌ Cannot proceed without user registration")
            return
        
        # Test 1: Daily Limits
        daily_limit_results = await self.test_daily_limits_comprehensive(device_id)
        
        # Test 2: Transcription (only if we have episodes left)
        if daily_limit_results.get('final_episodes', 3) < 3:
            transcription_results = await self.test_transcription_comprehensive(device_id)
        else:
            print("\n🚫 Skipping transcription test - daily limit reached")
            transcription_results = {"success": False, "reason": "daily_limit_reached"}
        
        # Final summary
        print("\n" + "=" * 60)
        print("🏁 FINAL TEST RESULTS")
        print("=" * 60)
        print(f"Daily Limits Test:")
        print(f"   Episodes advanced: {daily_limit_results.get('advancement_count', 0)}")
        print(f"   Limit enforced: {daily_limit_results.get('limit_enforced', False)}")
        print(f"Transcription Test:")
        print(f"   Success: {transcription_results.get('success', False)}")
        print(f"   Audio chunks sent: {transcription_results.get('audio_chunks_sent', 0)}")
        print(f"   Conversation saved: {transcription_results.get('conversation_saved', False)}")
        print("=" * 60)


async def main():
    """Main test runner"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Focused Transcription & Daily Limits Test")
    parser.add_argument("--base-url", default="http://localhost:8001", help="Base URL")
    parser.add_argument("--ws-url", default="ws://localhost:8001", help="WebSocket URL")
    parser.add_argument("--device-id", help="Specific device ID to test")
    
    args = parser.parse_args()
    
    tester = TranscriptionAndLimitTester(args.base_url, args.ws_url)
    
    try:
        await tester.run_focused_tests(args.device_id)
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())