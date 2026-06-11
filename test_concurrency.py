import asyncio
import httpx

async def fetch(client):
    try:
        resp = await client.post('http://127.0.0.1:8000/api/skill-memory-bridge/run?dry_run=false&limit=5')
        return resp.json()
    except Exception as e:
        return {'error': str(e)}

async def main():
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [fetch(client) for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        real_runs = 0
        skipped_runs = 0
        errors = 0
        for r in results:
            if r.get('skipped') and r.get('reason') == 'bridge_already_running':
                skipped_runs += 1
            elif 'error' in r:
                errors += 1
            else:
                real_runs += 1
                
        print('Real runs:', real_runs)
        print('Skipped by lock:', skipped_runs)
        print('Errors:', errors)

asyncio.run(main())
