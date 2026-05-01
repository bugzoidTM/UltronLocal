---
description: Diagnosticar e corrigir erros de código
version: 1.0.0
author: ultronpro
tags:
  - debug
  - error
  - fix
  - troubleshooting
  - diagnostic
allowed_tools:
  - sandbox.execute
  - rag.search
  - graph.add_triple
  - memory.remember
risk_level: high
budget:
  max_seconds: 120
  max_calls: 15
  max_cost_usd: 0.10
when_to_use: |
  Use este skill quando:
  - Usuário reportar um erro
  - Detectar exception/stacktrace
  - Sistema reportar falha
  - Log mostrar comportamento inesperado
  - Bug conhecido precisar de correção
path: debug_error
hooks:
  before: analisar_stacktrace
  after: documentar_solucao
success_checks:
  - erro foi identificado
  - causa raiz localizada
  - correção sugerida ou aplicada
enabled: true
---

# Debug Error Skill

Diagnostic errors systematically and find solutions.

## Fluxo de Debug

1. **Coletar Contexto**
   - Stack trace completo
   - Logs relacionados
   - Estado do sistema
   - Histórico de mudanças

2. **Analisar Erro**
   - Tipo de exception
   - Linha do código
   - Variáveis envolvidas
   - Condições que触发

3. **Buscar Soluções**
   - Consultar RAG para erros similares
   - Buscar no grafo causal
   - Verificar memória de erros passados

4. **Propor/Corrigir**
   - Sugerir mudança de código
   - Aplicar correção se seguro
   - Documentar no grafo causal

## Padrões de Erro

### Runtime Errors
- NullPointerException
- IndexOutOfBounds
- TypeError
- ImportError

### Logic Errors
- Off-by-one
- Race condition
- Memory leak

### System Errors
- Connection timeout
- Resource exhaustion
- Permission denied
