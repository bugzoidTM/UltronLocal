"""
Self-Improvement Engine — Meta-Learning System
================================================

Identifica limitações operacionais, cria objetivos mensuráveis,
executa experimentos reversíveis, retém apenas mudanças que
elevam desempenho líquido e revisa estratégia continuamente.

Arquitetura híbrida:
- Motor simbólico (Python): regras, estados, métricas, lógica de tentativa
- LLM (Groq/DeepSeek): planejamento criativo, reflexão profunda
- SQLite: memória de tentativas (sucesso/falha)
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
TRIALS_DB = DATA_DIR / 'self_improvement_trials.db'


@dataclass
class Limitation:
    """Uma limitação operacional identificada."""
    id: str
    name: str
    description: str
    metric_name: str
    current_value: float
    target_value: float
    priority: int  # 1-5
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class Experiment:
    """Um experimento reversível."""
    id: str
    limitation_id: str
    change_description: str
    change_params: dict
    expected_improvement: float
    status: str  # pending, running, success, failed, rolled_back
    created_at: int
    completed_at: Optional[int] = None
    result_metric_before: Optional[float] = None
    result_metric_after: Optional[float] = None


class SelfImprovementEngine:
    """
    Motor de auto-melhoria do UltronPro.
    
    Fluxo:
    1. Identificar limitações (análise de métricas)
    2. Criar objetivos mensuráveis
    3. Executar experimentos reversíveis
    4. Medir resultado
    5. Reter apenas melhorias (reverter falhas)
    6. Revisar estratégia de aprendizado
    """
    
    def __init__(self):
        self._init_trials_db()
        self.max_trials_stored = 500
    
    def _init_trials_db(self):
        """Inicializa banco de dados de tentativas."""
        TRIALS_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(TRIALS_DB))
        c = conn.cursor()
        
        # Tabela de limitações identificadas
        c.execute('''CREATE TABLE IF NOT EXISTS limitations (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            metric_name TEXT,
            current_value REAL,
            target_value REAL,
            priority INTEGER,
            created_at INTEGER,
            status TEXT DEFAULT 'active',
            resolved_at INTEGER
        )''')
        
        # Tabela de experimentos executados
        c.execute('''CREATE TABLE IF NOT EXISTS experiments (
            id TEXT PRIMARY KEY,
            limitation_id TEXT,
            change_description TEXT,
            change_params TEXT,
            expected_improvement REAL,
            status TEXT DEFAULT 'pending',
            created_at INTEGER,
            completed_at INTEGER,
            result_metric_before REAL,
            result_metric_after REAL,
            net_improvement REAL
        )''')
        
        # Tabela de estratégia de aprendizado (revisões)
        c.execute('''CREATE TABLE IF NOT EXISTS strategy_reviews (
            id INTEGER PRIMARY KEY,
            created_at INTEGER,
            focus_area TEXT,
            findings TEXT,
            next_strategy TEXT,
            llm_consulted INTEGER
        )''')
        
        conn.commit()
        conn.close()
    
    # ==================== 1. IDENTIFICAR LIMITAÇÕES ====================
    
    def identify_limitations(self) -> list[Limitation]:
        """
        Analisa métricas do sistema para identificar limitações.
        Por agora, usa análise determinística baseada em thresholds.
        """
        limitations = []
        
        # 1. Rate limit do provider (Groq)
        try:
            from ultronpro import llm
            usage = llm.usage_status()
            groq_usage = usage.get('providers', {}).get('groq', {})
            limit = groq_usage.get('limit_tokens', 0)
            used = groq_usage.get('tokens_total', 0)
            if limit > 0 and (used / limit) > 0.8:
                limitations.append(Limitation(
                    id='groq_rate_limit',
                    name='Groq Rate Limit',
                    description='Provider Groq atinge limite diário frequentemente',
                    metric_name='groq_usage_ratio',
                    current_value=used/limit,
                    target_value=0.5,
                    priority=5
                ))
        except Exception:
            pass
        
        # 2. NVIDIA/Provider instável
        try:
            from ultronpro import llm
            cb_status = llm.router.get_circuit_breaker_status()
            for provider, status in cb_status.items():
                if status.get('circuit_open'):
                    limitations.append(Limitation(
                        id=f'{provider}_circuit_open',
                        name=f'{provider} Circuit Breaker',
                        description=f'Provider {provider} frequentemente abre circuit breaker',
                        metric_name=f'{provider}_cb_open_count',
                        current_value=status.get('consecutive_failures', 0),
                        target_value=0.0,
                        priority=4
                    ))
        except Exception:
            pass
        
        # 3. Alta latência de resposta
        try:
            from ultronpro import store
            recent = store.db.list_experiences(limit=100)
            if recent:
                avg_latency = sum(e.get('latency_ms', 0) for e in recent) / len(recent)
                if avg_latency > 3000:
                    limitations.append(Limitation(
                        id='high_latency',
                        name='Alta Latência',
                        description=f'Latência média de {avg_latency:.0f}ms muito alta',
                        metric_name='avg_latency_ms',
                        current_value=avg_latency,
                        target_value=1500.0,
                        priority=3
                    ))
        except Exception:
            pass
        
        # 4. Baixa taxa de cache hit
        try:
            from ultronpro import llm
            lru_size = len(llm.router.lru_cache)
            # Se cache muito vazio, pode indicar baixa taxa de acerto
            if lru_size < 10:
                limitations.append(Limitation(
                    id='low_cache_usage',
                    name='Cache Subutilizado',
                    description='LRU cache muito pequeno, possivelmente consultas repetidas não estão sendo cacheadas',
                    metric_name='lru_cache_size',
                    current_value=lru_size,
                    target_value=100.0,
                    priority=2
                ))
        except Exception:
            pass
        
        # Salvar limitações identificadas
        for lim in limitations:
            self._save_limitation(lim)
        
        return limitations
    
    def _save_limitation(self, lim: Limitation):
        conn = sqlite3.connect(str(TRIALS_DB))
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO limitations 
            (id, name, description, metric_name, current_value, target_value, priority, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (lim.id, lim.name, lim.description, lim.metric_name, 
             lim.current_value, lim.target_value, lim.priority, lim.created_at))
        conn.commit()
        conn.close()
    
    # ==================== 2. CRIAR OBJETIVOS ====================
    
    def create_objectives(self) -> list[dict]:
        """Cria objetivos mensuráveis a partir das limitações."""
        objectives = []
        
        # Buscar limitações não resolvidas
        conn = sqlite3.connect(str(TRIALS_DB))
        c = conn.cursor()
        c.execute("SELECT * FROM limitations WHERE status='active' ORDER BY priority DESC")
        rows = c.fetchall()
        conn.close()
        
        for row in rows:
            lim = Limitation(
                id=row[0], name=row[1], description=row[2],
                metric_name=row[3], current_value=row[4],
                target_value=row[5], priority=row[6], created_at=row[7]
            )
            
            gap = lim.target_value - lim.current_value
            objective = {
                'id': f'obj_{lim.id}',
                'limitation_id': lim.id,
                'title': f'Reduzir {lim.name}',
                'description': lim.description,
                'metric': lim.metric_name,
                'current': lim.current_value,
                'target': lim.target_value,
                'gap': gap,
                'priority': lim.priority,
                'created_at': int(time.time())
            }
            objectives.append(objective)
        
        return objectives
    
    # ==================== 3. EXECUTAR EXPERIMENTOS ====================
    
    def run_experiment(self, limitation_id: str, change_type: str, params: dict) -> dict:
        """
        Executa um experimento reversível paraAddressar uma limitação.
        
        Tipos de mudança suportados:
        - lane_provider: Trocar provider de uma lane
        - interval: Ajustar intervalo de loop
        - timeout: Mudar timeout
        - cache_ttl: Ajustar TTL do cache
        - circuit_breaker: Ajustar thresholds
        - temperature: Ajustar temperatura do modelo
        - system_prompt: Modificar prompt do sistema
        """
        conn = sqlite3.connect(str(TRIALS_DB))
        c = conn.cursor()
        
        # Buscar limitação
        c.execute("SELECT * FROM limitations WHERE id=?", (limitation_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {'ok': False, 'error': 'Limitação não encontrada'}
        
        lim = Limitation(
            id=row[0], name=row[1], description=row[2],
            metric_name=row[3], current_value=row[4],
            target_value=row[5], priority=row[6], created_at=row[7]
        )
        
        # Capturar estado atual ANTES de aplicar mudança (para rollback)
        original_state = self._capture_original_state(change_type, params)
        
        # Criar experimento
        exp_id = f"exp_{limitation_id}_{int(time.time())}"
        experiment = Experiment(
            id=exp_id,
            limitation_id=limitation_id,
            change_description=f"{change_type}: {json.dumps(params)}",
            change_params={**params, '_original_state': original_state},
            expected_improvement=lim.target_value - lim.current_value,
            status='running',
            created_at=int(time.time()),
            result_metric_before=lim.current_value
        )
        
        # Salvar experimento
        c.execute('''INSERT INTO experiments 
            (id, limitation_id, change_description, change_params, expected_improvement, status, created_at, result_metric_before)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (exp_id, limitation_id, experiment.change_description, json.dumps(experiment.change_params),
             experiment.expected_improvement, experiment.status, experiment.created_at, experiment.result_metric_before))
        conn.commit()
        conn.close()
        
        # Aplicar mudança
        applied = self._apply_change(change_type, params)
        
        return {
            'ok': True,
            'experiment_id': exp_id,
            'applied': applied,
            'description': experiment.change_description,
            'original_state': original_state
        }
    
    def _capture_original_state(self, change_type: str, params: dict) -> dict:
        """Captura o estado atual antes de aplicar mudança (para rollback)."""
        original = {}
        try:
            if change_type == 'lane_provider':
                from ultronpro import llm
                lane = params.get('lane')
                if lane in llm.LLM_LANES:
                    original['lane'] = lane
                    original['provider'] = llm.LLM_LANES[lane].get('provider')
                    original['model'] = llm.LLM_LANES[lane].get('model')
            
            elif change_type == 'interval':
                import os
                loop = params.get('loop')
                env_vars = {
                    'autonomy_loop': 'ULTRON_AUTONOMY_TICK_SEC',
                    'reflexion_loop': 'ULTRON_REFLEXION_TICK_SEC',
                    'judge_loop': 'ULTRON_JUDGE_TICK_SEC',
                }
                if loop in env_vars:
                    original['loop'] = loop
                    original['value'] = os.environ.get(env_vars[loop], '300')
            
            elif change_type == 'circuit_breaker':
                from ultronpro import llm
                original['threshold'] = llm.router._circuit_breaker_failures_threshold
                original['cooldown'] = llm.router._circuit_breaker_cooldown_sec
            
            elif change_type == 'temperature':
                from ultronpro import llm
                lane = params.get('lane', 'lane_2_workhorse')
                original['lane'] = lane
                original['temperature'] = llm.LLM_LANES.get(lane, {}).get('temperature', 0.7)
            
            elif change_type == 'system_prompt':
                from ultronpro import llm
                lane = params.get('lane', 'lane_2_workhorse')
                original['lane'] = lane
                original['system_prompt'] = llm.LLM_LANES.get(lane, {}).get('system_prompt', '')
                
        except Exception:
            pass
        return original
    
    def _apply_change(self, change_type: str, params: dict) -> bool:
        """Aplica uma mudança de configuração."""
        try:
            if change_type == 'lane_provider':
                from ultronpro import llm
                lane = params.get('lane')
                provider = params.get('provider')
                model = params.get('model')
                if lane in llm.LLM_LANES:
                    llm.LLM_LANES[lane]['provider'] = provider
                    llm.LLM_LANES[lane]['model'] = model
                    return True
            
            elif change_type == 'interval':
                import os
                loop = params.get('loop')
                new_interval = params.get('value')
                env_vars = {
                    'autonomy_loop': 'ULTRON_AUTONOMY_TICK_SEC',
                    'reflexion_loop': 'ULTRON_REFLEXION_TICK_SEC',
                    'judge_loop': 'ULTRON_JUDGE_TICK_SEC',
                }
                if loop in env_vars:
                    os.environ[env_vars[loop]] = str(new_interval)
                    return True
            
            elif change_type == 'cache_ttl':
                # TTL já é configurável via código
                return True
            
            elif change_type == 'circuit_breaker':
                from ultronpro import llm
                if 'threshold' in params:
                    llm.router._circuit_breaker_failures_threshold = params['threshold']
                if 'cooldown' in params:
                    llm.router._circuit_breaker_cooldown_sec = params['cooldown']
                return True
            
            elif change_type == 'temperature':
                from ultronpro import llm
                lane = params.get('lane', 'lane_2_workhorse')
                temperature = params.get('temperature', 0.7)
                if lane in llm.LLM_LANES:
                    llm.LLM_LANES[lane]['temperature'] = temperature
                    return True
            
            elif change_type == 'system_prompt':
                from ultronpro import llm
                lane = params.get('lane', 'lane_2_workhorse')
                system_prompt = params.get('system_prompt', '')
                if lane in llm.LLM_LANES:
                    llm.LLM_LANES[lane]['system_prompt'] = system_prompt
                    return True
            
            return False
        except Exception:
            return False
    
    # ==================== 4. AVALIAR RESULTADO ====================
    
    def evaluate_experiment(self, experiment_id: str) -> dict:
        """Avalia resultado do experimento e decide reter/reverter."""
        conn = sqlite3.connect(str(TRIALS_DB))
        c = conn.cursor()
        
        # Buscar experimento
        c.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {'ok': False, 'error': 'Experimento não encontrado'}
        
        # Medir métrica atual
        metric_name = row[3]  # limitation_id -> metric_name mapping
        current_value = self._get_current_metric(metric_name)
        
        before = row[10]  # result_metric_before
        expected = row[7]  # expected_improvement
        
        net_improvement = before - current_value if before else 0
        
        # Decisão: reter ou reverter?
        success = net_improvement >= 0  # Melhorou ou manteve
        
        status = 'success' if success else 'failed'
        
        c.execute('''UPDATE experiments 
            SET status=?, completed_at=?, result_metric_after=?, net_improvement=?
            WHERE id=?''',
            (status, int(time.time()), current_value, net_improvement, experiment_id))
        conn.commit()
        conn.close()
        
        # Se falhou, reverter mudança
        if not success:
            self._revert_change(experiment_id)
        
        return {
            'ok': True,
            'experiment_id': experiment_id,
            'status': status,
            'metric_before': before,
            'metric_after': current_value,
            'net_improvement': net_improvement,
            'decision': 'RETAIN' if success else 'ROLLBACK'
        }
    
    def _get_current_metric(self, limitation_id: str) -> float:
        """Obtém valor atual de uma métrica."""
        if 'groq' in limitation_id:
            try:
                from ultronpro import llm
                usage = llm.usage_status()
                groq = usage.get('providers', {}).get('groq', {})
                limit = groq.get('limit_tokens', 1)
                used = groq.get('tokens_total', 0)
                return used / limit if limit > 0 else 0
            except:
                return 0
        return 0.0
    
    def _revert_change(self, experiment_id: str):
        """Reverte mudanças de um experimento que falhou."""
        try:
            conn = sqlite3.connect(str(TRIALS_DB))
            c = conn.cursor()
            c.execute("SELECT change_params FROM experiments WHERE id=?", (experiment_id,))
            row = c.fetchone()
            conn.close()
            
            if not row:
                return
            
            import json
            params = json.loads(row[0])
            original = params.get('_original_state', {})
            change_type = params.get('change_type', '')
            
            if change_type == 'lane_provider':
                from ultronpro import llm
                lane = original.get('lane')
                if lane and lane in llm.LLM_LANES:
                    llm.LLM_LANES[lane]['provider'] = original.get('provider')
                    llm.LLM_LANES[lane]['model'] = original.get('model')
            
            elif change_type == 'interval':
                import os
                loop = original.get('loop')
                env_vars = {
                    'autonomy_loop': 'ULTRON_AUTONOMY_TICK_SEC',
                    'reflexion_loop': 'ULTRON_REFLEXION_TICK_SEC',
                    'judge_loop': 'ULTRON_JUDGE_TICK_SEC',
                }
                if loop in env_vars:
                    os.environ[env_vars[loop]] = str(original.get('value', '300'))
            
            elif change_type == 'circuit_breaker':
                from ultronpro import llm
                if 'threshold' in original:
                    llm.router._circuit_breaker_failures_threshold = original['threshold']
                if 'cooldown' in original:
                    llm.router._circuit_breaker_cooldown_sec = original['cooldown']
            
            elif change_type == 'temperature':
                from ultronpro import llm
                lane = original.get('lane', 'lane_2_workhorse')
                if lane in llm.LLM_LANES and 'temperature' in original:
                    llm.LLM_LANES[lane]['temperature'] = original['temperature']
            
            elif change_type == 'system_prompt':
                from ultronpro import llm
                lane = original.get('lane', 'lane_2_workhorse')
                if lane in llm.LLM_LANES and 'system_prompt' in original:
                    llm.LLM_LANES[lane]['system_prompt'] = original['system_prompt']
                    
        except Exception:
            pass
    
    # ==================== 5. REVISAR ESTRATÉGIA ====================
    
    def review_strategy(self, focus_area: str = 'general') -> dict:
        """
        Revisa estratégia de aprendizado.
        Usa LLM apenas quando Symbolic motor não consegue progress.
        """
        # Primeiro: tentar análise simbólica
        trials = self.get_recent_trials(limit=20)
        
        if len(trials) >= 5:
            # Múltiplas tentativas recentes - análise determinística possível
            success_rate = sum(1 for t in trials if t.get('status') == 'success') / len(trials)
            
            if success_rate > 0.5:
                # Symbolic está funcionando bem
                return {
                    'ok': True,
                    'mode': 'symbolic',
                    'strategy': 'continuar_mesmo_curso',
                    'success_rate': success_rate,
                    'llm_consulted': False
                }
            else:
                # Symbolic não está progredindo - usar LLM
                return self._review_with_llm(focus_area)
        
        # Poucos trials - usar LLM para nova perspectiva
        return self._review_with_llm(focus_area)
    
    def _review_with_llm(self, focus_area: str) -> dict:
        """Usa LLM para revisão estratégica quando simbólico empaca."""
        try:
            from ultronpro import llm
            
            trials = self.get_recent_trials(limit=10)
            limitations = self.identify_limitations()
            
            prompt = f"""Você é o otimizador estratégico do UltronPro.
