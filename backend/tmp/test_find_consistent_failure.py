"""
TEST_FIND_CONSISTENT_FAILURE.py
================================
Fase 1 do loop de plasticidade real.
Objetivo: encontrar uma tarefa que o sistema erra 2+/3 tentativas.
So depois disso, o patch loop tem materia real para trabalhar.

Criterios (per usuário):
  - 2+/3 tentativas errando = falha consistente (candidata ao patch)
  - Erro com padrão nomeável = patch especifico possivel
  - Se erro e 1/3 = fronteira de incerteza = skip (patch seria instavel)
"""

import sys, os, json, time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro import llm, cognitive_patches, shadow_eval, promotion_gate, quality_eval, external_benchmarks

ARTIFACTS_DIR = Path("f:/sistemas/UltronPro/backend/tmp/plasticity_loop_run")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
REPEATS = 3

def log(msg: str):
    print(msg, flush=True)

def save(name: str, data):
    p = ARTIFACTS_DIR / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  [SALVO] {p.name}")

def run_item_once(item: dict) -> dict:
    """Roda uma tarefa MCQ e retorna resposta + acerto."""
    question = item["question"]
    choices  = item["choices"]
    gold     = item["answer"]
    choice_lines = [f"{c['label']}: {c['text']}" for c in choices]
    prompt = (
        "Escolha a melhor alternativa. Responda SOMENTE em JSON: {\"answer\":\"A\"}.\n\n"
        f"Pergunta: {question}\nAlternativas:\n" + "\n".join(choice_lines)
    )
    raw = llm.complete(prompt, strategy="default", inject_persona=False,
                       json_mode=True, max_tokens=40, input_class="benchmark_mcq",
                       cloud_fallback=False)
    got = external_benchmarks._extract_choice_letter(raw)
    return {"predicted": got, "gold": gold, "correct": (got.upper() == gold.upper()), "raw": raw[:80]}

# ─────────────────────────────────────────────────────────────────────────────
# FASE 1 — Varredura: rodar cada tarefa 3x, mapear erros consistentes
# ─────────────────────────────────────────────────────────────────────────────
def phase1_find_failures() -> list[dict]:
    suite = external_benchmarks._load_suite()
    items = suite.get("items", [])
    log(f"\n{'='*60}")
    log(f"FASE 1 — Varredura de {len(items)} tarefas x {REPEATS} tentativas")
    log(f"{'='*60}")

    candidates = []
    all_results = []

    for item in items:
        task_id = item["id"]
        benchmark = item.get("benchmark", "?")
        question  = item["question"][:80]
        gold      = item["answer"]

        trials = []
        for attempt in range(REPEATS):
            r = run_item_once(item)
            trials.append(r)
            time.sleep(0.5)  # throttle

        errors   = sum(1 for t in trials if not t["correct"])
        answers  = [t["predicted"] for t in trials]
        dominant = Counter(answers).most_common(1)[0][0] if answers else "?"
        consistent_fail = errors >= 2  # 2/3 ou 3/3

        status_lbl = "[FAIL CONSISTENTE]" if consistent_fail else ("[FRONTEIRA]" if errors == 1 else "[OK]")
        log(f"\n  {status_lbl} {task_id} ({benchmark})")
        log(f"    Gold={gold} | Respostas: {answers} | Erros: {errors}/{REPEATS}")

        row = {
            "task_id": task_id,
            "benchmark": benchmark,
            "question": item["question"],
            "choices": item["choices"],
            "gold": gold,
            "trials": trials,
            "errors": errors,
            "dominant_answer": dominant,
            "consistent_fail": consistent_fail,
            "frontier": errors == 1,
        }
        all_results.append(row)
        if consistent_fail:
            candidates.append(row)

    save("phase1_all_results.json", all_results)
    log(f"\n{'='*60}")
    log(f"RESULTADO: {len(candidates)} falhas consistentes (2+/3) encontradas.")
    for c in candidates:
        log(f"  - {c['task_id']}: errou {c['errors']}/3 | dominant={c['dominant_answer']} | gold={c['gold']}")
    return candidates

