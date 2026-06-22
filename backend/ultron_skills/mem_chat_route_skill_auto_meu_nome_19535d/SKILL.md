---
path: auto/memory_bridge
description: "Roteamento aprendido para reutilizar a skill auto_meu_nome_19535d antes de RAG/LLM."
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
  - "skill_auto_meu_nome_19535d"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Reutilizar skill auto_meu_nome_19535d

Roteamento aprendido para reutilizar a skill auto_meu_nome_19535d antes de RAG/LLM.

## Instruções

Consultar e executar a skill auto_meu_nome_19535d; se falhar, continuar o pipeline cognitivo normal.

## Exemplos observados

- qual o nome do sistema?

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-route-skill-auto-meu-nome-19535d' (success_count=6, confidence=0.960).*
