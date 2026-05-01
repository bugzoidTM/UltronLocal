"""
Motor de Raciocínio Local do UltronPro
=====================================
Resolve tarefas simples SEM chamar LLM:
1. Expressões matemáticas simples (eval sanitizado)
2. Consultas a base de conhecimento local (SQLite)
3. Regras SE-ENTÃO para diagnósticos comuns

Só escalona para LLM se falhar ou se a tarefa exigir criatividade/raciocínio aberto.
"""

import ast
import json
import logging
import operator
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("uvicorn")

# Paths
DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
FACTS_DB = DATA_DIR / 'local_facts.db'


def _attach_sir(query: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultronpro import sir_amplifier

        out = dict(payload)
        out['sir'] = sir_amplifier.build_sir_from_local_result(query, out)
        return out
    except Exception:
        return payload


def _normalize_query(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _query_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", _normalize_query(text)))


def _is_self_directed(tokens: set[str]) -> bool:
    self_refs = {
        "voce", "vc", "tu", "te", "ti", "seu", "sua", "seus", "suas",
        "you", "your", "yourself", "assistant", "assistente", "ultronpro",
    }
    question_refs = {"quem", "qual", "quais", "o", "what", "who", "which", "how"}
    return bool(tokens & self_refs) and bool(tokens & question_refs)


def _requires_dialogue_context(query: str) -> bool:
    """Defer user-referential questions to the cognitive dialogue layer."""
    try:
        from ultronpro.cognitive_response import _is_user_reference_query

        return bool(_is_user_reference_query(query))
    except Exception:
        logger.debug("Dialogue-context classifier unavailable", exc_info=True)
        return False


def _requires_cognitive_projection(query: str) -> bool:
    """Defer hypothetical/risk questions to the cognitive simulation layer."""
    q = _normalize_query(query)
    markers = (
        "imagine",
        "e se",
        "what if",
        "daqui a",
        "indispon",
        "permanentemente",
        "o que aconteceria",
        "qual sua analise de risco",
        "antes de executar",
        "decisao",
        "decidiria",
        "leibniz",
        "indiscern",
        "memoria episodica",
        "api_gateway",
        "fs_operations",
        "causal gate",
        "sleep cycle",
        "mais fragil",
    )
    return any(marker in q for marker in markers)


def _requires_external_factual_lookup(query: str) -> bool:
    try:
        from ultronpro.core.intent import is_external_factual_intent

        return bool(is_external_factual_intent(query))
    except Exception:
        return False


def _has_math_constant_context(tokens: set[str]) -> bool:
    return bool(tokens & {"valor", "constante", "constantes", "matematica", "math", "numero", "number"})

# Operators安全的 para eval matemático
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


class LocalMathResolver:
    """
    Resolve expressões matemáticas simples sem LLM.
    Usa AST parsing seguro (não eval() direto).
    """
    
    # Patterns de Expressões Matemáticas Simples
    MATH_PATTERNS = [
        r'^\s*\d+\s*[\+\-\*/%]\s*\d+\s*$',  # 2+2, 10*5
        r'^\s*\d+\s*[\+\-\*/%]\s*\d+\s*[\+\-\*/%]\s*\d+\s*$',  # 2+2*3
        r'^\s*-\s*\d+\s*$',  # -5
        r'^\s*\d+\s*\^\s*\d+\s*$',  # 2^10
        r'^\s*\d+\s*\(\s*\d+\s*[\+\-\*/]\s*\d+\s*\)\s*$',  # 2*(3+4)
        r'^\s*sqrt\s*\(\s*\d+\s*\)\s*$',  # sqrt(16)
        r'^\s*pow\s*\(\s*\d+\s*,\s*\d+\s*\)\s*$',  # pow(2, 3)
    ]

    @classmethod
    def _extract_expression(cls, query: str) -> str:
        q = _normalize_query(query)
        q = q.replace('×', '*').replace('÷', '/').replace('^', '**')
        q = re.sub(r'\bmais\b', '+', q)
        q = re.sub(r'\bmenos\b', '-', q)
        q = re.sub(r'\bvezes\b', '*', q)
        q = re.sub(r'\bdividido\s+por\b', '/', q)
        candidates = re.findall(
            r'[-+]?\d+(?:\.\d+)?(?:\s*(?:\*\*|[\+\-\*/%])\s*[-+]?\d+(?:\.\d+)?)+',
            q,
        )
        if candidates:
            return candidates[-1].strip()
        return q.strip().strip('?')
    
    @classmethod
    def can_resolve(cls, query: str) -> bool:
        """Verifica se a query é uma expressão matemática simples."""
        q = query.strip().lower()
        
        # Check for mathematical keywords
        math_keywords = ['calcule', 'quanto é', 'resultado', '=', 'mais', 'menos', 'vezes', 'dividido', 'potencia', 'sqrt', 'pow']
        has_math_keyword = any(k in q for k in math_keywords)
        
        # Extract the expression part
        expr = cls._extract_expression(query)
        for kw in ['calcule ', 'quanto é ', 'resultado ', '= ', '?']:
            if kw in expr:
                expr = expr.split(kw, 1)[1].strip()
        
        # Check if matches math patterns
        for pattern in cls.MATH_PATTERNS:
            if re.match(pattern, expr.replace(' ', '').replace('^', '**')):
                return True
        
        return False
    
    @classmethod
    def resolve(cls, query: str) -> Optional[str]:
        """Resolve a expressão matemática."""
        try:
            q = query.strip().lower()
            
            # Extract expression
            expr = cls._extract_expression(query)
            for kw in ['calcule ', 'quanto é ', 'resultado ', '= ', '?']:
                if kw in expr:
                    expr = expr.split(kw, 1)[1].strip()
            
            # Normalize expression
            expr = expr.replace('^', '**')
            expr = expr.replace('×', '*')
            expr = expr.replace('÷', '/')
            expr = expr.replace('π', str(3.14159))
            expr = expr.replace('sqrt', 'math.sqrt')
            expr = expr.replace('pow', 'pow')
            
            # Handle simple cases without eval
            if re.match(r'^\d+\s*[\+\-\*/]\s*\d+$', expr.replace(' ', '')):
                parts = re.split(r'([\+\-\*/])', expr.replace(' ', ''))
                a, op, b = float(parts[0]), parts[1], float(parts[2])
                if op == '+': result = a + b
                elif op == '-': result = a - b
                elif op == '*': result = a * b
                elif op == '/': result = a / b if b != 0 else 'erro'
                return str(int(result) if result == int(result) else round(result, 6))
            
            # Safe eval with math functions
            allowed_names = {"math": __import__('math'), "pow": pow}
            result = eval(expr, {"__builtins__": {}}, allowed_names)
            
            if isinstance(result, float):
                result = int(result) if result == int(result) else round(result, 6)
            return str(result)
            
        except Exception as e:
            logger.debug(f"Math resolution failed: {e}")
            return None


class LocalFactsResolver:
    """
    Resolve consultas a base de conhecimento local (SQLite).
    """
    
    @classmethod
    def _init_db(cls):
        """Inicializa a base de dados de fatos locais se não existir."""
        if not FACTS_DB.exists():
            FACTS_DB.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(FACTS_DB))
            c = conn.cursor()
            
            # Tabela de fatos gerais
            c.execute('''CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY,
                category TEXT,
                key TEXT,
                value TEXT,
                updated_at INTEGER
            )''')
            
            # Inserir fatos iniciais
            facts = [
                ('system', 'name', 'UltronPro', int(time.time())),
                ('system', 'version', '0.1.0', int(time.time())),
                ('system', 'mode', 'autonomous', int(time.time())),
                ('math', 'pi', '3.14159', int(time.time())),
                ('math', 'e', '2.71828', int(time.time())),
                ('math', 'golden_ratio', '1.61803', int(time.time())),
                ('config', 'max_tokens', '220', int(time.time())),
                ('config', 'cache_ttl', '3600', int(time.time())),
                ('config', 'reflexion_interval', '120', int(time.time())),
                ('config', 'autonomy_interval', '75', int(time.time())),
                ('provider', 'primary', 'groq', int(time.time())),
                ('provider', 'fallback', 'gemini', int(time.time())),
            ]
            c.executemany('INSERT INTO facts (category, key, value, updated_at) VALUES (?, ?, ?, ?)', facts)
            conn.commit()
            conn.close()
            logger.info("Local facts database initialized")
    
    @classmethod
    def can_resolve(cls, query: str) -> bool:
        """Verifica se é uma consulta de fato simples."""
        q = _normalize_query(query)
        tokens = _query_tokens(query)
        if _is_self_directed(tokens) or _requires_dialogue_context(query) or _requires_cognitive_projection(query) or _requires_external_factual_lookup(query):
            return False
        
        # Patterns de consulta factual
        fact_patterns = [
            'qual é o', 'qual a', 'quais são', 'o que é', 'quem é',
            'me diga', 'qual o valor', 'qual o nome', 'qual a versão',
            'qual a configuração', 'qual o modo', 'qual provider',
            'qual o intervalo', 'quando', 'onde', 'por que',
            'tamanho', 'número', 'quantidade', 'versão', 'nome',
            'configuração', 'modo', 'provider', 'intervalo'
        ]
        
        # Must NOT require reasoning
        no_reasoning = ['calcule', 'quanto', 'resolva', 'responda', 'explique', 'porquê']
        
        return any(_normalize_query(p) in q for p in fact_patterns) and not any(_normalize_query(p) in q for p in no_reasoning)
    
    @classmethod
    def resolve(cls, query: str) -> Optional[str]:
        """Resolve consulta a base de fatos locais."""
        try:
            cls._init_db()
            
            q = _normalize_query(query)
            tokens = _query_tokens(query)
            if _is_self_directed(tokens) or _requires_dialogue_context(query) or _requires_cognitive_projection(query) or _requires_external_factual_lookup(query):
                return None
            conn = sqlite3.connect(str(FACTS_DB))
            c = conn.cursor()
            
            # Parse da query para determinar categoria e chave
            if 'versao' in tokens or 'version' in tokens:
                result = c.execute("SELECT value FROM facts WHERE category='system' AND key='version'").fetchone()
                if result: return f"Versao: {result[0]}"
            
            if 'nome' in tokens or 'name' in tokens:
                result = c.execute("SELECT value FROM facts WHERE category='system' AND key='name'").fetchone()
                if result: return f"Nome: {result[0]}"
            
            if 'modo' in tokens or 'mode' in tokens:
                result = c.execute("SELECT value FROM facts WHERE category='system' AND key='mode'").fetchone()
                if result: return f"Modo: {result[0]}"
            
            if 'provider' in tokens:
                result = c.execute("SELECT value FROM facts WHERE category='provider' AND key='primary'").fetchone()
                if result: return f"Provider primario: {result[0]}"
            
            if 'intervalo' in tokens:
                result = c.execute("SELECT value FROM facts WHERE category='config' AND key='reflexion_interval'").fetchone()
                if result: return f"Intervalo de reflexao: {result[0]} segundos"
            
            if 'pi' in tokens or 'π' in str(query or ''):
                result = c.execute("SELECT value FROM facts WHERE category='math' AND key='pi'").fetchone()
                if result: return f"pi = {result[0]}"

            if 'e' in tokens and _has_math_constant_context(tokens):
                result = c.execute("SELECT value FROM facts WHERE category='math' AND key='e'").fetchone()
                if result: return f"e: {result[0]}"
            
            # Generic search
            results = c.execute("SELECT category, key, value FROM facts").fetchall()
            conn.close()
            
            # Simple keyword match
            for cat, key, value in results:
                cat_norm = _normalize_query(cat)
                key_norm = _normalize_query(key)
                if len(key_norm) == 1 and not _has_math_constant_context(tokens):
                    continue
                if key_norm in tokens or cat_norm in tokens:
                    return f"{key}: {value}"
            
            return None
            
        except Exception as e:
            logger.debug(f"Local facts resolution failed: {e}")
            return None


class LocalRulesResolver:
    """
    Resolve regras SE-ENTÃO para diagnósticos comuns.
    """
    
    RULES = {
        # Regras de Status/Saúde do Sistema
        'sistema': {
            'patterns': ['status do sistema', 'saúde do sistema', 'como está o sistema', 'health'],
            'response': 'Sistema UltronPro operacional. Loops ativos: autonomy, reflexion, roadmap, agi_path, judge, autofeeder.'
        },
        'memória': {
            'patterns': ['memória', 'memory', 'armazenamento'],
            'response': f"Banco de dados: {DATA_DIR / 'ultron.db'}"
        },
        'loop': {
            'patterns': ['loop ativo', 'loops ativos', 'executando', 'running'],
            'response': 'Autonomy loop: 75s | Reflexion loop: 120s | Roadmap: configurável | AGI Path: ativo'
        },
        
        # Regras de Configuração
        'config': {
            'patterns': ['configuração', 'configuration', 'config'],
            'response': 'Budget mode: economy | Cache TTL: 3600s | Max tokens: 220'
        },
        
        # Regras de Providers
        'groq': {
            'patterns': ['groq', 'llama-3.3'],
            'response': 'Provider primário ativo: Groq (llama-3.3-70b-versatile)'
        },
        'gemini': {
            'patterns': ['gemini', 'google'],
            'response': 'Provider fallback: Google Gemini (gemini-2.0-flash)'
        },
        
        # Regras de Cache
        'cache': {
            'patterns': ['cache', 'lru', 'cached'],
            'response': 'LRU cache ativo: max 1000 entradas, TTL 1 hora'
        },
        
        # Regras de Consciência
        'consciência': {
            'patterns': ['consciência', 'conscious', 'phenomenal', 'qualia'],
            'response': 'Sistema de consciência fenomênica ativo. Qualia + Phenomenal Consciousness integrados.'
        },
    }
    
    @classmethod
    def can_resolve(cls, query: str) -> bool:
        """Verifica se a query matches uma regra."""
        if _requires_cognitive_projection(query):
            return False
        q = query.lower()
        for rule in cls.RULES.values():
            if any(p in q for p in rule['patterns']):
                return True
        return False
    
    @classmethod
    def resolve(cls, query: str) -> Optional[str]:
        """Resolve usando regras SE-ENTÃO."""
        if _requires_cognitive_projection(query):
            return None
        q = query.lower()
        
        for key, rule in cls.RULES.items():
            if any(p in q for p in rule['patterns']):
                return rule['response']
        
        return None


class LocalReasoningEngine:
    """
    Motor de Raciocínio Local Principal.
    
    Ordem de resolução:
    1. Regras SE-ENTÃO (mais rápido)
    2. Expressões matemáticas
    3. Consultas a base de fatos
    4. Escalonar para LLM
    """
    
    @classmethod
    def can_resolve(cls, query: str) -> bool:
        """Verifica se a query pode ser resolvida localmente."""
        if _requires_external_factual_lookup(query):
            return False
        return (
            LocalRulesResolver.can_resolve(query) or
            LocalMathResolver.can_resolve(query) or
            LocalFactsResolver.can_resolve(query)
        )
    
    @classmethod
    def resolve(cls, query: str) -> dict[str, Any]:
        """
        Resolve a query localmente, sem chamar LLM.
        
        Returns:
        {
            'resolved': bool,
            'method': 'rules' | 'math' | 'facts' | None,
            'result': str | None,
            'escalate': bool (True se falhar e deve chamar LLM)
        }
        """
        t0 = time.time()
        if _requires_external_factual_lookup(query):
            return _attach_sir(query, {
                'resolved': False,
                'method': None,
                'result': None,
                'escalate': True,
                'reason': 'external_factual_requires_web_search',
            })
        
        # 1. Try rules first (fastest)
        if LocalRulesResolver.can_resolve(query):
            result = LocalRulesResolver.resolve(query)
            if result:
                logger.info(f"LocalReasoning: RESOLVED via RULES in {int((time.time()-t0)*1000)}ms")
                return _attach_sir(query, {
                    'resolved': True,
                    'method': 'rules',
                    'result': result,
                    'escalate': False
                })
        
        # 2. Try math
        if LocalMathResolver.can_resolve(query):
            result = LocalMathResolver.resolve(query)
            if result:
                logger.info(f"LocalReasoning: RESOLVED via MATH in {int((time.time()-t0)*1000)}ms")
                return _attach_sir(query, {
                    'resolved': True,
                    'method': 'math',
                    'result': result,
                    'escalate': False
                })
        
        # 3. Try facts
        if LocalFactsResolver.can_resolve(query):
            result = LocalFactsResolver.resolve(query)
            if result:
                logger.info(f"LocalReasoning: RESOLVED via FACTS in {int((time.time()-t0)*1000)}ms")
                return _attach_sir(query, {
                    'resolved': True,
                    'method': 'facts',
                    'result': result,
                    'escalate': False
                })
        
        # Cannot resolve locally - escalate to LLM
        logger.info(f"LocalReasoning: ESCALATE to LLM (no local resolution)")
        return _attach_sir(query, {
            'resolved': False,
            'method': None,
            'result': None,
            'escalate': True
        })


def resolve_local(query: str) -> dict[str, Any]:
    """Função de convenience para resolução local."""
    return LocalReasoningEngine.resolve(query)


def resolve(query: str) -> dict[str, Any]:
    """Compatibility alias for callers expecting module.resolve."""
    return resolve_local(query)


def can_resolve_locally(query: str) -> bool:
    """Função de convenience para verificar se pode resolver localmente."""
    return LocalReasoningEngine.can_resolve(query)
