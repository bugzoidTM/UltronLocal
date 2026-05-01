---
description: Pesquisa na web usando ferramentas de navegação
version: 1.0.0
author: ultronpro
tags:
  - web
  - search
  - research
  - information
allowed_tools:
  - web_browser.search
  - web_browser.fetch
  - rag.search
risk_level: low
budget:
  max_seconds: 30
  max_calls: 5
  max_cost_usd: 0.01
when_to_use: |
  Use este skill quando:
  - Precisar de informações atualizadas da web
  - Usuário pedir para pesquisar algo
  - Encontrar gaps de conhecimento no grafo causal
  - Validar informações contra fontes externas
path: web_search
hooks:
  before: verificar_permissao_web
  after: cache_resultado
success_checks:
  - resposta contem fonte/URL
  - informação é verificável
  - tempo de resposta < 30s
enabled: true
---

# Web Search Skill

Realiza pesquisas na web para coletar informações atualizadas e verificar fatos.

## Fluxo de Execução

1. **Analisar Query**
   - Extrair termos de busca
   - Identificar necessidade de múltiplas buscas

2. **Executar Busca**
   - Usar web_browser.search para termos principais
   - Priorizar fontes confiáveis

3. **Sintetizar Resultados**
   - Compilar informações relevantes
   - Citar fontes
   - Identificar lacunas de informação

4. **Armazenar Conhecimento**
   - Adicionar fatos ao grafo causal
   - Indexar no RAG para futuras consultas

## Exemplo de Uso

```
User: Qual a temperatura em São Paulo hoje?
Skill: web_search
Tools: web_browser.search
Output: 22°C, céu limpo, fonte: weather.com
Knowledge: Adicionado ao grafo: São Paulo -> tem_clima -> temperado
```
