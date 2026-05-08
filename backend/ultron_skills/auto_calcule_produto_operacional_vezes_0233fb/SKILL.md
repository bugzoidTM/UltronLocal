---
path: auto/generated
description: "Generated from real chat route using local_reasoning/local_logic."
allowed_tools: []
budget:
  max_seconds: 2
risk_level: low
when_to_use: |
  Use when a chat request shares operational tokens with: calcule, operacional, produto, vezes.
  Preferred local module: local_reasoning. Preferred strategy: local_logic.
success_checks: []
tags:
  - generated
  - chat
  - module_local_reasoning
  - calcule
  - operacional
  - produto
  - vezes
enabled: true
version: 1.0.0
author: skill_evolution
---

# auto_calcule_produto_operacional_vezes_0233fb

Generated from a real chat interaction after replay validation.

Execution is deterministic: the runtime rechecks local symbolic, local reasoning,
cognitive response and cache paths before any LLM fallback is considered.
