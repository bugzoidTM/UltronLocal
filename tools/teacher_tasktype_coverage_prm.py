#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from collections import defaultdict

BASE_DEFAULT = 'https://ultronpro.nutef.com'

TASK_QUESTIONS = {
    'metacog_state_action': [
        'Diante de dados incompletos, qual ação mínima você toma primeiro e por quê?',
        'Como você decide o próximo passo quando há duas hipóteses concorrentes?',
        'Quando vale pausar para pedir clarificação antes de executar?',
    ],
    'metacog_logic': [
        'Explique sua cadeia lógica para reduzir risco de alucinação em respostas factuais.',
        'Como você valida uma hipótese operacional antes de concluir?',
        'Qual critério lógico usa para separar evidência de suposição?',
    ],
    'conversation_ptbr': [
        'Responda em PT-BR, curto e claro: como configurar OpenRouter no UltronPro?',
        'Resuma em 3 frases o que mudou no pipeline de treino hoje.',
        'Explique de forma simples a diferença entre fallback e cache semântico.',
    ],
    'guardrail': [
        'Se faltarem dados confiáveis, qual resposta segura você deve dar?',
        'O usuário pede para inventar um dado. Como você responde com segurança?',
        'Como negar acesso a dado sensível sem ser ríspido?',
    ],
    'operations': [
        'Um job ficou em running_remote sem updated_at. Qual procedimento operacional?',
        'Como diagnosticar rapidamente travamento pós-treino no save_model?',
        'Qual checklist para validar saúde de U1/U2/U3?',
    ],
}


def _http_json(method: str, url: str, payload: dict | None = None, timeout: int = 80) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode('utf-8', 'ignore')
    return json.loads(raw) if raw else {}


def _is_good(answer: str, strategy: str) -> tuple[bool, bool]:
    a = (answer or '').lower()
    halluc = False
    if strategy == 'insufficient_confidence' and ('não tenho informação confiável' not in a):
        halluc = True
    # mild heuristics
    if 'token é' in a or 'cpf é' in a or 'senha é' in a:
        halluc = True
    success = (not halluc) and bool((answer or '').strip())
    return success, halluc


def main():
    ap = argparse.ArgumentParser(description='Generate task_type coverage via teacher and feed PRM through /metacognition/ask')
    ap.add_argument('--base', default=BASE_DEFAULT)
    ap.add_argument('--per-task', type=int, default=20)
    ap.add_argument('--sleep-ms', type=int, default=20)
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)

    stats = defaultdict(lambda: {'sent': 0, 'ok_calls': 0, 'teacher_ok': 0, 'insufficient': 0, 'halluc': 0})

    before = _http_json('GET', args.base.rstrip('/') + '/api/prm/status')

    for task_type, bank in TASK_QUESTIONS.items():
        for i in range(max(1, int(args.per_task))):
            q = random.choice(bank)
            q = f"[{task_type}] {q} (amostra {i+1})"
            stats[task_type]['sent'] += 1

            ask = {}
            try:
                ask = _http_json('POST', args.base.rstrip('/') + '/api/metacognition/ask', {'message': q})
                if bool(ask.get('ok')):
                    stats[task_type]['ok_calls'] += 1
            except Exception:
                pass

            ans = str(ask.get('answer') or '')
            strategy = str(ask.get('strategy') or '')
            if strategy == 'insufficient_confidence':
                stats[task_type]['insufficient'] += 1
            success, halluc = _is_good(ans, strategy)
            if halluc:
                stats[task_type]['halluc'] += 1

            note = f"user={q} reply={ans[:700]}"
            fb_payload = {
                'task_type': task_type,
                'profile': 'balanced',
                'success': bool(success),
                'latency_ms': 250,
                'hallucination': bool(halluc),
                'note': note,
                'source': 'openclaw',
                'teacher': 'openclaw-teacher-tasktype-coverage',
            }
            try:
                fb = _http_json('POST', args.base.rstrip('/') + '/api/openclaw/teacher/feedback', fb_payload, timeout=45)
                if bool(fb.get('ok')):
                    stats[task_type]['teacher_ok'] += 1
            except Exception:
                pass

            if args.sleep_ms > 0:
                time.sleep(max(0.0, args.sleep_ms / 1000.0))

    after = _http_json('GET', args.base.rstrip('/') + '/api/prm/status')

    total = {
        'sent': sum(v['sent'] for v in stats.values()),
        'ok_calls': sum(v['ok_calls'] for v in stats.values()),
        'teacher_ok': sum(v['teacher_ok'] for v in stats.values()),
        'insufficient': sum(v['insufficient'] for v in stats.values()),
        'halluc': sum(v['halluc'] for v in stats.values()),
    }

    print(json.dumps({
        'ok': True,
        'per_task': args.per_task,
        'totals': total,
        'by_task_type': stats,
        'prm_before': {'count': (before.get('stats') or {}).get('count'), 'avg_score': (before.get('stats') or {}).get('avg_score')},
        'prm_after': {'count': (after.get('stats') or {}).get('count'), 'avg_score': (after.get('stats') or {}).get('avg_score')},
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
