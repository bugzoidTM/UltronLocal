"""
Swap atomico dos routers da cauda do main.py
"""
import re

path = r'f:\sistemas\UltronPro\backend\ultronpro\main.py'
with open(path, 'rb') as f:
    raw = f.read()

content = raw.decode('utf-8', errors='replace')

REPLACEMENT = '''
# ==================== ROUTERS IMPORT ====================
from ultronpro.api.self_healer import router as self_healer_router
from ultronpro.api.mental_sim import router as mental_sim_router
from ultronpro.api.benchmarks import router as benchmarks_router
from ultronpro.api.system_loops import router as system_loops_router

app.include_router(self_healer_router)
app.include_router(mental_sim_router)
app.include_router(benchmarks_router)
app.include_router(system_loops_router)

'''

# Começa no Code Self Healer, termina no final (Static UI)
start_marker = b'# ==================== CODE SELF-HEALER (FASE 14) ====================\r\n'
end_marker   = b'# --- Static UI ---\r\n'

idx_start = raw.find(start_marker)
idx_end   = raw.find(end_marker)

if idx_start == -1 or idx_end == -1:
    # try \n
    start_marker = b'# ==================== CODE SELF-HEALER (FASE 14) ====================\n'
    end_marker   = b'# --- Static UI ---\n'
    idx_start = raw.find(start_marker)
    idx_end   = raw.find(end_marker)

if idx_start == -1 or idx_end == -1:
    print('ERRO: Marcadores nao encontrados.')
    exit(1)

new_raw = raw[:idx_start] + REPLACEMENT.encode('utf-8') + raw[idx_end:]

with open(path, 'wb') as f:
    f.write(new_raw)

print(f'Swapped routers successfully. Old len: {len(raw)}, New len: {len(new_raw)}')
