import sys
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')

from ultronpro import settings, llm

s = settings.load_settings()
print("OpenRouter key:", repr(s.get('openrouter_api_key', '')))
print("Groq key:", repr(s.get('groq_api_key', '')))

# Test direct call to groq
import httpx

try:
    with httpx.Client(timeout=10.0) as hc:
        r = hc.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {s.get('groq_api_key')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Say hello"}],
                "max_tokens": 10
            }
        )
        print(f"Groq response: {r.status_code}")
        print(f"Content: {r.text[:200]}")
except Exception as e:
    print(f"Groq error: {e}")
