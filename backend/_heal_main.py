"""Script to heal main.py from the duplicated router swap"""
import os

path = r'f:\sistemas\UltronPro\backend\ultronpro\main.py'
with open(path, 'rb') as f:
    raw = f.read()

REPLACEMENT = '''
# ==================== ROUTERS IMPORT (ULTRONBODY / ABSTRACTIONS) ====================
from ultronpro.api.ultron_body import router as ultronbody_router
from ultronpro.api.abstractions import router as abstractions_router

app.include_router(ultronbody_router)
app.include_router(abstractions_router)

'''

idx_rep = raw.find(b'# ==================== ROUTERS IMPORT (ULTRONBODY / ABSTRACTIONS)')
if idx_rep == -1:
    print('ERRO: REPLACEMENT marker nao encontrado')
    exit(1)

# Because I used string literal \n when swapping, I will replace it cleanly with utf-8
part1 = raw[:idx_rep]

idx_post = raw.find(b"@app.post('/api/causal-graph/ingest')")
if idx_post == -1:
    print('ERRO: post marker nao encontrado')
    exit(1)

new_raw = part1 + REPLACEMENT.encode('utf-8') + raw[idx_post:]

with open(path, 'wb') as f:
    f.write(new_raw)

print(f'MAIN CURADO! Original_bad: {len(raw)}, New_good: {len(new_raw)}')
