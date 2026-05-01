from __future__ import annotations
from typing import Any

# Definições de Squads Especializados (Inspirado em OpenSquad para extensão do Orquestrador)
# Cada squad possui um conjunto de agentes com papéis e ferramentas específicas.

PROFILES: dict[str, dict[str, Any]] = {
    'general': {
        'name': 'Squad Generalista',
        'description': 'Coordenação padrão para tarefas diversas e curiosidade geral.',
        'agents': [
            {
                'id': 'coord',
                'name': 'Ultron-Coor',
                'role': 'Coordinator',
                'purpose': 'Orquestrar prioridades, delegar, destravar bloqueios.',
                'heartbeat_minute_offset': 0,
                'tools': ['planner', 'goals', 'project_kernel', 'integrity'],
            },
            {
                'id': 'research',
                'name': 'Ultron-Research',
                'role': 'Research & Grounding',
                'purpose': 'Buscar evidência confiável, validar fontes e reduzir alucinação.',
                'heartbeat_minute_offset': 5,
                'tools': ['verify_source_headless', 'sql_explorer', 'conflicts'],
            },
            {
                'id': 'engineer',
                'name': 'Ultron-Engineer',
                'role': 'Execution & Refactor',
                'purpose': 'Validar hipóteses via Python sandbox e propor melhorias no código.',
                'heartbeat_minute_offset': 10,
                'tools': ['execute_python_sandbox', 'filesystem_audit', 'project_experiment_cycle'],
            },
        ]
    },
    'scientific_research': {
        'name': 'Squad de Pesquisa Científica',
        'description': 'Especializado em busca profunda, validação de claims e síntese de evidências.',
        'agents': [
            {
                'id': 'lead_researcher',
                'name': 'Ultron-Scientist',
                'role': 'Lead Researcher',
                'purpose': 'Formular hipóteses de busca e validar a autoridade de fontes.',
                'heartbeat_minute_offset': 0,
                'tools': ['verify_source_headless', 'ask_evidence', 'ground_claim_check'],
            },
            {
                'id': 'epistemic_critic',
                'name': 'Ultron-Critic',
                'role': 'Epistemic Critic',
                'purpose': 'Identificar contradições lógicas e falhas de evidência.',
                'heartbeat_minute_offset': 7,
                'tools': ['internal_critic', 'conflicts', 'analogy'],
            },
            {
                'id': 'librarian',
                'name': 'Ultron-Librarian',
                'role': 'Knowledge Librarian',
                'purpose': 'Organizar abstrações e indexar conhecimento no LightRAG.',
                'heartbeat_minute_offset': 15,
                'tools': ['explicit_abstractions', 'knowledge_bridge', 'rag_router'],
            },
        ]
    },
    'code_analysis': {
        'name': 'Squad de Análise de Código',
        'description': 'Especializado em engenharia reversa, refatoração segura e execução experimental.',
        'agents': [
            {
                'id': 'architect',
                'name': 'Ultron-Architect',
                'role': 'System Architect',
                'purpose': 'Mapear dependências e propor mudanças estruturais.',
                'heartbeat_minute_offset': 0,
                'tools': ['project_kernel', 'filesystem_audit', 'source_probe'],
            },
            {
                'id': 'devops_engineer',
                'name': 'Ultron-DevOps',
                'role': 'Execution Engineer',
                'purpose': 'Criar ambientes de teste e validar scripts em sandbox.',
                'heartbeat_minute_offset': 10,
                'tools': ['execute_python_sandbox', 'sandbox_client', 'env_tools'],
            },
            {
                'id': 'qa_tester',
                'name': 'Ultron-QA',
                'role': 'Quality Assurance',
                'purpose': 'Verificar regressões e medir performance experimental.',
                'heartbeat_minute_offset': 20,
                'tools': ['project_executor', 'benchmark_suite', 'quality_eval'],
            },
        ]
    },
    'logic_math': {
        'name': 'Squad Lógico-Matemático',
        'description': 'Especializado em raciocínio simbólico, provas formais e algoritmos.',
        'agents': [
            {
                'id': 'logician',
                'name': 'Ultron-Logician',
                'role': 'Symbolic Logician',
                'purpose': 'Reduzir problemas a formas simbólicas e verificar consistência.',
                'heartbeat_minute_offset': 0,
                'tools': ['symbolic_reasoner', 'neurosym', 'itc'],
            },
            {
                'id': 'algorithm_specialist',
                'name': 'Ultron-Algo',
                'role': 'Algorithm Expert',
                'purpose': 'Otimizar fluxos computacionais e prever complexidade.',
                'heartbeat_minute_offset': 12,
                'tools': ['execute_python_sandbox', 'subgoals', 'causal'],
            },
        ]
    }
}

def get_profile(profile_id: str) -> dict[str, Any]:
    return PROFILES.get(profile_id, PROFILES['general'])

def list_profiles() -> list[dict[str, str]]:
    return [{'id': k, 'name': v['name'], 'description': v['description']} for k, v in PROFILES.items()]
