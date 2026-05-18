---
path: auto/memory_bridge
description: "Reutilizar a rota local non_llm_autobiographical_state para mensagens semelhantes antes de acionar raciocinio caro."
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
  - "non_llm_autobiographical_state"
  - "chat_skill_memory"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Rota local non_llm_autobiographical_state

Reutilizar a rota local non_llm_autobiographical_state para mensagens semelhantes antes de acionar raciocinio caro.

## Instruções

Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Exemplos observados

- resuma seu estado operacional atual
- qual e seu estado operacional agora
- como esta seu estado cognitivo operacional
- resuma sua situacao interna atual

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-route-non-llm-autobiographical-state' (success_count=9, confidence=0.960).*
