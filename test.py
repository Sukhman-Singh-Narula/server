import asyncio
import websockets
import json
import time

async def test_client():
    uri = "ws://localhost:8001/ws/ABCD1234"
    
    async with websockets.connect(uri) as websocket:
        print("✅ Connected to server")
        
        # Listen for messages
        while True:
            try:
                message = await websocket.recv()
                data = json.loads(message)
                print(f"📨 Received: {data.get('type')} - {data.get('message', '')}")
                
                # Respond to pings
                if data.get('type') in ['server_ping', 'setup_ping']:
                    pong = {"type": "client_pong", "timestamp": time.time()}
                    await websocket.send(json.dumps(pong))
                    print("🏓 Sent pong")
                    
            except websockets.exceptions.ConnectionClosed:
                print("🔌 Connection closed by server")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                break

if __name__ == "__main__":
    asyncio.run(test_client())