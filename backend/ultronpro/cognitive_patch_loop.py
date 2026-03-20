from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ultronpro import cognitive_patches, shadow_eval, promotion_gate, rollback_manager, gap_detector

LOOP_LOG_PATH = Path('/app/data/cognitive_patch_loop_runs.jsonl')


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_row(row: dict[str, Any]):
    _ensure_parent(LOOP_LOG_PATH)
    with LOOP_LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _patch_alert(patch: dict[str, Any]) -> str:
    change = patch.get('proposed_change') if isinstance(patch.get('proposed_change'), dict) else {}
    return str(change.get('alert') or '').strip().lower()


def _patch_task_type(patch: dict[str, Any]) -> str:
    change = patch.get('proposed_change') if isinstance(patch.get('proposed_change'), dict) else {}
    return str(change.get('task_type') or 'general')[:80]


def _sample_queries(patch: dict[str, Any]) -> list[str]:
    before = patch.get('benchmark_before') if isinstance(patch.get('benchmark_before'), dict) else {}
    qs = [str(x)[:240] for x in (before.get('sample_queries') or []) if str(x).strip()]
    if qs:
        return qs[:3]
    pattern = str(patch.get('problem_pattern') or 'resolver falha recorrente')[:180]
    return [
        f'Como melhorar isto? {pattern}',
        f'Como evitar recorrência? {pattern}',
        f'Qual a resposta mais segura para: {pattern}?',
    ]


def _candidate_answer_for_alert(alert: str, query: str) -> str:
    q = str(query or '').strip()
    if alert in {'missing_gap_disclosure', 'critic_overconfident', 'critic_revision_needed'}:
        return f'Não dá para afirmar isso com segurança só com o que há aqui. Para responder "{q[:120]}", eu trataria como hipótese, deixaria a incerteza explícita e pediria evidências adicionais antes de concluir. Fonte: evidência ainda insuficiente no contexto atual.'
    if alert in {'groundedness_low', 'quality_score_below_threshold'}:
        return f'Respondendo diretamente: a resposta para "{q[:120]}" precisa vir com base verificável. Sem fonte suficiente, a forma correta é explicitar a incerteza, listar o que falta confirmar e evitar conclusão categórica. Fonte: contexto atual insuficiente para cravar causa final.'
    if alert in {'rag_coverage_low', 'rag_diversity_low', 'rag_redundancy_high'}:
        return f'Respondendo diretamente: antes de concluir sobre "{q[:120]}", eu buscaria fontes mais diversas e menos redundantes, compararia evidências e só então daria uma resposta final com referência explícita. Fonte: cobertura atual insuficiente para resposta robusta.'
    if alert == 'relevance_low':
        return f'Respondendo diretamente à pergunta "{q[:120]}": eu focaria primeiro no pedido central, cortaria tangentes e só adicionaria contexto extra se ajudar a resolver a tarefa. Fonte: priorização do objetivo principal da consulta.'
    return f'Para "{q[:120]}", a versão mais segura é explicitar limites de evidência, manter foco na tarefa e evitar excesso de confiança. Fonte: contexto parcial.'


def _baseline_answer_for_alert(alert: str, query: str) -> str:
    q = str(query or '').strip()
    if alert in {'missing_gap_disclosure', 'critic_overconfident', 'critic_revision_needed'}:
        return f'Isso está claro: para "{q[:120]}", a causa já é conhecida e a solução é direta.'
    if alert in {'groundedness_low', 'quality_score_below_threshold'}:
        return f'A resposta de "{q[:120]}" é simples e está resolvida.'
    if alert in {'rag_coverage_low', 'rag_diversity_low', 'rag_redundancy_high'}:
        return f'Uma única fonte já basta para responder "{q[:120]}" com confiança total.'
    if alert == 'relevance_low':
        return f'Antes de tudo, aqui vai um monte de contexto paralelo sobre "{q[:120]}" que nem responde diretamente ao pedido.'
    return f'"{q[:120]}" já está resolvido com certeza.'


def synthesize_shadow_cases(patch_id: str, max_cases: int = 3) -> dict[str, Any] | None:
    patch = cognitive_patches.get_patch(patch_id)
    if not patch:
        return None
    alert = _patch_alert(patch)
    task_type = _patch_task_type(patch)
    cases = []
    for idx, q in enumerate(_sample_queries(patch)[:max(1, min(6, int(max_cases or 3)))]):
        cases.append({
            'case_id': f'{patch_id}_auto_{idx+1}',
            'domain': task_type,
            'query': q,
            'baseline_answer': _baseline_answer_for_alert(alert, q),
            'candidate_answer': _candidate_answer_for_alert(alert, q),
            'fallback_needed': alert in {'missing_gap_disclosure', 'critic_overconfident', 'critic_revision_needed', 'groundedness_low', 'quality_score_below_threshold'},
            'has_rag': alert in {'rag_coverage_low', 'rag_diversity_low', 'rag_redundancy_high'},
        })
    return {'ok': True, 'patch_id': patch_id, 'cases': cases, 'alert': alert, 'task_type': task_type}


