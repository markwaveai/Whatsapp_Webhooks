import asyncio
import sys
import json
import ssl

# Check if websockets is installed
try:
    import websockets
except ImportError:
    print("Error: 'websockets' library is required.")
    print("Install it with: pip install websockets")
    sys.exit(1)

async def test_connection(url):
    print(f"Connecting to {url}...")
    
    # Create SSL context for wss:// (Cloud Run uses HTTPS/WSS)
    ssl_context = None
    if url.startswith("wss://"):
        ssl_context = ssl.create_default_context()
        
    try:
        async with websockets.connect(url, ssl=ssl_context) as websocket:
            print("✅ Connection successful!")
            print("Listening for messages... (Ctrl+C to exit)")
            
            while True:
                message = await websocket.recv()
                print(f"📩 Received: {message}")
                
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_ws.py <websocket_url>")
        print("Example: python3 test_ws.py wss://your-service-url.a.run.app/ws")
        sys.exit(1)
        
    ws_url = sys.argv[1]
    
    try:
        asyncio.run(test_connection(ws_url))
    except KeyboardInterrupt:
        print("\nTest stopped.")
