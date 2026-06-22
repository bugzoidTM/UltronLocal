---
path: auto/memory_bridge
description: "Roteamento aprendido para reutilizar a skill auto_risco_executar_comando_com_pouca_01a75f antes de RAG/LLM."
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
  - "skill_auto_risco_executar_comando_com_pouca_01a75f"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Reutilizar skill auto_risco_executar_comando_com_pouca_01a75f

Roteamento aprendido para reutilizar a skill auto_risco_executar_comando_com_pouca_01a75f antes de RAG/LLM.

## Instruções

Consultar e executar a skill auto_risco_executar_comando_com_pouca_01a75f; se falhar, continuar o pipeline cognitivo normal.

## Exemplos observados

- qual o risco de executar um comando com pouca memoria?

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-route-skill-auto-risco-executar-comando-com-pouca-01a75f' (success_count=5, confidence=0.960).*
