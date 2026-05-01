"""
Causal Maturity Assessment — Holdout Validation & Rare State Weighting
=======================================================================

Mede a maturidade causal real do sistema via:
  1. Holdout causal: 80/20 split, mede desempenho preditivo nos episódios reservados
  2. Rare state weighting: episódios com maior surpresa têm peso maior no treinamento
  3. Generalization gap: quando holdout ≈ training, o sistema generalizou de verdade

O critério de maturidade não é "quantos episódios" mas "qual proporção de
estados novos o sistema prevê com erro abaixo de threshold".
"""

from __future__ import annotations

import json
import time
import random
import hashlib
from typing import Any
from pathlib import Path

from ultronpro import store

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
MATURITY_LOG_PATH = DATA_DIR / 'causal_maturity_log.jsonl'
MATURITY_SNAPSHOT_PATH = DATA_DIR / 'causal_maturity_snapshot.json'

# ── Thresholds ──
HOLDOUT_RATIO = 0.20                    # 20% reservados para teste
PREDICTION_ERROR_THRESHOLD = 0.35       # Erro aceitável por episódio
MATURITY_GAP_THRESHOLD = 0.10           # Gap máximo train vs holdout para considerar maduro
RARE_STATE_SURPRISE_THRESHOLD = 0.50    # Acima disso = estado raro
RARE_STATE_WEIGHT_MULTIPLIER = 3.0      # Peso extra no treinamento
MIN_EPISODES_FOR_ASSESSMENT = 15        # Mínimo para um assessment válido


