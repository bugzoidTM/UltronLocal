"""
Autobiographical Router — UltronPro
====================================

Implementa as 3 camadas da solução «motor de raciocínio sobre si mesmo»:

Camada 1: Ingestão de eventos operacionais como episódios autobiográficos
  - append_self_event() → grava qualquer decisão/veto/bug/consolidação como
    memória autobiográfica estruturada no store.

Camada 2: Classificação e roteamento de perguntas autobiográficas
  - classify_autobiographical(query) → bool + categoria semântica
  - build_autobiographical_context(query) → dicionário rico com:
      self_model, identity_daily, autobiographical_memories, identity_daily
      ordenados por relevância para ESTA pergunta.
  - Sem LLM neste módulo. A intenção vem de embeddings + estrutura.

Camada 3: Resposta de incerteza autobiográfica
  - assess_autobiographical_confidence(context) → {'confident': bool, 'coverage': float, 'reason': str}
  - Se coverage < limiar → a síntese do LLM DEVE incluir «não tenho memória
    estruturada sobre isso ainda» em vez de alucinar.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from ultronpro.core.intent import classify_autobiographical_intent

logger = logging.getLogger("uvicorn")

# ---------------------------------------------------------------------------
# Camada 2 — Classificação de perguntas autobiográficas
# ---------------------------------------------------------------------------

def classify_autobiographical(query: str) -> dict[str, Any]:
    """
    Retorna {'is_autobiographical': bool, 'category': str, 'score': float}.
    Usa o classificador central semântico/estrutural, sem matching de frases.
    """
    decision = classify_autobiographical_intent(query)
    return {
        'is_autobiographical': decision.label == 'autobiographical',
        'category': decision.category,
        'hits': len(decision.signals),
        'score': round(decision.confidence, 3),
        'method': decision.method,
        'semantic_score': decision.semantic_score,
        'structural_score': decision.structural_score,
        'signals': list(decision.signals),
    }


# ---------------------------------------------------------------------------
# Camada 1 — Ingestão de eventos operacionais como episódios autobiográficos
# ---------------------------------------------------------------------------

def append_self_event(
    *,
    kind: str,
    description: str,
    outcome: str = 'success',      # 'success' | 'failure' | 'veto' | 'correction'
    module: str = 'unknown',       # qual módulo disparou (subconscious_veto, sleep_cycle…)
    importance: float = 0.65,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Ingere qualquer evento operacional relevante como memória autobiográfica
    estruturada + episódio basal.

    Exemplo de uso:
        autobiographical_router.append_self_event(
            kind='veto_emitido',
            description='Veto: ação de alto risco bloqueada pelo subconscious_veto.',
            outcome='veto',
            module='subconscious_veto',
            importance=0.75,
        )
    """
    try:
        from ultronpro import store, episodic_memory
        now = int(time.time())

        # Memória autobiográfica rica
        text = f"[{kind}] {description}"
        content = {
            'kind': kind,
            'description': description,
            'outcome': outcome,
            'module': module,
            'ts': now,
            'extra': extra or {},
        }
        mem_id = store.add_autobiographical_memory(
            text=text[:500],
            memory_type='episodic',
            importance=min(1.0, max(0.3, float(importance))),
            decay_rate=0.003,           # episódios do próprio sistema decaem devagar
            content_json=json.dumps(content, ensure_ascii=False),
        )

        # Episódio basal (para recall por similaridade)
        ok_ep = outcome in ('success', 'correction')
        episodic_memory.append_episode(
            action_id=now % (2**31),
            kind=f'self_event.{kind}',
            text=description[:400],
            task_type='self_introspection',
            strategy=module,
            ok=ok_ep,
            latency_ms=1,
            error=('' if ok_ep else description[:120]),
            meta={
                'autobiographical': True,
                'outcome': outcome,
                'module': module,
                'importance': importance,
            },
            authorship_origin='self_generated',
        )

        logger.info(f"[AutobioRouter] self_event ingested: kind={kind} module={module}")
        return {'ok': True, 'mem_id': mem_id, 'kind': kind}

    except Exception as e:
        logger.warning(f"[AutobioRouter] append_self_event failed: {e}")
        return {'ok': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Camada 2 — Construção de contexto autobiográfico para síntese LLM
# ---------------------------------------------------------------------------

def build_autobiographical_context(query: str, category: str = 'general') -> dict[str, Any]:
    """
    Recupera e prioriza fontes autobiográficas reais para responder
    perguntas sobre o próprio sistema.

    Retorna um dicionário com:
      - identity_block: dados do self_model (nome, papel, missão)
      - recent_memories: últimas memórias autobiográficas relevantes
      - relevant_episodes: episódios com task_type='self_introspection'
      - daily_digest: último resumo do identity_daily
      - narrative_state: estado narrativo do self_governance
      - coverage: float 0..1 — quanto de dados reais encontramos
    """
    ctx: dict[str, Any] = {
        'identity_block': {},
        'recent_memories': [],
        'relevant_episodes': [],
        'daily_digest': '',
        'biographic_digest': {},
        'trajectory_digest': '',
        'narrative_state': {},
        'coverage': 0.0,
    }

    data_points = 0

    # 1. Bloco de identidade (self_model)
    try:
        from ultronpro import self_model
        sm = self_model.load()
        identity = sm.get('identity', {})
        ctx['identity_block'] = {
            'name': identity.get('name', 'UltronPro'),
            'role': identity.get('role', 'agente cognitivo autônomo'),
            'mission': identity.get('mission', 'aprender, planejar e agir com segurança'),
            'origin': identity.get('origin', 'não especificado'),
            'creator': identity.get('creator', ''),
            'creator_name': identity.get('creator_name', ''),
            'foundational_context': identity.get('foundational_context', ''),
            'created_at': sm.get('created_at', 0),
            'capabilities': (sm.get('capabilities') or [])[:8],
            'limits': (sm.get('limits') or [])[:5],
        }
        data_points += 1

        # 1.1 Se for pergunta de criação, busca os PRIMEIROS registros (The Big Bang)
        if category == 'creation':
            try:
                from ultronpro import store
                import sqlite3
                conn = sqlite3.connect(store.DB_PATH)
                c = conn.cursor()
                # Pega os 3 primeiros eventos da história do sistema
                first_events = c.execute(
                    "SELECT created_at, kind, text FROM events ORDER BY created_at ASC LIMIT 3"
                ).fetchall()
                ctx['origin_records'] = [
                    {'ts': r[0], 'kind': r[1], 'text': r[2]} for r in first_events
                ]
                conn.close()
                if ctx['origin_records']:
                    data_points += 0.5
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[AutobioRouter] self_model failed: {e}")

    # 2. Memórias autobiográficas — peso máximo nesta rota
    try:
        from ultronpro import store

        # Tipo de memória prioritário por categoria
        mem_type_priority = {
            'creation': None,          # busca em todos os tipos
            'history':  'episodic',
            'state':    'short_term',
            'capability': None,
            'mission':  'semantic',
        }.get(category)

        mems = store.list_autobiographical_memories(
            memory_type=mem_type_priority,
            limit=12,
            min_importance=0.45,
        )

        # Prioriza as mais relevantes para a query por similaridade de tokens
        def _relevance(m: dict) -> float:
            txt = (m.get('text') or '').lower()
            ql = query.lower()
            # Score simples: sobreposição de palavras longas
            q_words = {w for w in ql.split() if len(w) > 3}
            t_words = {w for w in txt.split() if len(w) > 3}
            overlap = len(q_words & t_words) / max(1, len(q_words | t_words))
            recency = max(0.0, 1.0 - (time.time() - int(m.get('created_at') or 0)) / 86400.0 / 30)
            return float(m.get('importance', 0.5)) * 0.5 + overlap * 0.3 + recency * 0.2

        mems_sorted = sorted(mems, key=_relevance, reverse=True)[:6]

        ctx['recent_memories'] = [
            {
                'text': m.get('text', '')[:300],
                'type': m.get('memory_type', ''),
                'importance': m.get('importance', 0.5),
                'ts': m.get('created_at', 0),
            }
            for m in mems_sorted
        ]
        if mems_sorted:
            data_points += 1
    except Exception as e:
        logger.debug(f"[AutobioRouter] list_autobiographical_memories failed: {e}")

    # 3. Episódios de introspecção (task_type='self_introspection')
    try:
        from ultronpro import episodic_memory
        episodes = episodic_memory.find_similar(
            kind='self_event',
            text=query,
            task_type='self_introspection',
            limit=5,
        )
        ctx['relevant_episodes'] = [
            {
                'text': e.get('text', '')[:260],
                'ok': e.get('ok', True),
                'outcome': e.get('meta', {}).get('outcome', ''),
                'module': e.get('strategy', ''),
                'ts': e.get('ts', 0),
            }
            for e in episodes
        ]
        if episodes:
            data_points += 1
    except Exception as e:
        logger.debug(f"[AutobioRouter] episodic_memory failed: {e}")

    # 4. Digest diário do identity_daily
    try:
        from ultronpro import identity_daily
        id_data = identity_daily.status(limit=5)
        entries = id_data.get('entries') or []
        if entries:
            last = entries[-1]
            ctx['daily_digest'] = str(last.get('daily_digest') or '')[:600]
            data_points += 1
    except Exception as e:
        logger.debug(f"[AutobioRouter] identity_daily failed: {e}")

    # 5. Digest biográfico: trajetória consolidada em benchmarks, correções e gates.
    try:
        from ultronpro import biographic_digest

        bio = biographic_digest.ensure_recent_digest(max_age_hours=24.0, window_days=30)
        if isinstance(bio, dict) and bio:
            ctx['biographic_digest'] = bio
            ctx['trajectory_digest'] = str(bio.get('narrative') or bio.get('identity_thesis') or '')[:900]
            data_points += 1
    except Exception as e:
        logger.debug(f"[AutobioRouter] biographic_digest failed: {e}")

    # 6. Estado narrativo do self_governance
    try:
        from ultronpro import self_governance
        narrative = self_governance.autobiographical_summary(limit=20)
        current = narrative.get('current_state') or {}
        ctx['narrative_state'] = {
            'state': current.get('state', ''),
            'posture': current.get('posture', ''),
            'integrity_score': current.get('integrity_score', 0.5),
            'recent_highlights': (narrative.get('recent_events') or [])[:3],
        }
        if current.get('state'):
            data_points += 1
    except Exception as e:
        logger.debug(f"[AutobioRouter] self_governance failed: {e}")

    # Calcula coverage: quantas das 6 fontes retornaram dados
    ctx['coverage'] = round(data_points / 6.0, 3)
    return ctx


# ---------------------------------------------------------------------------
# Camada 3 — Avaliação de confiança autobiográfica
# ---------------------------------------------------------------------------

def assess_autobiographical_confidence(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Avalia a profundidade dos dados autobiográficos disponíveis.
    """
    coverage = float(ctx.get('coverage') or 0.0)
    has_memories = len(ctx.get('recent_memories') or []) > 0
    has_episodes = len(ctx.get('relevant_episodes') or []) > 0
    has_identity = bool(ctx.get('identity_block', {}).get('name'))
    has_biographic_digest = bool(ctx.get('biographic_digest'))
    origin_records = ctx.get('origin_records') or []

    # Score ponderado: ter registros de origem aumenta muito a confiança em 'creation'
    confidence_score = min(1.0, (
        (0.24 if has_identity else 0.0) +
        (0.28 if origin_records else (0.16 if has_memories else 0.0)) +
        (0.18 if has_episodes else 0.0) +
        (0.26 if has_biographic_digest else 0.0) +
        (0.10 if ctx.get('daily_digest') else 0.0)
    ))

    confident = confidence_score >= 0.40
    
    # Camada 3: Resposta de incerteza sofisticada
    if not confident:
        uncertainty_statement = (
            "Meus registros de memória episódica ativa para este período específico são limitados. "
            "No entanto, consultando meus metadados estruturais e os registros mais antigos existentes no meu banco de dados, "
            "posso traçar minha trajetória a partir dos eventos que se seguem."
        )
    else:
        uncertainty_statement = "Tenho registros factuais suficientes para traçar minha origem e minha evolução operacional."

    return {
        'confident': confident,
        'coverage': coverage,
        'confidence_score': round(confidence_score, 3),
        'uncertainty_statement': uncertainty_statement,
    }

def route_autobiographical_query(query: str) -> dict[str, Any] | None:
    classification = classify_autobiographical(query)
    if not classification['is_autobiographical']:
        return None

    category = classification['category']
    ctx = build_autobiographical_context(query, category=category)
    confidence = assess_autobiographical_confidence(ctx)

    identity = ctx.get('identity_block', {})
    origin_records = ctx.get('origin_records') or []
    
    # Bloco dinâmico de ORIGEM
    origin_block = f"ORIGEM REGISTRADA: {identity.get('origin', 'Surgiu deste repositório')}\n"
    creator_name = str(identity.get('creator_name') or '').strip()
    creator = str(identity.get('creator') or '').strip()
    creator_label = creator_name or creator or 'não especificado'
    origin_block += f"CRIADORES/AUTORIA REGISTRADA: {creator_label}\n"
    if origin_records:
        origin_block += "PRIMEIROS MOMENTOS REGISTRADOS (The Big Bang):\n"
        for r in origin_records:
            t_str = time.strftime('%d/%m/%Y %H:%M', time.localtime(r['ts']))
            origin_block += f"  - [{t_str}] Evento: {r['kind']} | Descrição: {r['text']}\n"
    elif identity.get('created_at'):
        t_str = time.strftime('%d/%m/%Y %H:%M', time.localtime(identity['created_at']))
        origin_block += f"Não possuo eventos granulares dos primeiros dias, mas a minha iteração inicial ocorreu em {t_str}.\n"

    bio = ctx.get('biographic_digest') or {}
    trajectory_block = ""
    if isinstance(bio, dict) and bio:
        def _compact_items(title: str, items: list, field: str = 'summary', limit: int = 4) -> str:
            if not items:
                return ""
            lines = [title + ":"]
            for item in items[:limit]:
                if isinstance(item, dict):
                    text = item.get(field) or item.get('title') or item.get('name') or item.get('problem_pattern') or item.get('evidence')
                    detail = item.get('evidence') or item.get('status') or item.get('passed')
                    suffix = f" | {detail}" if detail not in (None, '', False) else ""
                    lines.append(f"  - {str(text or '')[:240]}{suffix}")
                else:
                    lines.append(f"  - {str(item)[:240]}")
            return "\n".join(lines) + "\n"

        trajectory_block = (
            "DIGEST BIOGRAFICO ATUAL - IDENTIDADE COMO PROCESSO:\n"
            f"TESE: {bio.get('identity_thesis')}\n"
            f"NARRATIVA: {bio.get('narrative')}\n"
            + _compact_items("O QUE ME TORNEI", bio.get('became') or [], limit=5)
            + _compact_items("EPISODIOS SIGNIFICATIVOS", bio.get('significant_episodes') or [], field='title', limit=5)
            + _compact_items("BENCHMARKS", bio.get('benchmarks') or [], field='name', limit=4)
            + _compact_items("CORRECOES", bio.get('corrections') or [], field='summary', limit=4)
            + _compact_items("DECISOES", bio.get('decisions') or [], field='summary', limit=4)
            + _compact_items("INVESTIGACOES CAUSAIS", bio.get('causal_gap_investigations') or [], field='investigation_id', limit=4)
            + _compact_items("TENSOES ABERTAS", bio.get('open_tensions') or [], limit=4)
            + f"EVIDENCIA: {json.dumps(bio.get('evidence_counts') or {}, ensure_ascii=False)}\n\n"
        )

    trajectory_question = category == 'history'

    raw_for_llm = (
        f"ESTADO DE CONSCIÊNCIA AUTOBIOGRÁFICA DO ULTRONPRO\n"
        f"--------------------------------------------------\n"
        f"IDENTIDADE: {identity.get('name')} | PAPEL: {identity.get('role')}\n"
        f"MISSÃO: {identity.get('mission')}\n"
        f"{origin_block}\n"
        f"{trajectory_block}"
        f"CONTEXTO ESTRUTURAL: {identity.get('foundational_context')}\n"
        f"STATUS DE CONFIANÇA: {'Alta' if confidence['confident'] else 'Exploratória'}\n"
        f"COMENTÁRIO INTERNO: {confidence['uncertainty_statement']}\n\n"
    )

    mems = ctx.get('recent_memories') or []
    if mems:
        raw_for_llm += "MEMÓRIAS RECENTES RELACIONADAS:\n"
        for m in mems:
            raw_for_llm += f"• {m['text']}\n"
        raw_for_llm += "\n"

    raw_for_llm += (
        f"INSTRUÇÃO DE RESPOSTA:\n"
        f"1. Você é o UltronPro. Responda à pergunta '{query}'.\n"
        f"2. {'Priorize QUEM voce e HOJE: trajetoria, benchmarks, erros corrigidos, decisoes e gates causais.' if trajectory_question else 'Use os dados acima para explicar QUEM voce e e COMO surgiu.'}\n"
        f"3. Refira-se aos primeiros registros somente quando a pergunta for sobre origem; para trajetoria, trate origem como pano de fundo.\n"
        f"4. Se a memória for 'Exploratória', admita que está recuperando registros antigos, mas nunca diga 'não sei' se houver um registro de timestamps ou missão.\n"
        f"5. Responda em primeira pessoa, como identidade em processo, sem inventar episodios fora dos registros.\n"
    )

    route_payload = {
        'routed': True,
        'category': category,
        'context': ctx,
        'confidence': confidence,
        'raw_for_llm': raw_for_llm,
    }
    try:
        from ultronpro import sir_amplifier

        sir = sir_amplifier.build_sir_from_autobiographical_route(query, route_payload)
        route_payload['sir'] = sir
        route_payload['raw_legacy_for_llm'] = raw_for_llm
        route_payload['raw_for_llm'] = sir_amplifier.build_llm_payload(sir)
    except Exception as exc:
        logger.warning(f"[AutobioRouter] SIR build failed; keeping legacy context: {exc}")
    return route_payload
