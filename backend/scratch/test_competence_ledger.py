# -*- coding: utf-8 -*-
"""
Testa o Competence Ledger: classificação de intents e templates adaptativos.
Roda offline (sem servidor).
"""
import sys
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ultronpro.skill_memory_bridge import (
    _classify_mem_intent,
    _render_adaptive_smalltalk,
    _current_period,
    _COMPETENCE_LEDGER,
)

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


print("\n=== COMPETENCE LEDGER: Classificação de Intents ===\n")

# ─── Smalltalk ──────────────────────────────────────────────────────────────
skill_greeting = {"name": "chat-intent-greeting", "tags": ["greeting", "saudacao"]}
skill_thanks = {"name": "chat-intent-thanks", "tags": ["thanks"]}
skill_farewell = {"name": "chat-intent-farewell", "tags": ["farewell", "despedida"]}

check("Greeting → smalltalk", _classify_mem_intent(skill_greeting) == "smalltalk",
      _classify_mem_intent(skill_greeting))
check("Thanks → smalltalk", _classify_mem_intent(skill_thanks) == "smalltalk",
      _classify_mem_intent(skill_thanks))
check("Farewell → smalltalk", _classify_mem_intent(skill_farewell) == "smalltalk",
      _classify_mem_intent(skill_farewell))

# ─── Resolver ───────────────────────────────────────────────────────────────
skill_math = {"name": "chat-route-local-math", "tags": ["math", "calcul"]}
skill_translation = {"name": "chat-intent-translation", "tags": ["translation"]}
skill_logic = {"name": "chat-route-logic", "tags": ["logic", "logica"]}
skill_local_env = {"name": "local-environment-protocols", "tags": ["local_env"]}

check("Math → resolver", _classify_mem_intent(skill_math) == "resolver",
      _classify_mem_intent(skill_math))
check("Translation → resolver", _classify_mem_intent(skill_translation) == "resolver",
      _classify_mem_intent(skill_translation))
check("Logic → resolver", _classify_mem_intent(skill_logic) == "resolver",
      _classify_mem_intent(skill_logic))
check("Local env → resolver", _classify_mem_intent(skill_local_env) == "resolver",
      _classify_mem_intent(skill_local_env))

# ─── Open ────────────────────────────────────────────────────────────────────
skill_autobio = {"name": "chat-route-autobiographical-creation", "tags": ["autobio"]}
skill_web = {"name": "chat-route-skill-web-search", "tags": ["web"]}
skill_unknown = {"name": "mem-random-topic", "tags": []}

check("Autobiographical → open", _classify_mem_intent(skill_autobio) == "open",
      _classify_mem_intent(skill_autobio))
check("Web search → open", _classify_mem_intent(skill_web) == "open",
      _classify_mem_intent(skill_web))
check("Unknown skill → open", _classify_mem_intent(skill_unknown) == "open",
      _classify_mem_intent(skill_unknown))

print(f"\n=== TEMPLATES ADAPTATIVOS ===\n")
print(f"  {INFO} Período atual do sistema: {_current_period()}")

# Período explícito na tarefa — deve usar o da tarefa, não do relógio
output = _render_adaptive_smalltalk("ola bom dia", skill_greeting)
check("'bom dia' → resposta tem 'Bom dia'",
      output is not None and "Bom dia" in output, output)

output = _render_adaptive_smalltalk("boa noite", skill_greeting)
check("'boa noite' → resposta tem 'Boa noite'",
      output is not None and "Boa noite" in output, output)

output = _render_adaptive_smalltalk("boa tarde", skill_greeting)
check("'boa tarde' → resposta tem 'Boa tarde'",
      output is not None and "Boa tarde" in output, output)

# Saudação genérica usa período do sistema (não testa valor fixo)
output = _render_adaptive_smalltalk("oi", skill_greeting)
period = _current_period()
valid_greetings = {"morning": "Bom dia", "afternoon": "Boa tarde", "evening": "Boa noite"}
expected_word = valid_greetings[period]
check(f"'oi' → período={period}, resposta contém '{expected_word}'",
      output is not None and expected_word in output, output)

# Thanks
output = _render_adaptive_smalltalk("obrigado", skill_thanks)
check("'obrigado' → template de thanks",
      output is not None and len(output) > 2, output)

# Farewell
output = _render_adaptive_smalltalk("tchau", skill_farewell)
check("'tchau' → template de despedida",
      output is not None and len(output) > 2, output)

# Garantia: não copia exemplo antigo (templates são fixos/curtos)
output_greeting = _render_adaptive_smalltalk("ola", skill_greeting)
check("Template não contém '*Baseado em interação anterior*'",
      output_greeting is not None and "Baseado em" not in output_greeting, output_greeting)

# Garantia: smalltalk de math não cai em template
output_math = _render_adaptive_smalltalk("quanto é 2+2", skill_math)
print(f"  {INFO} Math skill via render_adaptive_smalltalk (deve ser None): {output_math}")
# skill_math é resolver, não chega a chamar render — mas se chamar, não deve dar template de saudação

print(f"\n{'='*60}")
print(f"  RESULTADO: {passed} PASS / {failed} FAIL")
print(f"{'='*60}\n")

if failed > 0:
    sys.exit(1)
