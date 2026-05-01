"""
Episodic Compiler — Ciclo Hipótese-Teste-Revisão
==================================================

Abstrações extraídas de episódios são HIPÓTESES, não fatos.
O compilador propõe → o sistema testa em episódios futuros → confirma ou revisa.

Lifecycle:
  hypothesis → under_test → compiled_skill | revised | discarded

Promoção a compiled_skill requer N confirmações acima de threshold.
Falha sistemática (taxa de confirmação < limiar) → revisão ou descarte.
"""

import json
import hashlib
import os
import time
import uuid
from typing import Any
from pathlib import Path

from ultronpro import llm, store

ABSTRACTIONS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'causal_abstractions_v2.json'

# ── Thresholds do ciclo hipótese-teste-revisão ──
MIN_TESTS_FOR_PROMOTION = 5          # Mínimo de testes antes de promover
CONFIRMATION_THRESHOLD = 0.70        # Taxa de confirmação mínima para virar skill
DISCARD_THRESHOLD = 0.30             # Abaixo disso após MIN_TESTS → descarte
REVISION_COOLDOWN_SEC = 3600         # Cooldown entre revisões LLM


def _load_abstractions() -> dict[str, Any]:
    if ABSTRACTIONS_PATH.exists():
        try:
            return json.loads(ABSTRACTIONS_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'version': 2, 'abstractions': []}


def _save_abstractions(data: dict[str, Any]):
    ABSTRACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ABSTRACTIONS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _short_label(value: Any, limit: int = 48) -> str:
    text = str(value or '').strip().replace('_', ' ')
    if not text:
        return 'geral'
    return ' '.join(text.split())[:limit]


def _deterministic_abstraction_payload(domain: str, action_kind: str, episode_data: dict[str, Any]) -> dict[str, Any]:
    """Constrói hipótese causal testável quando o professor LLM não está disponível."""
    episode = episode_data if isinstance(episode_data, dict) else {'episode': episode_data}
    preconditions = episode.get('preconditions') if isinstance(episode.get('preconditions'), dict) else {}
    guards = episode.get('guards') if isinstance(episode.get('guards'), dict) else {}
    evidence = episode.get('evidence') if isinstance(episode.get('evidence'), dict) else {}
    steps = episode.get('steps') if isinstance(episode.get('steps'), list) else []

    condition_keys = sorted(set(preconditions.keys()) | set(guards.keys()) | set(evidence.keys()))
    condition_text = ', '.join(condition_keys[:6]) if condition_keys else 'estado observavel equivalente'
    step_text = ' -> '.join(_short_label(s, 36) for s in steps[:4]) if steps else _short_label(action_kind)
    outcome = _short_label(episode.get('outcome') or episode.get('actual_outcome') or 'success')

    suffix = hashlib.sha1(f"{domain}|{action_kind}".encode("utf-8", errors="ignore")).hexdigest()[:6]

    return {
        'name': f"{_short_label(domain, 20).title().replace(' ', '_')}_{_short_label(action_kind, 20).title().replace(' ', '_')}_{suffix}",
        'causal_structure': (
            f"No dominio {_short_label(domain)}, a acao {_short_label(action_kind)} tende a {outcome} "
            f"quando as condicoes observaveis ({condition_text}) sustentam a sequencia {step_text}."
        ),
        'applicability_conditions': (
            f"Reusar apenas quando o dominio for {_short_label(domain)} ou estruturalmente equivalente, "
            f"com as condicoes ({condition_text}) verificadas antes da acao."
        ),
        'testable_prediction': (
            f"Em novos episodios de {_short_label(domain)} com {_short_label(action_kind)} e baixa surpresa, "
            f"as mesmas condicoes ({condition_text}) devem preservar sucesso operacional acima do baseline."
        ),
        'generalization_suggestion': (
            "Transferir pela estrutura causal das precondicoes, guardas e evidencias, nao pelo nome literal da tarefa."
        ),
    }


