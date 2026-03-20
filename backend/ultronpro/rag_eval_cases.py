from __future__ import annotations

DEFAULT_CASES = [
    {
        'id': 'runtime_timeout_worker',
        'query': 'erro de timeout no worker com latência alta e fila crescendo',
        'task_type': 'debug',
        'expected_domains': ['runtime', 'code'],
        'notes': 'Incidente operacional com forte componente de runtime.',
    },
    {
        'id': 'api_resilience_timeout',
        'query': 'api resilience circuit breaker timeout bulkhead',
        'task_type': 'debug',
        'expected_domains': ['runtime', 'factual'],
        'notes': 'Busca por padrões operacionais e documentação de resiliência.',
    },
    {
        'id': 'postgres_index_analyze',
        'query': 'postgresql indexing query planning explain analyze',
        'task_type': 'code',
        'expected_domains': ['code', 'factual'],
        'notes': 'Questão técnica de banco e tuning.',
    },
    {
        'id': 'sqlite_pragmas',
        'query': 'sqlite pragmas optimize analyze indexing',
        'task_type': 'code',
        'expected_domains': ['code', 'factual'],
        'notes': 'Busca técnica de implementação.',
    },
    {
        'id': 'roadmap_prioridades',
        'query': 'planejar roadmap com milestones e prioridades para arquitetura cognitiva',
        'task_type': 'planning',
        'expected_domains': ['planning', 'factual', 'memory'],
        'notes': 'Planejamento com continuidade.',
    },
    {
        'id': 'continuidade_decisoes',
        'query': 'quais decisões anteriores tomamos sobre governança de contexto e avaliação automática',
        'task_type': 'memory',
        'expected_domains': ['memory', 'planning'],
        'notes': 'Continuidade de projeto e memória.',
    },
    {
        'id': 'guardrails_risco',
        'query': 'guardrails de segurança e compliance para evitar promoção ruim',
        'task_type': 'general',
        'expected_domains': ['safety', 'factual'],
        'notes': 'Tema de segurança e governança.',
    },
    {
        'id': 'deploy_debug',
        'query': 'bug de deploy docker api endpoint falhando em produção',
        'task_type': 'debug',
        'expected_domains': ['runtime', 'code', 'factual'],
        'notes': 'Mistura de operação e implementação.',
    },
    {
        'id': 'memoria_episodios',
        'query': 'continuar trabalho de ontem e recuperar episódios relevantes',
        'task_type': 'memory',
        'expected_domains': ['memory'],
        'notes': 'Recuperação explícita de continuidade.',
    },
    {
        'id': 'factual_docs',
        'query': 'documentação do endpoint /api/metacognition/ask e fluxo RAG-first',
        'task_type': 'summarization',
        'expected_domains': ['factual', 'code'],
        'notes': 'Resumo factual com base documental/técnica.',
    },
]


def get_default_cases() -> list[dict]:
    return list(DEFAULT_CASES)
