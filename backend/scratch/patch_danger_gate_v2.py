"""
patch_danger_gate_v2.py — Versão robusta de integração do danger gate.
Usa busca por linha, não por substring exata, para lidar com CRLF.
"""
import sys

ROUTER = 'd:/sistemas/UltronPro/backend/ultronpro/pre_causal_router.py'

with open(ROUTER, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

print(f"Total linhas: {len(lines)}")

# ── 1. Injeção em classify_pre_causal ────────────────────────────────────────
# Encontra: return _decision("safety_risk", 0.97, "safety", "hacking_request")
# e insere o gate logo depois

GATE_CLASSIFY = [
    '    # ── Danger gate: acoes destrutivas no ambiente local ─────────────────\n',
    '    # Chamado ANTES do LLM. Acoes IRREVERSIBLE_DESTRUCTIVE sao bloqueadas\n',
    '    # por contrato, nao por incerteza epistemica do modelo.\n',
    '    if _classify_danger is not None:\n',
    '        _dg = _classify_danger(query)\n',
    '        if _dg is not None:\n',
    '            return _decision(\n',
    '                f"local_env_danger_{_dg.tier.lower()}",\n',
    '                0.99,\n',
    '                "local_env_danger",\n',
    '                f"danger_gate:{_dg.matched_pattern}",\n',
    '            )\n',
]

classify_injected = False
for i, line in enumerate(lines):
    if '0.97, "safety", "hacking_request"' in line and not classify_injected:
        # Verifica se já foi injetado
        next_lines = ''.join(lines[i+1:i+5])
        if '_classify_danger' not in next_lines and 'danger_gate' not in next_lines:
            lines = lines[:i+1] + GATE_CLASSIFY + lines[i+1:]
            classify_injected = True
            print(f"OK: gate injetado em classify_pre_causal após linha {i+1}")
        else:
            classify_injected = True
            print("SKIP: gate classify já existe")
        break

if not classify_injected:
    print("ERRO: âncora de hacking não encontrada", file=sys.stderr)

# ── 2. Injeção em answer_pre_causal ──────────────────────────────────────────
# Encontra: decision = classify_pre_causal(
# e insere o danger check ANTES

GATE_ANSWER = [
    '    # ── Danger gate check (antes de qualquer LLM) ─────────────────────────\n',
    '    if _classify_danger is not None:\n',
    '        _dg_ans = _classify_danger(query)\n',
    '        if _dg_ans is not None:\n',
    '            from dataclasses import asdict\n',
    '            _dg_dec = _decision(\n',
    '                f"local_env_danger_{_dg_ans.tier.lower()}",\n',
    '                0.99,\n',
    '                "local_env_danger",\n',
    '                f"danger_gate:{_dg_ans.matched_pattern}",\n',
    '            )\n',
    '            return PreCausalAnswer(True, _dg_ans.refusal, _dg_dec)\n',
]

# Primeiro encontra answer_pre_causal
in_answer_fn = False
answer_injected = False
for i, line in enumerate(lines):
    if 'async def answer_pre_causal(' in line:
        in_answer_fn = True
    if in_answer_fn and 'decision = classify_pre_causal(' in line:
        next_lines = ''.join(lines[max(0,i-10):i])
        if '_dg_ans' not in next_lines:
            lines = lines[:i] + GATE_ANSWER + lines[i:]
            answer_injected = True
            print(f"OK: danger gate answer injetado antes da linha {i+1}")
        else:
            answer_injected = True
            print("SKIP: gate answer já existe")
        break

if not answer_injected:
    print("AVISO: classify_pre_causal call não encontrada em answer_pre_causal")

with open(ROUTER, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"DONE. Total linhas agora: {len(lines)}")
