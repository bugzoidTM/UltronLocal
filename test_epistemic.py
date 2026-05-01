import urllib.request
import urllib.error

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/docs", timeout=2) as res:
        print("GET /docs:", len(res.read()), "bytes")
except Exception as e:
    print("API Failed:", e)
