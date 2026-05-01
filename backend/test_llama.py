import httpx
import json

url = "http://127.0.0.1:8080/completion"
payload = {"prompt": "Hello", "n_predict": 10, "temperature": 0.1}

print("Testing llama-server completion...")
with httpx.Client(timeout=30.0) as hc:
    r = hc.post(url, json=payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
