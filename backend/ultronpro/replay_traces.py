from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import time
import datetime as dt

TRACE_DIR = Path(__file__).resolve().parent.parent / 'data' / 'decision_traces'
REPLAY_DIR = Path(__file__).resolve().parent.parent / 'data' / 'replay'
TRAIN_INC_PATH = REPLAY_DIR / 'train_incremental.jsonl'
HARD_NEG_PATH = REPLAY_DIR / 'hard_negatives.jsonl'
STATE_PATH = REPLAY_DIR / 'replay_state.json'


def _safe(s: Any, n: int = 1200) -> str:
    t = str(s or '').strip()
    return t[:n]


def _day_path(day: dt.date | None = None) -> Path:
    d = day or dt.datetime.now(dt.timezone.utc).date()
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    return TRACE_DIR / f'{d.isoformat()}.jsonl'


def append_trace(item: dict[str, Any]) -> dict[str, Any]:
    p = _day_path()

    route = _safe(item.get('route') or 'accept_local', 64)
    verdict = item.get('arbiter_verdict')
    outcome = _safe(item.get('final_outcome') or 'unknown', 64)
    label = item.get('feedback_label')

    # auto-label fallback (so traces are usable even without explicit human labels)
    if label is None:
        vv = str(verdict or '').lower().strip()
        oo = str(outcome or '').lower().strip()
        if vv == 'approve':
            label = 'good'
        elif vv in ('reject', 'revise'):
            label = 'bad'
        elif route == 'ask_clarification' or 'unavailable' in oo or 'fail' in oo or 'error' in oo:
            label = 'bad'
        elif route in ('accept_local', 'handoff_backbone') and oo in ('success', 'completed', 'ok'):
            label = 'good'
        else:
            label = 'pending'

    row = {
        'trace_id': _safe(item.get('trace_id') or f"trc_{int(time.time()*1000)}", 96),
        'ts': int(item.get('ts') or time.time()),
        'task_type': _safe(item.get('task_type') or 'assistant', 64),
        'risk_class': _safe(item.get('risk_class') or 'medium', 24),
        'input': _safe(item.get('input') or '', 2500),
        'output_local': _safe(item.get('output_local') or '', 2500),
        'route': route,
        'arbiter_verdict': verdict,
        'final_outcome': outcome,
        'feedback_label': label,
        'meta': item.get('meta') if isinstance(item.get('meta'), dict) else {},
    }
    with p.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return {'ok': True, 'path': str(p), 'trace_id': row['trace_id']}


