"""
Swap atomico dos routers ultronbody e abstractions do main.py
"""
import re
import sys

path = r'f:\sistemas\UltronPro\backend\ultronpro\main.py'
with open(path, 'rb') as f:
    raw = f.read()

content = raw.decode('utf-8', errors='replace')

REPLACEMENT = '''
# ==================== ROUTERS IMPORT (ULTRONBODY / ABSTRACTIONS) ====================
from ultronpro.api.ultron_body import router as ultronbody_router
from ultronpro.api.abstractions import router as abstractions_router

app.include_router(ultronbody_router)
app.include_router(abstractions_router)

'''

# We want to replace from:
# @app.get('/api/ultronbody/status')
# Until the end of:
# @app.post('/api/ultronbody/benchmark-compare')
#     store.db.add_event(...)
#     return out

# Let's search using the literal string bounds in utf-8

start_marker = b"@app.get('/api/ultronbody/status')"
# Looking for the next route:
end_marker = b"@app.post('/api/plasticity/feedback')"

idx_start = raw.find(start_marker)
idx_end   = raw.find(end_marker)

if idx_start == -1 or idx_end == -1:
    print('ERRO: Marcadores nao encontrados.', idx_start, idx_end)
    exit(1)

new_raw = raw[:idx_start] + REPLACEMENT.encode('utf-8') + raw[idx_end:]

with open(path, 'wb') as f:
    f.write(new_raw)

print(f'Swapped routers successfully. Old len: {len(raw)}, New len: {len(new_raw)}')
