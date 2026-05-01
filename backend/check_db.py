import sys
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.append('F:/sistemas/UltronPro/backend')

import sqlite3
conn = sqlite3.connect('F:/sistemas/UltronPro/backend/data/ultron.db')

print('=== Recent Triples (subject contains AGI) ===')
cursor = conn.execute("SELECT subject, predicate, object, confidence FROM triples WHERE subject LIKE '%AGI%' OR object LIKE '%RLHF%' OR object LIKE '%DPO%' ORDER BY created_at DESC LIMIT 10")
for row in cursor:
    print(row)

print('\n=== Recent Insights (web_discovery) ===')
cursor = conn.execute("SELECT id, kind, title, created_at FROM insights WHERE kind='web_discovery' ORDER BY created_at DESC LIMIT 5")
for row in cursor:
    print(row)

print('\n=== Research Memories Count ===')
cursor = conn.execute("SELECT COUNT(*) FROM autobiographical_memories WHERE memory_type='research'")
print("Total:", cursor.fetchone()[0])

conn.close()
