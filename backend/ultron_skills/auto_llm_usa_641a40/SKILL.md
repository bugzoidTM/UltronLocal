---
path: auto/generated
description: "Generated from real chat route using skills/skill_code_review."
allowed_tools: []
budget:
  max_seconds: 2
risk_level: low
when_to_use: |
  Use when a chat request shares operational tokens with: llm, usa.
  Preferred local module: skills. Preferred strategy: skill_code_review.
success_checks: []
tags:
  - generated
  - chat
  - module_skills
  - llm
  - usa
enabled: true
version: 1.0.0
author: skill_evolution
---

# auto_llm_usa_641a40

Generated from a real chat interaction after replay validation.

Execution is deterministic: the runtime rechecks local symbolic, local reasoning,
cognitive response and cache paths before any LLM fallback is considered.
