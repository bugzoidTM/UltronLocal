import sys, json, os, time
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro import arc_hypothesis_guide
from ultronpro import arc_executor

DATA_DIR = Path("f:/sistemas/UltronPro/backend/data")
BLIND_PIDS = ["d0f5fe59", "6150a2bd", "e9614598", "44f52bb0", "1caeab9d"]

results = []
solved_count = 0

print("🔍 Iniciando TESTE TOTALMENTE CEGO (Elo 2 + Fase 12)...")
print(f"Alvos: {BLIND_PIDS}")

for pid in BLIND_PIDS:
    path = DATA_DIR / f"novo_blind_{pid}.json"
    if not path.exists():
        continue
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    train = data.get('train', [])
    test = data.get('test', [])
    if not train or not test: continue

    print(f"\n--- Analisando {pid} ---")
    t0 = time.time()
    res = arc_hypothesis_guide.guided_solve(pid, train, test[0]['input'])
    
    correct = False
    if res.get('output_grid') == test[0]['output']:
        correct = True
        solved_count += 1

    dt = time.time() - t0
    res['graded_correct'] = correct
    res['elapsed_s'] = round(dt, 2)
    results.append(res)
    
    status = "✅ ACERTOU" if correct else "❌ FALHOU"
    method = res.get('method', 'unknown')
    hyp = res.get('winning_hypothesis')
    print(f"{status} | Método: {method} | Hipótese: {hyp} | Tempo: {dt:.1f}s")
    if not correct and res.get('diagnosis'):
        print(f"   Motivo: {res['diagnosis']}")

print("\n" + "="*40)
print(f"RESULTADO FINAL: {solved_count}/{len(BLIND_PIDS)} ({solved_count/len(BLIND_PIDS)*100}%)")
print("="*40)

# Resumo para a Regra de Verdade
resumo = [f"{r['task_id']}: {'✅' if r['graded_correct'] else '❌'} ({r['method']})" for r in results]
print("\n".join(resumo))
