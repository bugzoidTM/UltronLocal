---
path: auto/memory_bridge
description: "Reutilizar a rota local local_math para mensagens semelhantes antes de acionar raciocinio caro."
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
  - "local_math"
  - "pt-BR"
  - "memory_bridge"
enabled: true
version: 1.0.0
author: skill_memory_bridge
---

# Rota local local_math

Reutilizar a rota local local_math para mensagens semelhantes antes de acionar raciocinio caro.

## Instruções

Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Exemplos observados

- quanto e 2+2?
- calcule 12 vezes 7
- quanto e 10 dividido por 2?
- quanto e 9+1?
- calcule 6 vezes 7

*Materializada automaticamente via skill_memory_bridge a partir de skill_memory 'chat-route-local-math' (success_count=11, confidence=0.960).*
