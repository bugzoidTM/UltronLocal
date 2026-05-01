import sys
import asyncio
from pathlib import Path
sys.path.append(str(Path.cwd()))
from ultronpro.main import _reasoning_engine

async def test():
    print("Testing Reasoning Engine (LightRAG)...")
    try:
        res = await _reasoning_engine("Quem é Gabriella Wright?", "quem é gabriella wright")
        print(f"Result: {res[:500]}...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