def compile_causal_invariant(domain: str, action_kind: str, episode_data: dict[str, Any], surprise_score: float) -> dict[str, Any] | None:
    """Extrai um padrão invariante causal de um episódio bem-sucedido e com baixa surpresa.
    A abstração nasce como HIPÓTESE, não como fato confirmado."""

    if surprise_score > 0.4:
        return None

    prompt = f"""Analise este episódio executado no domínio fechado '{domain}'. Este episódio teve sucesso e baixíssima taxa de surpresa.
Você é um Compilador Cognitivo. Sua tarefa não é resumir a sequência de ações, mas extrair a ESTRUTURA CAUSAL (invariante) que justificou o sucesso, para que o sistema possa reutilizar essa lógica.

Retorne APENAS um objeto JSON com as seguintes chaves:
- "name": Nome curto para a abstração (ex: "Rollback_Atomico_Financeiro")
- "causal_structure": O mecanismo causal central que garante o funcionamento
- "applicability_conditions": Condições contextuais estritas nas quais é seguro reusar
- "testable_prediction": Uma previsão CONCRETA e FALSIFICÁVEL que esta abstração implica (ex: "em operações de arquivo com rollback, threshold de risco 0.7 resulta em sucesso > 80%")
- "generalization_suggestion": Como isso poderia ser abstraído para outros domínios

Dados do Episódio:
{json.dumps(episode_data, ensure_ascii=False)[:3000]}
"""

    if os.environ.get('BENCHMARK_MODE') == '1':
        res = None
    else:
        try:
            res = llm.complete(prompt, json_mode=True, strategy='cheap')
        except Exception:
            res = None
    data = None

    try:
        if res:
            cleaned = res.strip()
            f_idx = cleaned.find('{')
            l_idx = cleaned.rfind('}')
            if f_idx != -1 and l_idx != -1 and l_idx > f_idx:
                data = json.loads(cleaned[f_idx:l_idx+1])
    except Exception:
        data = None

    if not isinstance(data, dict):
        data = _deterministic_abstraction_payload(domain, action_kind, episode_data)

    try:
            abs_record = {
                'id': f"abs_{int(time.time())}_{uuid.uuid4().hex[:4]}",
                'domain': domain,
                'action_kind': action_kind,
                'created_at': int(time.time()),
                'name': data.get('name', 'Abstração Genérica'),
                'causal_structure': data.get('causal_structure', ''),
                'applicability_conditions': data.get('applicability_conditions', ''),
                'testable_prediction': data.get('testable_prediction', ''),
                'generalization_suggestion': data.get('generalization_suggestion', ''),
                # ── Lifecycle fields ──
                'status': 'hypothesis',   # hypothesis | under_test | compiled_skill | revised | discarded
                'version': 1.0,
                'test_count': 0,
                'confirmation_count': 0,
                'refutation_count': 0,
                'confirmation_rate': 0.0,
                'test_history': [],       # últimos N resultados de teste
                'last_tested_at': 0,
                'last_revised_at': 0,
                'revision_count': 0,
                # ── Legacy compat ──
                'usage_count': 0,
                'success_count': 0,
                'baseline_gain': 0.0,
            }

            lib = _load_abstractions()
            recent_names = [a.get('name') for a in lib['abstractions'][-50:]]
            if abs_record['name'] not in recent_names:
                lib['abstractions'].append(abs_record)
                _save_abstractions(lib)

                store.publish_workspace(
                    module='episodic_compiler',
                    channel='causal.hypothesis_proposed',
                    payload_json=json.dumps({
                        'id': abs_record['id'],
                        'name': abs_record['name'],
                        'status': 'hypothesis',
                        'testable_prediction': abs_record['testable_prediction'],
                    }, ensure_ascii=False),
                    salience=0.75,
                    ttl_sec=3600
                )
                return abs_record
    except Exception:
        pass

    return None


