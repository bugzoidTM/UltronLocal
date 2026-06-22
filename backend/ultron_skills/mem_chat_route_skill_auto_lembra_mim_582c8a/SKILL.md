---
path: auto/memory_bridge
description: "Roteamento aprendido para reutilizar a skill auto_lembra_mim_582c8a antes de RAG/LLM."
allowed_tools: []
budget:
  max_seconds: 3
risk_level: low
when_to_use: |
  Quando a tarefa atual combina com exemplos anteriores que foram resolvidos por essa skill.
success_checks: []
tags:
  - "chat"
  - "learned"
  - "autoreflex"
  - "skill_auto_lembra_mim_582c8a"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Reutilizar skill auto_lembra_mim_582c8a

Roteamento aprendido para reutilizar a skill auto_lembra_mim_582c8a antes de RAG/LLM.

## Instruções

Consultar e executar a skill auto_lembra_mim_582c8a; se falhar, continuar o pipeline cognitivo normal.

## Exemplos observados

- você lembra de mim?

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-route-skill-auto-lembra-mim-582c8a' (success_count=6, confidence=0.960).*
