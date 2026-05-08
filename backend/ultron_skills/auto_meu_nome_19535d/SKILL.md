---
path: auto/generated
description: "Generated from real chat route using local_reasoning/local_facts."
allowed_tools: []
budget:
  max_seconds: 2
risk_level: low
when_to_use: |
  Use when a chat request shares operational tokens with: meu, nome.
  Preferred local module: local_reasoning. Preferred strategy: local_facts.
success_checks: []
tags:
  - generated
  - chat
  - module_local_reasoning
  - meu
  - nome
enabled: true
version: 1.0.0
author: skill_evolution
---

# auto_meu_nome_19535d

Generated from a real chat interaction after replay validation.

Execution is deterministic: the runtime rechecks local symbolic, local reasoning,
cognitive response and cache paths before any LLM fallback is considered.
