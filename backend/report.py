import sqlite3
import json
import os
import sys

# Forçar output utf-8
sys.stdout.reconfigure(encoding='utf-8')

db_path = 'f:/sistemas/UltronPro/backend/data/ultron.db'
if not os.path.exists(db_path):
    print("No DB")
    sys.exit(0)

db = sqlite3.connect(db_path)
c = db.cursor()

def fetch(query):
    try:
        c.execute(query)
        return c.fetchall()
    except:
        return []

metrics = {}

# Quantidade de triplas extraídas
triples = fetch("SELECT source, COUNT(*) FROM triples GROUP BY source")
if not triples:
    triples = fetch("SELECT source, COUNT(*) FROM knowledge_triples GROUP BY source")
metrics['local_triples'] = dict(triples)

# Experiencias
exp = fetch("SELECT source, COUNT(*) FROM experiences GROUP BY source")
metrics['experiences'] = dict(exp)

print("METRICS:", json.dumps(metrics, indent=2))
db.close()

# web_explorer_log.jsonl
web_log = 'f:/sistemas/UltronPro/backend/data/web_explorer_log.jsonl'
web_events = []
if os.path.exists(web_log):
    lines = open(web_log, 'r', encoding='utf-8').read().splitlines()
    for ln in lines[-1000:]:
        try:
            web_events.append(json.loads(ln).get('type'))
        except: pass
    
    from collections import Counter
    print("WEB EVENTS:", dict(Counter(web_events)))

# Analisar llm_quarantine / provider health if any
for f in ['provider_health.json', 'llm_provider_quarantine.json']:
    p = 'f:/sistemas/UltronPro/backend/data/' + f
    if os.path.exists(p):
        print(f, file=sys.stdout)
        print(open(p, 'r', encoding='utf-8').read(), file=sys.stdout)
