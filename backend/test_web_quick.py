import asyncio
import sys
import os
from pathlib import Path

os.environ['ULTRON_WEB_EXPLORER'] = '1'
os.environ['PYTHONPATH'] = str(Path(__file__).resolve().parent)

sys.path.insert(0, str(Path(__file__).resolve().parent))

async def quick_test():
    from ultronpro import web_browser
    from ultronpro import llm
    
    print("=== Quick Web Explorer Test ===\n")
    
    print("1. Testing search_web...")
    result = web_browser.search_web("agi benchmark 2024", top_k=3)
    print(f"   Search OK: {result.get('ok')}")
    print(f"   Results: {result.get('count')}")
    
    if result.get('ok') and result.get('items'):
        print("\n2. Testing browse_url_playwright...")
        url = result['items'][0]['url']
        browse = await web_browser.browse_url_playwright(url, timeout_ms=15000)
        print(f"   Browse OK: {browse.get('ok')}")
        print(f"   Title: {browse.get('title', 'N/A')[:50]}")
        print(f"   Text chars: {len(browse.get('text', ''))}")
    
    print("\n3. Testing LLM call...")
    try:
        resp = await llm.complete("Qual é a capital do Brasil?", lane="lane_1_micro")
        print(f"   LLM OK: {resp.text[:50]}...")
    except Exception as e:
        print(f"   LLM FAILED: {e}")
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(quick_test())
