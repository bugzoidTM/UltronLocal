import sys, os, time, json
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

# Force environment loading
try:
    from dotenv import load_dotenv
    _env_path = Path("f:/sistemas/UltronPro/backend/.env")
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

from ultronpro import arc_hypothesis_guide

def main():
    print("=== ARC BENCHMARK: RODADAS SEQUENCIAIS (Minimização de Variância) ===")
    
    # Carrega tarefas
    pool_path = Path("f:/sistemas/UltronPro/backend/data/arc_pool_blind_20.json")
    if not pool_path.exists():
        print("Pool not found!")
        return
    
    with pool_path.open("r", encoding="utf-8") as f:
        tasks = json.load(f)
    
    results = []
    for round_num in [2, 3]:
        print(f"\n--- Iniciando Rodada {round_num} ---")
        t_start = time.time()
        # RODAR BENCHMARK (Isso chama guided_solve 20 vezes)
        # Observação: guided_solve já possui o cloud_fallback=True que ativamos
        report = arc_hypothesis_guide.run_benchmark(tasks, verbose=True)
        t_end = time.time()
        
        score = report.get('score', 0.0)
        solved = report.get('solved', 0)
        print(f"Rodada {round_num} Concluída | Score: {score} ({solved}/20) | Tempo: {int(t_end - t_start)}s")
        results.append(report)
        
        # Opcional: Salvar individualmente
        out_path = Path(f"f:/sistemas/UltronPro/backend/data/arc_round_{round_num}_report.json")
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    
    print("\n=== RESUMO FINAL DE RODADAS ===")
    for i, r in enumerate(results):
        print(f"Rodada {i+2}: {r.get('score')} ({r.get('solved')}/20)")

if __name__ == "__main__":
    main()
