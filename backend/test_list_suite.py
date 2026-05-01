import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))
from ultronpro import external_benchmarks

def run():
    audit = getattr(external_benchmarks, 'list_suite', getattr(external_benchmarks, 'suite_audit', lambda: {}))()
    print(f"Suite Encontrada: {audit.get('suite')} (v{audit.get('version')})")
    print(f"Total de Casos Disponiveis: {audit.get('count')}")
    print("Benchmarks Identificados:")
    for bench, count in audit.get('benchmark_counts', {}).items():
        print(f" - {bench}: {count} itens")
    print("Familias:")
    for fam, count in audit.get('family_counts', {}).items():
        print(f" - {fam}: {count} itens")

if __name__ == '__main__':
    run()
