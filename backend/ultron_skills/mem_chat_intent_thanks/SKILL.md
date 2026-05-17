---
path: auto/memory_bridge
description: "Reconhecer e resolver rapidamente interacoes de chat do tipo thanks."
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
  - "intent_thanks"
  - "chat_stream"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Chat intent thanks

Reconhecer e resolver rapidamente interacoes de chat do tipo thanks.

## Instruções

Classifique a mensagem pela skill aprendida, responda por rota deterministica e registre o episodio. Use LLM apenas se a skill nao tiver confianca suficiente.

## Exemplos observados

- A manga 16 está muito verde. Como resolver?
- A manga 17 está muito verde. Como resolver?
- A manga 18 está muito verde. Como resolver?
- A manga 19 está muito verde. Como resolver?
- A manga 20 está muito verde. Como resolver?

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-intent-thanks' (success_count=66, confidence=0.960).*
