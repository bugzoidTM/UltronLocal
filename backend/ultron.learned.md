# ULTRON.learned.md - Aprendizados do Sistema

Este arquivo contém aprendizados que o UltronPro descobriu através de experiência.
Ele é enriquecido automaticamente pelo sistema e pode ser revisado por humanos.

## Padrões Descobertos

### Comandos Verificados

- `npm run build` - Leva ~10s em produção
- `pytest` - 100 testes em ~5s
- `ruff check` - Mais rápido que flake8

### Invariantes

- LLM timeout ocorre após ~30s em requisições normais
- Semantic cache tem hit rate de ~60% em queries repetidas
- RAG retrieval é mais efetivo com top_k=5

### Benchmarks

- Python benchmark: conceito descriptor protocol tem 85% de acerto
- RAG benchmark: conhecimento ensinado via /teach tem 75% de retrieval

## Melhorias Aprendidas

- Usar retry com backoff exponencial em chamadas de API
- Cachear resultados de queries frequentes
- Limitar contexto a 8000 tokens para performance

## Conhecimento Técnico

### Python

- Descriptor protocol: `__get__`, `__set__`, `__set_name__`
- asyncio: CancelledError em tasks canceladas
- GIL: limita paralelismo em threads

### RAG

- Chunking: 500 tokens por chunk
- Embedding: modelo default é suficiente
- Reranking: melhora precisão em 20%

## Lições Aprendidas

1. Não confiar em resposta de cache sem verificar score
2. LLM cloud tem rate limits (429) - usar retry
3. DeepSeek via OpenRouter causa timeout - evitar
4. Background loops não usam LLM local - seguros
