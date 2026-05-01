"""
ultronpro.core.state
====================
Estado de runtime compartilhado entre main.py e os workers de background.

Contém:
- Semáforos asyncio (criados aqui, consumidos pelos workers)
- Handles de tasks asyncio (um por loop de background)
- _autonomy_state: dict mutável de telemetria do loop de autonomia
- Token stores para ações externas e self-patch (dicts mutáveis)

Regra: importa APENAS de `core.config` e stdlib. Jamais importa de
`fastapi`, `ultronpro.*` ou outros módulos da aplicação.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from ultronpro.core.config import LIGHTRAG_CONCURRENCY, LLM_BLOCKING_CONCURRENCY

# ---------------------------------------------------------------------------
# Asyncio semaphores
# (são criados em nível de módulo; asyncio.Semaphore é seguro assim)
# ---------------------------------------------------------------------------

_LIGHTRAG_SEM      = asyncio.Semaphore(LIGHTRAG_CONCURRENCY)
_LLM_BLOCKING_SEM  = asyncio.Semaphore(LLM_BLOCKING_CONCURRENCY)

# ---------------------------------------------------------------------------
# Background task handles
# ---------------------------------------------------------------------------

_autofeeder_task:          Optional[asyncio.Task] = None
_autonomy_task:            Optional[asyncio.Task] = None
_judge_task:               Optional[asyncio.Task] = None
_prewarm_task:             Optional[asyncio.Task] = None
_roadmap_task:             Optional[asyncio.Task] = None
_agi_path_task:            Optional[asyncio.Task] = None
_reflexion_task:           Optional[asyncio.Task] = None
_self_governance_task:     Optional[asyncio.Task] = None
_meta_observer_task:       Optional[asyncio.Task] = None
_affect_task:              Optional[asyncio.Task] = None
_narrative_task:           Optional[asyncio.Task] = None
_integration_task:         Optional[asyncio.Task] = None
_web_explorer_task:        Optional[asyncio.Task] = None
_background_guard_task:    Optional[asyncio.Task] = None
_inner_monologue_task:     Optional[asyncio.Task] = None
_self_improvement_task:    Optional[asyncio.Task] = None
_recursive_si_task:        Optional[asyncio.Task] = None
_active_discovery_task:    Optional[asyncio.Task] = None
_no_cloud_campaign_task:   Optional[asyncio.Task] = None
_sleep_cycle_task:         Optional[asyncio.Task] = None
_healer_verify_task:       Optional[asyncio.Task] = None
_mission_control_task:     Optional[asyncio.Task] = None

# ---------------------------------------------------------------------------
# Autonomy runtime state (dict mutável — acesso por referência)
# ---------------------------------------------------------------------------

_autonomy_state: dict = {
    "ticks":                        0,
    "last_tick":                    None,
    "last_error":                   None,
    "circuit_open_until":           0,
    "consecutive_errors":           0,
    "last_actions_window":          [],
    "meta_last_snapshot":           None,
    "meta_stuck_cycles":            0,
    "meta_replans":                 0,
    "turbo_last_report_at":         0,
    "meta_quality_history":         [],
    "meta_low_quality_streak":      0,
    "milestone_auto_last_ts":       0,
    "milestone_auto_resolved_wm":   0,
}

# ---------------------------------------------------------------------------
# Token stores (dicts mutáveis — crescem em runtime)
# ---------------------------------------------------------------------------

_external_confirm_tokens: dict[str, dict] = {}
_selfpatch_tokens:        dict[str, dict] = {}
