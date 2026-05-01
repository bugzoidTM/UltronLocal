# ULTRON.md - Instruções Humanas para o Sistema

Este arquivo contém instruções humanas persistentes que o UltronPro carrega 
em cada sessão. Ele NÃO é sobrescrito pelo sistema.

## Sobre o UltronPro

O UltronPro é um sistema de raciocínio autônomo com "cérebro próprio".
- LLM é ferramenta, não cérebro
- Funciona sem dependência de cloud
- Accumula conhecimento através de experiência

## Convenções de Código

- Use Python 3.11+
- Testes unitários obrigatórios (pytest)
- Linting com ruff antes de commit
- Type hints em todas as funções públicas

## Comandos Comuns

```bash
# Backend
python -m uvicorn ultronpro.main:app --reload

# Testes
python test_*.py

# Linting
ruff check ultronpro/
```

## Estrutura do Projeto

```
backend/
├── ultronpro/           # Core do sistema
│   ├── main.py          # API FastAPI
│   ├── skill_*.py      # Skills declarativos
│   ├── task_*.py       # Sistema de tarefas
│   └── ...
├── ultron_skills/       # Skills em markdown
└── data/                # Memória persistente
```

## Sistema de Memória

O sistema usa memória operacional em camadas:

1. **HUMAN** (ultron.md) - Instruções humanas (este arquivo)
2. **LEARNED** (ultron.learned.md) - Aprendizados do sistema
3. **AUTO** (auto_memory.jsonl) - Observações automáticas

Escopos: global, project, env, sandbox, session

## Tarefas

Para criar uma tarefa:
```python
from ultronpro.task_types import TaskTemplates
task = TaskTemplates.remote_agent("pergunta")
```

Para executar:
```python
from ultronpro.task_manager import get_task_manager
tm = get_task_manager()
result = await tm.execute(task)
```

## Tools Disponíveis

Registrar em: `ultronpro/tool_registry.py`

Categorias:
- file: read, write, glob, grep
- bash: run, sandbox
- web: search, fetch
- memory: rag, graph, cache
- task: submit, execute, dream

## Benchmarks

- Python benchmark: 80%+ para conceptos centrais
- RAG benchmark: 70%+ para conhecimento ensinado
- Metacognition: quality > 0.3

## Troubleshooting

### Chat não responde
Verificar se main.py está rodando e LLM está configurado

### Skills não funcionam
Verificar ultron_skills/ e skill_loader.py

### Tasks travam
Verificar budget em task_types.py