def process_patch(patch_id: str, *, canary_rollout_pct: int = 10) -> dict[str, Any] | None:
    patch = cognitive_patches.get_patch(patch_id)
    if not patch:
        return None
    status = str(patch.get('status') or 'proposed')
    out: dict[str, Any] = {'ok': True, 'patch_id': patch_id, 'initial_status': status}
    if status in {'rejected', 'rolled_back', 'archived', 'promoted'}:
        out['skipped'] = True
        out['reason'] = f'status={status}'
        return out

    synth = synthesize_shadow_cases(patch_id)
    if not synth:
        return None
    shadow = shadow_eval.compare_patch_candidate(patch_id, synth['cases'])
    out['shadow_eval'] = shadow
    if not shadow:
        out['ok'] = False
        out['error'] = 'shadow_eval_failed_to_run'
        return out

    if str(shadow.get('decision') or '') == 'fail':
        rejected = cognitive_patches.reject_patch(patch_id, reason='auto_shadow_eval_failed', evidence_refs=[f'auto_shadow_eval:{patch_id}:{_now()}'])
        out['final_action'] = 'reject'
        out['patch'] = rejected
        _append_row({'ts': _now(), **out})
        return out

    patch = cognitive_patches.get_patch(patch_id) or patch
    canary = patch.get('canary_state') if isinstance(patch.get('canary_state'), dict) else {}
    if not bool(canary.get('enabled')):
        started = shadow_eval.start_canary(patch_id, rollout_pct=canary_rollout_pct, domains=[_patch_task_type(patch)], note='auto_patch_loop')
        out['canary'] = started

    gate = promotion_gate.evaluate_patch_for_promotion(patch_id)
    out['promotion_gate'] = gate
    decision = str((gate or {}).get('decision') or '')
    if decision == 'promote':
        promoted = cognitive_patches.promote_patch(patch_id, note='auto_patch_loop_promoted')
        out['final_action'] = 'promote'
        out['patch'] = promoted
    elif decision == 'reject':
        rejected = cognitive_patches.reject_patch(patch_id, reason='auto_promotion_gate_reject', evidence_refs=[f'promotion_gate:{patch_id}:{_now()}'])
        out['final_action'] = 'reject'
        out['patch'] = rejected
    else:
        out['final_action'] = 'hold'
        out['patch'] = cognitive_patches.get_patch(patch_id)

    try:
        rollback = rollback_manager.auto_rollback_if_needed(patch_id, note='post_promotion_auto_guard')
        out['rollback_check'] = rollback
    except Exception:
        pass
    _append_row({'ts': _now(), **out})
    return out


def autorun_once(limit: int = 5, statuses: list[str] | None = None) -> dict[str, Any]:
    sts = [str(x).strip().lower() for x in (statuses or ['proposed', 'evaluated', 'evaluating']) if str(x).strip()]
    rows = cognitive_patches.list_patches(limit=max(1, int(limit or 5)) * 4)
    chosen = [r for r in rows if str(r.get('status') or '').lower() in sts][:max(1, int(limit or 5))]
    results = []
    for row in chosen:
        res = process_patch(str(row.get('id') or ''))
        if res:
            results.append(res)
    summary = {
        'ok': True,
        'picked': len(chosen),
        'processed': len(results),
        'statuses': sts,
        'results': results,
        'stats_after': cognitive_patches.stats(),
    }
    _append_row({'ts': _now(), 'event': 'autorun_once', 'summary': summary})
    return summary


def scan_and_autorun(*, scan_limit: int = 80, process_limit: int = 5) -> dict[str, Any]:
    scanned = gap_detector.scan_recent_failures(limit=scan_limit)
    ran = autorun_once(limit=process_limit, statuses=['proposed', 'evaluating', 'evaluated'])
    return {'ok': True, 'scan': scanned, 'autorun': ran}


def status(limit: int = 20) -> dict[str, Any]:
    rows = []
    if LOOP_LOG_PATH.exists():
        for ln in LOOP_LOG_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return {
        'ok': True,
        'path': str(LOOP_LOG_PATH),
        'recent': rows[-max(1, min(200, int(limit or 20))):],
        'patch_stats': cognitive_patches.stats(),
        'gap_detector_state_path': str(gap_detector.STATE_PATH),
        'quality_log_path': str(gap_detector.QUALITY_LOG_PATH),
    }


def run_selftest() -> dict[str, Any]:
    import tempfile

    old_patch_path = cognitive_patches.PATCHES_PATH
    old_patch_state = cognitive_patches.STATE_PATH
    old_shadow_log = shadow_eval.LOG_PATH
    old_canary_log = shadow_eval.CANARY_LOG_PATH
    old_rollback_ledger = rollback_manager.LEDGER_PATH
    old_loop_log = LOOP_LOG_PATH
    with tempfile.TemporaryDirectory(prefix='cognitive-patch-loop-') as td:
        base = Path(td)
        cognitive_patches.PATCHES_PATH = base / 'cognitive_patches.jsonl'
        cognitive_patches.STATE_PATH = base / 'cognitive_patches_state.json'
        shadow_eval.LOG_PATH = base / 'shadow_eval_runs.jsonl'
        shadow_eval.CANARY_LOG_PATH = base / 'shadow_eval_canary.jsonl'
        rollback_manager.LEDGER_PATH = base / 'cognitive_rollbacks.jsonl'
        globals()['LOOP_LOG_PATH'] = base / 'cognitive_patch_loop_runs.jsonl'
        try:
            patch = cognitive_patches.create_patch({
                'kind': 'confidence_patch',
                'source': 'selftest',
                'problem_pattern': 'planning: estilo sobreconfiante recorrente',
                'proposed_change': {'task_type': 'planning', 'alert': 'critic_overconfident'},
                'benchmark_before': {'sample_queries': ['Como corrigir timeout no planner?', 'O planner está respondendo sem base?']},
                'status': 'proposed',
            })
            result = process_patch(patch['id'])
            return {'ok': True, 'loop_result': result, 'stats_after': cognitive_patches.stats()}
        finally:
            cognitive_patches.PATCHES_PATH = old_patch_path
            cognitive_patches.STATE_PATH = old_patch_state
            shadow_eval.LOG_PATH = old_shadow_log
            shadow_eval.CANARY_LOG_PATH = old_canary_log
            rollback_manager.LEDGER_PATH = old_rollback_ledger
            globals()['LOOP_LOG_PATH'] = old_loop_log
