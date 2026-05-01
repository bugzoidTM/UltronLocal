import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

async def test_web_explorer():
    from ultronpro import web_browser
    
    print("=== Teste Web Explorer ===\n")
    
    topic = "emergent behaviors in large scale agentic systems"
    
    print(f"1. Busca DuckDuckGo: '{topic}'")
    search_res = web_browser.search_web(topic, top_k=3)
    print(f"   OK: {search_res.get('ok')}")
    print(f"   Resultados: {search_res.get('count')}")
    
    if search_res.get('ok') and search_res.get('items'):
        items = search_res['items']
        print(f"\n2. Resultados da busca:")
        for i, item in enumerate(items[:3], 1):
            print(f"   {i}. {item.get('title', 'N/A')[:50]}")
            print(f"      URL: {item.get('url', '')}")
        
        print(f"\n3. Navegando no primeiro link...")
        url = items[0]['url']
        browse_res = await web_browser.browse_url_playwright(url, timeout_ms=15000)
        print(f"   OK: {browse_res.get('ok')}")
        print(f"   Error: {browse_res.get('error', 'N/A')}")
        print(f"   Title: {browse_res.get('title', 'N/A')}")
        print(f"   Text chars: {len(browse_res.get('text', ''))}")
        print(f"   JSON-LD items: {len(browse_res.get('json_ld', []))}")
        
        if browse_res.get('ok'):
            print(f"\n=== Web Explorer FUNCIONAL ===")
            return True
    
    print(f"\n=== Web Explorer com PROBLEMAS ===")
    return False

if __name__ == "__main__":
    result = asyncio.run(test_web_explorer())
    sys.exit(0 if result else 1)
