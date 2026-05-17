# -*- coding: utf-8 -*-
"""
Testa o avaliador semântico de qualidade de respostas mem_*.
Roda offline (sem servidor), importando diretamente os módulos.
"""
import sys
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[96mINFO\033[0m"

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    status = PASS if cond else FAIL
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail else ""))
    return cond


print("\n=== TESTE DO AVALIADOR SEMÂNTICO DE QUALIDADE ===\n")

from ultronpro.skill_memory_bridge import (
    _evaluate_response_quality,
    _build_deterministic_output,
    _rule_greeting,
    _rule_thanks,
    _match_domain_rules,
)

# ── 1. Regras de domínio: greeting ──────────────────────────────────────────

print(f"  {INFO} Testando regra de domínio: greeting\n")

# Cenário correto: "bom dia" → resposta com "bom dia"
ok, reason = _rule_greeting("ola bom dia", "Bom dia! Como posso ajudar?")
check("Greeting OK: bom dia → Bom dia", ok, reason)

# Cenário com erro: "bom dia" → resposta com "boa noite"
ok, reason = _rule_greeting("ola bom dia", "Boa noite! Como posso ajudar?")
check("Greeting FAIL: bom dia → Boa noite (deve falhar)", not ok, reason)

# Cenário correto: "boa noite" → resposta com "boa noite"
ok, reason = _rule_greeting("boa noite", "Boa noite!")
check("Greeting OK: boa noite → Boa noite", ok, reason)

# Cenário com erro: "boa noite" → resposta com "bom dia"
ok, reason = _rule_greeting("boa noite", "Bom dia!")
check("Greeting FAIL: boa noite → Bom dia (deve falhar)", not ok, reason)

# Cenário neutro: "ola" sem período → deve aceitar qualquer resposta
ok, reason = _rule_greeting("ola", "Olá! Como posso ajudar?")
check("Greeting OK: saudação genérica aceita qualquer resposta", ok, reason)

# Cenário correto: "boa tarde" → "boa tarde"
ok, reason = _rule_greeting("boa tarde", "Boa tarde!")
check("Greeting OK: boa tarde → Boa tarde", ok, reason)

# Cenário com erro: "boa tarde" → "bom dia"
ok, reason = _rule_greeting("boa tarde", "Bom dia!")
check("Greeting FAIL: boa tarde → Bom dia (deve falhar)", not ok, reason)

# ── 2. Regras de domínio: thanks ────────────────────────────────────────────

print(f"\n  {INFO} Testando regra de domínio: thanks\n")

ok, reason = _rule_thanks("obrigado", "Disponha! Estou aqui para ajudar.")
check("Thanks OK: obrigado → Disponha", ok, reason)

ok, reason = _rule_thanks("valeu", "Por nada!")
check("Thanks OK: valeu → Por nada", ok, reason)

ok, reason = _rule_thanks("obrigado", "")
check("Thanks FAIL: obrigado → resposta vazia (deve falhar)", not ok, reason)

# ── 3. Match de domínio por nome da skill ────────────────────────────────────

print(f"\n  {INFO} Testando match de domínio por nome da skill\n")

skill_greeting = {"name": "chat-intent-greeting", "tags": ["greeting", "saudacao"]}
success, reason = _match_domain_rules("bom dia", "Boa noite!", skill_greeting)
check("Domain match: greeting detectado por nome da skill", success is False, reason)

skill_thanks = {"name": "chat-intent-thanks", "tags": ["thanks"]}
success, reason = _match_domain_rules("obrigado", "Disponha!", skill_thanks)
check("Domain match: thanks detectado por nome da skill", success is True, reason)

skill_math = {"name": "chat-route-local-math", "tags": ["math"]}
success, reason = _match_domain_rules("2+2", "4", skill_math)
check("Domain match: skill sem regra específica retorna None", success is None, reason)

# ── 4. Avaliação completa (_evaluate_response_quality) ───────────────────────

print(f"\n  {INFO} Testando avaliador completo\n")

# Output vazio → falha
q = _evaluate_response_quality("bom dia", "", {"source": "none"}, skill_greeting)
check("Quality: output vazio → success=False", q["success"] is False, q["reason"])

# Greeting correto
q = _evaluate_response_quality(
    "ola bom dia", "Bom dia!",
    {"source": "example", "match_score": 2, "matched_query": "bom dia", "matched_answer": "Bom dia!"},
    skill_greeting,
)
check("Quality: greeting correto → success=True", q["success"] is True, q["reason"])

# Greeting com período invertido
q = _evaluate_response_quality(
    "ola bom dia", "Boa noite!",
    {"source": "example", "match_score": 1, "matched_query": "boa noite", "matched_answer": "Boa noite!"},
    skill_greeting,
)
check("Quality: greeting errado (Boa noite para bom dia) → success=False", q["success"] is False, q["reason"])

# Exemplo com baixo Jaccard (irrelevante)
q = _evaluate_response_quality(
    "como se diz obrigado em francês",
    "Disponha!",
    {"source": "example", "match_score": 1, "matched_query": "obrigado", "matched_answer": "Disponha!"},
    skill_math,  # skill sem regra de domínio
)
check("Quality: Jaccard baixo → success=False", q["success"] is False, q["reason"])

# Fallback por instruções (sem regra de domínio)
q = _evaluate_response_quality(
    "resolva 2+2", "4",
    {"source": "instruction", "match_score": 0, "matched_query": "", "matched_answer": ""},
    skill_math,
)
check("Quality: fallback por instrução → success=True com confiança moderada",
      q["success"] is True and q["confidence"] == 0.5, q["reason"])

# ── 5. _build_deterministic_output retorna tuple ─────────────────────────────

print(f"\n  {INFO} Testando que _build_deterministic_output retorna (str, dict)\n")

skill_data = {
    "instructions": "Responda com saudação adequada.",
    "summary": "Saudações",
    "examples": [
        {"query": "bom dia", "answer_summary": "Bom dia!"},
        {"query": "boa noite", "answer_summary": "Boa noite!"},
    ],
}

output, meta = _build_deterministic_output(skill_data, "ola bom dia")
check("Build output retorna tuple", isinstance(output, str) and isinstance(meta, dict))
check("Build output: source == 'example'", meta["source"] == "example", f"source={meta['source']}")
check("Build output: matched_query contém 'bom dia'",
      "bom dia" in meta.get("matched_query", ""),
      f"matched_query={meta.get('matched_query')}")

output2, meta2 = _build_deterministic_output({"instructions": "Teste", "examples": []}, "qualquer coisa")
check("Build output sem exemplo: source == 'instruction'",
      meta2["source"] == "instruction", f"source={meta2['source']}")

output3, meta3 = _build_deterministic_output({"summary": "Resumo"}, "qualquer coisa")
check("Build output só summary: source == 'summary'",
      meta3["source"] == "summary", f"source={meta3['source']}")

# ── Resumo ───────────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"  RESULTADO: {passed} PASS / {failed} FAIL")
print(f"{'='*60}\n")

if failed > 0:
    sys.exit(1)