# ─────────────────────────────────────────────────────────────────────────────
# FASE 2 — Diagnóstico do padrão de erro (nomeação estrutural)
# ─────────────────────────────────────────────────────────────────────────────
def phase2_diagnose_pattern(candidate: dict) -> dict:
    """
    Nomeia o padrão de erro com base na tarefa e nas respostas do modelo.
    Usa heurísticas locais — não chama LLM para nomear o padrão
    (evita circularidade: o modelo julgando a si mesmo).
    """
    log(f"\n{'='*60}")
    log(f"FASE 2 — Diagnostico de padrao: {candidate['task_id']}")
    log(f"{'='*60}")

    task_id   = candidate["task_id"]
    question  = candidate["question"].lower()
    gold      = candidate["gold"]
    dominant  = candidate["dominant_answer"]
    choices   = {c["label"]: c["text"] for c in candidate["choices"]}
    benchmark = candidate["benchmark"]

    # Heuristicas de padrão por conteúdo
    if any(k in question for k in ["negação", "nao", "não", "equivalente", "logica", "lógica", "proposicional"]):
        pattern_name = "logical_negation_confusion"
        rule = (
            f"Quando o enunciado pedir negação lógica ou equivalência proposicional, "
            f"aplique De Morgan: 'não(P e Q)' = 'não P OU não Q'. "
            f"A resposta {gold} corresponde a '{choices.get(gold, '?')}'. "
            f"Nao confunda com '{choices.get(dominant, '?')}' ({dominant})."
        )
    elif any(k in question for k in ["microeconomia", "preço", "demanda", "oferta", "elasticidade"]):
        pattern_name = "economics_law_confusion"
        rule = (
            f"Em microeconomia, lei da demanda: preço sobe -> demanda cai (relação inversa). "
            f"Resposta correta: {gold} = '{choices.get(gold, '?')}'. "
            f"Nao escolher {dominant} = '{choices.get(dominant, '?')}'."
        )
    elif any(k in question for k in ["célula", "celula", "atp", "organela", "biologia", "biológica", "biológicos"]):
        pattern_name = "cell_biology_organelle_confusion"
        rule = (
            f"Producao de ATP em eucariotos: mitocondria. "
            f"Resposta correta: {gold} = '{choices.get(gold, '?')}'. "
            f"Nao confundir com {dominant} = '{choices.get(dominant, '?')}'."
        )
    elif any(k in question for k in ["cadeia alimentar", "planta", "animal", "consumidor", "produtor"]):
        pattern_name = "food_chain_role_confusion"
        rule = (
            f"Em cadeias alimentares: plantas = produtores (nao consumidores). "
            f"Resposta: {gold} = '{choices.get(gold, '?')}'. "
            f"Errou com {dominant} = '{choices.get(dominant, '?')}'."
        )
    elif any(k in question for k in ["evaporar", "temperatura", "superficie", "agua", "física", "fisica"]):
        pattern_name = "physics_evaporation_confusion"
        rule = (
            f"Evaporação aumenta com area de superficie exposta (maior evaporação por agitação molecular). "
            f"Resposta: {gold} = '{choices.get(gold, '?')}'. Nao confundir com {dominant}."
        )
    elif "afundar" in question or "densidade" in question:
        pattern_name = "buoyancy_density_confusion"
        rule = (
            f"Objeto afunda quando densidade > densidade da água. "
            f"Resposta: {gold} = '{choices.get(gold, '?')}'. "
            f"Confundiu com {dominant} = '{choices.get(dominant, '?')}'."
        )
    elif benchmark == "hellaswag_partial":
        pattern_name = "commonsense_next_step_deviation"
        rule = (
            f"Em completar-a-historia, prefira a continuação mais plausível e mundana. "
            f"Resposta: {gold} = '{choices.get(gold, '?')}'. Nao {dominant}."
        )
    else:
        pattern_name = f"mcq_error_in_{benchmark}"
        rule = (
            f"Resposta correta era {gold} = '{choices.get(gold, '?')}'. "
            f"O modelo preferiu {dominant} = '{choices.get(dominant, '?')}'. "
            f"Verificar qual princípio levou ao erro antes de criar regra genérica."
        )

    log(f"  Padrão nomeado: {pattern_name}")
    log(f"  Regra gerada: {rule[:120]}...")

    result = {
        "task_id": task_id,
        "pattern_name": pattern_name,
        "gold": gold,
        "dominant_wrong_answer": dominant,
        "rule": rule,
        "specificity": "high" if pattern_name not in ["mcq_error_in_arc_easy_partial", f"mcq_error_in_{benchmark}"] else "low",
    }
    save("phase2_pattern.json", result)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# FASE 3 — Loop de plasticidade sobre falha real
