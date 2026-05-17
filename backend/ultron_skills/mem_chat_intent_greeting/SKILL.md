---
path: auto/memory_bridge
description: "Reconhecer e resolver rapidamente interacoes de chat do tipo greeting."
allowed_tools: []
budget:
  max_seconds: 3
risk_level: low
when_to_use: |
  Quando a mensagem do usuario se parece com exemplos anteriores bem-sucedidos dessa intencao.
success_checks: []
tags:
  - "chat"
  - "learned"
  - "autoreflex"
  - "intent_greeting"
  - "chat_stream"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Chat intent greeting

Reconhecer e resolver rapidamente interacoes de chat do tipo greeting.

## Instruções

Classifique a mensagem pela skill aprendida, responda por rota deterministica e registre o episodio. Use LLM apenas se a skill nao tiver confianca suficiente.

## Exemplos observados

- oi
- ola

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-intent-greeting' (success_count=37, confidence=0.960).*