def test_abstraction(abs_id: str, episode_data: dict[str, Any], episode_ok: bool,
                     episode_surprise: float) -> dict[str, Any] | None:
    """Testa uma abstração-hipótese contra um novo episódio.
    Verifica se a previsão implícita da abstração se confirmou.
    Retorna o resultado do teste e atualiza o lifecycle."""
    lib = _load_abstractions()
    target = None
    for a in lib['abstractions']:
        if a.get('id') == abs_id:
            target = a
            break
    if not target:
        return None
    if target.get('status') == 'discarded':
        return {'ok': False, 'reason': 'abstraction_discarded'}

    # Determinar se o episódio confirma ou refuta a hipótese
    # Confirmação: episódio bem-sucedido + baixa surpresa no domínio da abstração
    confirmed = episode_ok and episode_surprise < 0.4

    target['test_count'] = target.get('test_count', 0) + 1
    target['last_tested_at'] = int(time.time())

    if confirmed:
        target['confirmation_count'] = target.get('confirmation_count', 0) + 1
    else:
        target['refutation_count'] = target.get('refutation_count', 0) + 1

    # Manter histórico de testes (últimos 20)
    history = target.get('test_history', [])
    history.append({
        'ts': int(time.time()),
        'confirmed': confirmed,
        'surprise': round(episode_surprise, 4),
        'ok': episode_ok,
    })
    target['test_history'] = history[-20:]

    # Calcular taxa de confirmação
    total = target['test_count']
    target['confirmation_rate'] = round(target['confirmation_count'] / max(1, total), 4)

    # ── Lifecycle Transitions ──
    old_status = target.get('status', 'hypothesis')

    if target['status'] in ('hypothesis', 'under_test', 'revised'):
        target['status'] = 'under_test'

        if total >= MIN_TESTS_FOR_PROMOTION:
            if target['confirmation_rate'] >= CONFIRMATION_THRESHOLD:
                # PROMOÇÃO: hipótese → skill compilada
                target['status'] = 'compiled_skill'
                target['version'] = round(target.get('version', 1.0) + 0.5, 1)
                store.publish_workspace(
                    module='episodic_compiler',
                    channel='causal.skill_promoted',
                    payload_json=json.dumps({
                        'id': abs_id,
                        'name': target['name'],
                        'confirmation_rate': target['confirmation_rate'],
                        'tests': total,
                    }, ensure_ascii=False),
                    salience=0.9,
                    ttl_sec=7200
                )
                # Camada 1: episodio autobiografico de conquista cognitiva
                try:
                    from ultronpro import autobiographical_router as _abio
                    _abio.append_self_event(
                        kind='abstraction_promoted',
                        description=(
                            "Abstracao '" + target['name'] + "' promovida a compiled_skill apos " + str(total) + " testes "
                            + "(taxa de confirmacao: " + str(round(target['confirmation_rate']*100)) + "%, dominio: " + str(target.get('domain')) + ")."
                        ),
                        outcome='success',
                        module='episodic_compiler',
                        importance=0.85,
                        extra={'abs_id': abs_id, 'name': target['name'],
                               'confirmation_rate': target['confirmation_rate'],
                               'domain': target.get('domain')},
                    )
                except Exception:
                    pass
            elif target['confirmation_rate'] < DISCARD_THRESHOLD:
                # DESCARTE: falha sistemática
                target['status'] = 'discarded'
                store.publish_workspace(
                    module='episodic_compiler',
                    channel='causal.hypothesis_discarded',
                    payload_json=json.dumps({
                        'id': abs_id,
                        'name': target['name'],
                        'confirmation_rate': target['confirmation_rate'],
                        'tests': total,
                    }, ensure_ascii=False),
                    salience=0.7,
                    ttl_sec=3600
                )
            elif target['confirmation_rate'] < CONFIRMATION_THRESHOLD:
                # REVISÃO: taxa intermediária, pedir ao LLM para refinar
                _maybe_revise(target, lib)

    _save_abstractions(lib)

    return {
        'ok': True,
        'abs_id': abs_id,
        'confirmed': confirmed,
        'status': target['status'],
        'old_status': old_status,
        'confirmation_rate': target['confirmation_rate'],
        'test_count': total,
    }


def _maybe_revise(target: dict[str, Any], lib: dict[str, Any]):
    """Pede ao LLM para revisar uma abstração que não está confirmando bem."""
    now = int(time.time())
    if now - target.get('last_revised_at', 0) < REVISION_COOLDOWN_SEC:
        return  # Cooldown ativo

    if target.get('revision_count', 0) >= 3:
        # Já revisou demais sem melhorar → descartar
        target['status'] = 'discarded'
        return

    prompt = f"""Uma abstração causal está falhando nos testes empíricos.
Nome: {target.get('name')}
Estrutura Causal: {target.get('causal_structure')}
Previsão Testável: {target.get('testable_prediction')}
Taxa de Confirmação: {target.get('confirmation_rate')} ({target.get('confirmation_count')}/{target.get('test_count')} testes)
Últimos testes: {json.dumps(target.get('test_history', [])[-5:], ensure_ascii=False)}

REVISE a abstração. O que ela está errando? Qual variável oculta ela ignora?
Retorne JSON com:
- "revised_causal_structure": A estrutura corrigida
- "revised_prediction": A previsão corrigida
- "revision_reason": Por que a versão anterior falhava"""

    res = llm.complete(prompt, json_mode=True, strategy='cheap')
    if res:
        try:
            cleaned = res.strip()
            f_idx = cleaned.find('{')
            l_idx = cleaned.rfind('}')
            if f_idx != -1 and l_idx != -1:
                data = json.loads(cleaned[f_idx:l_idx+1])
                target['causal_structure'] = data.get('revised_causal_structure', target['causal_structure'])
                target['testable_prediction'] = data.get('revised_prediction', target['testable_prediction'])
                target['status'] = 'revised'
                target['revision_count'] = target.get('revision_count', 0) + 1
                target['last_revised_at'] = now
                target['version'] = round(target.get('version', 1.0) + 0.1, 1)
                # Reset parcial dos contadores para dar chance à versão revisada
                target['test_count'] = 0
                target['confirmation_count'] = 0
                target['refutation_count'] = 0
                target['confirmation_rate'] = 0.0
                target['test_history'] = []

                store.publish_workspace(
                    module='episodic_compiler',
                    channel='causal.hypothesis_revised',
                    payload_json=json.dumps({
                        'id': target['id'],
                        'name': target['name'],
                        'revision_reason': data.get('revision_reason', ''),
                        'revision_count': target['revision_count'],
                    }, ensure_ascii=False),
                    salience=0.8,
                    ttl_sec=3600
                )
                
                # Camada 1: episodio autobiografico de auto-correcao
                try:
                    from ultronpro import autobiographical_router as _abio
                    _abio.append_self_event(
                        kind='abstraction_revised',
                        description=(
                            f"Abstracao '{target['name']}' revisada pelo LLM (revisao #{target.get('revision_count')}) "
                            f"apos falha na taxa de confirmacao. Hipotese refinada com variavel oculta corrigida."
                        ),
                        outcome='correction',
                        module='episodic_compiler',
                        importance=0.75,
                        extra={'id': target['id'], 'name': target['name'],
                               'revision_count': target.get('revision_count')},
                    )
                except Exception:
                    pass

        except Exception:
            pass


