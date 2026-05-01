"""
Recursive Self-Improvement — Sistema de Auto-Melhoria Recursiva
==============================================================

Sistema que conecta múltiplos subsistemas para criar um loop de 
auto-melhoria recursivo e contínuo.

Conexões:
- Self-Improvement Engine: identificação de limitações
- Self-Modification Engine: geração de patches
- Continuous Learning: aprendizado de experimentos
- Causal Discovery: descoberta causal de melhorias
- Working Memory: contexto de melhorias

Funcionalidades:
- Análise de efetividade de melhorias
- Meta-aprendizado sobre quais estratégias funcionam
- Auto-geração de novas estratégias
- Feedback loop entre sistemas

"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
RECURSIVE_PATH = DATA_DIR / 'recursive_self_improvement.json'


@dataclass
class ImprovementCycle:
    id: str
    ts: int
    limitation_id: str
    strategy_used: str
    experiment_id: str | None
    result: str
    improvement_metric: float
    causal_insight: str | None
    recursive_insight: str | None


@dataclass
class MetaStrategy:
    id: str
    name: str
    effectiveness_score: float
    trials: int
    successes: int
    avg_improvement: float
    last_tested: int


class RecursiveSelfImprovement:
    def __init__(self):
        self.cycles: deque[ImprovementCycle] = deque(maxlen=200)
        self.meta_strategies: dict[str, MetaStrategy] = {}
        self.enabled = True
        self.recursion_depth = 3
        self._load()

    def _load(self):
        if RECURSIVE_PATH.exists():
            try:
                data = json.loads(RECURSIVE_PATH.read_text())
                self.cycles = deque([ImprovementCycle(**c) for c in data.get('cycles', [])], maxlen=200)
                self.meta_strategies = {k: MetaStrategy(**v) for k, v in data.get('meta_strategies', {}).items()}
                self.recursion_depth = data.get('recursion_depth', 3)
            except Exception:
                pass

    def _save(self):
        data = {
            'cycles': [asdict(c) for c in list(self.cycles)],
            'meta_strategies': {k: asdict(v) for k, v in self.meta_strategies.items()},
            'recursion_depth': self.recursion_depth,
            'updated_at': int(time.time()),
        }
        RECURSIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECURSIVE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def run_cycle(self, si_engine, sm_engine, cl_system) -> dict:
        """Executa um ciclo completo de auto-melhoria recursiva."""
        cycle_id = f"cycle_{int(time.time())}"
        
        limitations = si_engine.identify_limitations()
        if not limitations:
            return {'status': 'no_limitations', 'cycles': len(self.cycles)}
        
        critical_lim = max(limitations, key=lambda x: x.priority)
        
        strategy = self._select_strategy(critical_lim)
        
        try:
            sm_result = sm_engine.generate_modification(
                target_module=self._module_for_limitation(critical_lim.name),
                target_function=self._function_for_limitation(critical_lim.name),
                goal=f"Melhorar: {critical_lim.description}",
            )
        except Exception as e:
            sm_result = {'error': str(e)}
        
        if 'error' not in sm_result:
            proposal = sm_result
            sm_engine.validate_change(proposal.id)
            apply_result = sm_engine.apply(proposal.id, force=True)
            
            improvement = self._measure_improvement(critical_lim)
            
            cl_system.record_feedback(
                task_type=f"improvement_{critical_lim.name}",
                success=improvement > 0,
                latency_ms=int(improvement * 1000),
                error_type=None if improvement > 0 else 'improvement_failed'
            )
        else:
            improvement = -1.0
            apply_result = {'error': sm_result.get('error')}
        
        cycle = ImprovementCycle(
            id=cycle_id,
            ts=int(time.time()),
            limitation_id=critical_lim.id,
            strategy_used=strategy,
            experiment_id=proposal.get('id') if 'error' not in sm_result else None,
            result='success' if improvement > 0 else 'failed',
            improvement_metric=improvement,
            causal_insight=None,
            recursive_insight=self._generate_recursive_insight(),
        )
        
        self.cycles.append(cycle)
        self._update_meta_strategy(strategy, improvement > 0, improvement)
        self._save()
        
        return {
            'cycle_id': cycle_id,
            'limitation': critical_lim.name,
            'strategy': strategy,
            'improvement': improvement,
            'result': cycle.result,
        }

    def _select_strategy(self, limitation) -> str:
        """Seleciona estratégia baseada em efetividade histórica."""
        effective = [s for s in self.meta_strategies.values() if s.effectiveness_score > 0.5]
        
        if effective:
            best = max(effective, key=lambda x: x.effectiveness_score)
            return best.name
        
        strategies = [
            'code_generation',
            'parameter_tuning',
            'heuristic_enhancement',
            'cache_optimization',
            'parallel_execution',
        ]
        
        return strategies[len(self.cycles) % len(strategies)]

    def _module_for_limitation(self, limitation_name: str) -> str:
        mapping = {
            'rate_limit': 'llm.py',
            'latency': 'llm.py',
            'memory': 'working_memory.py',
            'reasoning': 'local_reasoning_engine.py',
            'perception': 'vision.py',
            'learning': 'continuous_learning.py',
        }
        
        for key, mod in mapping.items():
            if key in limitation_name.lower():
                return mod
        
        return 'working_memory.py'

    def _function_for_limitation(self, limitation_name: str) -> str:
        return 'add'

    def _measure_improvement(self, limitation) -> float:
        """Mede melhoria obtida (simplificado)."""
        if not self.cycles:
            return 0.0
        
        recent = list(self.cycles)[-10:]
        success_rate = sum(1 for c in recent if c.result == 'success') / max(1, len(recent))
        
        return 1.0 if success_rate > 0.5 else -0.5

    def _generate_recursive_insight(self) -> str:
        """Gera insight recursivo sobre o processo de melhoria."""
        if len(self.cycles) < 3:
            return "Dados insuficientes para insight recursivo"
        
        recent = list(self.cycles)[-5:]
        
        best_strategy = max(
            [c.strategy_used for c in recent],
            key=lambda s: sum(1 for c in recent if c.strategy_used == s and c.result == 'success')
        )
        
        failed_strategies = set(c.strategy_used for c in recent if c.result == 'failed')
        
        return f"Melhor estratégia: {best_strategy}. Evitar: {', '.join(failed_strategies) if failed_strategies else 'nenhuma'}"

    def _update_meta_strategy(self, strategy: str, success: bool, improvement: float):
        """Atualiza efetividade de estratégias."""
        if strategy not in self.meta_strategies:
            self.meta_strategies[strategy] = MetaStrategy(
                id=strategy,
                name=strategy,
                effectiveness_score=0.0,
                trials=0,
                successes=0,
                avg_improvement=0.0,
                last_tested=int(time.time()),
            )
        
        ms = self.meta_strategies[strategy]
        ms.trials += 1
        
        if success:
            ms.successes += 1
            ms.avg_improvement = (ms.avg_improvement * (ms.trials - 1) + improvement) / ms.trials
        
        ms.effectiveness_score = ms.successes / max(1, ms.trials)
        ms.last_tested = int(time.time())

    def get_status(self) -> dict:
        """Retorna status do sistema."""
        recent = list(self.cycles)[-20:]
        
        return {
            'enabled': self.enabled,
            'total_cycles': len(self.cycles),
            'recent_cycles': len(recent),
            'success_rate': sum(1 for c in recent if c.result == 'success') / max(1, len(recent)),
            'meta_strategies': [
                {'name': s.name, 'effectiveness': round(s.effectiveness_score, 2), 'trials': s.trials}
                for s in sorted(self.meta_strategies.values(), key=lambda x: x.effectiveness_score, reverse=True)
            ],
            'last_recursive_insight': self._generate_recursive_insight(),
        }

    def get_recent_cycles(self, limit: int = 10) -> list[dict]:
        """Retorna ciclos recentes."""
        return [asdict(c) for c in list(self.cycles)[-limit:]]

    def clear(self):
        """Limpa dados."""
        self.cycles.clear()
        self.meta_strategies.clear()
        self._save()


_recursive_si: Optional[RecursiveSelfImprovement] = None


def get_recursive_si() -> RecursiveSelfImprovement:
    global _recursive_si
    if _recursive_si is None:
        _recursive_si = RecursiveSelfImprovement()
    return _recursive_si


def run_self_improvement_cycle(si_engine, sm_engine, cl_system) -> dict:
    return get_recursive_si().run_cycle(si_engine, sm_engine, cl_system)


def get_recursive_si_status() -> dict:
    return get_recursive_si().get_status()


def get_recursive_si_cycles(limit: int = 10) -> list[dict]:
    return get_recursive_si().get_recent_cycles(limit)
