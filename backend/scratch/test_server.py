import httpx
import time

try:
    with httpx.Client(timeout=10.0) as client:
        print("Sending request...")
        with client.stream("POST", "http://127.0.0.1:8000/api/chat/stream", json={"message": "Oi", "session_id": "test_1"}) as response:
            print("Response status:", response.status_code)
            for line in response.iter_lines():
                print("Line:", line)
except Exception as e:
    print("Error:", e)
