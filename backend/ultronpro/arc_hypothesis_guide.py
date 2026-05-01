"""
arc_hypothesis_guide.py — Fase 12: LLM como Guia de Hipóteses
==============================================================
Estratégia de vocabulário restrito:
  O LLM NÃO traduz linguagem natural para código.
  O LLM SELECIONA sequências dentro do vocabulário fixo do executor.

Loop:
  1. LLM lê grids (texto com coordenadas) + mapa de cores
  2. LLM propõe 3-5 hipóteses no formato JSON
  3. Executor simbólico testa cada hipótese contra TODOS os train_pairs
  4. Primeira hipótese que passa em 100% dos pares → aplica no test_input
"""
from __future__ import annotations

import json
import time
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("uvicorn")

# ── Configurações Visuais ───────────────────────────────────────────────────

COLOR_NAMES = {
    0: "preto (fundo)", 1: "azul", 2: "vermelho", 3: "verde", 
    4: "amarelo", 5: "cinza", 6: "magenta", 7: "laranja", 
    8: "azure", 9: "marrom"
}

# ── Primitivos disponíveis (vocabulário do executor) ─────────────────────────
AVAILABLE_PRIMITIVES: list[str] = [
    "rotate_90", "reflect_v", "reflect_h",
    "crop", "scale_2", "scale_3",
    "invert", "border", "label",
    "fractal", "gravity", "fill", "keep_max",
    "obj_rotate_90", "obj_reflect_v", "obj_reflect_h",
    "obj_fill", "obj_invert",
    "quad_rotate_90", "quad_reflect_v", "quad_reflect_h",
    "quad_fill", "quad_keep_max",
    "gravity_v", "gravity_up", "spread_X_Y",
]

PRIMITIVES_STR = ", ".join(AVAILABLE_PRIMITIVES)

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "arc_hypothesis_runs.jsonl"

# ── Formatação de grids para o LLM ───────────────────────────────────────────

def _grid_to_text(grid: list[list[int]], max_rows: int = 30) -> str:
    """Converte grid para string com eixos coordenados para maior fidelidade visual."""
    if not grid: return "Grid Vazio"
    rows = grid[:max_rows]
    h, w = len(grid), len(grid[0]) if grid else 0
    
    # Cabeçalho das colunas (ex: 0 1 2 3...)
    header = "    " + " ".join(str(i % 10) for i in range(w))
    lines = [f"Dimensões: {h}x{w}", header]
    
    for i, row in enumerate(rows):
        line = f"{i:2}: " + " ".join(str(c) for c in row)
        lines.append(line)
    
    return "\n".join(lines)


def _format_examples(train_pairs: list[dict], max_pairs: int = 4) -> str:
    """Formata exemplos com labels claros."""
    lines = []
    for i, pair in enumerate(train_pairs[:max_pairs]):
        inp = _grid_to_text(pair["input"])
        out = _grid_to_text(pair["output"])
        lines.append(f"### Par de Treino {i+1}:\n[INPUT]:\n{inp}\n\n[OUTPUT]:\n{out}")
    return "\n\n".join(lines)


# ── Construção do prompt ──────────────────────────────────────────────────────

def _build_prompt(train_pairs: list[dict], task_id: str = "") -> str:
    examples_text = _format_examples(train_pairs)
    color_map = "\n".join([f"- {k}: {v}" for k, v in COLOR_NAMES.items()])
    
    return f"""Você é um especialista em raciocínio visual e puzzles ARC (Abstraction and Reasoning Corpus).
Sua tarefa é identificar a regra lógica que transforma o grid INPUT no grid OUTPUT.

MAPA DE CORES (use para identificar objetos e padrões):
{color_map}

PRIMITIVOS DISPONÍVEIS (SELECIONE EXATAMENTE DESTES):
{PRIMITIVES_STR}

DESCRIÇÃO DOS PRIMITIVOS:
- rotate_90: rotaciona o grid inteiro 90° horário.
- reflect_v: espelha o grid inteiro verticalmente (top-down flip).
- reflect_h: espelha o grid inteiro horizontalmente (left-right flip).
- crop: recorta o grid mantendo apenas o retângulo que contém cores não-zero.
- scale_2 / scale_3: aumenta o tamanho do grid em 2x ou 3x repetindo os pixels.
- invert: inverte cores (0 -> max_color, outros -> 0).
- border: mantém apenas os pixels que formam o contorno externo de um padrão colorido.
- label: preenche cada objeto com uma cor diferente para identificação.
- fractal: repete o padrão do grid em cada pixel colorido do próprio grid.
- gravity: faz todos os pixels não-zero 'caírem' para o fundo de suas colunas.
- fill: preenche buracos fechados de cor 0 cercados por outras cores.
- keep_max: mantém apenas a cor que possui mais pixels no grid, limpando o resto.
- obj_X: aplica o primitivo X separadamente em cada objeto isolado (ex: obj_rotate_90). Retornos de segmentação por cor e conectividade são usados internamente.
- quad_X: aplica o primitivo X em cada quadrante separado por linhas ou colunas uniformes de cor sólida.
- gravity_v / gravity_up: move pixels para baixo ou para cima até colidirem com o fundo ou com outros pixels.
- spread_X_Y: propaga a cor Y para todos os pixels conectados a pixels que possuem a cor de semente X. (X e Y devem ser dígitos de 0-9, ex: spread_1_2).

REGRAS DE OURO:
1. PREFIRA SIMPLICIDADE: Se rotate_90, reflect_v ou reflect_h resolvem o grid inteiro, use-os em vez de "obj_X".
2. ORIENTAÇÃO: Olhe os índices de linha (0: , 1:) e coluna (0 1 2) para detectar se o padrão mudou de lado ou girou.

EXEMPLOS DO PUZZLE {task_id}:

{examples_text}

Analise os exemplos passo a passo. Descreva a mudança visual primeiro e depois proponha as sequências.

Responda SOMENTE com JSON válido:
{{
  "visual_analysis": "O que mudou entre input e output? (ex: 'o objeto azul no canto superior foi espelhado para baixo').",
  "hypotheses": [
    {{"sequence": ["reflect_h"], "rationale": "Justificativa curta."}},
    {{"sequence": ["rotate_90"], "rationale": "Hipótese alternativa."}}
  ]
}}
"""


