from __future__ import annotations
import math
from typing import Any, Tuple

def _clip(v: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(v)))

def estimate_uncertainty(successes: int, total: int, prior_alpha: float = 1.0, prior_beta: float = 1.0) -> dict[str, Any]:
    """
    Estima a incerteza estatística usando a posterior Beta para um processo de Bernoulli.
    Retorna a confiança (média), a incerteza (largura do intervalo de credibilidade) e o score calibrado.
    """
    alpha = prior_alpha + successes
    beta = prior_beta + (total - successes)
    
    # Média da posterior (confiança bayesiana)
    mean = alpha / (alpha + beta)
    
    # Variância da posterior
    variance = (alpha * beta) / ((alpha + beta)**2 * (alpha + beta + 1))
    std_dev = math.sqrt(variance)
    
    # Intervalo de credibilidade aproximado (95% ~ 2 sigmas)
    # Largura do intervalo é uma métrica direta de incerteza epistêmica
    uncertainty = _clip(2 * std_dev)
    
    # Score calibrado penalizando pela incerteza (conservative lower bound)
    calibrated_score = _clip(mean - std_dev)
    
    return {
        'mean': round(mean, 4),
        'uncertainty': round(uncertainty, 4),
        'std_dev': round(std_dev, 4),
        'calibrated_score': round(calibrated_score, 4),
        'sample_robustness': round(_clip(total / 20.0), 4) # 1.0 se tivermos 20+ amostras
    }

def calibrate_prediction(base_confidence: float, domain_stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Ajusta uma confiança base baseada no histórico estatístico do domínio.
    """
    if not domain_stats:
        return {
            'calibrated': round(base_confidence * 0.8, 4), # Penalização padrão para ignorância
            'uncertainty': 0.5,
            'reason': 'no_historical_data'
        }
    
    s = int(domain_stats.get('success', 0))
    t = int(domain_stats.get('count', 0))
    
    est = estimate_uncertainty(s, t)
    
    # Se a estatística bayesiana for muito diferente da confiança baseada no LLM, 
    # projeta uma média ponderada.
    confidence = (base_confidence * 0.3) + (est['calibrated_score'] * 0.7)
    
    return {
        'calibrated': round(confidence, 4),
        'uncertainty': est['uncertainty'],
        'sample_size': t,
        'is_robust': t >= 10
    }
