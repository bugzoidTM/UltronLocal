import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from ultronpro import web_browser

async def test_browse():
    url = "https://duckduckgo.com"
    print(f"Browsing: {url}...")
    res = await web_browser.browse_url_playwright(url)
    
    if res.get('ok'):
        print(f"SUCCESS: Title = {res.get('title')}")
        print(f"HTML Length: {len(res.get('html', ''))}")
        print(f"Text chars: {len(res.get('text', ''))}")
    else:
        print(f"FAILED: {res.get('error')}")

if __name__ == "__main__":
    asyncio.run(test_browse())