# ── Parser e validação das hipóteses ─────────────────────────────────────────

def _parse_hypotheses(raw: str) -> tuple[list[list[str]], str, str]:
    """
    Parseia a resposta do LLM.
    Retorna: (hypotheses, reasoning, parse_error)
    """
    # Extrai bloco JSON mesmo com texto em volta
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return [], "", "no_json_found"
    try:
        obj = json.loads(raw[start:end])
    except json.JSONDecodeError as e:
        return [], "", f"json_decode_error: {e}"

    raw_hyps = obj.get("hypotheses", [])
    if not isinstance(raw_hyps, list):
        return [], "", "hypotheses_not_list"

    valid = []
    for h in raw_hyps:
        seq = h.get("sequence", []) if isinstance(h, dict) else []
        if not seq or not isinstance(seq, list):
            continue
        valid_seq = []
        for p in seq:
            ps = str(p)
            # Match spread_digit_digit
            import re
            if ps in AVAILABLE_PRIMITIVES:
                valid_seq.append(ps)
            elif re.match(r"^spread_\d_\d$", ps):
                valid_seq.append(ps)
        if valid_seq:
            valid.append(valid_seq)

    reasoning = str(obj.get("visual_analysis", obj.get("reasoning", "")))
    return valid, reasoning, ""


def _validate_hypothesis(
    hypothesis: list[str],
    train_pairs: list[dict],
    executor,
) -> tuple[bool, list[str]]:
    """
    Testa uma hipótese contra todos os train_pairs.
    Retorna (all_passed, reasons_for_failure).
    """
    failures = []
    for i, pair in enumerate(train_pairs):
        try:
            result = executor.execute_plan(pair["input"], hypothesis)
            if result != pair["output"]:
                failures.append(
                    f"pair_{i}: output_mismatch "
                    f"(got shape {len(result)}x{len(result[0]) if result else 0} "
                    f"vs expected {len(pair['output'])}x{len(pair['output'][0]) if pair['output'] else 0})"
                )
        except Exception as e:
            failures.append(f"pair_{i}: execution_error: {e}")
    return (len(failures) == 0), failures


# ── Função principal ──────────────────────────────────────────────────────────

