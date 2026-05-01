"""
Roadmap Auditor (Fase 6.2)
==========================

Analisa o arquivo ROADMAP_AGI_FRONTS.md e publica o progresso no Global Workspace.
Isso permite que o sistema tenha consciência de seu próprio desenvolvimento.
"""

import re
from pathlib import Path
from ultronpro import store

ROADMAP_PATH = Path(__file__).resolve().parent.parent.parent / 'ROADMAP_AGI_FRONTS.md'

def audit_roadmap():
    if not ROADMAP_PATH.exists():
        return {"error": "Roadmap file not found"}

    content = ROADMAP_PATH.read_text(encoding='utf-8')
    
    # Regex para encontrar tarefas e status
    # Ex: - [FEITO] 5.1 ...
    # Ex: - [EM ANDAMENTO 54%] 5.2 ...
    tasks = re.findall(r'- \[(FEITO|EM ANDAMENTO|PENDENTE)(?:\s+(\d+)%)?\]\s+([\d\.]+)\s+(.*)', content)
    
    total_tasks = len(tasks)
    done_tasks = sum(1 for t in tasks if t[0] == 'FEITO')
    in_progress = [t for t in tasks if t[0] == 'EM ANDAMENTO']
    
    # Cálculo de progresso médio
    progress_sum = done_tasks * 100
    for t in in_progress:
        progress_sum += int(t[1] or 0)
    
    avg_progress = (progress_sum / (total_tasks * 100)) if total_tasks > 0 else 0.0
    
    summary = {
        "total_tasks": total_tasks,
        "done": done_tasks,
        "avg_progress": round(avg_progress, 4),
        "last_milestone": tasks[-1][2] if tasks else "0.0",
        "critical_pending": [t[3] for t in tasks if t[0] != 'FEITO'][:5]
    }
    
    # Publica no Global Workspace com alta saliência
    try:
        store.publish_workspace(
            module='roadmap_auditor',
            channel='self.development_state',
            payload_json=__import__('json').dumps(summary, ensure_ascii=False),
            salience=0.7,
            ttl_sec=3600 # 1 hora
        )
    except Exception:
        pass
        
    return summary

if __name__ == "__main__":
    print(audit_roadmap())
