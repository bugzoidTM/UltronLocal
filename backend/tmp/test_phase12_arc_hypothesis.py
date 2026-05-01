"""
test_phase12_arc_hypothesis.py
==============================
Executa o benchmark Fase 12 com o pool de 20 tarefas ARC cego.
Produz:
  - Score: X/20
  - Por tarefa: qual hipótese ganhou, quantas foram testadas
  - Diagnóstico: llm_hypothesis_gap vs primitive_gap vs solved
"""
import sys, json, os
from pathlib import Path
try:
    from dotenv import load_dotenv
    _env_path = Path("f:/sistemas/UltronPro/backend/.env")
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro.arc_hypothesis_guide import run_benchmark

ARC_POOL_PATH = Path("f:/sistemas/UltronPro/backend/data/arc_pool_blind_20.json")
FALLBACK_PATHS = [
    Path("f:/sistemas/UltronPro/backend/data/arc_tasks"),
    Path("f:/sistemas/UltronPro/backend/data/real_arc_inductive_report.json"),
]
REPORT_PATH = Path("f:/sistemas/UltronPro/backend/data/arc_phase12_report.json")


def load_tasks() -> list[dict]:
    """Tenta carregar o pool cego. Se não existir, monta do relatório anterior."""
    if ARC_POOL_PATH.exists():
        data = json.loads(ARC_POOL_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "tasks" in data:
            return data["tasks"]

    # Fallback: lê do relatório da fase 11.5
    report_path = Path("f:/sistemas/UltronPro/backend/data/real_arc_inductive_report.json")
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        # O relatório tem estrutura {results: [{task_id, train, test, ...}]}
        items = report.get("results", report.get("tasks", []))
        if items:
            print(f"  [INFO] Pool cego nao encontrado. Usando {len(items)} tarefas do relatorio 11.5.")
            # Normaliza para formato esperado
            tasks = []
            for item in items[:20]:
                tid = item.get("task_id") or item.get("id") or "unknown"
                train = item.get("train") or item.get("examples") or []
                test  = item.get("test") or []
                if train:
                    tasks.append({"task_id": tid, "train": train, "test": test})
            return tasks

    print("[ERRO] Nenhum pool ARC encontrado. Crie arc_pool_blind_20.json.")
    return []


def main():
    print("\n" + "=" * 60)
    print("FASE 12 — LLM como Guia de Hipoteses — Benchmark ARC")
    print("=" * 60)

    tasks = load_tasks()
    if not tasks:
        print("Nenhuma tarefa carregada. Abortando.")
        return

    print(f"Tarefas carregadas: {len(tasks)}")
    print(f"Primitivos disponiveis: 23")
    print(f"Estrategia: vocabulario restrito + validacao simbolica\n")

    summary = run_benchmark(tasks, verbose=True)

    print("\n" + "=" * 60)
    print("RESULTADO FINAL")
    print("-" * 60)
    print(f"Score: {summary['solved']}/{summary['total']} ({summary['score']*100:.1f}%)")
    print(f"Alvo: 4/20 (20%)")
    print(f"\nDiagnostico por categoria:")
    for diag, count in sorted(summary["diagnosis_summary"].items()):
        print(f"  {count}x {diag}")

    if summary.get("solved_ids"):
        print(f"\nTarefas resolvidas: {summary['solved_ids']}")
    if summary.get("failed_ids"):
        print(f"Tarefas falhas:     {summary['failed_ids']}")

    # Salva relatorio completo
    REPORT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )
    print(f"\nRelatorio salvo em: {REPORT_PATH}")
    print("=" * 60)

    # Veredicto
    if summary["solved"] >= 4:
        print("\n[OK] FASE 12 CONCLUIDA. Criterio 4/20 atingido.")
        print("     Front 1 + Fase 12 = primeiro sistema de raciocinio hibrido funcionando.")
    elif summary["solved"] >= 1:
        print(f"\n[PARCIAL] {summary['solved']}/20. Abaixo do alvo.")
        gaps = [d for d in summary["diagnosis_summary"] if "gap" in d]
        if "primitive_gap" in summary["diagnosis_summary"]:
            print("  Acao: adicionar primitivos que o executor nao tem mas o LLM propos.")
        if "llm_hypothesis_gap" in summary["diagnosis_summary"]:
            print("  Acao: melhorar prompt ou tentar few-shot com exemplos de hipoteses corretas.")
    else:
        print("\n[ZERO] Nenhuma tarefa resolvida.")
        print("  Verificar: LLM esta gerando hipoteses validas? (ver arc_hypothesis_runs.jsonl)")


if __name__ == "__main__":
    main()
