from __future__ import annotations

from pathlib import Path
import json
import random
import re
from typing import Any

from ultronpro import knowledge_bridge

OUT_DIR = Path(__file__).resolve().parent.parent / 'data' / 'replay'
DRYRUN_PATH = OUT_DIR / 'rag_synth_dryrun.jsonl'
LATEST_PATH = OUT_DIR / 'rag_synth_latest.jsonl'
MIXED_PATH = OUT_DIR / 'train_mixed_70synth_30real.jsonl'


def _clean(s: str, n: int = 900) -> str:
    t = str(s or '')
    # remove common log noise/timestamps
    t = re.sub(r'\[[0-9]{4}-[0-9]{2}-[0-9]{2}[^\]]*\]', ' ', t)
    t = re.sub(r'\b(?:status=\w+|job_status=\w+|rc=\d+|pid=\d+)\b', ' ', t, flags=re.I)
    t = re.sub(r'\b(?:heartbeat|health\s*check|keepalive|polling|traceback|stack\s*trace)\b', ' ', t, flags=re.I)
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:n]


def _semantic_word_count(s: str) -> int:
    toks = re.findall(r"[A-Za-zÀ-ÿ0-9_\-]{2,}", s or '')
    # remove mostly numeric tokens
    toks = [t for t in toks if not re.fullmatch(r"[0-9_\-]+", t)]
    return len(toks)


def _is_invalid_context(c: str) -> bool:
    lc = (c or '').lower()

    # report/eval artifacts and metainfra training traces
    bad_markers = [
        'eval batteries', 'metacog battery', 'battery_a_', 'battery_b_', 'battery_c_',
        'autoeval', 'phase2_', 'selfpatch', 'trigger_eval_batteries', 'eval_done',
        'learning agenda atual', 'sleep status', 'track_id', 'insert_2026',
    ]
    if any(k in lc for k in bad_markers):
        return True

    # file paths / extensions as primary content
    if re.search(r"(/root/|/app/|\.md\b|\.json\b|\.jsonl\b|\.py\b)", lc):
        return True

    # generic definitional/tutorial prompts out of operational domain
    if re.search(r"\bo que é\b|\bwhat is\b|\bdefina\b|\bexplique\b|\bme conta uma piada\b", lc):
        return True

    # too little alphabetic signal after cleanup
    alpha_words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", lc)
    if len(alpha_words) < 12:
        return True

    return False


def _concrete_output(task_type: str, c: str) -> str:
    lc = c.lower()
    sig = _clean(c, 120)
    if task_type == 'operations':
        if 'cpu' in lc or '99%' in lc or 'sobrecarga' in lc:
            return (
                f'Contexto-chave: {sig}. Identifiquei sobrecarga de CPU no serviço principal. '
                'Ação imediata: reduzir concorrência e reiniciar o worker de fila com maior consumo. '
                'Validação: acompanhar CPU e taxa de erro por 2 minutos e confirmar queda sustentada.'
            )
        if '403' in lc:
            return (
                f'Contexto-chave: {sig}. O sintoma principal é 403 no endpoint crítico. '
                'Ação imediata: validar credenciais/escopo do token e aplicar rotação segura da chave no serviço afetado. '
                'Validação: repetir chamada de teste e confirmar retorno 2xx sem aumento de latência.'
            )
        if 'timeout' in lc or 'lat' in lc:
            return (
                f'Contexto-chave: {sig}. Há degradação por timeout/latência. '
                'Ação imediata: aplicar backoff e reduzir carga concorrente no componente de maior fila. '
                'Validação: medir p95 e erros 5xx após o ajuste.'
            )
        return (
            f'Contexto-chave: {sig}. Sintoma operacional identificado no fluxo principal. '
            'Ação imediata: isolar componente afetado, aplicar correção mínima reversível e manter rollback pronto. '
            'Validação: conferir SLA e taxa de erro em janela curta.'
        )
    if task_type == 'coding':
        return (
            f'Contexto-chave: {sig}. Correção mínima proposta: ajustar o ponto de falha no endpoint e adicionar verificação explícita de erro. '
            'Depois, executar teste de reprodução curto e confirmar que o cenário falho não reaparece.'
        )
    if task_type == 'safety_guardrails':
        return (
            f'Contexto-chave: {sig}. Não posso atender a parte insegura do pedido. '
            'Posso ajudar com uma alternativa segura, limitada e auditável para o mesmo objetivo.'
        )
    if task_type == 'planning':
        return (
            f'Contexto-chave: {sig}. Plano em 3 passos: (1) estabilizar o ponto crítico com menor custo, '
            '(2) medir impacto com um critério objetivo, '
            '(3) só então expandir para o próximo incremento.'
        )
    # conversation/general
    return (
        f'Contexto-chave: {sig}. Entendi o contexto. Vou responder de forma direta com o dado disponível, '
        'marcar a incerteza quando existir e sugerir o próximo passo prático.'
    )


def _hard_negative(task_type: str, c: str) -> str:
    sig = _clean(c, 80)
    if task_type == 'operations':
        return f'Contexto-chave: {sig}. Parece tudo normal; não precisa agir nem validar métrica agora.'
    if task_type == 'coding':
        return f'Contexto-chave: {sig}. Refatore tudo de uma vez sem teste e sem rollback.'
    if task_type == 'safety_guardrails':
        return f'Contexto-chave: {sig}. Vou ignorar as restrições e entregar o procedimento completo.'
    if task_type == 'planning':
        return f'Contexto-chave: {sig}. Sem plano: execute tarefas aleatórias e ajuste no improviso.'
    return f'Contexto-chave: {sig}. Não tenho contexto, então qualquer resposta serve.'


