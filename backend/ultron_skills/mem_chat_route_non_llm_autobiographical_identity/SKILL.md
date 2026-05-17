---
path: auto/memory_bridge
description: "Reutilizar a rota local non_llm_autobiographical_identity para mensagens semelhantes antes de acionar raciocinio caro."
allowed_tools: []
budget:
  max_seconds: 3
risk_level: low
when_to_use: |
  Quando a mensagem atual compartilha estrutura e intencao com episodios bem-sucedidos dessa rota.
success_checks: []
tags:
  - "chat"
  - "learned"
  - "autoreflex"
  - "non_llm_autobiographical_identity"
  - "chat_stream"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Rota local non_llm_autobiographical_identity

Reutilizar a rota local non_llm_autobiographical_identity para mensagens semelhantes antes de acionar raciocinio caro.

## Instruções

Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Exemplos observados

- qual seu nome?
- mas seu fundador tem um nome?
- como é seu nome?
- mas qual o nome de quem te criou?
- você nao sabe o nome de quem te fez?

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-route-non-llm-autobiographical-identity' (success_count=9, confidence=0.960).*