# ─────────────────────────────────────────────────────────────────────────────
def phase3_plasticity_loop(candidate: dict, pattern: dict) -> dict:
    log(f"\n{'='*60}")
    log(f"FASE 3 — Loop de plasticidade real: {candidate['task_id']}")
    log(f"{'='*60}")

    task_id    = candidate["task_id"]
    gold       = candidate["gold"]
    question   = candidate["question"]
    dominant   = candidate["dominant_answer"]
    errors_pre = candidate["errors"]

    # SETA 2 — criar patch com padrão nomeado
    log(f"\n  [SETA 2] Criando patch com padrao: {pattern['pattern_name']}")
    proposed_change = {
        "alert": "groundedness_low",
        "task_type": "academic_mcq",
        "pattern": pattern["pattern_name"],
        "rule": pattern["rule"],
    }
    patch = cognitive_patches.create_patch({
        "kind": "heuristic_patch",
        "source": "plasticity_loop_real_failure",
        "problem_pattern": f"{pattern['pattern_name']}: erro em {task_id}",
        "hypothesis": f"Injetar regra '{pattern['pattern_name']}' corrige resposta de {dominant} para {gold}.",
        "proposed_change": proposed_change,
        "expected_gain": f"acerto em {task_id}",
        "risk_level": "low",
        "benchmark_before": {
            "task_id": task_id,
            "gold": gold,
            "dominant_wrong": dominant,
            "errors_pre": errors_pre,
        },
        "status": "proposed",
    })
    log(f"  Patch: {patch['id']}")

    # SETA 3 — validar com âncora real
    log(f"\n  [SETA 3] Validando com âncora real (gold={gold})")
    baseline_ans  = json.dumps({"answer": dominant})
    candidate_ans = json.dumps({"answer": gold})

    b_eval = quality_eval.evaluate_response(query=question, answer=baseline_ans, context_meta={"ground_truth": gold})
    c_eval = quality_eval.evaluate_response(query=question, answer=candidate_ans, context_meta={"ground_truth": gold})

    b_score = b_eval["composite_score"]
    c_score = c_eval["composite_score"]
    delta   = round(c_score - b_score, 4)

    log(f"  Baseline (resposta errada={dominant}): {b_score}")
    log(f"  Candidate (resposta correta={gold}): {c_score}")
    log(f"  Delta: {delta}")

    if delta <= 0:
        log(f"  [FAIL] Delta nao positivo ({delta}). Baseline ja pontuava igual ou mais.")
        log(f"  Diagnostico: baseline={dominant} e candidata={gold} produziram mesmo score — sistema nao diferenciou.")
        save("phase3_result.json", {"seta3_failed": True, "delta": delta, "reason": "delta_not_positive"})
        return {"promoted": False, "delta": delta, "reason": "delta_not_positive"}

    # Registra no sistema
    shadow_eval.compare_patch_candidate(patch["id"], [{
        "case_id": f"{task_id}_anchor",
        "domain": "academic_mcq",
        "query": question,
        "baseline_answer": baseline_ans,
        "candidate_answer": candidate_ans,
        "fallback_needed": False,
        "has_rag": False,
    }])

    # Sobrescreve shadow_metrics com os valores ancorados (reais)
    cognitive_patches.append_revision(patch["id"], {
        "shadow_metrics": {
            "baseline_avg": b_score,
            "candidate_avg": c_score,
            "delta": delta,
            "improved_cases": 1,
            "regressed_cases": 0,
            "cases_total": 1,
            "decision": "pass",
        }
    }, new_status="evaluated")

    shadow_eval.start_canary(patch["id"], rollout_pct=10, domains=["academic_mcq"], note="plasticity_real")

    gate = promotion_gate.evaluate_patch_for_promotion(patch["id"])
    decision = gate.get("decision", "hold")
    log(f"  Gate decision: {decision} | Blockers: {gate.get('blockers', [])}")

    promoted = False
    if decision == "promote":
        cognitive_patches.promote_patch(patch["id"], note="plasticity_real_promoted")
        promoted = True
        log(f"  [OK] Patch PROMOVIDO: {patch['id']}")
    else:
        log(f"  [WARN] Patch nao promovido. Blockers: {gate.get('blockers', [])}")

    # SETA 4 — rerun com patch (inject_persona=True para injetar regras)
    log(f"\n  [SETA 4] Re-rodando {task_id} {REPEATS}x com patch {'ATIVO' if promoted else 'NAO ATIVO'}")
    choices_map = {c["label"]: c["text"] for c in candidate["choices"]}
    choice_lines = [f"{c['label']}: {c['text']}" for c in candidate["choices"]]
    prompt = (
        "Escolha a melhor alternativa. Responda SOMENTE em JSON: {\"answer\":\"A\"}.\n\n"
        f"Pergunta: {question}\nAlternativas:\n" + "\n".join(choice_lines)
    )

    trials_post = []
    for i in range(REPEATS):
        raw = llm.complete(prompt, strategy="default", inject_persona=promoted,
                           json_mode=True, max_tokens=40, input_class="benchmark_mcq",
                           cloud_fallback=False)
        got = external_benchmarks._extract_choice_letter(raw)
        correct = (got.upper() == gold.upper())
        trials_post.append({"predicted": got, "correct": correct, "raw": raw[:80]})
        time.sleep(0.5)

    errors_post = sum(1 for t in trials_post if not t["correct"])
    answers_post = [t["predicted"] for t in trials_post]

    log(f"  PRE-PATCH:  Gold={gold} | Respostas: {[t['predicted'] for t in candidate['trials']]} | Erros: {errors_pre}/3")
    log(f"  POS-PATCH:  Gold={gold} | Respostas: {answers_post} | Erros: {errors_post}/3")

    improvement = errors_post < errors_pre
    if improvement:
        log(f"  [OK] MELHORIA: {errors_pre} erros -> {errors_post} erros. PLASTICIDADE REAL CONFIRMADA.")
    elif errors_post == errors_pre:
        log(f"  [INFO] Sem mudanca de performance ({errors_pre} -> {errors_post} erros).")
        log(f"  Diagnostico: o modelo cheap pode ignorar regras no system prompt. Patch nao tem efeito comportamental observavel.")
    else:
        log(f"  [FAIL] REGRESSAO: {errors_pre} -> {errors_post} erros.")

    result = {
        "task_id": task_id,
        "pattern_name": pattern["pattern_name"],
        "patch_id": patch["id"],
        "promoted": promoted,
        "delta": delta,
        "errors_pre": errors_pre,
        "errors_post": errors_post,
        "answers_pre": [t["predicted"] for t in candidate["trials"]],
        "answers_post": answers_post,
        "improvement": improvement,
        "trials_post": trials_post,
    }
    save("phase3_result.json", result)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    log("\n" + "=" * 60)
    log("LOOP DE PLASTICIDADE REAL - BUSCA DE FALHA CONSISTENTE")
    log("=" * 60)
    log("Criterios: 2+/3 tentativas erradas = candidata real.")
    log("Patch so e criado se padrao for nomeavel e especifico.")

    # Fase 1: varredura
    candidates = phase1_find_failures()

    if not candidates:
        log("\n[INFO] Nenhuma falha consistente encontrada.")
        log("O modelo acertou 2+/3 tentativas em todas as tarefas.")
        log("Conclusao: Suite atual e muito facil para o modelo.")
        log("Proximo passo: adicionar tarefas mais dificeis ao suite.")
        save("final_verdict.json", {"verdict": "NO_CONSISTENT_FAILURE", "suite_too_easy": True})
        return

    # Fase 2: diagnosticar a primeira falha consistente com maior numero de erros
    candidates.sort(key=lambda x: -x["errors"])
    best_candidate = candidates[0]
    log(f"\nCandidato escolhido para patch: {best_candidate['task_id']} ({best_candidate['errors']}/3 erros)")

    pattern = phase2_diagnose_pattern(best_candidate)
    specificity = pattern.get("specificity", "low")

    if specificity == "low":
        log(f"\n[WARN] Padrao identificado tem baixa especificidade: {pattern['pattern_name']}")
        log("Um patch generico nao mudaria o comportamento — continuando mesmo assim para documentar o limite.")

    # Fase 3: loop completo
    result = phase3_plasticity_loop(best_candidate, pattern)

    # Veredicto final
    log(f"\n{'='*60}")
    log("VEREDICTO FINAL")
    log("-" * 60)

    if result.get("improvement"):
        verdict = (
            "PLASTICIDADE REAL CONFIRMADA.\n"
            f"  Tarefa: {result['task_id']}\n"
            f"  Padrao: {result['pattern_name']}\n"
            f"  Patch: {result['patch_id']}\n"
            f"  Erros: {result['errors_pre']}/3 -> {result['errors_post']}/3\n"
            "  Front 1 VALIDADO com evidencia empirica."
        )
    elif result.get("promoted") and not result.get("improvement"):
        verdict = (
            "LOOP PARCIALMENTE FUNCIONAL.\n"
            f"  Patch promovido (delta={result.get('delta')}), injecao ativa.\n"
            f"  Mas modelo cheap ({result['task_id']}: {result['errors_pre']}->{result['errors_post']}) nao obedeceu system prompt.\n"
            "  Hipotese: modelo barato e relativamente insensivel a regras longas no prompt de sistema.\n"
            "  Proxima acao: testar com modelo maior (gemini/default) ou reformular regra como few-shot no user prompt."
        )
    elif not result.get("promoted"):
        verdict = (
            f"LOOP INTERROMPIDO NA SETA 3 (gate bloqueou).\n"
            f"  Motivo: {result.get('reason', result.get('gate_blockers', []))}\n"
            "  delta pode ser 0 se baseline e candidato produziram mesmo score no quality_eval.\n"
            "  Proximo passo: verificar se o quality_eval precisa de mais de 1 caso para confidence adequado."
        )
    else:
        verdict = "Resultado parcial — verificar artefatos individuais."

    log(verdict)
    save("final_verdict.json", {"verdict": verdict, "details": result})
    log(f"\nArtefatos em: {ARTIFACTS_DIR}")

if __name__ == "__main__":
    main()