def auto_test_applicable(domain: str, episode_data: dict[str, Any],
                         episode_ok: bool, episode_surprise: float) -> list[dict[str, Any]]:
    """Varre todas as hipóteses/under_test aplicáveis ao domínio do episódio
    e testa cada uma automaticamente. Retorna lista de resultados."""
    lib = _load_abstractions()
    results = []
    testable_statuses = {'hypothesis', 'under_test', 'revised', 'compiled_skill'}

    for a in lib['abstractions']:
        if a.get('status') not in testable_statuses:
            continue
        if a.get('domain') != domain:
            continue

        res = test_abstraction(a['id'], episode_data, episode_ok, episode_surprise)
        if res:
            results.append(res)

    return results


def retrieve_applicable_abstractions(domain: str, context_hints: str) -> list[dict[str, Any]]:
    """Recupera abstrações que podem ser reusadas. Prioriza compiled_skills."""
    lib = _load_abstractions()
    matches = []

    for a in lib['abstractions']:
        if a.get('status') == 'discarded':
            continue
        if a.get('domain') == domain:
            matches.append(a)

    # Prioridade: compiled_skill > under_test > hypothesis
    status_order = {'compiled_skill': 0, 'under_test': 1, 'revised': 2, 'hypothesis': 3}
    matches.sort(key=lambda x: (
        status_order.get(x.get('status', 'hypothesis'), 99),
        -x.get('confirmation_rate', 0),
        -x.get('version', 1.0),
    ))
    return matches[:5]


def record_abstraction_usage(abs_id: str, success: bool, base_latency: float, new_latency: float):
    """Mede ganho empírico validando se a abstração foi util no ciclo subsequente."""
    lib = _load_abstractions()
    for a in lib['abstractions']:
        if a.get('id') == abs_id:
            a['usage_count'] = a.get('usage_count', 0) + 1
            if success:
                a['success_count'] = a.get('success_count', 0) + 1

            if base_latency > 0 and new_latency > 0:
                gain = (base_latency - new_latency) / base_latency
                old_gain = a.get('baseline_gain', 0.0)
                a['baseline_gain'] = round((old_gain * (a['usage_count'] - 1) + gain) / a['usage_count'], 4)

            break
    _save_abstractions(lib)


def get_lifecycle_summary() -> dict[str, Any]:
    """Retorna resumo do estado do lifecycle de todas as abstrações."""
    lib = _load_abstractions()
    counts = {'hypothesis': 0, 'under_test': 0, 'compiled_skill': 0, 'revised': 0, 'discarded': 0}
    for a in lib['abstractions']:
        s = a.get('status', 'hypothesis')
        counts[s] = counts.get(s, 0) + 1

    return {
        'total': len(lib['abstractions']),
        'by_status': counts,
        'top_skills': [
            {
                'id': a['id'],
                'name': a['name'],
                'confirmation_rate': a.get('confirmation_rate', 0),
                'tests': a.get('test_count', 0),
            }
            for a in sorted(
                [x for x in lib['abstractions'] if x.get('status') == 'compiled_skill'],
                key=lambda x: x.get('confirmation_rate', 0),
                reverse=True
            )[:5]
        ],
    }
