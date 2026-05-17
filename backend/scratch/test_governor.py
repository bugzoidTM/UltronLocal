# -*- coding: utf-8 -*-
import sys
import os
import time
import httpx
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = "http://127.0.0.1:8000/api"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[96mINFO\033[0m"

def check(label, cond, detail=""):
    status = PASS if cond else FAIL
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail else ""))
    return cond

print("\n=== 8. TESTE DO GOVERNOR (Demotion de chat-intent-greeting) ===")
db_path = os.path.join(os.path.dirname(__file__), "..", "data", "ultron.db")
db_path = os.path.normpath(db_path)

print(f"  {INFO} Injetando 10 falhas recentes para chat-intent-greeting no banco de dados...")
try:
    conn = sqlite3.connect(db_path)
    ts = time.time()
    for i in range(10):
        conn.execute("INSERT INTO skill_execution_log(ts, skill_name, success, route, task, expected, output) VALUES(?, ?, 0, 'memory_bridge_exact', 'boa noite', 'Boa noite', 'Bom dia')", (ts + i, "chat-intent-greeting"))
    conn.commit()
    conn.close()
    check("Falhas injetadas com sucesso", True)
except Exception as e:
    check("Falha ao injetar erros no BD", False, str(e))

print(f"  {INFO} Executando skill-memory-governor/run...")
with httpx.Client(timeout=10) as c:
    r = c.post(f"{BASE}/skill-memory-governor/run?dry_run=false&limit=10")
    data = r.json()

demoted_skills = [d.get("skill") for d in data.get("details", []) if d.get("action") == "demoted"]
check("Governor detectou regressao", "chat-intent-greeting" in demoted_skills, f"Skills demovidas: {demoted_skills}")

with httpx.Client(timeout=10) as c:
    r = c.get(f"{BASE}/skills2/list")
    active_skills = [s.get("name") for s in r.json().get("skills", [])]
    
check("Skill nao esta mais na lista ativa (SKILL.md apagado)", "mem_chat_intent_greeting" not in active_skills)
