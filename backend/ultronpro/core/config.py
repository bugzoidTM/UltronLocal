"""
ultronpro.core.config
=====================
Todas as constantes de configuração do UltronPro derivadas de variáveis de
ambiente (ENV flags, timeouts, caminhos de dados, cooldowns de ações).

Regra: este módulo usa APENAS stdlib (os, pathlib). Jamais importa de
`ultronpro.*` nem de `fastapi` para evitar dependências circulares.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _env_flag(name: str, default: str = '0') -> bool:
    """Retorna True para valores '1', 'true', 'yes', 'on' (case-insensitive)."""
    return str(os.getenv(name, default)).strip().lower() in ('1', 'true', 'yes', 'on')


# ---------------------------------------------------------------------------
# Paths de dados (base relativa ao pacote ultronpro/)
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'

RUNTIME_HEALTH_PATH         = _DATA_DIR / 'runtime_health.json'
TURBO_REPORT_PATH           = _DATA_DIR / 'turbo_safe_report.json'
BENCHMARK_HISTORY_PATH      = _DATA_DIR / 'benchmark_history.json'
PERSISTENT_GOALS_PATH       = _DATA_DIR / 'persistent_goals.json'
DEEP_CONTEXT_PATH           = _DATA_DIR / 'deep_context_snapshot.json'
MISSION_CONTROL_LOG_PATH    = _DATA_DIR / 'mission_control_log.jsonl'
MISSION_CONTROL_CFG_PATH    = _DATA_DIR / 'mission_control_config.json'
MISSION_CONTROL_STATE_PATH  = _DATA_DIR / 'mission_control_state.json'
PROCEDURE_ARTIFACTS_DIR     = _DATA_DIR / 'procedure_artifacts'
NEUROPLASTIC_GATE_STATE_PATH = _DATA_DIR / 'neuroplastic_gate_state.json'

# ---------------------------------------------------------------------------
# Budgets / timeouts LLM
# ---------------------------------------------------------------------------

AUTONOMY_BUDGET_PER_MIN          = int(os.getenv('ULTRON_AUTONOMY_BUDGET_PER_MIN', '2'))
METACOG_LLM_ATTEMPT_TIMEOUT_SEC  = float(os.getenv('METACOG_LLM_ATTEMPT_TIMEOUT_SEC', '18') or 18)
METACOG_LLM_TOTAL_BUDGET_SEC     = float(os.getenv('METACOG_LLM_TOTAL_BUDGET_SEC', '28') or 28)

# ---------------------------------------------------------------------------
# Background loops — master switch
# ---------------------------------------------------------------------------

BACKGROUND_LOOPS_ENABLED = _env_flag('ULTRON_BACKGROUND_LOOPS_ENABLED', '1')
_BACKGROUND_DEFAULT      = '1' if BACKGROUND_LOOPS_ENABLED else '0'

# Loop-level toggles
MISSION_CONTROL_LOOP_ENABLED  = _env_flag('ULTRON_MISSION_CONTROL_LOOP_ENABLED',  _BACKGROUND_DEFAULT)
AUTONOMY_LOOP_ENABLED         = _env_flag('ULTRON_AUTONOMY_LOOP_ENABLED',          _BACKGROUND_DEFAULT)
JUDGE_LOOP_ENABLED            = _env_flag('ULTRON_JUDGE_LOOP_ENABLED',             _BACKGROUND_DEFAULT)
AUTOFEEDER_ENABLED            = _env_flag('ULTRON_AUTOFEEDER_ENABLED',             _BACKGROUND_DEFAULT)
ROADMAP_LOOP_ENABLED          = _env_flag('ULTRON_ROADMAP_LOOP_ENABLED',           _BACKGROUND_DEFAULT)
AGI_PATH_LOOP_ENABLED         = _env_flag('ULTRON_AGI_PATH_LOOP_ENABLED',          _BACKGROUND_DEFAULT)
REFLEXION_LOOP_ENABLED        = _env_flag('ULTRON_REFLEXION_LOOP_ENABLED',         _BACKGROUND_DEFAULT)
VOICE_PREWARM_ENABLED         = _env_flag('ULTRON_VOICE_PREWARM_ENABLED',          _BACKGROUND_DEFAULT)
METACOGNITIVE_LOOP_ENABLED    = _env_flag('ULTRON_METACOGNITIVE_LOOP_ENABLED',     _BACKGROUND_DEFAULT)
RECURSIVE_SI_LOOP_ENABLED     = _env_flag('ULTRON_RECURSIVE_SI_LOOP_ENABLED',      _BACKGROUND_DEFAULT)
INNER_MONOLOGUE_LOOP_ENABLED  = _env_flag('ULTRON_INNER_MONOLOGUE_LOOP_ENABLED',   _BACKGROUND_DEFAULT)
SELF_GOVERNANCE_LOOP_ENABLED  = _env_flag('ULTRON_SELF_GOVERNANCE_LOOP_ENABLED',   _BACKGROUND_DEFAULT)
SLEEP_CYCLE_LOOP_ENABLED      = _env_flag('ULTRON_SLEEP_CYCLE_LOOP_ENABLED',       _BACKGROUND_DEFAULT)
HEALER_VERIFY_LOOP_ENABLED    = _env_flag('ULTRON_HEALER_VERIFY_LOOP_ENABLED',     _BACKGROUND_DEFAULT)
ACTIVE_DISCOVERY_LOOP_ENABLED = _env_flag('ULTRON_ACTIVE_DISCOVERY_LOOP_ENABLED',  _BACKGROUND_DEFAULT)
NO_CLOUD_CAMPAIGN_LOOP_ENABLED = _env_flag('ULTRON_NO_CLOUD_CAMPAIGN_LOOP_ENABLED', _BACKGROUND_DEFAULT)
SELF_TALK_LOOP_ENABLED        = _env_flag('ULTRON_SELF_TALK_LOOP_ENABLED',         _BACKGROUND_DEFAULT)
WEB_EXPLORER_LOOP_ENABLED     = (
    _env_flag('ULTRON_WEB_EXPLORER_LOOP_ENABLED', _BACKGROUND_DEFAULT)
    and _env_flag('ULTRON_WEB_EXPLORER', _BACKGROUND_DEFAULT)
)

# Startup-only features (disabled by default)
STARTUP_BOOTSTRAP_ENABLED  = _env_flag('ULTRON_STARTUP_BOOTSTRAP_ENABLED', '0')
STARTUP_BACKFILL_ENABLED   = _env_flag('ULTRON_STARTUP_BACKFILL_ENABLED',  '0')
PHENOMENAL_STARTUP_ENABLED = _env_flag('ULTRON_PHENOMENAL_STARTUP_ENABLED', _BACKGROUND_DEFAULT)
SELF_IMPROVEMENT_ENABLED   = _env_flag('ULTRON_SELF_IMPROVEMENT_ENABLED',   _BACKGROUND_DEFAULT)

# ---------------------------------------------------------------------------
# Tick intervals (seconds)
# ---------------------------------------------------------------------------

SELF_IMPROVEMENT_INTERVAL_SEC = max(300, int(os.getenv('ULTRON_SELF_IMPROVEMENT_INTERVAL', '600')))
AUTONOMY_TICK_SEC    = max(60,  int(os.getenv('ULTRON_AUTONOMY_TICK_SEC',    '300')))
JUDGE_TICK_SEC       = max(60,  int(os.getenv('ULTRON_JUDGE_TICK_SEC',       '180')))
AUTOFEEDER_TICK_SEC  = max(120, int(os.getenv('ULTRON_AUTOFEEDER_TICK_SEC',  '300')))
REFLEXION_TICK_SEC   = max(60,  int(os.getenv('ULTRON_REFLEXION_TICK_SEC',   '300')))
NO_CLOUD_CAMPAIGN_TICK_SEC = max(300, int(os.getenv('ULTRON_NO_CLOUD_CAMPAIGN_TICK_SEC', '900')))

# ---------------------------------------------------------------------------
# Concurrency limits
# ---------------------------------------------------------------------------

LIGHTRAG_CONCURRENCY     = max(1, int(os.getenv('ULTRON_LIGHTRAG_CONCURRENCY',      '2')))
LLM_BLOCKING_CONCURRENCY = max(1, int(os.getenv('ULTRON_LLM_BLOCKING_CONCURRENCY',  '3')))

# ---------------------------------------------------------------------------
# Architecture flags (immutable)
# ---------------------------------------------------------------------------

TRAINING_DISABLED_BY_ARCHITECTURE: bool = True
FINETUNE_AUTOTRIGGER_ENABLED: bool = False

# ---------------------------------------------------------------------------
# Action queue
# ---------------------------------------------------------------------------

ACTION_DEFAULT_TTL_SEC = 15 * 60  # 15 minutes

EXTERNAL_ACTION_ALLOWLIST: frozenset[str] = frozenset({"notify_human"})

# Cooldown por tipo de ação (segundos)
ACTION_COOLDOWNS_SEC: dict[str, int] = {
    "auto_resolve_conflicts":         90,
    "generate_questions":            120,
    "ask_evidence":                  180,
    "execute_subgoal":               120,
    "clarify_laws":                  300,
    "curate_memory":                 300,
    "prune_memory":                  420,
    "execute_procedure":             180,
    "execute_procedure_active":      240,
    "generate_analogy_hypothesis":   300,
    "maintain_question_queue":       240,
    "clarify_semantics":             180,
    "unsupervised_discovery":        600,
    "neuroplastic_cycle":            900,
    "invent_procedure":              420,
    "intrinsic_tick":                600,
    "emergence_tick":                420,
    "deliberate_task":               480,
    "horizon_review":               1800,
    "subgoal_planning":             1200,
    "project_management_cycle":     1500,
    "route_toolchain":               420,
    "project_experiment_cycle":     1800,
    "absorb_lightrag_general":      2400,
    "self_model_refresh":           1800,
    "execute_python_sandbox":        300,
}
