import sys, json, os, time
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro.visual_inductor import VisualInductor
from ultronpro.arc_executor import ARCExecutor

DATA_DIR = Path("f:/sistemas/UltronPro/backend/data")
ids = ["d0f5fe59", "6150a2bd", "e9614598", "44f52bb0", "1caeab9d"]

print("⚡ Teste Simbólico Puro (Depth 3 + Pruning) ⚡")

for pid in ids:
    path = DATA_DIR / f"novo_blind_{pid}.json"
    if not path.exists(): continue
    with open(path) as f: task = json.load(f)
    train, test = task['train'], task['test']
    
    t0 = time.time()
    plan = VisualInductor.infer_sequence(train, max_depth=3)
    dt = time.time() - t0
    
    if plan is not None:
        try:
            pred = ARCExecutor.execute_plan(test[0]['input'], plan)
            correct = (pred == test[0]['output'])
            status = "✅ ACERTOU" if correct else "⚠️ OVERFIT"
            print(f"- {pid}: {status} em {dt:.2f}s | Plan: {plan}")
        except Exception as e:
            print(f"- {pid}: ❌ ERRO EXEC {e} | Plan: {plan}")
    else:
        print(f"- {pid}: ❌ NÃO ENCONTRADO em {dt:.2f}s")
