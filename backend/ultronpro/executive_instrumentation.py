"""
Executive Instrumentation (Fase 6.1)
====================================

Métricas de alinhamento executivo e integridade operacional.
Monitora a relação entre metas (goals) e ações (actions).
"""

import json
from ultronpro import store

def get_executive_summary():
    """Calcula o snapshot de alinhamento executivo."""
    
    # 1. Alinhamento de Meta: Ações vinculadas a um goal_id vs Ações totais (últimas 100)
    actions = store.list_actions(limit=100)
    total_actions = len(actions)
    aligned_actions = 0
    
    for act in actions:
        meta = {}
        try:
            if act.get('meta_json'):
                meta = json.loads(act['meta_json'])
        except Exception:
            pass
        
        if meta.get('goal_id'):
            aligned_actions += 1
            
    alignment_score = (aligned_actions / total_actions) if total_actions > 0 else 1.0
    
    # 2. Eficiência de Execução: Reward médio das tentativas de goal
    # Precisamos de um método no store para pegar goal_attempts recentes
    try:
        with store._conn() as c:
            rows = c.execute("SELECT reward, duration_ms FROM goal_attempts ORDER BY id DESC LIMIT 20").fetchall()
            rewards = [float(r[0] or 0) for r in rows]
            avg_reward = sum(rewards) / len(rewards) if rewards else 0.0
    except Exception:
        avg_reward = 0.0

    # 3. Drift de Integridade: Itens não consumidos no workspace de canais críticos
    workspace = store.read_workspace(channels=['integrity.alert', 'causal.assessment'], limit=50)
    unconsumed = 0
    for it in workspace:
        consumed = json.loads(it.get('consumed_by_json') or '{}')
        if not consumed:
            unconsumed += 1
            
    integrity_drift = (unconsumed / len(workspace)) if workspace else 0.0

    summary = {
        "alignment_score": round(alignment_score, 4),
        "execution_efficiency": round(avg_reward, 4),
        "integrity_drift": round(integrity_drift, 4),
        "total_actions_analyzed": total_actions,
        "unconsumed_critical_items": unconsumed
    }
    
    # Publicar no Workspace
    store.publish_workspace(
        module='executive_instrumentation',
        channel='executive.metrics',
        payload_json=json.dumps(summary),
        salience=0.6,
        ttl_sec=3600
    )
    
    return summary

if __name__ == "__main__":
    print(get_executive_summary())