def guided_solve(
    task_id: str,
    train_pairs: list[dict],
    test_input: list[list[int]],
    *,
    max_retries: int = 2,
    log_results: bool = True,
) -> dict[str, Any]:
    """Loop principal da Fase 12."""
    from ultronpro.arc_executor import ARCExecutor
    from ultronpro import llm

    t_start = time.time()
    prompt = _build_prompt(train_pairs, task_id=task_id)
    hypotheses: list[list[str]] = []
    reasoning = ""
    llm_calls = 0
    parse_error = ""

    # SETA 0 — Indutor Simbólico Puro (Zero API)
    from ultronpro.visual_inductor import VisualInductor
    try:
        sym_hyp = VisualInductor.infer_sequence(train_pairs)
        if sym_hyp is not None:
            # Se encontrou uma regra puramente simbólica que satisfaz o treino
            result = ARCExecutor.execute_plan(test_input, sym_hyp)
            logger.info(f"[HypGuide] {task_id} resolvido via Indução Simbólica Pura! | hyp={sym_hyp}")
            return {
                "ok": True, 
                "task_id": task_id, 
                "output_grid": result,
                "winning_hypothesis": sym_hyp, 
                "reasoning": "Indução simbólica baseada em invariantes estruturais (Zero API).",
                "hypotheses_tried": [{"sequence": sym_hyp, "passed": True, "failures": []}], 
                "failures": {}, 
                "parse_error": "", 
                "method": "pure_symbolic", 
                "llm_calls": 0, 
                "elapsed_s": time.time() - t_start
            }
    except Exception as e:
        logger.debug(f"[HypGuide] Erro no indutor simbólico para {task_id}: {e}")

    # SETA 1 — LLM propõe hipóteses (com retries em parse error)
    for attempt in range(max(1, max_retries)):
        llm_calls += 1
        raw = llm.complete(
            prompt,
            strategy="default",
            inject_persona=False,
            json_mode=True,
            max_tokens=1024,
            cloud_fallback=True,
        )
        hypotheses, reasoning, parse_error = _parse_hypotheses(raw)
        if hypotheses:
            break
        if attempt < max_retries - 1:
            logger.warning(f"[HypGuide] {task_id} parse failed ({parse_error}), retrying...")
            time.sleep(0.5)

    if not hypotheses:
        result = {
            "ok": False, "task_id": task_id, "output_grid": None,
            "winning_hypothesis": None, "reasoning": reasoning,
            "hypotheses_tried": [], "failures": {},
            "parse_error": parse_error, "method": "llm_guided_symbolic",
            "llm_calls": llm_calls,
            "diagnosis": "llm_failed_to_propose_valid_hypotheses",
            "elapsed_s": round(time.time() - t_start, 2),
        }
        _maybe_log(result, log_results)
        return result

    # SETA 2 — Validação simbólica de cada hipótese
    hypotheses_tried = []
    failures: dict[str, list[str]] = {}
    winning = None
    output_grid = None

    for hyp in hypotheses:
        hyp_key = json.dumps(hyp)
        passed, reasons = _validate_hypothesis(hyp, train_pairs, ARCExecutor)
        hypotheses_tried.append({"sequence": hyp, "passed": passed, "failures": reasons})

        if passed:
            # SETA 3 — Aplicar no test_input
            try:
                output_grid = ARCExecutor.execute_plan(test_input, hyp)
                winning = hyp
                break
            except Exception as e:
                failures[hyp_key] = [f"test_execution_error: {e}"]
        else:
            failures[hyp_key] = reasons

    elapsed = round(time.time() - t_start, 2)

    # Diagnóstico de falha
    diagnosis = None
    if not winning:
        all_failed_for_same_reason = all(
            "execution_error" in r for reasons in failures.values() for r in reasons
        )
        if all_failed_for_same_reason:
            diagnosis = "primitive_gap: hypotheses were structurally valid but executor failed"
        else:
            diagnosis = "llm_hypothesis_gap: no proposed sequence matched all train pairs"

    result = {
        "ok": winning is not None,
        "task_id": task_id,
        "output_grid": output_grid,
        "winning_hypothesis": winning,
        "reasoning": reasoning,
        "hypotheses_tried": hypotheses_tried,
        "failures": failures,
        "parse_error": parse_error,
        "method": "llm_guided_symbolic",
        "llm_calls": llm_calls,
        "elapsed_s": elapsed,
    }
    if diagnosis:
        result["diagnosis"] = diagnosis

    _maybe_log(result, log_results)
    return result


# ── Benchmark runner ──────────────────────────────────────────────────────────

def run_benchmark(
    tasks: list[dict],
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    """Roda guided_solve em múltiplas tarefas ARC."""
    solved = []
    failed = []
    results = []
    diagnosis_counts: dict[str, int] = {}

    for task in tasks:
        tid = task.get("task_id", "unknown")
        train = task.get("train", [])
        test_cases = task.get("test", [])
        if not train or not test_cases:
            failed.append(tid)
            continue

        test_input = test_cases[0]["input"]
        test_output = test_cases[0].get("output")

        res = guided_solve(tid, train, test_input, log_results=True)
        results.append(res)

        if test_output is not None and res.get("output_grid") is not None:
            correct = res["output_grid"] == test_output
            res["graded_correct"] = correct
            if correct:
                solved.append(tid)
            else:
                failed.append(tid)
        elif res["ok"]:
            solved.append(tid)
        else:
            failed.append(tid)

        diag = res.get("diagnosis", "solved" if res["ok"] else "unknown_failure")
        diagnosis_counts[diag] = diagnosis_counts.get(diag, 0) + 1

        if verbose:
            status = "[OK]" if (tid in solved) else "[FAIL]"
            hyp = res.get("winning_hypothesis")
            print(
                f"  {status} {tid} | hyp={hyp} | "
                f"tried={len(res.get('hypotheses_tried', []))} | "
                f"elapsed={res.get('elapsed_s')}s"
            )

    total = len(tasks)
    score = len(solved) / total if total > 0 else 0.0

    return {
        "score": round(score, 3),
        "solved": len(solved),
        "total": total,
        "solved_ids": solved,
        "failed_ids": failed,
        "diagnosis_summary": diagnosis_counts,
        "results": results,
    }


def _maybe_log(result: dict, enabled: bool):
    if not enabled:
        return
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[HypGuide] log write failed: {e}")
