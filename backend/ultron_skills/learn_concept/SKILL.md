---
description: Aprender e armazenar novos conceitos no grafo causal
version: 1.0.0
author: ultronpro
tags:
  - learn
  - concept
  - knowledge
  - teaching
  - rag
allowed_tools:
  - graph.add_triple
  - rag.ingest
  - memory.remember
  - semantic_cache.store
risk_level: low
budget:
  max_seconds: 30
  max_calls: 5
  max_cost_usd: 0.01
when_to_use: |
  Use este skill quando:
  - Usuário ensinar algo novo via aba Ensinar
  - Encontrar conceito não conhecido
  - Sistema detectar gap de conhecimento
  - Necessitar expandir base de conhecimento
  - Validar informação contra fontes
path: learn_concept
hooks:
  before: verificar_nao_existe
  after: indexar_no_rag
success_checks:
  - conceito adicionado ao grafo
  - conceito indexado no RAG
  - resposta de confirmação enviada
enabled: true
---

# Learn Concept Skill

Aprende novos conceitos e os armazena no grafo causal e RAG.

## Fluxo de Aprendizado

1. **Parse da Informação**
   - Identificar conceito principal
   - Extrair relações
   - Determinar categoria

2. **Validar**
   - Verificar se já existe
   - Buscar conflitos
   - Avaliar confiança

3. **Armazenar**
   - Adicionar triplas ao grafo
   - Indexar no RAG
   - Guardar na memória episódica

4. **Confirmar**
   - Retornar resumo do aprendido
   - Sugerir aplicações
   - Identificar gaps

## Estrutura de Conhecimento

### Conceitos
- Entidade: o que é
- Atributos: características
- Relações: conexões com outros

### Triplas S-P-O
- Sujeito: conceito principal
- Predicado: tipo de relação
- Objeto: conceito relacionado

## Exemplo

Input: "Python é uma linguagem de programação"

Output:
```
Tripla: Python -> é_uma -> linguagem_de_programacao
Conceito: Python
Atributos: interpretada, alto_nível, multiparadigma
Relacionado: programação, desenvolvimento, scripts
```
