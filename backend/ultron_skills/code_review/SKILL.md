---
description: Revisar código e identificar problemas potenciais
version: 1.0.0
author: ultronpro
tags:
  - code
  - review
  - quality
  - security
  - linting
allowed_tools:
  - sandbox.execute
  - file.read
  - rag.search
risk_level: medium
budget:
  max_seconds: 60
  max_calls: 10
  max_cost_usd: 0.05
when_to_use: |
  Use este skill quando:
  - Usuário pedir para revisar código
  - Detectar padrões de erro recorrentes
  - Avaliar qualidade de código novo
  - Verificar compliance com padrões do projeto
  - Analisar segurança de código
path: code_review
hooks:
  before: analisar_contexto_projeto
  after: registrar_padroes_encontrados
success_checks:
  - identificou pelo menos 1 issue
  - forneceu sugestões concretas
  - tempo < 60s
enabled: true
---

# Code Review Skill

Revisa código de forma sistemática, identificando:
- Bugs potenciais
- Problemas de performance
- Issues de segurança
- Violações de estilo
- Code smells

## Fluxo de Revisão

1. **Parse do Código**
   - Identificar linguagem
   - Extrair funções/classes
   - Mapear imports

2. **Análise Estática**
   - Verificar padrões conhecidos
   - Buscar code smells
   - Validar estilo

3. **Análise Semântica**
   - Comparar com padrões do projeto
   - Buscar issues similares no RAG
   - Verificar dependências

4. **Gerar Relatório**
   - Listar issues por severidade
   - Sugerir correções
   - Priorizar por impacto

## Categorias de Issue

- 🛑 **Critical**: Vulnerabilidades de segurança
- 🔴 **High**: Bugs que causam falha
- 🟡 **Medium**: Code smells, performance
- 🟢 **Low**: Estilo, formatação