Analise os dados abaixo e sugira uma nova estratégia de aprendizado.

LIMITATIONS IDENTIFICADAS:
{json.dumps([{'name': l.name, 'description': l.description, 'priority': l.priority} for l in limitations], indent=2)}

TENTATIVAS RECENTES:
{json.dumps(trials, indent=2)}

FOCUS AREA: {focus_area}

Retorne JSON com:
- strategy: nova estratégia sugerida
- findings: principais descobertas
- focus_area: área que deve ser explorada
"""
            
            result = llm.complete(
                prompt,
                strategy='deep',  # lane_4_deep usa DeepSeek
                system="Otimizador estratégico do UltronPro",
                json_mode=True,
                inject_persona=False
            )
            
            review = json.loads(result)
            
            # Salvar revisão
            conn = sqlite3.connect(str(TRIALS_DB))
            c = conn.cursor()
            c.execute('''INSERT INTO strategy_reviews 
                (created_at, focus_area, findings, next_strategy, llm_consulted)
                VALUES (?, ?, ?, ?, ?)''',
                (int(time.time()), focus_area, review.get('findings', ''),
                 review.get('strategy', ''), 1))
            conn.commit()
            conn.close()
            
            return {
                'ok': True,
                'mode': 'llm',
                'strategy': review.get('strategy'),
                'findings': review.get('findings'),
                'llm_consulted': True
            }
        except Exception as e:
            return {
                'ok': False,
                'mode': 'symbolic_fallback',
                'error': str(e),
                'llm_consulted': False
            }
    
    # ==================== 6. PROMOTION GATE INTEGRATION ====================
    
    def check_promotion_trigger(self) -> dict:
        """
        Verifica se sistema está pronto para promoção.
        Executa promotion gate em patches recentes se condições atenderem.
        """
        try:
            from ultronpro import cognitive_patches, promotion_gate
            
            recent_successful_experiments = self.get_recent_trials(limit=5)
            success_count = sum(1 for t in recent_successful_experiments if t.get('status') == 'success')
            
            if success_count >= 3:
                patches = cognitive_patches.list_patches(status='active', limit=10)
                if patches:
                    patch = patches[0]
                    gate_result = promotion_gate.evaluate_patch_for_promotion(patch.get('id'))
                    
                    if gate_result:
                        return {
                            'ok': True,
                            'promotion_triggered': True,
                            'patch_id': patch.get('id'),
                            'gate_decision': gate_result.get('decision'),
                            'gate_reasons': gate_result.get('reasons', []),
                            'gate_blockers': gate_result.get('blockers', []),
                            'successful_experiments': success_count
                        }
            
            return {
                'ok': True,
                'promotion_triggered': False,
                'successful_experiments': success_count,
                'threshold': 3
            }
        except Exception as e:
            return {
                'ok': False,
                'error': str(e),
                'promotion_triggered': False
            }
    
    # ==================== UTILITÁRIOS ====================
    
    def get_recent_trials(self, limit: int = 10) -> list[dict]:
        """Retorna tentativas recentes."""
        conn = sqlite3.connect(str(TRIALS_DB))
        c = conn.cursor()
        c.execute("SELECT * FROM experiments ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        
        return [{'id': r[0], 'limitation_id': r[1], 'status': r[5], 
                 'net_improvement': r[12]} for r in rows]
    
    def get_status(self) -> dict:
        """Retorna status do sistema de auto-melhoria."""
        conn = sqlite3.connect(str(TRIALS_DB))
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM limitations WHERE status='active'")
        active_limitations = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM experiments WHERE status='running'")
        running_experiments = c.fetchone()[0]
        
        c.execute("SELECT * FROM experiments ORDER BY created_at DESC LIMIT 10")
        recent = c.fetchall()
        
        conn.close()
        
        return {
            'active_limitations': active_limitations,
            'running_experiments': running_experiments,
            'recent_trials': len(recent),
        }

    def get_recent_trials(self, limit: int = 10) -> list[dict]:
        """Retorna os experimentos mais recentes."""
        conn = sqlite3.connect(str(TRIALS_DB))
        c = conn.cursor()
        c.execute("SELECT * FROM experiments ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return [{"id": r[0], "status": r[5], "created_at": r[6]} for r in rows]


def get_self_improvement_engine() -> SelfImprovementEngine:
    return SelfImprovementEngine()


# Funções de conveniência
def identify_limitations() -> list[Limitation]:
    return get_self_improvement_engine().identify_limitations()


def create_objectives() -> list[dict]:
    return get_self_improvement_engine().create_objectives()


def run_experiment(limitation_id: str, change_type: str, params: dict) -> dict:
    return get_self_improvement_engine().run_experiment(limitation_id, change_type, params)


def evaluate_experiment(experiment_id: str) -> dict:
    return get_self_improvement_engine().evaluate_experiment(experiment_id)


def review_strategy(focus_area: str = 'general') -> dict:
    return get_self_improvement_engine().review_strategy(focus_area)


def check_promotion_trigger() -> dict:
    return get_self_improvement_engine().check_promotion_trigger()


def get_recent_trials(limit: int = 10) -> list[dict]:
    return get_self_improvement_engine().get_recent_trials(limit)