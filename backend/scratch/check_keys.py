import urllib.request
import urllib.error
import json

def test_key(name, url, headers, body):
    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as res:
            print(f"{name}: {res.getcode()} OK")
    except urllib.error.HTTPError as e:
        content = e.read().decode('utf-8', errors='ignore')
        print(f"{name}: {e.code} {content[:200]}")
    except Exception as e:
        print(f"{name}: Error {e}")

keys = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "headers": {
            "Authorization": "Bearer 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",
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1
        }).encode('utf-8')
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "headers": {
            "Authorization": "Bearer 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",
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "model": "google/gemma-2-9b-it:free",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1
        }).encode('utf-8')
    },
    "nvidia": {
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "headers": {
            "Authorization": "Bearer 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",
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "model": "meta/llama-3.1-8b-instruct",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1
        }).encode('utf-8')
    },
    "github": {
        "url": "https://models.inference.ai.azure.com/chat/completions",
        "headers": {
            "Authorization": "Bearer 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",
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1
        }).encode('utf-8')
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=AIzaSyAsBSMVCiOwDbxTKuY27zLXv06rS-ucJLU",
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "contents": [{"parts": [{"text": "hi"}]}]
        }).encode('utf-8')
    }
}

for name, data in keys.items():
    test_key(name, data["url"], data["headers"], data["body"])
