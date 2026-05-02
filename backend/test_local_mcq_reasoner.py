import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _accuracy(rows):
    return sum(1 for row in rows if row["got"] == row["gold"]) / max(1, len(rows))


def test_local_mcq_reasoner_beats_first_choice_baseline_on_unseen_holdout():
    from ultronpro import local_mcq_reasoner

    holdout = [
        {
            "question": "Um bloco de metal compacto tende a afundar em agua porque tem qual propriedade?",
            "choices": [
                {"label": "A", "text": "cor mais escura"},
                {"label": "B", "text": "alta densidade"},
                {"label": "C", "text": "formato redondo"},
                {"label": "D", "text": "baixa massa por volume"},
            ],
            "gold": "B",
        },
        {
            "question": "Em uma teia alimentar, organismos que fabricam seu proprio alimento sao chamados de:",
            "choices": [
                {"label": "A", "text": "consumidores primarios"},
                {"label": "B", "text": "decompositores finais"},
                {"label": "C", "text": "produtores"},
                {"label": "D", "text": "predadores"},
            ],
            "gold": "C",
        },
        {
            "question": "Para uma camiseta molhada secar mais rapido, qual acao ajuda mais?",
            "choices": [
                {"label": "A", "text": "cobrir a camiseta com plastico"},
                {"label": "B", "text": "espalhar a camiseta aumentando a area exposta"},
                {"label": "C", "text": "reduzir a temperatura do ambiente"},
                {"label": "D", "text": "diminuir a circulacao de ar"},
            ],
            "gold": "B",
        },
        {
            "question": "A negacao de 'A e B' pela lei de De Morgan e:",
            "choices": [
                {"label": "A", "text": "nao A e nao B"},
                {"label": "B", "text": "A ou B"},
                {"label": "C", "text": "nao A ou nao B"},
                {"label": "D", "text": "A implica B"},
            ],
            "gold": "C",
        },
        {
            "question": "Se o preco do cafe aumenta, mantendo o resto constante, espera-se:",
            "choices": [
                {"label": "A", "text": "aumento da quantidade demandada"},
                {"label": "B", "text": "reducao da quantidade demandada"},
                {"label": "C", "text": "desaparecimento imediato da oferta"},
                {"label": "D", "text": "demanda perfeitamente inelastica em todos os casos"},
            ],
            "gold": "B",
        },
        {
            "question": "Qual organela e mais associada a producao de ATP em celulas eucarioticas?",
            "choices": [
                {"label": "A", "text": "nucleo"},
                {"label": "B", "text": "complexo de Golgi"},
                {"label": "C", "text": "mitocondria"},
                {"label": "D", "text": "lisossomo"},
            ],
            "gold": "C",
        },
    ]

    candidate = []
    baseline = []
    for case in holdout:
        got = local_mcq_reasoner.solve_mcq(case["question"], case["choices"])["answer"]
        candidate.append({"got": got, "gold": case["gold"]})
        baseline.append({"got": case["choices"][0]["label"], "gold": case["gold"]})

    candidate_accuracy = _accuracy(candidate)
    baseline_accuracy = _accuracy(baseline)
    assert candidate_accuracy >= 0.8
    assert candidate_accuracy - baseline_accuracy >= 0.5


def test_external_benchmark_local_strategy_uses_non_llm_solver(tmp_path, monkeypatch):
    from ultronpro import external_benchmarks, llm

    monkeypatch.setattr(external_benchmarks, "RUNS_PATH", tmp_path / "runs.jsonl")

    def forbidden_llm(*args, **kwargs):
        raise AssertionError("local strategy must not call llm.complete")

    monkeypatch.setattr(llm, "complete", forbidden_llm)

    report = external_benchmarks.run_suite(limit_per_benchmark=1, strategy="local", predictor="llm", tag="unit_local")

    assert report["total"] == 3
    assert report["correct"] == 3
    assert report["overall_accuracy"] == 1.0
    assert {item["prediction_source"] for item in report["items"]} == {"local_mcq_reasoner"}