def _deterministic_split(episodes: list[dict[str, Any]], holdout_ratio: float = HOLDOUT_RATIO
                          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split determinístico baseado no hash do episode_id.
    Garante que o mesmo episódio sempre vai para o mesmo set,
    permitindo avaliação reprodutível."""
    train = []
    test = []
    for ep in episodes:
        ep_id = str(ep.get('episode_id') or ep.get('id') or '')
        h = int(hashlib.md5(ep_id.encode()).hexdigest()[:8], 16) % 100
        if h < int(holdout_ratio * 100):
            test.append(ep)
        else:
            train.append(ep)
    return train, test


def _evaluate_prediction_accuracy(episodes: list[dict[str, Any]],
                                   predict_fn) -> dict[str, Any]:
    """Avalia a acurácia preditiva do modelo em um conjunto de episódios.
    Retorna métricas agregadas de erro."""
    if not episodes:
        return {'n': 0, 'mean_error': 1.0, 'accuracy': 0.0, 'rare_state_accuracy': 0.0}

    errors = []
    rare_errors = []
    correct = 0
    rare_correct = 0
    rare_total = 0

    for ep in episodes:
        epi = ep.get('episodic_memory', {}) if isinstance(ep.get('episodic_memory'), dict) else {}
        ctx = epi.get('contexto_entrada', {}) if isinstance(epi.get('contexto_entrada'), dict) else {}
        resultado = epi.get('resultado_objetivo', {}) if isinstance(epi.get('resultado_objetivo'), dict) else {}
        surprise = float(epi.get('surpresa_calculada', 0.5))
        actual_ok = bool(resultado.get('ok', ep.get('ok', False)))

        # Prever com o modelo atual
        try:
            pred = predict_fn(ctx)
        except Exception:
            pred = {'predicted_ok': None, 'confidence': 0.0}

        predicted_ok = bool(pred.get('predicted_ok')) if pred.get('predicted_ok') is not None else None

        # Calcular erro
        if predicted_ok is not None:
            match = (predicted_ok == actual_ok)
            error = 0.0 if match else 1.0
            # Ajustar pelo nível de confiança (erro ponderado)
            confidence = float(pred.get('confidence', 0.5))
            weighted_error = error * (1.0 + (1.0 - confidence))  # Mais penalidade se estava confiante e errou
        else:
            match = False
            error = 1.0
            weighted_error = 1.0

        errors.append(weighted_error)
        if match:
            correct += 1

        # Tracking de estados raros
        is_rare = surprise >= RARE_STATE_SURPRISE_THRESHOLD
        if is_rare:
            rare_total += 1
            rare_errors.append(weighted_error)
            if match:
                rare_correct += 1

    n = len(errors)
    mean_error = sum(errors) / max(1, n)
    accuracy = correct / max(1, n)
    rare_accuracy = rare_correct / max(1, rare_total) if rare_total > 0 else None

    return {
        'n': n,
        'mean_error': round(mean_error, 4),
        'accuracy': round(accuracy, 4),
        'rare_state_count': rare_total,
        'rare_state_accuracy': round(rare_accuracy, 4) if rare_accuracy is not None else None,
        'rare_state_mean_error': round(sum(rare_errors) / max(1, len(rare_errors)), 4) if rare_errors else None,
    }


def run_maturity_assessment(episodes: list[dict[str, Any]],
                             predict_fn,
                             domain: str = 'all') -> dict[str, Any]:
    """Executa a avaliação completa de maturidade causal.

    Args:
        episodes: Episódios estruturados do sistema
        predict_fn: Função que recebe contexto e retorna previsão
        domain: Filtro de domínio (ou 'all')

    Returns:
        Avaliação de maturidade com métricas train/holdout e gap de generalização.
    """
    now = int(time.time())

    # Filtrar por domínio se necessário
    if domain != 'all':
        episodes = [
            e for e in episodes
            if str((e.get('episodic_memory', {}).get('contexto_entrada', {}) or {}).get('preflight_domain_mode', '')) == domain
               or str(e.get('task_type', '')) == domain
        ]

    if len(episodes) < MIN_EPISODES_FOR_ASSESSMENT:
        return {
            'ok': False,
            'reason': f'insufficient_episodes ({len(episodes)}/{MIN_EPISODES_FOR_ASSESSMENT})',
            'domain': domain,
            'episode_count': len(episodes),
        }

    # ── Split determinístico ──
    train_set, holdout_set = _deterministic_split(episodes)

    if len(holdout_set) < 3:
        return {
            'ok': False,
            'reason': 'holdout_too_small',
            'domain': domain,
            'train_size': len(train_set),
            'holdout_size': len(holdout_set),
        }

    # ── Avaliar em ambos os conjuntos ──
    train_metrics = _evaluate_prediction_accuracy(train_set, predict_fn)
    holdout_metrics = _evaluate_prediction_accuracy(holdout_set, predict_fn)

    # ── Calcular Gap de Generalização ──
    train_accuracy = train_metrics['accuracy']
    holdout_accuracy = holdout_metrics['accuracy']
    generalization_gap = round(abs(train_accuracy - holdout_accuracy), 4)

    # ── Determinar Maturidade ──
    is_mature = (
        generalization_gap <= MATURITY_GAP_THRESHOLD
        and holdout_metrics['mean_error'] <= PREDICTION_ERROR_THRESHOLD
        and holdout_metrics['n'] >= 3
    )

    # ── Análise de Estados Raros ──
    rare_coverage = 'insufficient_data'
    if holdout_metrics.get('rare_state_count', 0) > 0:
        rare_acc = holdout_metrics.get('rare_state_accuracy', 0)
        if rare_acc is not None and rare_acc >= 0.5:
            rare_coverage = 'adequate'
        elif rare_acc is not None:
            rare_coverage = 'poor'

    result = {
        'ok': True,
        'ts': now,
        'domain': domain,
        'episode_count': len(episodes),
        'train_size': len(train_set),
        'holdout_size': len(holdout_set),
        'train_metrics': train_metrics,
        'holdout_metrics': holdout_metrics,
        'generalization_gap': generalization_gap,
        'is_mature': is_mature,
        'rare_state_coverage': rare_coverage,
        'maturity_criteria': {
            'gap_ok': generalization_gap <= MATURITY_GAP_THRESHOLD,
            'holdout_error_ok': holdout_metrics['mean_error'] <= PREDICTION_ERROR_THRESHOLD,
            'holdout_size_ok': holdout_metrics['n'] >= 3,
            'rare_coverage_ok': rare_coverage == 'adequate',
        },
    }

    # Persistir snapshot e log
    try:
        _persist_assessment(result)
    except Exception:
        pass

    # Publicar no workspace
    try:
        store.publish_workspace(
            module='causal_maturity',
            channel='maturity.assessment',
            payload_json=json.dumps({
                'domain': domain,
                'is_mature': is_mature,
                'generalization_gap': generalization_gap,
                'holdout_accuracy': holdout_accuracy,
                'rare_coverage': rare_coverage,
            }, ensure_ascii=False),
            salience=0.85 if is_mature else 0.6,
            ttl_sec=7200
        )
    except Exception:
        pass

    return result


def compute_surprise_weight(surprise: float) -> float:
    """Calcula o peso de treinamento baseado na surpresa.
    Estados raros (alta surpresa) recebem peso multiplicado.
    Estados previsíveis (baixa surpresa) recebem peso base."""
    if surprise >= RARE_STATE_SURPRISE_THRESHOLD:
        # Peso exponencialmente maior para estados raros
        return 1.0 + (RARE_STATE_WEIGHT_MULTIPLIER - 1.0) * min(1.0, surprise)
    return 1.0


def get_weighted_training_episodes(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retorna episódios com pesos de treinamento.
    Episódios com alta surpresa são sobre-amostrados (weight > 1)
    para forçar o modelo a aprender nos casos difíceis."""
    weighted = []
    for ep in episodes:
        epi = ep.get('episodic_memory', {}) if isinstance(ep.get('episodic_memory'), dict) else {}
        surprise = float(epi.get('surpresa_calculada', 0.0))
        weight = compute_surprise_weight(surprise)
        weighted.append({
            **ep,
            '_training_weight': round(weight, 4),
            '_is_rare_state': surprise >= RARE_STATE_SURPRISE_THRESHOLD,
        })

    # Ordenar por peso descendente: estados raros primeiro
    weighted.sort(key=lambda x: x.get('_training_weight', 1.0), reverse=True)
    return weighted


def _persist_assessment(result: dict[str, Any]):
    """Persiste o resultado da avaliação para auditoria."""
    MATURITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MATURITY_LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(result, ensure_ascii=False) + '\n')

    # Snapshot mais recente por domínio
    snapshot = {}
    if MATURITY_SNAPSHOT_PATH.exists():
        try:
            snapshot = json.loads(MATURITY_SNAPSHOT_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass

    snapshot[result.get('domain', 'all')] = {
        'ts': result['ts'],
        'is_mature': result['is_mature'],
        'generalization_gap': result['generalization_gap'],
        'holdout_accuracy': result['holdout_metrics']['accuracy'],
        'train_accuracy': result['train_metrics']['accuracy'],
        'rare_coverage': result.get('rare_state_coverage'),
        'episode_count': result['episode_count'],
    }
    MATURITY_SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')


def get_maturity_snapshot() -> dict[str, Any]:
    """Retorna o snapshot mais recente de maturidade por domínio."""
    if not MATURITY_SNAPSHOT_PATH.exists():
        return {}
    try:
        return json.loads(MATURITY_SNAPSHOT_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}
