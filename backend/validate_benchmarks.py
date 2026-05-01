import os
import sys
import json
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

def run_external_benchmarks():
    print(f"\n{'='*60}")
    print(" Executando Benchmarks Padronizados (ARC, MMLU, HellaSwag proxies)")
    print(f"{'='*60}")
    try:
        from ultronpro import external_benchmarks
        # Freeze a new baseline using local strategy without cloud dependencies
        print("Iniciando avaliação externa (isso pode levar alguns segundos)...")
        baseline = external_benchmarks.freeze_baseline(strategy='local')
        
        print("\n=== Resultado do Baseline ===")
        print(f"Run ID: {baseline.get('source_run_id')}")
        print(f"Suite: {baseline.get('suite')} v{baseline.get('version')}")
        print(f"Accuracy Geral: {baseline.get('overall_accuracy'):.2%}")
        print(f"Total Avaliado: {baseline.get('total')} casos")
        
        print("\n--- Por Benchmark ---")
        by_bench = baseline.get('by_benchmark', {})
        for b_name, b_data in by_bench.items():
            print(f"- {b_name}: {b_data.get('accuracy'):.2%} ({b_data.get('correct')}/{b_data.get('total')})")
            
        print("\n--- Por Família ---")
        by_fam = baseline.get('by_family', {})
        for f_name, f_data in by_fam.items():
            print(f"- {f_name}: {f_data.get('accuracy'):.2%} ({f_data.get('correct')}/{f_data.get('total')})")

        print("\n>>> PROVA CONCRETA: Baseline quantitativo de benchmarks padronizados estabelecido com sucesso.")
    except Exception as e:
        print(f"Erro ao executar benchmarks externos: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    run_external_benchmarks()