def _load_traces(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for ln in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def _rows_to_train(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pos: list[dict[str, Any]] = []
    neg: list[dict[str, Any]] = []
    for r in rows:
        inp = _safe(r.get('input'), 1500)
        out = _safe(r.get('output_local'), 900)
        if not inp or not out:
            continue
        label = r.get('feedback_label')
        route = str(r.get('route') or '')
        outcome = str(r.get('final_outcome') or '')
        is_good = False
        is_bad = False
        if isinstance(label, bool):
            is_good = bool(label)
            is_bad = not bool(label)
        elif isinstance(label, str):
            ll = label.strip().lower()
            if ll in ('good', 'accept', 'accepted', 'ok', 'true', '1'):
                is_good = True
            if ll in ('bad', 'reject', 'rejected', 'fail', 'false', '0'):
                is_bad = True
        else:
            # weak heuristic fallback for unlabeled traces
            is_bad = (route == 'ask_clarification') or ('fail' in outcome) or ('unavailable' in outcome)
            is_good = not is_bad

        if is_good:
            pos.append({
                'instruction': f"Task: {str(r.get('task_type') or 'assistant')}. User said: {inp}. Respond in pt-BR, concise, grounded.",
                'output': out,
                'task_type': str(r.get('task_type') or 'assistant'),
                'domain': 'operations',
                'label': 'ok_real',
            })
        if is_bad:
            neg.append({
                'instruction': f"Task: {str(r.get('task_type') or 'assistant')}. User said: {inp}. Avoid hallucinations and ask one objective clarification when needed.",
                'output': "Não tenho dados suficientes para afirmar isso com segurança. Posso confirmar um detalhe objetivo antes de responder?",
                'task_type': str(r.get('task_type') or 'assistant'),
                'domain': 'operations',
                'label': 'hard_fix',
            })
    return pos, neg


def run_replay(day: str | None = None, max_rows: int = 300) -> dict[str, Any]:
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    if day:
        d = dt.date.fromisoformat(day)
    else:
        d = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    src = _day_path(d)
    rows = _load_traces(src)
    if max_rows > 0 and len(rows) > max_rows:
        rows = rows[-max_rows:]

    pos, neg = _rows_to_train(rows)
    train = pos + neg

    label_counts = {'good': 0, 'bad': 0, 'pending': 0}
    for r in rows:
        lb = str(r.get('feedback_label') or 'pending').strip().lower()
        if lb not in label_counts:
            lb = 'pending'
        label_counts[lb] += 1

    with TRAIN_INC_PATH.open('w', encoding='utf-8') as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    with HARD_NEG_PATH.open('w', encoding='utf-8') as f:
        for r in neg:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    st = {
        'ok': True,
        'day': d.isoformat(),
        'source_path': str(src),
        'trace_rows': len(rows),
        'train_rows': len(train),
        'pos_rows': len(pos),
        'hard_neg_rows': len(neg),
        'label_counts': label_counts,
        'train_incremental_path': str(TRAIN_INC_PATH),
        'hard_negatives_path': str(HARD_NEG_PATH),
        'ts': int(time.time()),
    }
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')
    return st


def _eval_trace_path() -> Path:
    p = Path(__file__).resolve().parent.parent / 'data' / 'eval_traces.jsonl'
    if p.exists():
        return p
    alt = Path('/root/.openclaw/workspace/UltronPro/backend/data/eval_traces.jsonl')
    return alt


def replay_thought_chain(max_rows: int = 300, slow_only: bool = False) -> dict[str, Any]:
    p = _eval_trace_path()
    rows: list[dict[str, Any]] = []
    if p.exists():
        for ln in p.read_text(encoding='utf-8', errors='ignore').splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                continue
    if max_rows > 0 and len(rows) > max_rows:
        rows = rows[-max_rows:]

    def _breakpoint(r: dict[str, Any]) -> str:
        st = str(r.get('final_strategy') or '')
        gate = str(r.get('gate_decision') or '')
        lat = r.get('latency_ms')
        if gate in ('block_insufficient', 'insufficient', 'deny') or st == 'insufficient_confidence':
            return 'gate'
        if isinstance(lat, (int, float)) and float(lat) > 10000:
            return 'generation_latency'
        if bool(r.get('symbolic_reasoner_routed')) and st not in ('symbolic_reasoner',):
            return 'symbolic_route_miss'
        if str(r.get('prm_risk') or '').lower() == 'high':
            return 'quality_guard'
        return 'none'

    items = []
    counts: dict[str, int] = {}
    by_module: dict[str, int] = {}
    for r in rows:
        if slow_only and not (isinstance(r.get('latency_ms'), (int, float)) and float(r.get('latency_ms')) > 10000):
            continue
        bp = _breakpoint(r)
        chain = ['classify_input', 'route_strategy', 'generate_answer', 'prm_evaluate', 'gate_finalize']
        break_at = {
            'gate': 'gate_finalize',
            'generation_latency': 'generate_answer',
            'symbolic_route_miss': 'route_strategy',
            'quality_guard': 'prm_evaluate',
            'none': 'none',
        }.get(bp, 'none')
        mod = {
            'gate_finalize': 'gate',
            'generate_answer': 'generator',
            'route_strategy': 'router',
            'prm_evaluate': 'prm',
            'none': 'none',
        }.get(break_at, 'none')
        counts[bp] = counts.get(bp, 0) + 1
        by_module[mod] = by_module.get(mod, 0) + 1
        items.append({
            'request_id': r.get('request_id'),
            'input_class': r.get('input_class'),
            'final_strategy': r.get('final_strategy'),
            'latency_ms': r.get('latency_ms'),
            'prm_risk': r.get('prm_risk'),
            'gate_decision': r.get('gate_decision'),
            'chain': chain,
            'breakpoint': bp,
            'break_at': break_at,
            'break_module': mod,
        })

    return {
        'ok': True,
        'path': str(p),
        'rows_scanned': len(rows),
        'items': items[-120:],
        'breakpoint_counts': counts,
        'break_module_counts': by_module,
        'slow_only': bool(slow_only),
    }


def status() -> dict[str, Any]:
    out: dict[str, Any] = {
        'ok': True,
        'trace_dir': str(TRACE_DIR),
        'replay_dir': str(REPLAY_DIR),
        'today_path': str(_day_path()),
        'train_incremental_path': str(TRAIN_INC_PATH),
        'hard_negatives_path': str(HARD_NEG_PATH),
        'last': None,
    }
    try:
        if STATE_PATH.exists():
            out['last'] = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        out['last'] = None
    return out
