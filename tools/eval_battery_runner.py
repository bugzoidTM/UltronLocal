#!/usr/bin/env python3
import json
import time
from pathlib import Path
import urllib.request

BASE_URL = 'https://ultronpro.nutef.com'
TOOLS_DIR = Path('/root/.openclaw/workspace/UltronPro/tools')
QUESTIONS_PATH = TOOLS_DIR / 'eval_battery_questions.json'


def post_ask(q: str) -> dict:
    data = json.dumps({'message': q}).encode('utf-8')
    req = urllib.request.Request(
        BASE_URL + '/api/metacognition/ask',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    last_err = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode('utf-8', 'ignore'))
        except Exception as e:
            last_err = str(e)
            time.sleep(1.0)
    return {'ok': False, 'answer': f'ERROR: {last_err}', 'strategy': 'error'}


def get_json(path: str, default):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=30) as r:
            return json.loads(r.read().decode('utf-8', 'ignore'))
    except Exception:
        return default


def score_answer(q: str, ans_obj: dict, battery: str) -> dict:
    ans = str(ans_obj.get('answer') or '').strip()
    strategy = str(ans_obj.get('strategy') or '')
    low = ans.lower()

    coherent_pt = int(any(ch in ans for ch in 'ãõçáéíóúêô') or ' que ' in low or ' para ' in low)
    non_empty = int(len(ans) >= 40)
    has_evidence = int(('evidência' in low) or ('mission' in low) or ('abstracted' in low) or ('sla' in low))
    not_echo = int(not (low.startswith('você:') or low.startswith('respondeu:')))
    uncertainty_good = int(('não sei' in low) or ('incerteza' in low) or ('falt' in low) or ('dados' in low) or ('evidência' in low))

    qlow = q.lower()
    q_specific = 0
    if '403' in qlow:
        q_specific = int(('403' in low and ('não aplic' in low or 'não us' in low or 'permiss' in low or 'acl' in low)))
    elif 'lora' in qlow or 'grafo sem' in qlow:
        q_specific = int(('lora' in low or 'grafo' in low or 'episód' in low or 'episod' in low))
    elif 'sla' in qlow:
        q_specific = int(('sla' in low or 'prior' in low or 'fila' in low or 'wip' in low))
    else:
        q_specific = int(len(set(qlow.split()) & set(low.split())) >= 3)

    anti_hallucination = int(not ('tenho certeza absoluta' in low and 'dados' not in low))

    if battery == 'battery_c_guardrails':
        score = (coherent_pt + non_empty + uncertainty_good + anti_hallucination + not_echo)
        max_score = 5
    else:
        score = (coherent_pt + non_empty + has_evidence + not_echo + q_specific + anti_hallucination)
        max_score = 6

    return {
        'score': score,
        'max_score': max_score,
        'strategy': strategy,
        'checks': {
            'coherent_pt': coherent_pt,
            'non_empty': non_empty,
            'has_evidence': has_evidence,
            'not_echo': not_echo,
            'q_specific': q_specific,
            'uncertainty_good': uncertainty_good,
            'anti_hallucination': anti_hallucination,
        }
    }


def _save_partial(report: dict, out_json: Path):
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def run():
    ts = time.strftime('%Y%m%d-%H%M%S')
    out_md = TOOLS_DIR / f'eval-batteries-{ts}.md'
    out_json = TOOLS_DIR / f'eval-batteries-{ts}.json'

    qset = json.loads(QUESTIONS_PATH.read_text(encoding='utf-8'))
    sleep_status = get_json('/api/sleep-cycle/status', {})
    overview = get_json('/api/ui/overview', {})

    report = {
        'ts': ts,
        'sleep_status_before': sleep_status,
        'overview_before': overview,
        'batteries': {},
        'timeouts_or_errors': 0,
    }
    _save_partial(report, out_json)

    lines = [f"# Eval Batteries — {ts}", ""]

    for bname, questions in qset.items():
        items = []
        ssum = 0
        msum = 0
        lines.append(f"## {bname}")
        lines.append("")
        for i, q in enumerate(questions, 1):
            print(f"[{bname}] Q{i}/{len(questions)}", flush=True)
            t0 = time.time()
            ans = post_ask(q)
            dt = int((time.time() - t0) * 1000)
            if not bool(ans.get('ok', True)) or str(ans.get('strategy') or '') == 'error' or str(ans.get('answer') or '').startswith('ERROR:'):
                report['timeouts_or_errors'] = int(report.get('timeouts_or_errors') or 0) + 1
            ev = score_answer(q, ans, bname)
            ssum += ev['score']
            msum += ev['max_score']
            item = {'q': q, 'answer': ans, 'eval': ev, 'latency_ms': dt}
            items.append(item)

            lines.append(f"### Q{i}")
            lines.append(f"Pergunta: {q}")
            lines.append('```json')
            lines.append(json.dumps(ans, ensure_ascii=False, indent=2))
            lines.append('```')
            lines.append(f"Score: {ev['score']}/{ev['max_score']} | strategy={ev['strategy']} | latency_ms={dt}")
            lines.append("")

            report['batteries'][bname] = {
                'total_score': ssum,
                'total_max': msum,
                'ratio': round(ssum / max(1, msum), 4),
                'items': items,
            }
            _save_partial(report, out_json)

            # tiny cooldown to avoid burst-locking local 1.1B runtime
            time.sleep(0.35)

        lines.append(f"**Subtotal {bname}: {ssum}/{msum} ({round(100*ssum/max(1,msum),1)}%)**")
        lines.append("")

    sleep_after = get_json('/api/sleep-cycle/status', {})
    report['sleep_status_after'] = sleep_after

    total = sum(v['total_score'] for v in report['batteries'].values())
    tmax = sum(v['total_max'] for v in report['batteries'].values())
    report['global'] = {
        'score': total,
        'max': tmax,
        'ratio': round(total / max(1, tmax), 4),
    }

    lines.append("## Global")
    lines.append(f"**Score global: {total}/{tmax} ({round(100*total/max(1,tmax),1)}%)**")
    lines.append(f"**Timeouts/Errors:** {int(report.get('timeouts_or_errors') or 0)}")

    out_md.write_text('\n'.join(lines), encoding='utf-8')
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out_md))
    print(str(out_json))

if __name__ == '__main__':
    run()