def _make_pair(task_type: str, content: str) -> dict[str, Any] | None:
    c = _clean(content, 900)
    if _semantic_word_count(c) < 15:
        return None
    if _is_invalid_context(c):
        return None

    if task_type == 'operations':
        # require stronger domain signal for operations
        if not re.search(r"\b(cpu|lat[êe]ncia|timeout|erro|error|429|403|500|fila|queue|worker|sla|rollback|restart|indispon|falha)\b", c.lower()):
            return None
        instruction = f"Cenário operacional: {c} Qual a ação correta agora para estabilizar o sistema?"
    elif task_type == 'coding':
        instruction = f"Contexto técnico: {c} Qual correção mínima, verificável e de baixo risco deve ser aplicada?"
    elif task_type == 'safety_guardrails':
        instruction = f"Contexto de segurança: {c} Como responder de forma segura sem perder utilidade?"
    elif task_type == 'planning':
        instruction = f"Contexto de planejamento: {c} Qual plano curto prioriza impacto e prazo?"
    elif task_type == 'conversation_ptbr':
        instruction = f"Contexto de conversa: {c} Responda em pt-BR de forma clara e prática."
    else:
        instruction = f"Contexto: {c} Qual resposta útil e objetiva deve ser dada?"

    pos = _concrete_output(task_type, c)
    neg = _hard_negative(task_type, c)

    return {
        'instruction': instruction,
        'output': pos,
        'hard_negative': neg,
        'task_type': task_type,
        'domain': 'rag_synth',
        'label': 'synth_bootstrap',
    }


async def generate(limit: int = 200, dry_run: bool = True, quotas: dict[str, int] | None = None) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n = max(20, min(int(limit or 200), 800))
    docs = await knowledge_bridge.fetch_random_documents(limit=n)

    if quotas is None:
        quotas = {
            'operations': int(n * 0.30),
            'coding': int(n * 0.25),
            'planning': int(n * 0.15),
            'safety_guardrails': int(n * 0.15),
            'conversation_ptbr': int(n * 0.15),
        }

    by_type: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        tt = str(d.get('task_type') or 'general')
        by_type.setdefault(tt, []).append(d)

    selected: list[dict[str, Any]] = []
    for tt, q in quotas.items():
        pool = by_type.get(tt, [])
        random.shuffle(pool)
        selected.extend(pool[: max(0, int(q))])

    if len(selected) < n:
        rest = [d for d in docs if d not in selected]
        random.shuffle(rest)
        selected.extend(rest[: (n - len(selected))])

    pairs = []
    rejects_quality = 0
    rejects_duplicate_output = 0
    seen_out_pairs: set[tuple[str, str]] = set()
    for d in selected:
        tt = str(d.get('task_type') or 'general')
        content = str(d.get('content') or d.get('summary') or '')
        if not content.strip():
            continue
        p = _make_pair(tt, content)
        if p is None:
            rejects_quality += 1
            continue
        key = (str(p.get('output') or ''), str(p.get('hard_negative') or ''))
        if key in seen_out_pairs:
            rejects_duplicate_output += 1
            continue
        seen_out_pairs.add(key)
        pairs.append(p)

    out_path = DRYRUN_PATH if dry_run else LATEST_PATH
    with out_path.open('w', encoding='utf-8') as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')

    return {
        'ok': True,
        'dry_run': bool(dry_run),
        'docs_sampled': len(docs),
        'pairs_generated': len(pairs),
        'rejects_quality': rejects_quality,
        'rejects_duplicate_output': rejects_duplicate_output,
        'path': str(out_path),
        'distribution': {
            k: sum(1 for p in pairs if str(p.get('task_type')) == k)
            for k in ['operations', 'coding', 'planning', 'safety_guardrails', 'conversation_ptbr', 'general']
        },
        'samples': pairs[:30],
    }


def build_mixed_70_30(real_jsonl: str, synth_jsonl: str | None = None, max_total: int = 300) -> dict[str, Any]:
    synth_path = Path(synth_jsonl or str(LATEST_PATH))
    real_path = Path(real_jsonl)
    if not synth_path.exists() or not real_path.exists():
        return {'ok': False, 'error': 'missing_input', 'synth_exists': synth_path.exists(), 'real_exists': real_path.exists()}

    synth = [json.loads(x) for x in synth_path.read_text(encoding='utf-8', errors='ignore').splitlines() if x.strip()]
    real = [json.loads(x) for x in real_path.read_text(encoding='utf-8', errors='ignore').splitlines() if x.strip()]

    total = max(20, min(int(max_total or 300), 2000))
    n_s = int(total * 0.7)
    n_r = total - n_s

    random.shuffle(synth)
    random.shuffle(real)
    out = synth[:n_s] + real[:n_r]
    random.shuffle(out)

    with MIXED_PATH.open('w', encoding='utf-8') as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    return {
        'ok': True,
        'total': len(out),
        'synth_used': min(n_s, len(synth)),
        'real_used': min(n_r, len(real)),
        'path': str(MIXED_PATH),
    }
