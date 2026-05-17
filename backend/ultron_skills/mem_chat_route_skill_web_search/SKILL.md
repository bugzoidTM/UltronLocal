---
path: auto/memory_bridge
description: "Roteamento aprendido para reutilizar a skill web_search antes de RAG/LLM."
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
  - "skill_web_search"
  - "chat_stream"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Reutilizar skill web_search

Roteamento aprendido para reutilizar a skill web_search antes de RAG/LLM.

## Instruções

Consultar e executar a skill web_search; se falhar, continuar o pipeline cognitivo normal.

## Exemplos observados

- Qual é a capital do país número 16 na lista da ONU?
- Qual é a capital do país número 17 na lista da ONU?
- Qual é a capital do país número 18 na lista da ONU?
- Qual é a capital do país número 19 na lista da ONU?
- Qual é a capital do país número 20 na lista da ONU?

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-route-skill-web-search' (success_count=65, confidence=0.960).*
