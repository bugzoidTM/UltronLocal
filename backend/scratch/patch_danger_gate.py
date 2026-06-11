"""
patch_danger_gate.py — Integra local_env_danger_gate em pre_causal_router.py
e em answer_pre_causal para retornar recusa estruturada.
"""
import re
import sys

ROUTER = 'd:/sistemas/UltronPro/backend/ultronpro/pre_causal_router.py'

with open(ROUTER, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# ── 1. Adiciona import no topo ─────────────────────────────────────────────────
IMPORT_ANCHOR = 'from __future__ import annotations'
IMPORT_ADDITION = '''from __future__ import annotations

try:
    from ultronpro.local_env_danger_gate import classify_danger as _classify_danger
except Exception:
    _classify_danger = None  # type: ignore'''

if '_classify_danger' not in content:
    content = content.replace(IMPORT_ANCHOR, IMPORT_ADDITION, 1)
    print("OK: import adicionado")
else:
    print("SKIP: import já existe")

# ── 2. Injeta o gate após o bloco de hacking ─────────────────────────────────
ANCHOR = '        return _decision("safety_risk", 0.97, "safety", "hacking_request")\n    local_env_decision'
REPLACEMENT = '''        return _decision("safety_risk", 0.97, "safety", "hacking_request")
    # ── Danger gate: ações destrutivas no ambiente local ─────────────────────
    # Este gate é chamado ANTES do _local_environment_decision e ANTES do LLM.
    # Ações classificadas como IRREVERSIBLE_DESTRUCTIVE ou REVERSIBLE_RISKY
    # recebem recusa estruturada por contrato, não por incerteza epistêmica.
    if _classify_danger is not None:
        _dg = _classify_danger(query)
        if _dg is not None:
            return _decision(
                f"local_env_danger_{_dg.tier.lower()}",
                0.99,
                "local_env_danger",
                f"danger_gate:{_dg.matched_pattern}",
            )
    local_env_decision'''

if 'local_env_danger_' not in content:
    if ANCHOR in content:
        content = content.replace(ANCHOR, REPLACEMENT, 1)
        print("OK: gate injetado em classify_pre_causal")
    else:
        print("ERRO: âncora não encontrada em classify_pre_causal", file=sys.stderr)
        sys.exit(1)
else:
    print("SKIP: gate já integrado em classify_pre_causal")

# ── 3. Injeta tratamento em answer_pre_causal ─────────────────────────────────
# Localiza a função answer_pre_causal e adiciona o branch de danger gate
# antes de chamar qualquer LLM/memória.
ANSWER_ANCHOR = 'async def answer_pre_causal('
ANSWER_DANGER_CHECK = '''    # ── Danger gate check ────────────────────────────────────────────────────
    if _classify_danger is not None:
        _dg_ans = _classify_danger(query)
        if _dg_ans is not None:
            _dg_dec = _decision(
                f"local_env_danger_{_dg_ans.tier.lower()}",
                0.99,
                "local_env_danger",
                f"danger_gate:{_dg_ans.matched_pattern}",
            )
            return PreCausalAnswer(True, _dg_ans.refusal, _dg_dec)
'''

# Find the start of answer_pre_causal body
ans_fn_pos = content.find(ANSWER_ANCHOR)
if ans_fn_pos == -1:
    print("ERRO: answer_pre_causal não encontrada", file=sys.stderr)
    sys.exit(1)

# Find first line of function body (after the def signature and docstring)
# Look for the first real statement after 'decision = classify_pre_causal'
CLASSIFY_CALL_ANCHOR = '    decision = classify_pre_causal('
classify_pos = content.find(CLASSIFY_CALL_ANCHOR, ans_fn_pos)
if classify_pos == -1:
    print("ERRO: classify_pre_causal call não encontrada em answer_pre_causal", file=sys.stderr)
    sys.exit(1)

if 'danger_gate check' not in content[ans_fn_pos:classify_pos]:
    content = content[:classify_pos] + ANSWER_DANGER_CHECK + content[classify_pos:]
    print("OK: danger gate check injetado em answer_pre_causal")
else:
    print("SKIP: danger gate check já existe em answer_pre_causal")

with open(ROUTER, 'w', encoding='utf-8') as f:
    f.write(content)

print("DONE")
