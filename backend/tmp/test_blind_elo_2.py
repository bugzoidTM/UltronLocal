import sys, json, os
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro.visual_inductor import VisualInductor
from ultronpro.arc_executor import ARCExecutor

DATA_DIR = Path("f:/sistemas/UltronPro/backend/data")
UNSEEN_PIDS = ["0b148d64", "3bdb4ada", "4093f84a", "1f0c79e5", "2013d3e2"]

results = {}
total_solved = 0

print("🚀 Executando Teste Cego do Elo 2 (DSL de Objetos)...")

for pid in UNSEEN_PIDS:
    path = DATA_DIR / f"novo_{pid}.json"
    if not path.exists():
        print(f"⚠️ Arquivo {path.name} não encontrado.")
        continue
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    train = data.get('train', [])
    test = data.get('test', [])
    
    if not train or not test:
        print(f"⚠️ Tarefa {pid} sem exemplos.")
        continue

    # 1. Inferir sequência
    plan = VisualInductor.infer_sequence(train)
    
    # 2. Testar na tarefa de teste
    task_ok = True
    for t in test:
        try:
            pred = ARCExecutor.execute_plan(t['input'], plan)
            if pred == t['output']:
                pass
            else:
                task_ok = False
        except Exception:
            task_ok = False
    
    results[pid] = {
        "solved": task_ok,
        "plan": plan
    }
    if task_ok:
        total_solved += 1
        print(f"✅ {pid}: SOLVIDO {plan}")
    else:
        print(f"❌ {pid}: FALHOU")

print("\n--- RESUMO DO TESTE CEGO ---")
print(f"Score: {total_solved}/{len(UNSEEN_PIDS)} ({total_solved/len(UNSEEN_PIDS)*100}%)")
for pid, res in results.items():
    print(f"- {pid}: {'✅' if res['solved'] else '❌'} {res['plan']}")

if total_solved >= 2:
    print("\n🏆 VEREDITO: Elo 2 Validado! Generalização real detectada.")
else:
    print("\n⚠️ VEREDITO: Melhoria detectada, mas generalização ainda insuficiente.")
