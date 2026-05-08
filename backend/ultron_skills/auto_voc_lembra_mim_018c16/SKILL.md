---
path: auto/generated
description: "Generated from real chat route using dialogue_reference/non_llm_dialogue_reference."
allowed_tools: []
budget:
  max_seconds: 2
risk_level: low
when_to_use: |
  Use when a chat request shares operational tokens with: lembra, mim, voc.
  Preferred local module: dialogue_reference. Preferred strategy: non_llm_dialogue_reference.
success_checks: []
tags:
  - generated
  - chat
  - module_dialogue_reference
  - lembra
  - mim
  - voc
enabled: true
version: 1.0.0
author: skill_evolution
---

# auto_voc_lembra_mim_018c16

Generated from a real chat interaction after replay validation.

Execution is deterministic: the runtime rechecks local symbolic, local reasoning,
cognitive response and cache paths before any LLM fallback is considered.
