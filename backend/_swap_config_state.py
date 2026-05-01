"""
Swap atômico do bloco de config/state no main.py.

Remove as constantes e variáveis de estado inline e substitui por
imports de ultronpro.core.config e ultronpro.core.state.
"""
import re

path = r'f:\sistemas\UltronPro\backend\ultronpro\main.py'
with open(path, 'rb') as f:
    raw = f.read()

content = raw.decode('utf-8', errors='replace')

REPLACEMENT = '''# --- Config (moved to ultronpro/core/config.py) ---
from ultronpro.core.config import (  # noqa: F401
    _env_flag,
    AUTONOMY_BUDGET_PER_MIN, METACOG_LLM_ATTEMPT_TIMEOUT_SEC, METACOG_LLM_TOTAL_BUDGET_SEC,
    BACKGROUND_LOOPS_ENABLED, MISSION_CONTROL_LOOP_ENABLED, AUTONOMY_LOOP_ENABLED,
    JUDGE_LOOP_ENABLED, AUTOFEEDER_ENABLED, ROADMAP_LOOP_ENABLED, AGI_PATH_LOOP_ENABLED,
    REFLEXION_LOOP_ENABLED, VOICE_PREWARM_ENABLED, METACOGNITIVE_LOOP_ENABLED,
    RECURSIVE_SI_LOOP_ENABLED, INNER_MONOLOGUE_LOOP_ENABLED, SELF_GOVERNANCE_LOOP_ENABLED,
    SLEEP_CYCLE_LOOP_ENABLED, HEALER_VERIFY_LOOP_ENABLED, ACTIVE_DISCOVERY_LOOP_ENABLED,
    SELF_TALK_LOOP_ENABLED, WEB_EXPLORER_LOOP_ENABLED,
    STARTUP_BOOTSTRAP_ENABLED, STARTUP_BACKFILL_ENABLED, PHENOMENAL_STARTUP_ENABLED,
    SELF_IMPROVEMENT_ENABLED, SELF_IMPROVEMENT_INTERVAL_SEC,
    TRAINING_DISABLED_BY_ARCHITECTURE, FINETUNE_AUTOTRIGGER_ENABLED,
    AUTONOMY_TICK_SEC, JUDGE_TICK_SEC, AUTOFEEDER_TICK_SEC, REFLEXION_TICK_SEC,
    LIGHTRAG_CONCURRENCY, LLM_BLOCKING_CONCURRENCY,
    RUNTIME_HEALTH_PATH, TURBO_REPORT_PATH, BENCHMARK_HISTORY_PATH, PERSISTENT_GOALS_PATH,
    DEEP_CONTEXT_PATH, MISSION_CONTROL_LOG_PATH, MISSION_CONTROL_CFG_PATH,
    MISSION_CONTROL_STATE_PATH, PROCEDURE_ARTIFACTS_DIR, NEUROPLASTIC_GATE_STATE_PATH,
    ACTION_DEFAULT_TTL_SEC, EXTERNAL_ACTION_ALLOWLIST, ACTION_COOLDOWNS_SEC,
)

# --- State (moved to ultronpro/core/state.py) ---
from ultronpro.core.state import (  # noqa: F401
    _LIGHTRAG_SEM, _LLM_BLOCKING_SEM,
    _autofeeder_task, _autonomy_task, _judge_task, _prewarm_task, _roadmap_task,
    _agi_path_task, _reflexion_task, _self_governance_task, _meta_observer_task,
    _affect_task, _narrative_task, _integration_task, _web_explorer_task,
    _background_guard_task, _inner_monologue_task, _self_improvement_task,
    _recursive_si_task, _active_discovery_task, _sleep_cycle_task, _healer_verify_task,
    _mission_control_task, _autonomy_state, _external_confirm_tokens, _selfpatch_tokens,
)

'''

# ── Localizar o bloco a remover ──────────────────────────────────────────────
# Começa em: '# --- Startup ---\r\n_autofeeder_task = None'
# Termina em: 'NEUROPLASTIC_GATE_STATE_PATH = ...\r\n\r\n\r\n'

# Estratégia: byte search exata das linhas âncora
start_marker = b'# --- Startup ---\r\n_autofeeder_task = None'
end_marker   = b"NEUROPLASTIC_GATE_STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'neuroplastic_gate_state.json'\r\n"

idx_start = raw.find(start_marker)
idx_end   = raw.find(end_marker)

if idx_start == -1:
    print('ERRO: start_marker nao encontrado')
    exit(1)
if idx_end == -1:
    print('ERRO: end_marker nao encontrado')
    exit(1)

# Avança idx_end para incluir toda a linha do end_marker + blanks seguintes
end_after = idx_end + len(end_marker)
# Pula \r\n extras logo após
while raw[end_after:end_after+2] in (b'\r\n', b'\n\n'):
    end_after += 2

print(f'Bloco localizado: bytes {idx_start} .. {end_after}')
print(f'Conteudo inicial: {repr(raw[idx_start:idx_start+80])}')
print(f'Conteudo final:   {repr(raw[end_after-60:end_after])}')

new_raw = raw[:idx_start] + REPLACEMENT.encode('utf-8') + raw[end_after:]

with open(path, 'wb') as f:
    f.write(new_raw)

print(f'main.py atualizado. Tamanho original={len(raw)}, novo={len(new_raw)}')
