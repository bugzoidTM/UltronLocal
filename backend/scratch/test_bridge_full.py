# -*- coding: utf-8 -*-
"""
Bateria de testes da skill_memory_bridge.
Execute com: python backend/scratch/test_bridge_full.py
"""
import sys
import os
import time
import asyncio
import httpx
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = "http://127.0.0.1:8000/api"
LOCK_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "skill_memory_bridge_log.lock")
LOCK_FILE = os.path.normpath(LOCK_FILE)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[96mINFO\033[0m"

def check(label, cond, detail=""):
    status = PASS if cond else FAIL
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail else ""))
    return cond


# ── Teste 1: lock recente ─────────────────────────────────────────────────────
print("\n=== 1. LOCK RECENTE ===")
# Cria lock manualmente com mtime agora
open(LOCK_FILE, "w").close()
with httpx.Client(timeout=10) as c:
    r = c.post(f"{BASE}/skill-memory-bridge/run?dry_run=false&limit=5")
    data = r.json()
check("retorna skipped=True", data.get("skipped") is True, str(data.get("reason")))
check("reason=bridge_already_running", data.get("reason") == "bridge_already_running")
# Remove o lock para não bloquear próximos testes
try: os.unlink(LOCK_FILE)
except: pass


# ── Teste 2: lock orfão ───────────────────────────────────────────────────────
print("\n=== 2. LOCK ORFAO (> 5 min) ===")
# Cria lock com mtime há 6 minutos atrás
open(LOCK_FILE, "w").close()
old_time = time.time() - 370  # 370 segundos atrás
os.utime(LOCK_FILE, (old_time, old_time))
with httpx.Client(timeout=30) as c:
    r = c.post(f"{BASE}/skill-memory-bridge/run?dry_run=false&limit=5")
    data = r.json()
check("lock orfao: nao retornou skipped", data.get("skipped") is not True, str(data))
check("lock orfao: ok=True", data.get("ok") is True)
check("lock removido apos execucao", not os.path.exists(LOCK_FILE))


# ── Teste 3: dry_run com metricas separadas ───────────────────────────────────
print("\n=== 3. DRY_RUN COM METRICAS SEPARADAS ===")
with httpx.Client(timeout=30) as c:
    r = c.post(f"{BASE}/skill-memory-bridge/run?dry_run=true&limit=5")
    data = r.json()
check("dry_run=True no retorno", data.get("dry_run") is True)
check("materialized=0 no dry_run", data.get("materialized") == 0,
      f"materialized={data.get('materialized')}")
check("would_materialize existe", "would_materialize" in data,
      f"keys={list(data.keys())}")
print(f"  {INFO} would_materialize={data.get('would_materialize')} materialized={data.get('materialized')}")


# ── Teste 4: mem_* match exato ────────────────────────────────────────────────
print("\n=== 4. MEM_* MATCH EXATO ===")
with httpx.Client(timeout=20) as c:
    r = c.post(f"{BASE}/skills2/execute?skill_name=mem_chat_intent_greeting&task=ola+bom+dia")
    data = r.json()
check("ok=True", data.get("ok") is True)
check("skill=mem_chat_intent_greeting", data.get("skill_name") == "mem_chat_intent_greeting")
check("output nao vazio", bool(data.get("output")), str(data.get("output", ""))[:80])
print(f"  {INFO} tempo={data.get('execution_time_ms')}ms fonte=memory_bridge")


# ── Teste 5: mem_* match semantico ────────────────────────────────────────────
print("\n=== 5. MEM_* MATCH SEMANTICO ===")
with httpx.Client(timeout=20) as c:
    # Usa tarefa relacionada semanticamente mas com palavras diferentes
    r = c.post(f"{BASE}/skills2/execute?skill_name=mem_chat_intent_greeting&task=ei+tudo+bem+com+voce")
    data = r.json()
check("ok=True", data.get("ok") is True)
check("output nao vazio", bool(data.get("output")), str(data.get("output", ""))[:80])


# ── Teste 6: mem_* sem match (fallback LLM) ───────────────────────────────────
print("\n=== 6. MEM_* SEM MATCH -> FALLBACK LLM ===")
with httpx.Client(timeout=60) as c:
    # Skill que nao existe -> executor deve usar LLM sem travar
    r = c.post(f"{BASE}/skills2/execute?skill_name=mem_skill_inexistente_xyzabc123&task=teste+de+fallback")
    data = r.json()
check("nao travou (retornou)", True)
check("sem erro fatal", "error" not in data or data.get("ok") is not False,
      str(data.get("error", "")))
print(f"  {INFO} ok={data.get('ok')} status={data.get('status')} output={str(data.get('output', ''))[:60]}")


# ── Teste 7: persistencia apos restart ───────────────────────────────────────
print("\n=== 7. PERSISTENCIA APOS RESTART ===")
print(f"  {INFO} Verificando /api/skills2/list no servidor atual...")
with httpx.Client(timeout=10) as c:
    r = c.get(f"{BASE}/skills2/list")
    data = r.json()
mem_skills = [s for s in data.get("skills", []) if s.get("name", "").startswith("mem_")]
check("skills mem_* existem na lista", len(mem_skills) > 0,
      f"encontradas={len(mem_skills)}")
for s in mem_skills:
    print(f"  {INFO}  - {s['name']}")


# ── Resumo ─────────────────────────────────────────────────────────────────────
print("\n=== RESUMO: verificar lock e arquivo orfao ===")
if os.path.exists(LOCK_FILE):
    print(f"  [{FAIL}] lock file ainda existe: {LOCK_FILE}")
else:
    print(f"  [{PASS}] Nenhum lock file pendente.")
