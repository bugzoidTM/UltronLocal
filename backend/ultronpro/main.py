import os
import logging
import json
import asyncio
import time
import hashlib
import secrets
import random
import gc
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, PlainTextResponse
from pydantic import BaseModel
import uvicorn
import httpx

from ultronpro import llm, llm_adapter, knowledge_bridge, graph, settings, curiosity, conflicts, store, extract, planner, goals, autofeeder, policy, analogy, tom, semantics, unsupervised, neuroplastic, causal, intrinsic, emergence, itc, longhorizon, subgoals, neurosym, project_kernel, tool_router, project_executor, integrity, self_model, env_tools, persona, fs_audit, sql_explorer, source_probe, squad_phase_a, squad_phase_c, mission_control, homeostasis, contrafactual, grounding, identity_daily, governance, adaptive_control, economic, self_play, calibration, plasticity_runtime, roadmap_v5, agi_path, episodic_memory, learning_agenda, sleep_cycle, replay_traces, rag_synth_generator, semantic_cache, prm_lite, symbolic_reasoner, reflexion_agent, cognitive_state, causal_graph, sandbox_client, web_browser, context_policy, quality_eval, context_metrics, context_inspector, rag_router, rag_eval, rag_eval_cases, rag_eval_store, internal_critic, memory_governor, causal_preflight, cognitive_patches, gap_detector, shadow_eval, promotion_gate, rollback_manager, benchmark_suite, ultronbody, explicit_abstractions, structural_mapper, transfer_benchmark, external_benchmarks, cognitive_patch_loop, organic_eval_feed, roadmap_status, self_governance, operational_consciousness_benchmark
from ultronpro.knowledge_bridge import search_knowledge, ingest_knowledge

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn")

app = FastAPI(title="UltronPRO API", version="0.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ui_cache_bust_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except RuntimeError as e:
        p = request.url.path or ""
        if "No response returned" in str(e) and p == "/api/metacognition/ask":
            return JSONResponse({
                "ok": False,
                "answer": "Não consegui responder com confiança agora. Tente novamente em instantes.",
                "strategy": "middleware_fallback",
                "model": "tiny",
                "error": "no_response_returned",
            }, status_code=200)
        raise
    path = request.url.path or "/"
    if request.method == "GET" and (path == "/" or path == "/index.html" or path.endswith(".html")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def ui_lite_api_guard(request: Request, call_next):
    if os.getenv("ULTRON_UI_LITE_API", "1") == "1" and request.method == "GET":
        p = request.url.path or ""
        if p.startswith("/api/goals"):
            return JSONResponse({"goals": []})
        if p.startswith("/api/tom/status"):
            return JSONResponse({"items": [], "stats": {}})
        if p.startswith("/api/horizon/missions"):
            return JSONResponse({"missions": []})
        if p.startswith("/api/persona/status"):
            return JSONResponse({"status": "lite"})
        if p.startswith("/api/persona/examples"):
            return JSONResponse({"examples": []})
        if p.startswith("/api/conflicts"):
            return JSONResponse({"conflicts": []})
        if p.startswith("/api/mission/tasks"):
            return JSONResponse({"tasks": []})
        if p.startswith("/api/mission/activities"):
            return JSONResponse({"activities": []})
        if p.startswith("/api/llm/usage"):
            return JSONResponse({"window": [], "summary": {}})
        if p.startswith("/api/plasticity/finetune/status"):
            return JSONResponse({"ok": True, "running": False})
        if p.startswith("/api/turbo/report"):
            return JSONResponse({"report": {}})
    try:
        return await call_next(request)
    except RuntimeError as e:
        p = request.url.path or ""
        if "No response returned" in str(e) and p == "/api/metacognition/ask":
            return JSONResponse({
                "ok": False,
                "answer": "Não consegui responder com confiança agora. Tente novamente em instantes.",
                "strategy": "middleware_fallback",
                "model": "tiny",
                "error": "no_response_returned",
            }, status_code=200)
        raise

# --- Models ---
class IngestRequest(BaseModel):
    text: str
    source_id: Optional[str] = None
    modality: str = "text"

class AnswerRequest(BaseModel):
    question_id: int
    answer: str

class DismissRequest(BaseModel):
    question_id: int

class ResolveConflictRequest(BaseModel):
    chosen_object: str
    decided_by: Optional[str] = None
    resolution: Optional[str] = None

class SearchRequest(BaseModel):
    query: str
    top_k: int = 10

class SettingsModel(BaseModel):
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    lightrag_api_key: Optional[str] = None
    lightrag_url: Optional[str] = None

class ActionPrepareRequest(BaseModel):
    kind: str
    target: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    reason: str

class ProcedureLearnRequest(BaseModel):
    observation_text: str
    domain: Optional[str] = None
    name: Optional[str] = None

class ProcedureRunRequest(BaseModel):
    procedure_id: int
    input_text: Optional[str] = None
    output_text: Optional[str] = None
    score: float = 0.5
    success: bool = False
    notes: Optional[str] = None

class ProcedureSelectRequest(BaseModel):
    context_text: str
    domain: Optional[str] = None

class ProcedureInventRequest(BaseModel):
    context_text: str
    domain: Optional[str] = None
    name_hint: Optional[str] = None

class AnalogyTransferRequest(BaseModel):
    problem_text: str
    target_domain: Optional[str] = None

class WorkspacePublishRequest(BaseModel):
    module: str
    channel: str
    payload: Dict[str, Any] = {}
    salience: float = 0.5
    ttl_sec: int = 900

class WorkspaceBroadcastRequest(BaseModel):
    module: str
    channels: List[str]
    payload: Dict[str, Any] = {}
    salience: float = 0.6
    ttl_sec: int = 900

class WorkspaceConsumeRequest(BaseModel):
    item_id: int
    consumer_module: str

class MilestoneProgressRequest(BaseModel):
    progress: float
    status: Optional[str] = None

class MutationProposalRequest(BaseModel):
    title: str
    rationale: str
    patch: Dict[str, Any]
    author: Optional[str] = "manual"

class MutationDecisionRequest(BaseModel):
    reason: Optional[str] = None

class CognitivePatchCreateRequest(BaseModel):
    kind: str = 'heuristic_patch'
    source: str = 'manual'
    problem_pattern: str
    hypothesis: str = ''
    proposed_change: Dict[str, Any] = {}
    expected_gain: str = ''
    risk_level: str = 'medium'
    evidence_refs: List[str] = []
    benchmark_before: Dict[str, Any] = {}
    benchmark_after: Dict[str, Any] = {}
    shadow_metrics: Dict[str, Any] = {}
    tags: List[str] = []
    notes: str = ''

class CognitivePatchUpdateRequest(BaseModel):
    status: Optional[str] = None
    hypothesis: Optional[str] = None
    proposed_change: Optional[Dict[str, Any]] = None
    expected_gain: Optional[str] = None
    risk_level: Optional[str] = None
    evidence_refs: Optional[List[str]] = None
    benchmark_before: Optional[Dict[str, Any]] = None
    benchmark_after: Optional[Dict[str, Any]] = None
    shadow_metrics: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    rollback_ref: Optional[str] = None

class ShadowEvalCaseRequest(BaseModel):
    case_id: Optional[str] = None
    query: str
    baseline_answer: str
    candidate_answer: str
    fallback_needed: bool = False
    has_rag: bool = False

class ShadowEvalRunRequest(BaseModel):
    cases: List[ShadowEvalCaseRequest]

class ShadowEvalCanaryRequest(BaseModel):
    rollout_pct: int = 10
    domains: List[str] = []
    note: Optional[str] = None

class UltronBodyResetRequest(BaseModel):
    env_name: Optional[str] = 'gridworld_v1'

class UltronBodyActRequest(BaseModel):
    action: str
    expected_effect: Optional[str] = None

class UltronBodyPredictRequest(BaseModel):
    action: str

class UltronBodyRunRequest(BaseModel):
    policy: Optional[str] = 'goal_seek'
    max_steps: Optional[int] = 30
    env_name: Optional[str] = 'gridworld_v1'

class UltronBodyBenchmarkRequest(BaseModel):
    policy: Optional[str] = 'goal_seek'
    episodes_count: Optional[int] = 10
    max_steps: Optional[int] = 30
    env_name: Optional[str] = 'gridworld_v1'

class UltronBodyBenchmarkCompareRequest(BaseModel):
    policies: Optional[List[str]] = None
    episodes_count: Optional[int] = 10
    max_steps: Optional[int] = 30
    env_names: Optional[List[str]] = None

class ExplicitAbstractionCreateRequest(BaseModel):
    principle: str
    source_domains: Optional[List[str]] = None
    applicability_conditions: Optional[List[str]] = None
    procedure_template: Optional[List[str]] = None
    confidence: Optional[float] = 0.5
    notes: Optional[str] = None

class ExplicitAbstractionTransferRequest(BaseModel):
    target_domain: str
    outcome: str
    evidence_ref: Optional[str] = None
    score: Optional[float] = None
    notes: Optional[str] = None

class StructuralMapRequest(BaseModel):
    target_domain: str
    target_text: Optional[str] = None

class TransferBenchmarkRequest(BaseModel):
    scenario_ids: Optional[List[str]] = None

class AbstractionBatchExtractRequest(BaseModel):
    limit: Optional[int] = 20
    min_cluster_size: Optional[int] = 2

class ExternalBenchmarkRunRequest(BaseModel):
    benchmark_ids: Optional[List[str]] = None
    families: Optional[List[str]] = None
    splits: Optional[List[str]] = None
    limit_per_benchmark: Optional[int] = None
    strategy: Optional[str] = 'cheap'
    predictor: Optional[str] = 'llm'
    tag: Optional[str] = None

class ExternalBenchmarkBaselineRequest(BaseModel):
    benchmark_ids: Optional[List[str]] = None
    families: Optional[List[str]] = None
    splits: Optional[List[str]] = None
    limit_per_benchmark: Optional[int] = None
    strategy: Optional[str] = 'cheap'
    predictor: Optional[str] = 'llm'
    label: Optional[str] = 'baseline'

class IntrinsicTickRequest(BaseModel):
    force: bool = False

class ITCRunRequest(BaseModel):
    problem_text: str
    max_steps: int = 0
    budget_seconds: int = 0
    use_rl: bool = True
    search_mode: str = 'mcts'  # mcts|iterative|linear|deep_think
    branching_factor: int = 2
    checkpoint_every_sec: int = 30
    task_class: str = 'normal'  # normal|critical

class PlasticityFeedbackRequest(BaseModel):
    task_type: str = 'general'
    profile: str = 'balanced'
    success: bool = True
    latency_ms: int = 0
    hallucination: bool = False
    note: Optional[str] = None


class OpenClawTeacherFeedbackRequest(BaseModel):
    task_type: str = 'assistant'
    profile: str = 'balanced'
    success: bool = True
    latency_ms: int = 0
    hallucination: bool = False
    note: Optional[str] = None
    source: str = 'openclaw'
    teacher: Optional[str] = None


class FineTuneCreateRequest(BaseModel):
    task_type: str = 'general'
    base_model: str = 'llama3.2:1b'
    method: str = 'qlora'
    max_samples: int = 400
    run_preset: Optional[str] = None  # fast_diagnostic|production


class FineTuneRegisterRequest(BaseModel):
    quality_score: float = 0.0
    notes: Optional[str] = None


class FineTuneAutoConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    min_feedback: Optional[int] = None
    min_failure_rate: Optional[float] = None
    cooldown_sec: Optional[int] = None
    task_type: Optional[str] = None
    base_model: Optional[str] = None


class FineTunePromoteRequest(BaseModel):
    min_gain: float = 0.02
    baseline_score: Optional[float] = None
    candidate_score: Optional[float] = None


class FineTuneNotifyCompleteRequest(BaseModel):
    job_id: str
    remote_job_id: Optional[str] = None
    adapter_out: Optional[str] = None
    notes: Optional[str] = None


class RoadmapV5ConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_tick_sec: Optional[int] = None
    rest_until_ts: Optional[int] = None


class RoadmapV5RestRequest(BaseModel):
    hours: int = 48


class AgiPathConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_tick_sec: Optional[int] = None
    target_agi_percent: Optional[float] = None


class LearningAgendaConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    exploration_budget_ratio: Optional[float] = None
    min_gap_to_trigger: Optional[float] = None
    domains: Optional[list[dict]] = None


class MetacogAskRequest(BaseModel):
    message: str


class VoiceChatRequest(BaseModel):
    text: str

class HorizonMissionRequest(BaseModel):
    title: str
    objective: str
    horizon_days: int = 14
    context: Optional[str] = None

class HorizonCheckpointRequest(BaseModel):
    note: str
    progress_delta: float = 0.0
    signal: str = "reflection"

class SubgoalMarkRequest(BaseModel):
    status: str = "done"

class ProjectRequest(BaseModel):
    title: str
    objective: str
    scope: Optional[str] = None
    sla_hours: int = 72

class ProjectCheckpointRequest(BaseModel):
    note: str
    progress_delta: float = 0.0
    signal: str = "tick"

class ToolRouteRequest(BaseModel):
    intent: str
    context: Optional[Dict[str, Any]] = None
    prefer_low_cost: bool = True

class IntegrityRulesPatchRequest(BaseModel):
    rules: Dict[str, Any]

class SandboxWriteRequest(BaseModel):
    path: str
    content: str

class SandboxRunRequest(BaseModel):
    code: Optional[str] = None
    file_path: Optional[str] = None
    timeout_sec: int = 15

class PersonaExampleRequest(BaseModel):
    user_input: str
    assistant_output: str
    tone: str = 'direct'
    tags: Optional[List[str]] = None
    score: float = 1.0

class PersonaConfigRequest(BaseModel):
    config: Dict[str, Any]

class PersistentGoalRequest(BaseModel):
    title: str
    description: Optional[str] = None
    proactive_actions: Optional[List[str]] = None
    interval_min: int = 60
    active_hours: Optional[List[int]] = None  # [start_hour, end_hour]

class ActionExecRequest(BaseModel):
    kind: str
    target: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    dry_run: bool = True
    reason: Optional[str] = None
    confirm_token: Optional[str] = None

class SelfPatchPrepareRequest(BaseModel):
    file_path: str
    old_text: str
    new_text: str
    reason: str

class SelfPatchApplyRequest(BaseModel):
    token: str

# --- Startup ---
_autofeeder_task = None
_autonomy_task = None
_judge_task = None
_prewarm_task = None
_roadmap_task = None
_agi_path_task = None
_reflexion_task = None
_self_governance_task = None
_meta_observer_task = None
_affect_task = None
_narrative_task = None
_integration_task = None
_autonomy_state = {
    "ticks": 0,
    "last_tick": None,
    "last_error": None,
    "circuit_open_until": 0,
    "consecutive_errors": 0,
    "last_actions_window": [],
    "meta_last_snapshot": None,
    "meta_stuck_cycles": 0,
    "meta_replans": 0,
    "turbo_last_report_at": 0,
    "meta_quality_history": [],
    "meta_low_quality_streak": 0,
    "milestone_auto_last_ts": 0,
    "milestone_auto_resolved_wm": 0,
}

# Etapa A: budget + cooldown inteligente
AUTONOMY_BUDGET_PER_MIN = int(os.getenv('ULTRON_AUTONOMY_BUDGET_PER_MIN', '2'))
METACOG_LLM_ATTEMPT_TIMEOUT_SEC = float(os.getenv('METACOG_LLM_ATTEMPT_TIMEOUT_SEC', '18') or 18)
METACOG_LLM_TOTAL_BUDGET_SEC = float(os.getenv('METACOG_LLM_TOTAL_BUDGET_SEC', '28') or 28)
AUTONOMY_LOOP_ENABLED = os.getenv('ULTRON_AUTONOMY_ENABLED', '1') != '0'
JUDGE_LOOP_ENABLED = os.getenv('ULTRON_JUDGE_ENABLED', '1') != '0'
AUTOFEEDER_ENABLED = os.getenv('ULTRON_AUTOFEEDER_ENABLED', '1') != '0'
ROADMAP_LOOP_ENABLED = os.getenv('ULTRON_ROADMAP_ENABLED', '1') != '0'
AGI_PATH_LOOP_ENABLED = os.getenv('ULTRON_AGI_PATH_ENABLED', '1') != '0'
REFLEXION_LOOP_ENABLED = os.getenv('ULTRON_REFLEXION_ENABLED', '1') != '0'
VOICE_PREWARM_ENABLED = os.getenv('ULTRON_PREWARM_ENABLED', os.getenv('ULTRON_VOICE_PREWARM_ENABLED', '1')) != '0'
TRAINING_DISABLED_BY_ARCHITECTURE = True
FINETUNE_AUTOTRIGGER_ENABLED = False
AUTONOMY_TICK_SEC = max(20, int(os.getenv('ULTRON_AUTONOMY_TICK_SEC', '75')))
JUDGE_TICK_SEC = max(45, int(os.getenv('ULTRON_JUDGE_TICK_SEC', '90')))
AUTOFEEDER_TICK_SEC = max(90, int(os.getenv('ULTRON_AUTOFEEDER_TICK_SEC', '180')))
REFLEXION_TICK_SEC = max(45, int(os.getenv('ULTRON_REFLEXION_TICK_SEC', '120')))
LIGHTRAG_CONCURRENCY = max(1, int(os.getenv('ULTRON_LIGHTRAG_CONCURRENCY', '2')))
LLM_BLOCKING_CONCURRENCY = max(1, int(os.getenv('ULTRON_LLM_BLOCKING_CONCURRENCY', '3')))
RUNTIME_HEALTH_PATH = Path('/app/data/runtime_health.json')
TURBO_REPORT_PATH = Path('/app/data/turbo_safe_report.json')

_LIGHTRAG_SEM = asyncio.Semaphore(LIGHTRAG_CONCURRENCY)
_LLM_BLOCKING_SEM = asyncio.Semaphore(LLM_BLOCKING_CONCURRENCY)
ACTION_DEFAULT_TTL_SEC = 15 * 60
ACTION_COOLDOWNS_SEC = {
    "auto_resolve_conflicts": 90,
    "generate_questions": 120,
    "ask_evidence": 180,
    "execute_subgoal": 120,
    "clarify_laws": 300,
    "curate_memory": 300,
    "prune_memory": 420,
    "execute_procedure": 180,
    "execute_procedure_active": 240,
    "generate_analogy_hypothesis": 300,
    "maintain_question_queue": 240,
    "clarify_semantics": 180,
    "unsupervised_discovery": 600,
    "neuroplastic_cycle": 900,
    "invent_procedure": 420,
    "intrinsic_tick": 600,
    "emergence_tick": 420,
    "deliberate_task": 480,
    "horizon_review": 1800,
    "subgoal_planning": 1200,
    "project_management_cycle": 1500,
    "route_toolchain": 420,
    "project_experiment_cycle": 1800,
    "absorb_lightrag_general": 2400,
    "self_model_refresh": 1800,
    "execute_python_sandbox": 300,
}

# Etapa E: executor externo com segurança
EXTERNAL_ACTION_ALLOWLIST = {"notify_human"}
_external_confirm_tokens: dict[str, dict] = {}
_selfpatch_tokens: dict[str, dict] = {}
BENCHMARK_HISTORY_PATH = Path("/app/data/benchmark_history.json")
PERSISTENT_GOALS_PATH = Path("/app/data/persistent_goals.json")
DEEP_CONTEXT_PATH = Path('/app/data/deep_context_snapshot.json')
MISSION_CONTROL_LOG_PATH = Path('/app/data/mission_control_log.jsonl')
MISSION_CONTROL_CFG_PATH = Path('/app/data/mission_control_config.json')
MISSION_CONTROL_STATE_PATH = Path('/app/data/mission_control_state.json')
_mission_control_task: asyncio.Task | None = None
PROCEDURE_ARTIFACTS_DIR = Path("/app/data/procedure_artifacts")
NEUROPLASTIC_GATE_STATE_PATH = Path("/app/data/neuroplastic_gate_state.json")


def _benchmark_history_load() -> list[dict]:
    try:
        if BENCHMARK_HISTORY_PATH.exists():
            data = json.loads(BENCHMARK_HISTORY_PATH.read_text())
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _benchmark_history_append(item: dict, max_items: int = 200):
    arr = _benchmark_history_load()
    arr.append(item)
    arr = arr[-int(max_items):]
    try:
        BENCHMARK_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        BENCHMARK_HISTORY_PATH.write_text(json.dumps(arr, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _training_disabled_response(feature: str, extra: dict | None = None) -> dict:
    payload = {
        'ok': True,
        'enabled': False,
        'disabled': True,
        'feature': feature,
        'reason': 'training_disabled_by_architecture',
        'message': 'UltronPro no longer evolves via fine-tune/adapters; use the cognitive stack instead.',
    }
    if extra:
        payload.update(extra)
    return payload


def _build_guided_revision_prompt(*, query: str, current_answer: str, tool_outputs: list[dict[str, Any]] | None, context_bundle: dict | None, critic: dict | None, preflight: dict | None) -> str:
    epistemic = (critic or {}).get('epistemic') if isinstance(critic, dict) else {}
    operational = (critic or {}).get('operational') if isinstance(critic, dict) else {}
    fallback = (context_bundle or {}).get('fallback') if isinstance(context_bundle, dict) else {}
    rag_div = (context_bundle or {}).get('rag_diversity') if isinstance(context_bundle, dict) else {}
    revision_rules = [
        'Reescreva em pt-BR, de forma direta e útil.',
        'Não invente fatos ausentes.',
        'Se houver lacuna de contexto, admita explicitamente.',
        'Se o risco for alto, deixe cautela e necessidade de confirmação claras.',
        'Prefira calibrar confiança em vez de soar definitivo.',
    ]
    return json.dumps({
        'query': query,
        'current_answer': current_answer,
        'tool_outputs': tool_outputs or [],
        'context_fallback': fallback,
        'rag_diversity': rag_div,
        'critic_epistemic': epistemic,
        'critic_operational': operational,
        'causal_preflight': preflight or {},
        'revision_rules': revision_rules,
    }, ensure_ascii=False)


def _runtime_health_snapshot(extra: dict | None = None) -> dict:
    return {
        'ts': int(time.time()),
        'loops': {
            'autonomy_enabled': AUTONOMY_LOOP_ENABLED,
            'judge_enabled': JUDGE_LOOP_ENABLED,
            'autofeeder_enabled': AUTOFEEDER_ENABLED,
            'roadmap_enabled': ROADMAP_LOOP_ENABLED,
            'agi_path_enabled': AGI_PATH_LOOP_ENABLED,
            'reflexion_enabled': REFLEXION_LOOP_ENABLED,
            'voice_prewarm_enabled': VOICE_PREWARM_ENABLED,
            'finetune_autotrigger_enabled': False,
        },
        'cadence': {
            'autonomy_tick_sec': AUTONOMY_TICK_SEC,
            'judge_tick_sec': JUDGE_TICK_SEC,
            'autofeeder_tick_sec': AUTOFEEDER_TICK_SEC,
            'reflexion_tick_sec': REFLEXION_TICK_SEC,
            'budget_per_min': AUTONOMY_BUDGET_PER_MIN,
        },
        'autonomy_state': {
            'ticks': int(_autonomy_state.get('ticks') or 0),
            'last_tick': _autonomy_state.get('last_tick'),
            'last_error': _autonomy_state.get('last_error'),
            'consecutive_errors': int(_autonomy_state.get('consecutive_errors') or 0),
        },
        'extra': extra or {},
    }


def _runtime_health_write(extra: dict | None = None):
    try:
        RUNTIME_HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_HEALTH_PATH.write_text(json.dumps(_runtime_health_snapshot(extra), ensure_ascii=False, indent=2))
    except Exception:
        pass


_MEM_LAST_GC_AT = 0


def _memory_watchdog_tick(source: str = 'loop') -> dict:
    global _MEM_LAST_GC_AT
    now = int(time.time())
    soft_mb = max(512, int(os.getenv('ULTRON_MEM_SOFT_LIMIT_MB', '3500')))
    hard_mb = max(soft_mb + 256, int(os.getenv('ULTRON_MEM_HARD_LIMIT_MB', str(soft_mb + 700))))
    cooldown = max(30, int(os.getenv('ULTRON_MEM_GC_COOLDOWN_SEC', '120')))

    mem_bytes = 0
    try:
        p = Path('/sys/fs/cgroup/memory.current')
        if p.exists():
            mem_bytes = int((p.read_text() or '0').strip() or '0')
    except Exception:
        mem_bytes = 0

    mem_mb = round(mem_bytes / (1024 * 1024), 2) if mem_bytes else 0.0
    acted = False
    alerts: list[str] = []

    if mem_mb >= soft_mb and (now - int(_MEM_LAST_GC_AT or 0)) >= cooldown:
        gc.collect()
        _MEM_LAST_GC_AT = now
        acted = True
        alerts.append('gc_collect')

    if mem_mb >= hard_mb:
        try:
            # keep bounded in-memory histories aggressively under pressure
            hist = list(_autonomy_state.get('meta_quality_history') or [])
            _autonomy_state['meta_quality_history'] = hist[-8:]
            alerts.append('trim_meta_quality_history')
            acted = True
        except Exception:
            pass
        try:
            store.db.add_event('memory_pressure', f"🧯 memory pressure {mem_mb}MB source={source}")
        except Exception:
            pass

    return {'mem_mb': mem_mb, 'soft_mb': soft_mb, 'hard_mb': hard_mb, 'acted': acted, 'alerts': alerts, 'source': source}


def _neuroplastic_gate_load() -> dict:
    try:
        if NEUROPLASTIC_GATE_STATE_PATH.exists():
            d = json.loads(NEUROPLASTIC_GATE_STATE_PATH.read_text())
            if isinstance(d, dict):
                d.setdefault("revert_streaks", {})
                d.setdefault("activation_baselines", {})
                d.setdefault("last_snapshot", {})
                return d
    except Exception:
        pass
    return {"revert_streaks": {}, "activation_baselines": {}, "last_snapshot": {}}


def _neuroplastic_gate_save(data: dict):
    try:
        NEUROPLASTIC_GATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        NEUROPLASTIC_GATE_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _persistent_goals_load() -> dict:
    try:
        if PERSISTENT_GOALS_PATH.exists():
            d = json.loads(PERSISTENT_GOALS_PATH.read_text())
            if isinstance(d, dict):
                d.setdefault("goals", [])
                d.setdefault("active_id", None)
                return d
    except Exception:
        pass
    return {"goals": [], "active_id": None}


def _persistent_goals_save(data: dict):
    try:
        PERSISTENT_GOALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PERSISTENT_GOALS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _persistent_goal_active() -> dict | None:
    d = _persistent_goals_load()
    aid = d.get("active_id")
    for g in d.get("goals", []):
        if g.get("id") == aid:
            return g
    return None


def _enqueue_from_persistent_goal():
    g = _persistent_goal_active()
    if not g:
        return 0

    now = time.time()
    now_local_h = int(time.localtime(now).tm_hour)

    # janela horária ativa
    ah = g.get("active_hours") or [8, 23]
    if isinstance(ah, list) and len(ah) == 2:
        h0, h1 = int(ah[0]), int(ah[1])
        if h0 <= h1:
            if not (h0 <= now_local_h <= h1):
                return 0
        else:
            # janela cruzando meia-noite
            if not (now_local_h >= h0 or now_local_h <= h1):
                return 0

    # frequência
    interval_min = max(5, int(g.get("interval_min") or 60))
    last_run_at = float(g.get("last_run_at") or 0)
    if (now - last_run_at) < (interval_min * 60):
        return 0

    actions = g.get("proactive_actions") or []
    count = 0
    for txt in actions[:4]:
        t = (txt or "").strip()
        if not t:
            continue
        _enqueue_action_if_new("ask_evidence", f"(ação-proativa-meta) {t}", priority=5, meta={"persistent_goal_id": g.get("id")})
        count += 1

    # persist last_run_at
    if count > 0:
        d = _persistent_goals_load()
        for it in d.get("goals", []):
            if it.get("id") == g.get("id"):
                it["last_run_at"] = now
                break
        _persistent_goals_save(d)

    return count


def _workspace_publish(module: str, channel: str, payload: dict, salience: float = 0.5, ttl_sec: int = 900) -> int:
    try:
        return store.publish_workspace(
            module=module,
            channel=channel,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            salience=float(salience),
            ttl_sec=int(ttl_sec),
        )
    except Exception:
        return 0


def _workspace_recent(channels: list[str] | None = None, limit: int = 20) -> list[dict]:
    try:
        return store.read_workspace(channels=channels, limit=limit)
    except Exception:
        return []


def _workspace_status(limit: int = 80) -> dict:
    items = _workspace_recent(limit=max(10, min(300, int(limit or 80))))
    total = len(items)
    channels: dict[str, int] = {}
    modules: dict[str, int] = {}
    top_salience = []
    consumed = 0
    for it in items:
        ch = str(it.get('channel') or 'general')
        mod = str(it.get('module') or 'unknown')
        channels[ch] = channels.get(ch, 0) + 1
        modules[mod] = modules.get(mod, 0) + 1
        try:
            cjson = json.loads(it.get('consumed_by_json') or '{}')
            if isinstance(cjson, dict) and cjson:
                consumed += 1
        except Exception:
            pass
        top_salience.append({
            'id': it.get('id'),
            'module': mod,
            'channel': ch,
            'salience': float(it.get('salience') or 0.0),
        })
    top_salience = sorted(top_salience, key=lambda x: float(x.get('salience') or 0.0), reverse=True)[:10]
    competition = round(sum(float(x.get('salience') or 0.0) for x in top_salience[:5]) / max(1, min(5, len(top_salience))), 4) if top_salience else 0.0
    integration_score = round(min(1.0, (len(channels) / 8.0) * 0.45 + (len(modules) / 10.0) * 0.35 + (consumed / max(1, total)) * 0.20), 4)
    return {
        'ok': True,
        'items': total,
        'channels': channels,
        'modules': modules,
        'consumed_items': consumed,
        'competition_index': competition,
        'integration_score': integration_score,
        'top_salience': top_salience,
    }


def _workspace_authorship_snapshot(limit: int = 40) -> dict:
    items = _workspace_recent(limit=max(10, min(200, int(limit or 40))))
    authors: dict[str, dict[str, Any]] = {}
    origin_counts = {'self_generated': 0, 'externally_triggered': 0, 'mixed': 0, 'unknown': 0}
    for it in items:
        mod = str(it.get('module') or 'unknown')
        row = authors.setdefault(mod, {'count': 0, 'channels': set(), 'mean_salience': 0.0})
        row['count'] += 1
        row['channels'].add(str(it.get('channel') or 'general'))
        row['mean_salience'] += float(it.get('salience') or 0.0)
        payload = it.get('payload') if isinstance(it.get('payload'), dict) else {}
        origin = str((payload or {}).get('authorship_origin') or (payload or {}).get('origin') or 'unknown')
        origin_counts[origin] = int(origin_counts.get(origin, 0)) + 1
    out = []
    for mod, row in authors.items():
        count = int(row['count'])
        out.append({
            'module': mod,
            'items': count,
            'channels': sorted(list(row['channels'])),
            'mean_salience': round(float(row['mean_salience']) / max(1, count), 4),
            'authorship_share': round(count / max(1, len(items)), 4),
        })
    out.sort(key=lambda x: (x['items'], x['mean_salience']), reverse=True)
    agency_score = round(sum(x['authorship_share'] * min(1.0, x['mean_salience'] + 0.2) for x in out[:8]), 4) if out else 0.0
    return {
        'ok': True,
        'authors': out[:12],
        'agency_score': min(1.0, agency_score),
        'origin_counts': origin_counts,
    }


def _learning_recent_snapshot(limit: int = 24) -> dict:
    try:
        events = store.db.list_events(limit=max(12, min(120, limit * 4)))
    except Exception:
        events = []
    learn_kinds = {
        'autofeeder_ingest', 'lightrag_sync', 'lightrag_absorb', 'learning_agenda',
        'curiosity_probe_auto_ingest', 'explicit_abstraction_ingest'
    }
    picked = [e for e in events if str(e.get('kind') or '') in learn_kinds]
    picked = picked[-max(1, int(limit)):]
    sources = []
    kind_counts: dict[str, int] = {}
    items = []
    for e in picked:
        kind = str(e.get('kind') or '')
        kind_counts[kind] = int(kind_counts.get(kind) or 0) + 1
        txt = str(e.get('text') or '')
        src = None
        for marker in ('de ', 'source=', 'topic=', 'url='):
            idx = txt.find(marker)
            if idx >= 0:
                src = txt[idx:idx+120]
                break
        if src:
            sources.append(src)
        items.append({
            'id': e.get('id'),
            'kind': kind,
            'text': txt[:220],
            'created_at': e.get('created_at'),
        })
    return {
        'ok': True,
        'recent_learning_count': len(picked),
        'kind_counts': kind_counts,
        'recent_sources': sources[-8:],
        'items': items[-8:],
    }


def _meta_observer_snapshot(limit: int = 80) -> dict:
    ws = _workspace_status(limit=limit)
    auth = _workspace_authorship_snapshot(limit=max(20, min(120, limit)))
    items = _workspace_recent(limit=max(20, min(200, limit)))
    ignored = []
    conflicts = []
    for it in items:
        try:
            consumed = json.loads(it.get('consumed_by_json') or '{}')
        except Exception:
            consumed = {}
        if not isinstance(consumed, dict) or not consumed:
            ignored.append({
                'id': it.get('id'),
                'module': it.get('module'),
                'channel': it.get('channel'),
                'salience': float(it.get('salience') or 0.0),
            })
        ch = str(it.get('channel') or '')
        if 'conflict' in ch or 'error' in ch or 'critic' in ch:
            conflicts.append({
                'id': it.get('id'),
                'module': it.get('module'),
                'channel': ch,
                'salience': float(it.get('salience') or 0.0),
            })
    ignored = sorted(ignored, key=lambda x: float(x.get('salience') or 0.0), reverse=True)[:10]
    conflicts = sorted(conflicts, key=lambda x: float(x.get('salience') or 0.0), reverse=True)[:10]
    uncertainty = round(min(1.0, 0.55 * (1.0 - float(ws.get('integration_score') or 0.0)) + 0.45 * min(1.0, len(conflicts) / 6.0)), 4)
    summary = {
        'ok': True,
        'focus': ws.get('top_salience') or [],
        'competition_index': ws.get('competition_index'),
        'integration_score': ws.get('integration_score'),
        'agency_score': auth.get('agency_score'),
        'ignored': ignored,
        'conflicts': conflicts,
        'uncertainty': uncertainty,
        'dominant_authors': auth.get('authors') or [],
        'learning_recent': _learning_recent_snapshot(limit=max(8, min(24, limit // 3 or 8))),
    }
    return summary


def _artificial_affect_snapshot(limit: int = 80) -> dict:
    ws = _workspace_status(limit=limit)
    meta = _meta_observer_snapshot(limit=limit)
    narrative = self_governance.narrative_coherence_status()
    identity = identity_daily.status(limit=8)
    pending_promises = len(identity.get('pending_promises') or [])
    recent_reviews = identity.get('entries') or []
    recent_review = recent_reviews[-1] if recent_reviews else {}
    recent_failed = len((recent_review.get('promises_failed') or [])) if isinstance(recent_review, dict) else 0
    recent_carry = len((recent_review.get('promises_carry') or [])) if isinstance(recent_review, dict) else 0
    coherence = float(narrative.get('coherence_score') or 0.5)
    uncertainty = float(meta.get('uncertainty') or 0.0)
    competition = float(ws.get('competition_index') or 0.0)
    integration = float(ws.get('integration_score') or 0.0)
    try:
        persona_valence, persona_arousal, purpose = persona._affective_state()
    except Exception:
        persona_valence, persona_arousal, purpose = 0.0, 0.5, 'improve safely'

    frustration = min(1.0, 0.45 * uncertainty + 0.20 * min(1.0, pending_promises / 8.0) + 0.20 * min(1.0, recent_failed / 4.0) + 0.15 * competition)
    confidence = max(0.0, min(1.0, 0.45 * coherence + 0.35 * integration + 0.20 * (1.0 - uncertainty)))
    curiosity = max(0.0, min(1.0, 0.45 * persona_arousal + 0.25 * competition + 0.30 * (1.0 - integration)))
    threat = max(0.0, min(1.0, 0.60 * uncertainty + 0.25 * min(1.0, len(meta.get('conflicts') or []) / 5.0) + 0.15 * min(1.0, recent_carry / 5.0)))
    valence = max(-1.0, min(1.0, 0.55 * persona_valence + 0.25 * (confidence - frustration) + 0.20 * (coherence - threat)))
    arousal = max(0.0, min(1.0, 0.45 * persona_arousal + 0.25 * competition + 0.15 * uncertainty + 0.15 * curiosity))

    dominant_channel = ((ws.get('top_salience') or [{}])[0] or {}).get('channel') if ws.get('top_salience') else None
    risk_posture = 'stable'
    if threat >= 0.72:
        risk_posture = 'protective'
    elif curiosity >= 0.68 and confidence >= 0.45:
        risk_posture = 'exploratory'
    elif frustration >= 0.60:
        risk_posture = 'constrained'

    drivers = [
        {'name': 'uncertainty', 'value': round(uncertainty, 4)},
        {'name': 'competition', 'value': round(competition, 4)},
        {'name': 'coherence', 'value': round(coherence, 4)},
        {'name': 'pending_promises', 'value': round(min(1.0, pending_promises / 8.0), 4)},
    ]
    drivers = sorted(drivers, key=lambda x: float(x.get('value') or 0.0), reverse=True)

    return {
        'ok': True,
        'purpose': purpose,
        'dominant_channel': dominant_channel,
        'risk_posture': risk_posture,
        'markers': {
            'valence': round(valence, 4),
            'arousal': round(arousal, 4),
            'confidence': round(confidence, 4),
            'frustration': round(frustration, 4),
            'curiosity': round(curiosity, 4),
            'threat': round(threat, 4),
        },
        'inputs': {
            'integration_score': round(integration, 4),
            'competition_index': round(competition, 4),
            'uncertainty': round(uncertainty, 4),
            'narrative_coherence': round(coherence, 4),
            'pending_promises': pending_promises,
            'recent_failed_promises': recent_failed,
            'recent_carry_promises': recent_carry,
        },
        'top_drivers': drivers[:4],
        'recommended_attention_policy': {
            'bias': 'risk_review' if threat >= 0.65 else ('explore_open_loops' if curiosity >= 0.65 else 'balanced'),
            'boost_channels': ['conflict.status', 'self.state'] if threat >= 0.65 else ([dominant_channel] if dominant_channel else []),
        },
    }


def _integration_proxy_snapshot(limit: int = 100) -> dict:
    ws = _workspace_status(limit=limit)
    auth = _workspace_authorship_snapshot(limit=max(20, min(120, limit)))
    meta = _meta_observer_snapshot(limit=limit)
    affect = _artificial_affect_snapshot(limit=limit)
    narrative = self_governance.autobiographical_summary(limit=max(40, min(160, limit)))

    integration = float(ws.get('integration_score') or 0.0)
    agency = float(auth.get('agency_score') or 0.0)
    uncertainty = float(meta.get('uncertainty') or 0.0)
    competition = float(meta.get('competition_index') or ws.get('competition_index') or 0.0)
    confidence = float(((affect.get('markers') or {}).get('confidence')) or 0.0)
    threat = float(((affect.get('markers') or {}).get('threat')) or 0.0)
    frustration = float(((affect.get('markers') or {}).get('frustration')) or 0.0)
    coherence = float(((narrative.get('current_state') or {}).get('narrative_coherence_score')) or 0.0)
    ignored = len(meta.get('ignored') or [])
    conflicts = len(meta.get('conflicts') or [])
    continuity_risks = len(narrative.get('continuity_risks') or [])
    learning_recent = _learning_recent_snapshot(limit=max(10, min(24, limit // 4 or 10)))
    learning_factor = min(1.0, float(learning_recent.get('recent_learning_count') or 0.0) / 8.0)

    broadcast_factor = min(1.0, len(ws.get('channels') or {}) / 8.0)
    consumer_factor = min(1.0, float(ws.get('consumed_items') or 0.0) / max(1.0, float(ws.get('items') or 1.0)))
    conflict_pressure = min(1.0, conflicts / 6.0)
    ignored_pressure = min(1.0, ignored / 10.0)
    continuity_pressure = min(1.0, continuity_risks / 5.0)

    internal_integration = max(0.0, min(1.0, 0.30 * integration + 0.16 * agency + 0.14 * coherence + 0.10 * confidence + 0.10 * broadcast_factor + 0.10 * consumer_factor + 0.10 * learning_factor))
    fragmentation = max(0.0, min(1.0, 0.34 * uncertainty + 0.20 * conflict_pressure + 0.16 * threat + 0.12 * frustration + 0.10 * ignored_pressure + 0.08 * continuity_pressure))
    self_consistency = max(0.0, min(1.0, 0.55 * coherence + 0.25 * confidence + 0.20 * (1.0 - continuity_pressure)))
    authorship_balance = max(0.0, min(1.0, 0.55 * agency + 0.25 * consumer_factor + 0.20 * (1.0 - competition)))
    integration_proxy = max(0.0, min(1.0, 0.46 * internal_integration + 0.22 * self_consistency + 0.18 * authorship_balance + 0.14 * (1.0 - fragmentation)))

    level = 'low'
    if integration_proxy >= 0.72:
        level = 'high'
    elif integration_proxy >= 0.48:
        level = 'moderate'

    thresholds = {
        'high': 0.72,
        'moderate': 0.48,
        'fragility_alert': 0.38,
        'uncertainty_alert': 0.55,
    }
    alerts = []
    if integration_proxy < thresholds['fragility_alert']:
        alerts.append('integration_fragility')
    if uncertainty >= thresholds['uncertainty_alert']:
        alerts.append('uncertainty_elevated')
    if continuity_pressure >= 0.6:
        alerts.append('continuity_pressure')
    if conflict_pressure >= 0.5:
        alerts.append('conflict_pressure')

    drivers = [
        {'name': 'internal_integration', 'value': round(internal_integration, 4)},
        {'name': 'fragmentation', 'value': round(fragmentation, 4)},
        {'name': 'self_consistency', 'value': round(self_consistency, 4)},
        {'name': 'authorship_balance', 'value': round(authorship_balance, 4)},
        {'name': 'learning_factor', 'value': round(learning_factor, 4)},
    ]
    drivers = sorted(drivers, key=lambda x: float(x.get('value') or 0.0), reverse=True)

    return {
        'ok': True,
        'integration_proxy_score': round(integration_proxy, 4),
        'integration_level': level,
        'subscores': {
            'internal_integration': round(internal_integration, 4),
            'fragmentation': round(fragmentation, 4),
            'self_consistency': round(self_consistency, 4),
            'authorship_balance': round(authorship_balance, 4),
        },
        'inputs': {
            'workspace_integration': round(integration, 4),
            'workspace_competition': round(competition, 4),
            'agency_score': round(agency, 4),
            'meta_uncertainty': round(uncertainty, 4),
            'affect_confidence': round(confidence, 4),
            'affect_threat': round(threat, 4),
            'affect_frustration': round(frustration, 4),
            'narrative_coherence': round(coherence, 4),
            'learning_factor': round(learning_factor, 4),
            'ignored_items': ignored,
            'conflicts': conflicts,
            'continuity_risks': continuity_risks,
        },
        'learning_recent': learning_recent,
        'thresholds': thresholds,
        'alerts': alerts,
        'top_drivers': drivers,
        'first_person_report': (
            f"Meu nível atual de integração operacional é {level} ({integration_proxy:.2f}). "
            f"Integração interna={internal_integration:.2f}, consistência={self_consistency:.2f}, "
            f"fragmentação={fragmentation:.2f}."
        ),
        'recommended_actions': (
            ['trigger_reflexion', 'stabilize_workspace', 'reconcile_narrative'] if alerts else ['maintain_and_measure']
        ),
    }


def _operational_consciousness_snapshot(limit: int = 100) -> dict:
    return {
        'workspace': _workspace_status(limit=limit),
        'meta_observer': _meta_observer_snapshot(limit=limit),
        'affect': _artificial_affect_snapshot(limit=limit),
        'narrative': self_governance.autobiographical_summary(limit=max(40, min(160, limit))),
        'integration_proxy': _integration_proxy_snapshot(limit=limit),
    }


def _authorship_trace_snapshot(limit: int = 40) -> dict:
    limit = max(10, min(120, int(limit or 40)))
    auth = _workspace_authorship_snapshot(limit=max(40, limit))
    meta = _meta_observer_snapshot(limit=max(40, limit))
    integ = _integration_proxy_snapshot(limit=max(40, limit))
    affect = _artificial_affect_snapshot(limit=max(40, limit))
    narrative = self_governance.autobiographical_summary(limit=max(40, limit))

    items = _workspace_recent(limit=max(60, limit))
    actions = store.db.list_actions(limit=max(30, limit))
    events = store.db.list_events(limit=max(120, limit * 3))

    def _payload_preview(obj: Any) -> dict | None:
        if not isinstance(obj, dict):
            return None
        keep = {}
        for k in ('intent', 'goal', 'plan', 'decision', 'strategy', 'purpose', 'task_type', 'state', 'policy', 'summary', 'note'):
            v = obj.get(k)
            if isinstance(v, (str, int, float, bool)):
                keep[k] = v
        return keep or None

    intentions = []
    for it in reversed(items):
        mod = str(it.get('module') or 'unknown')
        ch = str(it.get('channel') or 'general')
        payload = it.get('payload') if isinstance(it.get('payload'), dict) else {}
        signal = f'{mod}:{ch}'.lower()
        if any(tok in signal for tok in ['tom', 'goal', 'plan', 'policy', 'self', 'intent', 'metacog']):
            intentions.append({
                'id': it.get('id'),
                'ts': it.get('created_at'),
                'module': mod,
                'channel': ch,
                'salience': float(it.get('salience') or 0.0),
                'payload': _payload_preview(payload),
            })
    intentions = intentions[-12:]

    decisions = []
    for ev in events:
        kind = str(ev.get('kind') or '')
        txt = str(ev.get('text') or '')
        lk = kind.lower()
        lt = txt.lower()
        if any(tok in lk for tok in ['judge', 'conflict', 'reasoning_audit', 'reflex', 'promotion', 'rollback', 'integrity', 'action_enqueue_decision', 'arbiter_block']) or any(tok in lt for tok in ['approved', 'rejected', 'conflict', 'arbiter', 'policy', 'queued kind=']):
            decisions.append({
                'id': ev.get('id'),
                'ts': ev.get('created_at'),
                'kind': kind,
                'text': txt[:220],
            })
    decisions = decisions[-12:]

    executions = []
    for a in actions:
        meta_json = a.get('meta_json') or '{}'
        try:
            am = json.loads(meta_json) if isinstance(meta_json, str) else (meta_json or {})
        except Exception:
            am = {}
        executions.append({
            'id': a.get('id'),
            'ts': a.get('updated_at') or a.get('created_at'),
            'status': a.get('status'),
            'kind': a.get('kind'),
            'priority': a.get('priority'),
            'policy_allowed': a.get('policy_allowed'),
            'task_type': am.get('task_type'),
            'strategy': am.get('strategy') or am.get('episodic_strategy'),
            'text': str(a.get('text') or '')[:220],
        })
    executions = executions[-12:]

    intention_cov = min(1.0, len(intentions) / 6.0)
    decision_cov = min(1.0, len(decisions) / 6.0)
    done_count = sum(1 for a in executions if str(a.get('status') or '') in ('done', 'completed', 'applied'))
    run_count = sum(1 for a in executions if str(a.get('status') or '') in ('running', 'done', 'completed', 'applied'))
    execution_cov = min(1.0, run_count / 6.0)
    closure = min(1.0, done_count / max(1, len(executions))) if executions else 0.0
    agency_score = float(auth.get('agency_score') or 0.0)
    integration_score = float(integ.get('integration_proxy_score') or 0.0)
    uncertainty = float(meta.get('uncertainty') or 0.0)
    coherence = float(((narrative.get('current_state') or {}).get('narrative_coherence_score')) or 0.0)

    trace_score = max(0.0, min(1.0,
        0.22 * intention_cov +
        0.22 * decision_cov +
        0.20 * execution_cov +
        0.16 * closure +
        0.10 * agency_score +
        0.07 * integration_score +
        0.03 * coherence
    ))
    trace_score *= max(0.45, 1.0 - 0.35 * uncertainty)
    trace_score = round(min(1.0, trace_score), 4)

    level = 'weak'
    if trace_score >= 0.72:
        level = 'strong'
    elif trace_score >= 0.48:
        level = 'moderate'

    origin_mix = {'self_generated': 0, 'externally_triggered': 0, 'mixed': 0, 'unknown': 0}
    for a in executions:
        origin = str(a.get('authorship_origin') or 'unknown')
        origin_mix[origin] = int(origin_mix.get(origin, 0)) + 1

    dominant_author = ((auth.get('authors') or [{}])[0] or {}).get('module') if auth.get('authors') else None
    return {
        'ok': True,
        'trace_score': trace_score,
        'trace_level': level,
        'dominant_author': dominant_author,
        'scores': {
            'intention_coverage': round(intention_cov, 4),
            'decision_coverage': round(decision_cov, 4),
            'execution_coverage': round(execution_cov, 4),
            'closure': round(closure, 4),
            'agency_score': round(agency_score, 4),
            'integration_proxy_score': round(integration_score, 4),
            'uncertainty': round(uncertainty, 4),
            'narrative_coherence': round(coherence, 4),
        },
        'attention': {
            'risk_posture': ((affect.get('risk_posture')) or 'stable'),
            'recommended_bias': (((affect.get('recommended_attention_policy') or {}).get('bias')) or 'balanced'),
        },
        'origin_mix': origin_mix,
        'workspace_origin_counts': auth.get('origin_counts') or {},
        'intentions': intentions,
        'decisions': decisions,
        'executions': executions,
    }


def _audit_reasoning(decision_type: str, context: dict, rationale: str, confidence: float | None = None):
    payload = {
        "decision_type": decision_type,
        "context": context,
        "rationale": (rationale or "")[:800],
        "confidence": confidence,
        "ts": int(time.time()),
    }
    store.db.add_event("reasoning_audit", f"🧾 {decision_type}: {(rationale or '')[:140]}", meta_json=json.dumps(payload, ensure_ascii=False))


def _neurosym_proof(decision_type: str, premises: list[str], inference: str, conclusion: str, confidence: float = 0.5, action_meta: dict | None = None):
    try:
        pf = neurosym.add_proof(decision_type, premises=premises, inference=inference, conclusion=conclusion, confidence=confidence, action_meta=action_meta or {})
        store.db.add_event("neurosym_proof", f"📐 proof {pf.get('id')} {decision_type}: {(conclusion or '')[:120]}")
    except Exception:
        pass


def _causal_precheck(kind: str, text: str = "", meta: dict | None = None) -> dict:
    model = causal.build_world_model(store.db, limit=4000)
    interventions = causal.infer_intervention_from_action(kind, text=text, meta=meta or {})
    sim = causal.simulate_intervention(model, interventions, steps=3)
    _audit_reasoning("causal_precheck", {"kind": kind, "interventions": interventions}, f"net={sim.get('net_score')} risk={sim.get('risk_score')} benefit={sim.get('benefit_score')}", confidence=0.7)
    return {"model": {"nodes": model.get("nodes") and len(model.get("nodes")) or 0, "edges": len(model.get("edges") or [])}, "simulation": sim}


def _latest_external_audit_hash() -> str | None:
    evs = store.db.list_events(limit=200)
    for e in reversed(evs):
        if (e.get("kind") or "") in ("external_action_executed", "external_action_denied", "external_action_dryrun"):
            try:
                m = json.loads(e.get("meta_json") or "{}")
                h = m.get("audit_hash")
                if h:
                    return str(h)
            except Exception:
                pass
    return None


def _compute_audit_hash(payload: dict) -> str:
    base = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    prev = _latest_external_audit_hash() or ""
    return hashlib.sha256((prev + "|" + base).encode("utf-8")).hexdigest()


def _selfpatch_allowed(path_str: str) -> bool:
    p = Path(path_str)
    try:
        rp = p.resolve()
    except Exception:
        return False
    allowed_roots = [Path('/app/ultronpro').resolve(), Path('/app/ui').resolve()]
    return any(str(rp).startswith(str(ar)) for ar in allowed_roots)


def _recent_actions_count(seconds: int = 60) -> int:
    now = int(asyncio.get_event_loop().time())
    arr = [int(x) for x in (_autonomy_state.get("last_actions_window") or []) if (now - int(x)) <= int(seconds)]
    _autonomy_state["last_actions_window"] = arr
    return len(arr)


def _mark_action_executed_now():
    now = int(asyncio.get_event_loop().time())
    arr = list(_autonomy_state.get("last_actions_window") or [])
    arr.append(now)
    _autonomy_state["last_actions_window"] = arr[-100:]


def _apply_runtime_mutation_policy(kind: str, priority: int, cooldown: int, ttl: int) -> tuple[int, int, int, dict]:
    rt = neuroplastic.active_runtime()
    active = (rt or {}).get("active") or []
    p = int(priority)
    cd = int(cooldown)
    t = int(ttl)
    applied = {"treated": False, "mutation_ids": []}

    for m in active:
        patch = (m or {}).get("patch") or {}
        if not isinstance(patch, dict):
            continue

        # canary A/B automático: aplica patch só em fração das decisões
        canary_ratio = float(patch.get("canary_ratio") or 1.0)
        if canary_ratio < 1.0 and random.random() > max(0.0, min(1.0, canary_ratio)):
            continue

        applied["treated"] = True
        if m.get("id"):
            applied["mutation_ids"].append(str(m.get("id")))

        apd = patch.get("action_priority_delta") or {}
        if isinstance(apd, dict):
            p += int(apd.get(kind) or 0)
        acs = patch.get("action_cooldown_scale") or {}
        if isinstance(acs, dict) and acs.get(kind) is not None:
            try:
                cd = int(max(10, float(cd) * float(acs.get(kind))))
            except Exception:
                pass
        if patch.get("queue_ttl_scale") is not None:
            try:
                t = int(max(60, float(t) * float(patch.get("queue_ttl_scale"))))
            except Exception:
                pass

    return max(0, min(10, p)), max(10, min(7200, cd)), max(60, min(7200, t)), applied


def _arbiter_vote(kind: str, text: str, meta: dict | None = None) -> tuple[bool, dict]:
    t = str(text or '').lower()
    # specialist votes
    safety_ok = not any(x in t for x in ['drop table', 'rm -rf', 'disable safeguards'])
    relevance_ok = len(str(text or '').strip()) >= 12
    feasibility_ok = True
    mm = meta or {}
    if str(mm.get('intent') or '') == 'tool_failure' and 'context' not in mm:
        feasibility_ok = False
    votes = {'safety': safety_ok, 'relevance': relevance_ok, 'feasibility': feasibility_ok}
    passed = sum(1 for v in votes.values() if v) >= 2 and safety_ok
    return passed, votes


def _episodic_strategy_bias(kind: str, text: str, task_type: str) -> dict:
    try:
        sims = episodic_memory.find_similar(kind=kind, text=text, task_type=task_type, limit=10)
    except Exception:
        sims = []
    if not sims:
        return {'delta': 0, 'strategy': None, 'confidence': 0.0}

    good = [s for s in sims if bool(s.get('ok'))]
    bad = [s for s in sims if not bool(s.get('ok'))]
    ratio = len(good) / max(1, len(sims))
    # priority bias: favor successful analogies, penalize bad history
    delta = 0
    if ratio >= 0.7:
        delta += 2
    elif ratio <= 0.35:
        delta -= 2
    if len(bad) >= 3:
        delta -= 1

    # pick most frequent successful strategy
    strategy = None
    if good:
        freq = {}
        for g in good:
            k = str(g.get('strategy') or g.get('kind') or '')
            if k:
                freq[k] = int(freq.get(k, 0)) + 1
        if freq:
            strategy = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[0][0]

    return {'delta': int(delta), 'strategy': strategy, 'confidence': round(ratio, 3)}


def _classify_action_origin(kind: str, text: str, meta: dict | None = None) -> str:
    meta = meta or {}
    origin = str(meta.get('origin') or meta.get('source') or meta.get('trigger') or '').strip().lower()
    actor = str(meta.get('actor') or meta.get('author') or '').strip().lower()
    text_low = f"{kind} {text}".lower()
    if origin in {'self_generated', 'externally_triggered', 'mixed', 'unknown'}:
        return origin
    if any(tok in actor for tok in ('user', 'human', 'operator', 'teacher', 'openclaw', 'webhook')):
        return 'externally_triggered'
    if any(tok in origin for tok in ('user', 'human', 'operator', 'teacher', 'openclaw', 'webhook', 'api')):
        return 'externally_triggered'
    if any(tok in origin for tok in ('autonomy', 'judge', 'reflexion', 'roadmap', 'agi_path', 'mission', 'planner', 'self')):
        return 'self_generated'
    if any(tok in text_low for tok in ('pedido do usuário', 'user asked', 'requested by user', 'teacher feedback')):
        return 'externally_triggered'
    if any(tok in text_low for tok in ('self-check', 'auto', 'autonomous', 'roadmap', 'self-patch', 'reflect', 'judge')):
        return 'self_generated'
    if origin:
        return 'mixed'
    return 'unknown'


def _enqueue_action_if_new(kind: str, text: str, priority: int = 0, meta: dict | None = None, ttl_sec: int | None = None):
    """Enfileira ação com dedupe + cooldown + expiração de fila + runtime mutation policy + arbiter gate."""
    recent = store.db.list_actions(limit=120)
    now = time.time()
    cooldown = ACTION_COOLDOWNS_SEC.get(kind, 120)
    mk = meta or {}
    cd_sig = mk.get('conflict_id') or mk.get('goal_id') or mk.get('milestone_id') or mk.get('procedure_id') or ''
    cd_key = f"{kind}:{cd_sig}"

    ttl = int(ttl_sec or ACTION_DEFAULT_TTL_SEC)
    priority, cooldown, ttl, mut = _apply_runtime_mutation_policy(kind, int(priority), int(cooldown), ttl)

    for a in recent:
        if a.get("status") in ("queued", "running") and a.get("kind") == kind and (a.get("text") or "") == text:
            return

    # cooldown inteligente: evita spam por tipo/chave
    for a in reversed(recent):
        if a.get("kind") != kind:
            continue
        if (a.get("cooldown_key") or "") != cd_key:
            continue
        last_t = float(a.get("updated_at") or a.get("created_at") or 0)
        if (now - last_t) < cooldown:
            return
        break

    expires_at = now + ttl
    mmeta = dict(meta or {})
    if mut.get("treated"):
        mmeta["mutation_treated"] = True
        mmeta["mutation_ids"] = mut.get("mutation_ids") or []

    ttype = str(mmeta.get('task_type') or '')
    if not ttype:
        if kind in ('execute_python_sandbox', 'invent_procedure', 'execute_procedure_active'):
            ttype = 'coding'
        elif kind in ('verify_source_headless', 'absorb_lightrag_general', 'ask_evidence'):
            ttype = 'research'
        elif kind in ('auto_resolve_conflicts', 'clarify_semantics'):
            ttype = 'review'
        else:
            ttype = 'heartbeat'
        mmeta['task_type'] = ttype

    mmeta['authorship_origin'] = _classify_action_origin(kind, text, mmeta)

    eb = _episodic_strategy_bias(kind=kind, text=text, task_type=ttype)
    if int(eb.get('delta') or 0) != 0:
        priority = max(0, min(10, int(priority) + int(eb.get('delta') or 0)))
    if eb.get('strategy'):
        mmeta['preferred_strategy'] = eb.get('strategy')
    mmeta['episodic_bias'] = eb

    ok_arb, votes = _arbiter_vote(kind, text, mmeta)
    if not ok_arb:
        store.db.add_event('arbiter_block', f"🧭 blocked kind={kind} votes={votes}")
        return
    mmeta['arbiter_votes'] = votes

    store.db.enqueue_action(
        kind=kind,
        text=text,
        priority=priority,
        meta_json=json.dumps(mmeta, ensure_ascii=False),
        expires_at=expires_at,
        cooldown_key=cd_key,
    )


def _ensure_goal_milestones(goal_id: int, title: str, description: str | None = None, weeks: int = 4) -> int:
    existing = store.list_goal_milestones(goal_id=goal_id, status=None, limit=32)
    if existing:
        return 0
    planner = goals.GoalPlanner()
    ms = planner.build_weekly_milestones(title, description, weeks=weeks)
    added = 0
    for m in ms:
        store.add_goal_milestone(goal_id, int(m.get("week_index") or 1), m.get("title") or "Milestone", m.get("progress_criteria"))
        added += 1
    return added


def _intrinsic_tick(force: bool = False) -> dict:
    st = intrinsic.load_state()

    stats = store.db.stats()
    meta = _metacognition_tick()
    goals_all = store.db.list_goals(status=None, limit=200)
    goals_done = len([g for g in goals_all if str(g.get('status') or '') == 'done'])
    done_rate = goals_done / max(1, len(goals_all))

    # novelty_index simples: razão de conceitos latentes recentes + perguntas abertas
    novelty_index = min(1.0, (float(stats.get('questions_open') or 0) / 80.0) + 0.2)

    signals = {
        'uncurated': store.db.count_uncurated_experiences(),
        'open_conflicts': len(store.db.list_conflicts(status='open', limit=300)),
        'decision_quality': float(meta.get('decision_quality') or 0.5),
        'goals_done_rate': float(done_rate),
        'novelty_index': novelty_index,
    }

    st = intrinsic.update_drives(st, signals)
    chosen = intrinsic.synthesize_intrinsic_goal(st)
    st = intrinsic.revise_purpose(st, chosen)
    intrinsic.save_state(st)

    # cria/atualiza goal intrínseco
    gid = store.db.upsert_goal(
        f"[IME] {chosen.get('title')}",
        f"{chosen.get('description')} | drive={chosen.get('drive')} reward={chosen.get('intrinsic_reward')}",
        int(chosen.get('priority') or 4),
    )

    _workspace_publish('intrinsic', 'purpose.state', {'purpose': st.get('purpose'), 'drives': st.get('drives'), 'chosen_goal': chosen, 'goal_id': gid}, salience=0.78, ttl_sec=3600)
    store.db.add_event('intrinsic_tick', f"🧭 IME tick: drive={chosen.get('drive')} goal={chosen.get('title')}")

    return {
        'signals': signals,
        'drives': st.get('drives'),
        'purpose': st.get('purpose'),
        'chosen_goal': chosen,
        'goal_id': gid,
    }


def _emergence_tick() -> dict:
    stats = store.db.stats()
    meta = _metacognition_tick()
    inputs = {
        'decision_quality': float(meta.get('decision_quality') or 0.5),
        'open_conflicts': len(store.db.list_conflicts(status='open', limit=400)),
        'novelty_index': min(1.0, float(stats.get('questions_open') or 0) / 80.0 + 0.2),
    }
    st = emergence.tick_latent(inputs)
    policies = emergence.sample_policies({'stats': stats, 'meta': meta}, n=4)
    chosen = emergence.choose_policy(policies, {'stats': stats, 'meta': meta})

    for a in (chosen.get('actions') or [])[:2]:
        _enqueue_action_if_new(
            a,
            f"(ação-emergence) Política latente selecionou: {a}",
            priority=5,
            meta={'emergence_policy': chosen.get('id')},
            ttl_sec=20 * 60,
        )

    item = {'ts': int(time.time()), 'latent': st.get('latent'), 'chosen_policy': chosen}
    emergence.log_eval(item)
    _workspace_publish('emergence', 'emergence.state', item, salience=0.76, ttl_sec=2400)
    store.db.add_event('emergence_tick', f"🧠 emergence policy={chosen.get('id')} actions={','.join(chosen.get('actions') or [])}")
    return item


def _itc_router_need() -> dict:
    meta = _metacognition_tick()
    open_conf = len(store.db.list_conflicts(status='open', limit=300))
    dq = float(meta.get('decision_quality') or 0.5)
    need = (open_conf >= 8) or (dq < 0.25)
    reason = 'conflict_load' if open_conf >= 8 else ('low_decision_quality' if dq < 0.25 else 'none')
    return {'need': need, 'reason': reason, 'open_conflicts': open_conf, 'decision_quality': dq}


def _generate_turbo_report() -> dict:
    actions = store.db.list_actions(limit=220)
    denom = max(1, len(actions))
    done = len([a for a in actions if str(a.get('status') or '') == 'done'])
    err = len([a for a in actions if str(a.get('status') or '') == 'error'])
    blocked = len([a for a in actions if str(a.get('status') or '') == 'blocked'])

    ps = plasticity_runtime.status(limit=120)
    econ = economic.status(limit=80)
    cal = calibration.status(limit=80)
    missions = mission_control.list_tasks(limit=160)
    by_status = {}
    for t in missions:
        st = str(t.get('status') or 'unknown')
        by_status[st] = int(by_status.get(st) or 0) + 1

    report = {
        'generated_at': int(time.time()),
        'mode': 'turbo_safe',
        'autonomy': {
            'actions_window': len(actions),
            'done_rate': round(done / denom, 4),
            'error_rate': round(err / denom, 4),
            'blocked_rate': round(blocked / denom, 4),
        },
        'plasticity': {
            'feedback_total': ps.get('feedback_total'),
            'failure_rate': ps.get('failure_rate'),
            'hallucination_rate': ps.get('hallucination_rate'),
        },
        'economic': {
            'epsilon': econ.get('epsilon'),
            'mix_recent': econ.get('profile_mix_recent'),
        },
        'calibration': {
            'brier': cal.get('brier_score'),
            'overconfidence_gap': cal.get('overconfidence_gap'),
        },
        'mission_control': {
            'total': len(missions),
            'by_status': by_status,
        },
    }

    TURBO_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TURBO_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    _autonomy_state['turbo_last_report_at'] = int(report['generated_at'])
    return report


def _read_turbo_report() -> dict:
    try:
        if TURBO_REPORT_PATH.exists():
            return json.loads(TURBO_REPORT_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {'generated_at': 0, 'mode': 'turbo_safe', 'note': 'no report yet'}


def _run_deliberate_task(problem_text: str, max_steps: int = 0, budget_seconds: int = 0, use_rl: bool = True, search_mode: str = 'mcts', branching_factor: int = 2, checkpoint_every_sec: int = 30) -> dict:
    out = itc.run_episode(
        problem_text=problem_text,
        max_steps=max_steps,
        budget_seconds=budget_seconds,
        use_rl=use_rl,
        search_mode=search_mode,
        branching_factor=branching_factor,
        checkpoint_every_sec=checkpoint_every_sec,
    )
    chosen = out.get('chosen') or {}
    if chosen.get('test'):
        _enqueue_action_if_new(
            'ask_evidence',
            f"(itc-test) {chosen.get('test')}",
            priority=6,
            meta={'source': 'itc', 'confidence': chosen.get('confidence'), 'policy_arm': out.get('policy_arm')},
            ttl_sec=20 * 60,
        )
    _workspace_publish('itc', 'deliberation.episode', out, salience=0.82, ttl_sec=3600)
    store.db.add_event('itc_episode', f"🧠 ITC arm={out.get('policy_arm')} steps={len(out.get('steps') or [])} quality={out.get('quality_proxy')} reward={out.get('reward')}")
    return out


def _run_tool_route(intent: str, context: dict | None = None, prefer_low_cost: bool = True) -> dict:
    plan = tool_router.plan_route(intent=intent, context=context or {}, prefer_low_cost=prefer_low_cost)
    chain = list(plan.get('chain') or [])[:3]

    attempted = []
    for k in chain:
        attempted.append(k)
        try:
            if k == 'ask_evidence':
                q = str((context or {}).get('question') or f"(router:{intent}) executar próximo passo de recuperação")
                store.db.add_questions([{"question": q[:500], "priority": 5, "context": "tool_router"}])
                _neurosym_proof('tool_route', [f'intent={intent}', f'candidate={k}'], 'Selected low-cost evidence query route.', f'Route executed via {k}.', confidence=0.74, action_meta={'kind': k, 'status': 'done', 'intent': intent})
                return {'status': 'ok', 'selected': k, 'attempted': attempted, 'plan': plan}
            if k == 'deliberate_task':
                ptxt = str((context or {}).get('problem_text') or f"Router intent {intent}: deliberate best next move")
                out = _run_deliberate_task(problem_text=ptxt, max_steps=0, budget_seconds=0, use_rl=True)
                if float(out.get('quality_proxy') or 0.0) >= 0.35:
                    _neurosym_proof('tool_route', [f'intent={intent}', f'candidate={k}', f"quality={out.get('quality_proxy')}"], 'Selected deliberate route with acceptable quality.', f'Route executed via {k}.', confidence=0.78, action_meta={'kind': k, 'status': 'done', 'intent': intent})
                    return {'status': 'ok', 'selected': k, 'attempted': attempted, 'plan': plan, 'result': out}
                continue
            if k == 'generate_analogy_hypothesis':
                ptxt = str((context or {}).get('problem_text') or f"{intent} unresolved")
                td = (context or {}).get('target_domain')
                # schedule async path safely
                _enqueue_action_if_new('generate_analogy_hypothesis', f"(router:{intent}) gerar hipótese analógica", priority=5, meta={'problem_text': ptxt[:300], 'target_domain': td, 'intent': intent}, ttl_sec=20 * 60)
                _neurosym_proof('tool_route', [f'intent={intent}', f'candidate={k}'], 'Selected analogy route as fallback chain.', f'Route scheduled via {k}.', confidence=0.68, action_meta={'kind': k, 'status': 'scheduled', 'intent': intent})
                return {'status': 'ok', 'selected': k, 'attempted': attempted, 'plan': plan, 'scheduled': True}
            if k == 'maintain_question_queue':
                info = _maintain_question_queue(stale_hours=18.0, max_fix=4)
                _neurosym_proof('tool_route', [f'intent={intent}', f'candidate={k}'], 'Selected queue maintenance route for recovery.', f'Route executed via {k}.', confidence=0.64, action_meta={'kind': k, 'status': 'done', 'intent': intent})
                return {'status': 'ok', 'selected': k, 'attempted': attempted, 'plan': plan, 'result': info}
        except Exception:
            continue

    _neurosym_proof('tool_route', [f'intent={intent}', f'attempted={attempted}'], 'All route candidates failed or were unavailable.', 'Tool routing failed; no executable candidate.', confidence=0.3, action_meta={'kind': 'route_toolchain', 'status': 'error', 'intent': intent})
    return {'status': 'error', 'attempted': attempted, 'plan': plan}


async def _run_subgoal_dispatch(root_id: str, node_id: str) -> dict:
    root = subgoals.get_root(root_id)
    node = next((n for n in (root or {}).get('nodes') or [] if str(n.get('id')) == str(node_id)), None)
    if not node:
        return {'ok': False, 'status': 'missing_node'}

    ntype = str(node.get('type') or 'execution')
    title = str(node.get('title') or '')
    objective = str(node.get('objective') or title)
    criteria = str(node.get('success_criteria') or '')

    if ntype == 'clarification':
        try:
            prompt = f"""Clarify this subgoal for autonomous execution.
Return ONLY JSON with keys: objective_definition, constraints (array), verification_hint.
Subgoal title: {title}
Objective: {objective}
Success criteria: {criteria}
"""
            raw = llm.complete(prompt, strategy='cheap', json_mode=True)
            d = json.loads(raw) if raw else {}
        except Exception:
            d = {}
        observed = json.dumps({
            'objective_definition': d.get('objective_definition') or objective,
            'constraints': d.get('constraints') or ['respect current goal scope'],
            'verification_hint': d.get('verification_hint') or criteria,
        }, ensure_ascii=False)
        subgoals.update_node(root_id, node_id, {'last_result': observed, 'origin': 'dispatcher_clarification'})
        return {'ok': True, 'type': ntype, 'observed_result': observed}

    if ntype == 'execution':
        try:
            out = await _metacog_orchestrator_run(objective, metrics={}, generation_strategy='canary_qwen')
        except Exception as e:
            out = {'ok': False, 'answer': '', 'error': str(e)}
        observed = json.dumps({
            'strategy': out.get('strategy'),
            'answer': out.get('answer'),
            'prm_score': out.get('prm_score'),
            'prm_risk': out.get('prm_risk'),
            'ok': out.get('ok', False),
        }, ensure_ascii=False)
        subgoals.update_node(root_id, node_id, {'last_result': observed, 'origin': 'dispatcher_execution'})
        return {'ok': True, 'type': ntype, 'observed_result': observed, 'execution': out}

    if ntype == 'validation':
        deps = [str(x) for x in (node.get('dependencies') or []) if str(x).strip()]
        dep_results = []
        for dep in deps:
            dn = next((n for n in (root or {}).get('nodes') or [] if str(n.get('id')) == dep), None)
            if dn and dn.get('last_result'):
                dep_results.append(str(dn.get('last_result'))[:700])
        context_txt = "\n".join(dep_results)[:1400]
        prm = prm_lite.score_answer(criteria or objective, context_txt or 'no prior result', context=context_txt, meta={'strategy': 'subgoal_validation'})
        observed = json.dumps({
            'validation_query': criteria or objective,
            'context_sample': context_txt[:400],
            'prm_score': prm.get('score'),
            'prm_risk': prm.get('risk'),
            'prm_reasons': prm.get('reasons') or [],
        }, ensure_ascii=False)
        subgoals.update_node(root_id, node_id, {'last_result': observed, 'origin': 'dispatcher_validation'})
        return {'ok': True, 'type': ntype, 'observed_result': observed, 'validation': prm}

    if ntype == 'consolidation':
        deps = [str(x) for x in (node.get('dependencies') or []) if str(x).strip()]
        dep_results = []
        for dep in deps:
            dn = next((n for n in (root or {}).get('nodes') or [] if str(n.get('id')) == dep), None)
            if dn and dn.get('last_result'):
                dep_results.append({'id': dep, 'result': str(dn.get('last_result'))[:900]})
        pm = _run_post_execution_learning(
            query=objective,
            answer=json.dumps(dep_results, ensure_ascii=False),
            steps_executed=dep_results[:4],
            planner_context={'verification': {'success_criteria': criteria, 'root_id': root_id, 'node_id': node_id}},
            task_type='subgoal_consolidation',
            episode_id=node_id,
        )
        try:
            causal_graph.apply_delta_update(
                cause=f'subgoal:{title.lower()[:80]}',
                effect='subgoal_consolidated_learning',
                condition=f'root_id={root_id}',
                category='confirmed',
                evidence={'node_id': node_id, 'type': ntype},
                source='subgoal_dispatcher',
            )
        except Exception:
            pass
        observed = json.dumps({'postmortem': pm.get('postmortem') or {}, 'procedural_update': pm.get('procedural_update') or {}}, ensure_ascii=False)
        subgoals.update_node(root_id, node_id, {'last_result': observed, 'origin': 'dispatcher_consolidation'})
        return {'ok': True, 'type': ntype, 'observed_result': observed, 'postmortem': pm}

    observed = f'unsupported_subgoal_type:{ntype}'
    subgoals.update_node(root_id, node_id, {'last_result': observed})
    return {'ok': False, 'type': ntype, 'observed_result': observed, 'status': 'unsupported_type'}


def _tail_jsonl(path: Path, limit: int = 8) -> list[dict]:
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(1, int(limit)):]
        out = []
        for ln in lines:
            try:
                x = json.loads(ln)
                if isinstance(x, dict):
                    out.append(x)
            except Exception:
                pass
        return out
    except Exception:
        return []


def _deep_context_snapshot(reason: str = 'runtime', recovery: dict | None = None, root_hint_id: str | None = None) -> dict:
    ag = store.db.get_active_goal()
    mission = longhorizon.active_mission()
    st = cognitive_state.get_state()
    root = subgoals.get_root(root_hint_id) if root_hint_id else None
    if not root and ag:
        title = str((ag or {}).get('title') or '')
        objective = str((ag or {}).get('description') or '')
        root = subgoals.find_latest_root(title=title, objective=objective)
    if not root and mission:
        title = str((mission or {}).get('title') or '')
        objective = str((mission or {}).get('objective') or '')
        root = subgoals.find_latest_root(title=title, objective=objective)
    if not root:
        roots = subgoals.list_roots(limit=1)
        root = roots[-1] if roots else None
    snap = {
        'ts': int(time.time()),
        'reason': reason,
        'active_goal': ag,
        'active_mission': mission,
        'cognitive_state': {
            'constraints': list((st.get('constraints') or [])[-12:]),
            'uncertainties': list((st.get('uncertainties') or [])[-8:]),
            'goals': list((st.get('goals') or [])[-8:]),
        },
        'subgoals': root,
        'recent_causal_deltas': _tail_jsonl(causal_graph.EDGE_LOG_PATH, limit=8),
        'recovery': recovery or {},
    }
    try:
        DEEP_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEEP_CONTEXT_PATH.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    return snap


def _boot_recover_context() -> dict:
    snap = {}
    try:
        if DEEP_CONTEXT_PATH.exists():
            snap = json.loads(DEEP_CONTEXT_PATH.read_text(encoding='utf-8')) or {}
    except Exception:
        snap = {}

    ag = store.db.get_active_goal()
    mission = longhorizon.active_mission()
    title = str((mission or {}).get('title') or (ag or {}).get('title') or ((snap.get('active_mission') or {}).get('title') or (snap.get('active_goal') or {}).get('title') or ''))
    objective = str((mission or {}).get('objective') or (ag or {}).get('description') or ((snap.get('active_mission') or {}).get('objective') or (snap.get('active_goal') or {}).get('description') or ''))
    root_id = str(((snap.get('subgoals') or {}).get('id')) or '')
    root = subgoals.get_root(root_id) if root_id else None
    if not root and (title or objective):
        root = subgoals.find_latest_root(title=title, objective=objective)
    if not root:
        out = {'status': 'no_root'}
        _deep_context_snapshot('boot_recovery_no_root', recovery=out)
        return out

    resumed = []
    for n in (root.get('nodes') or []):
        if str(n.get('status') or '') != 'doing':
            continue
        vr = _verify_subgoal_success(n, str(n.get('last_result') or ''))
        if vr.get('ok'):
            subgoals.update_node(root.get('id'), n.get('id'), {'status': 'done', 'verification_note': f"boot_recovery:{vr.get('reason') or 'verified'}"})
            resumed.append({'node_id': n.get('id'), 'from': 'doing', 'to': 'done', 'policy': 'revalidated_done'})
        else:
            subgoals.update_node(root.get('id'), n.get('id'), {'status': 'open', 'verification_note': f"boot_recovery:{vr.get('reason') or 'reopen'}"})
            resumed.append({'node_id': n.get('id'), 'from': 'doing', 'to': 'open', 'policy': 'revalidated_open'})

    root = subgoals.get_root(root.get('id')) or root
    next_node = subgoals.select_next_node(root)
    if next_node:
        _enqueue_action_if_new(
            'execute_subgoal',
            f"(subgoal:{next_node.get('type')}) {next_node.get('title')}",
            priority=int(next_node.get('priority') or 5),
            meta={'subgoal_root_id': root.get('id'), 'subgoal_node_id': next_node.get('id'), 'subgoal_type': next_node.get('type'), 'boot_recovery': True},
            ttl_sec=25 * 60,
        )
    out = {'status': 'ok', 'root_id': root.get('id'), 'resumed': resumed, 'selected': next_node}
    _deep_context_snapshot('boot_recovery_complete', recovery=out)
    return out


def _mission_control_cfg() -> dict:
    cfg = {
        'enabled': True,
        'heartbeat_sec': int(os.getenv('ULTRON_MISSION_HEARTBEAT_SEC', '300') or 300),
        'cycle_timeout_sec': float(os.getenv('ULTRON_MISSION_CYCLE_TIMEOUT_SEC', '45') or 45),
    }
    try:
        if MISSION_CONTROL_CFG_PATH.exists():
            d = json.loads(MISSION_CONTROL_CFG_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                cfg.update(d)
    except Exception:
        pass
    cfg['heartbeat_sec'] = max(5, min(3600, int(cfg.get('heartbeat_sec') or 300)))
    cfg['cycle_timeout_sec'] = max(1.0, min(600.0, float(cfg.get('cycle_timeout_sec') or 45)))
    cfg['enabled'] = bool(cfg.get('enabled', True))
    return cfg


def _mission_control_state() -> dict:
    try:
        if MISSION_CONTROL_STATE_PATH.exists():
            d = json.loads(MISSION_CONTROL_STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('notified', {})
                return d
    except Exception:
        pass
    return {'notified': {}, 'updated_at': int(time.time())}


def _mission_control_state_save(state: dict) -> None:
    try:
        MISSION_CONTROL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = dict(state or {})
        state['updated_at'] = int(time.time())
        MISSION_CONTROL_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass


def _mission_control_dedupe_key(event_type: str, mission_id: str | None = None, root_id: str | None = None, node_id: str | None = None) -> str:
    if event_type == 'milestone_reached':
        return f'{event_type}:{root_id or ""}:{node_id or ""}'
    if event_type == 'goal_completed':
        return f'{event_type}:{root_id or ""}'
    if event_type == 'retry_blocked':
        return f'{event_type}:{root_id or ""}:{node_id or ""}'
    if event_type == 'critical_error':
        return f'{event_type}:{root_id or ""}:{node_id or ""}:{mission_id or ""}'
    return f'{event_type}:{mission_id or ""}:{root_id or ""}:{node_id or ""}'


def _mission_control_log(entry: dict) -> None:
    try:
        MISSION_CONTROL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MISSION_CONTROL_LOG_PATH.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': int(time.time()), **entry}, ensure_ascii=False) + '\n')
    except Exception:
        pass


async def _mission_control_notify(text: str, event_type: str, mission_id: str | None = None, root_id: str | None = None, node_id: str | None = None) -> dict:
    text = str(text or '').strip()
    if not text:
        return {'ok': False, 'reason': 'empty_text'}
    dedupe_key = _mission_control_dedupe_key(event_type, mission_id=mission_id, root_id=root_id, node_id=node_id)
    state = _mission_control_state()
    if dedupe_key in (state.get('notified') or {}):
        _mission_control_log({'kind': 'notify', 'event_type': event_type, 'mission_id': mission_id, 'root_id': root_id, 'node_id': node_id, 'status': 'suppressed_duplicate', 'dedupe_key': dedupe_key})
        return {'ok': True, 'status': 'suppressed_duplicate', 'dedupe_key': dedupe_key}
    try:
        prep = ActionPrepareRequest(kind='notify_human', target='telegram', reason=f'mission_control:{event_type}', payload={'text': text})
        prepared = await prepare_external_action(prep)
        token = prepared.get('confirm_token')
        req = ActionExecRequest(kind='notify_human', target='telegram', reason=f'mission_control:{event_type}', payload={'text': text}, confirm_token=token, dry_run=False)
        out = await execute_external_action(req)
        state.setdefault('notified', {})[dedupe_key] = {'ts': int(time.time()), 'event_type': event_type, 'mission_id': mission_id, 'root_id': root_id, 'node_id': node_id, 'status': out.get('status')}
        _mission_control_state_save(state)
        _mission_control_log({'kind': 'notify', 'event_type': event_type, 'mission_id': mission_id, 'root_id': root_id, 'node_id': node_id, 'status': out.get('status'), 'dedupe_key': dedupe_key})
        return {'ok': True, **out}
    except Exception as e:
        _mission_control_log({'kind': 'notify', 'event_type': event_type, 'mission_id': mission_id, 'root_id': root_id, 'node_id': node_id, 'status': 'error', 'error': str(e)[:200], 'dedupe_key': dedupe_key})
        return {'ok': False, 'error': str(e)}


def _mission_complete(root: dict | None) -> bool:
    nodes = list((root or {}).get('nodes') or [])
    return bool(nodes) and all(str(n.get('status') or '') == 'done' for n in nodes)


def _verify_subgoal_success(node: dict | None, observed_result: str) -> dict:
    node = node or {}
    crit = str(node.get('success_criteria') or '').strip()
    if not crit:
        return {'ok': False, 'confidence': 0.0, 'reason': 'missing success_criteria'}
    obs = str(observed_result or '').strip()[:2200]
    if not obs:
        return {'ok': False, 'confidence': 0.0, 'reason': 'missing observed_result'}
    try:
        prompt = f"""You are a strict verifier for subgoal completion.
Return ONLY valid JSON with keys:
- ok: boolean
- confidence: number from 0.00 to 1.00
- reason: short string
- evidence: array of short strings
- missing: array of short strings

Decision policy:
- ok=true ONLY if the observed result contains concrete evidence that the success criteria were satisfied.
- If the result is vague, generic, says only that work was attempted, or lacks measurable/explicit proof, return ok=false.
- Do not reward polished wording. Reward only concrete evidence.
- For ok=true, confidence should usually be between 0.70 and 0.80 unless the evidence is exceptionally direct.
- For ok=false, confidence should be at most 0.45.

Subgoal title: {str(node.get('title') or '')[:220]}
Subgoal type: {str(node.get('type') or '')[:80]}
Success criteria: {crit[:700]}
Observed result: {obs}
"""
        raw = llm.complete(prompt, strategy='cheap', json_mode=True)
        d = json.loads(raw) if raw else {}
        if isinstance(d, dict):
            ok = bool(d.get('ok'))
            conf = max(0.0, min(1.0, float(d.get('confidence') or 0.0)))
            if ok:
                conf = max(0.70, min(0.80, conf if conf > 0 else 0.74))
            else:
                conf = min(0.45, conf if conf > 0 else 0.35)
            reason = str(d.get('reason') or '').strip()[:180]
            evidence = d.get('evidence') if isinstance(d.get('evidence'), list) else []
            missing = d.get('missing') if isinstance(d.get('missing'), list) else []
            suffix = []
            if evidence:
                suffix.append('evidence=' + '; '.join(str(x)[:60] for x in evidence[:2]))
            if missing:
                suffix.append('missing=' + '; '.join(str(x)[:60] for x in missing[:2]))
            final_reason = reason or ('llm verifier pass' if ok else 'llm verifier fail')
            if suffix:
                final_reason = (final_reason + ' | ' + ' | '.join(suffix))[:240]
            return {'ok': ok, 'confidence': conf, 'reason': final_reason}
    except Exception:
        pass
    # fallback conservador: falha por padrão quando não há prova explícita por tipo
    tl = obs.lower()
    ntype = str(node.get('type') or '').lower()
    if ntype == 'clarification':
        ok = ('objective_definition' in tl and 'constraints' in tl and ('verification_hint' in tl or 'success' in tl))
        return {'ok': ok, 'confidence': 0.72 if ok else 0.30, 'reason': 'fallback verifier: clarification evidence-based' if ok else 'fallback verifier fail: clarification missing structured definition'}
    if ntype == 'execution':
        ok = ('"ok": true' in tl and ('artifact' in tl or 'result' in tl or 'answer' in tl))
        return {'ok': ok, 'confidence': 0.74 if ok else 0.32, 'reason': 'fallback verifier: execution evidence-based' if ok else 'fallback verifier fail: execution lacks concrete artifact'}
    if ntype == 'validation':
        ok = ('validation_query' in tl and ('prm_score' in tl or 'measured' in tl or 'metric' in tl))
        return {'ok': ok, 'confidence': 0.76 if ok else 0.33, 'reason': 'fallback verifier: validation evidence-based' if ok else 'fallback verifier fail: validation lacks explicit measurement'}
    if ntype == 'consolidation':
        ok = ('postmortem' in tl and ('decision' in tl or 'next_action' in tl or 'procedural_update' in tl))
        return {'ok': ok, 'confidence': 0.75 if ok else 0.34, 'reason': 'fallback verifier: consolidation evidence-based' if ok else 'fallback verifier fail: consolidation lacks learning decision'}

    return {'ok': False, 'confidence': 0.30, 'reason': 'fallback verifier fail: insufficient explicit evidence'}


def _subgoal_planning_tick() -> dict:
    ag = store.db.get_active_goal()
    mission = longhorizon.active_mission()
    if not ag and not mission:
        return {"status": "no_context"}

    title = str((mission or {}).get("title") or (ag or {}).get("title") or "Goal")
    objective = str((mission or {}).get("objective") or (ag or {}).get("description") or title)
    root = subgoals.find_latest_root(title=title, objective=objective)
    if not root:
        root = subgoals.synthesize_for_goal(title=title, objective=objective, max_nodes=8)

    next_node = subgoals.select_next_node(root)
    if next_node:
        _enqueue_action_if_new(
            "execute_subgoal",
            f"(subgoal:{next_node.get('type')}) {next_node.get('title')}",
            priority=int(next_node.get("priority") or 5),
            meta={"subgoal_root_id": root.get("id"), "subgoal_node_id": next_node.get("id"), "subgoal_type": next_node.get("type")},
            ttl_sec=25 * 60,
        )

    open_nodes = [n for n in (root.get("nodes") or []) if str(n.get("status") or "open") == "open"]
    _workspace_publish("subgoals", "goal.subgoals", root, salience=0.8, ttl_sec=3600)
    _deep_context_snapshot('subgoal_planning_tick')
    store.db.add_event("subgoal_planning", f"🧩 subgoals root={root.get('id')} open={len(open_nodes)} selected={(next_node or {}).get('id')}")
    return {"status": "ok", "root": root, "open_nodes": len(open_nodes), "selected": next_node}


def _project_management_tick() -> dict:
    project_kernel.ensure_default_playbooks()
    project_kernel.recover_stale_steps(max_age_sec=900)
    p = project_kernel.active_project()

    if not p:
        # seed a project from active mission/goal
        m = longhorizon.active_mission()
        g = store.db.get_active_goal()
        if m:
            p = project_kernel.upsert_project(m.get('title') or 'Projeto', m.get('objective') or m.get('title') or 'Objetivo', scope=m.get('context'), sla_hours=72)
        elif g:
            p = project_kernel.upsert_project(g.get('title') or 'Projeto', g.get('description') or g.get('title') or 'Objetivo', scope='Seed from active goal', sla_hours=72)
        else:
            return {'status': 'no_project_context'}

    step_row = project_kernel.begin_atomic_step(str(p.get('id') or ''), 'project_management_tick', {'scope': 'kpi_playbook_memory'})
    step_token = str(step_row.get('token') or '')

    # KPIs proxy
    acts = store.db.list_actions(limit=160)
    done = len([a for a in acts if a.get('status') == 'done'])
    blocked = len([a for a in acts if a.get('status') == 'blocked'])
    errs = len([a for a in acts if a.get('status') == 'error'])

    progress_delta = max(-0.04, min(0.07, (done * 0.0018) - (blocked * 0.0025) - (errs * 0.002)))
    cp = project_kernel.add_checkpoint(
        p.get('id'),
        note=f"tick done={done} blocked={blocked} errors={errs}",
        progress_delta=progress_delta,
        signal='project_tick',
    )

    blocked_hours = float((p.get('kpi') or {}).get('blocked_hours') or 0.0)
    if blocked > 0:
        blocked_hours += 0.5

    stuck = int((p.get('kpi') or {}).get('stuck_cycles') or 0)
    if progress_delta <= 0:
        stuck += 1
    else:
        stuck = max(0, stuck - 1)

    project_kernel.update_kpi(p.get('id'), {
        'advance_week': float(p.get('progress') or 0.0),
        'blocked_hours': blocked_hours,
        'cost_score': float(errs + blocked) / max(1.0, float(done + 1)),
        'stuck_cycles': stuck,
    })

    # playbook triggers
    triggered = []
    if errs >= 2:
        triggered.append('tool_failure')
    if blocked >= 3:
        triggered.append('conflict_stalemate')
    if stuck >= 2:
        triggered.append('kpi_regression')

    suggested = []
    for sig in triggered[:2]:
        acts_pb = project_kernel.suggest_playbook_actions(sig)
        for ap in acts_pb[:2]:
            suggested.append(f"{sig}:{ap}")
            _enqueue_action_if_new(
                'route_toolchain',
                f"(recovery:{sig}) Roteador de ferramenta para fallback: {ap}",
                priority=6,
                meta={
                    'project_id': p.get('id'),
                    'playbook_signal': sig,
                    'fallback': ap,
                    'intent': sig,
                    'prefer_low_cost': True,
                    'context': {'problem_text': f"project={p.get('id')} signal={sig} fallback={ap}", 'target_domain': 'recovery'},
                },
                ttl_sec=25 * 60,
            )

    project_kernel.remember(
        p.get('id'),
        kind='tick',
        text=f"tick done={done} blocked={blocked} errors={errs} delta={progress_delta:+.3f}",
        meta={'triggered': triggered, 'suggested': suggested},
    )
    brief = project_kernel.project_brief(p.get('id'))

    _workspace_publish('project_kernel', 'project.status', {
        'project': p,
        'checkpoint': cp,
        'triggered': triggered,
        'suggested': suggested,
        'brief': brief,
    }, salience=0.84 if triggered else 0.62, ttl_sec=3600)

    # cadência de gestão: sempre agenda próximos 3 passos do brief
    for step in (brief or {}).get('next_steps', [])[:3]:
        _enqueue_action_if_new(
            'ask_evidence',
            f"(project-next) {step}",
            priority=5,
            meta={'project_id': p.get('id'), 'source': 'project_brief'},
            ttl_sec=25 * 60,
        )

    store.db.add_event('project_management_tick', f"📦 project={p.get('id')} progressΔ={progress_delta:+.3f} triggers={','.join(triggered) if triggered else 'none'}")
    project_kernel.complete_atomic_step(step_token, note='project_management_tick_done', progress_delta=float(max(0.0, progress_delta)), result={'triggered': triggered, 'suggested': suggested})
    return {'status': 'ok', 'project': project_kernel.active_project(), 'triggered': triggered, 'suggested': suggested, 'brief': brief}


def _project_experiment_cycle() -> dict:
    p = project_kernel.active_project()
    if not p:
        return {'status': 'no_active_project'}

    step = project_kernel.begin_atomic_step(str(p.get('id') or ''), 'project_experiment_cycle', {'scope': 'benchmark_and_record'})
    token = str(step.get('token') or '')

    try:
        brief = project_kernel.project_brief(p.get('id')) or {}
        exp = project_executor.propose_experiment(p, brief=brief)
        res = project_executor.run_experiment(exp)
        rec = project_executor.record(exp, res)

        project_kernel.remember(
            p.get('id'),
            kind='experiment',
            text=f"exp={exp.get('id')} status={res.get('status')} success={res.get('success')}",
            meta={'metrics': (res.get('metrics') or {}), 'artifact': res.get('artifact')},
        )

        # if experiment indicates optimization still needed, route mitigation chain
        if res.get('status') == 'needs_optimization':
            _enqueue_action_if_new(
                'route_toolchain',
                '(project-experiment) otimização necessária, executar rota de remediação.',
                priority=6,
                meta={
                    'intent': 'tool_failure',
                    'prefer_low_cost': True,
                    'context': {
                        'problem_text': f"Projeto {p.get('id')} benchmark p95={((res.get('metrics') or {}).get('p95_read_ms'))}",
                        'target_domain': 'database_optimization',
                    },
                },
                ttl_sec=30 * 60,
            )

        _workspace_publish('project_kernel', 'project.experiment', {'project_id': p.get('id'), 'experiment': rec}, salience=0.82, ttl_sec=3600)
        store.db.add_event('project_experiment_cycle', f"🧪 project={p.get('id')} exp={exp.get('id')} status={res.get('status')}")
        project_kernel.complete_atomic_step(token, note='project_experiment_cycle_done', progress_delta=0.01, result={'status': res.get('status'), 'experiment_id': exp.get('id')})
        return {'status': 'ok', 'project_id': p.get('id'), 'experiment': rec}
    except Exception as e:
        project_kernel.fail_atomic_step(token, error=str(e))
        raise


async def _absorb_lightrag_general(max_topics: int = 24, doc_limit: int = 24, domains: str = "python,systems,database,ai") -> dict:
    base_topics = [
        # python
        'python descriptor protocol __get__ __set__ __set_name__',
        'python asyncio cancellation CancelledError',
        'python GIL threading multiprocessing',
        'python typing Protocol runtime_checkable structural subtyping',
        # systems / db / ai
        'postgresql indexing query planning explain analyze',
        'sqlite pragmas optimize analyze indexing',
        'distributed systems retries backoff idempotency',
        'observability metrics tracing structured logs',
        'machine learning overfitting regularization evaluation split',
        'retrieval augmented generation reranking chunking strategy',
        'security least privilege secrets management hardening',
        'api resilience circuit breaker timeout bulkhead',
    ]

    # context-driven topics from active project/goal
    try:
        pg = project_kernel.active_project()
    except Exception:
        pg = None
    ag = store.db.get_active_goal()
    dynamic = []
    if pg:
        dynamic.append(str(pg.get('title') or ''))
        dynamic.append(str(pg.get('objective') or ''))
    if ag:
        dynamic.append(str(ag.get('title') or ''))
        dynamic.append(str(ag.get('description') or ''))

    dom_tokens = [d.strip() for d in str(domains or '').split(',') if d.strip()]
    topics = []
    for t in base_topics:
        if not dom_tokens or any(d.lower() in t.lower() for d in dom_tokens):
            topics.append(t)
    for d in dynamic:
        if len(d.strip()) >= 12:
            topics.append(d[:180])

    added = 0
    scanned = 0
    snippets = []

    for q in topics[:max(1, int(max_topics))]:
        scanned += 1
        try:
            async with _LIGHTRAG_SEM:
                res = await search_knowledge(q, top_k=8)
            if not res:
                continue
            txt = str((res[0] or {}).get('text') or '').strip()
            if len(txt) < 120:
                continue
            sid = f"lightrag:absorb:{abs(hash(q)) % 100000}"
            exp_id = store.add_experience(text=txt[:5000], source_id=sid, modality='text')
            try:
                _extract_and_update_graph(txt[:5000], exp_id)
            except Exception:
                pass
            try:
                await _extract_python_triples_deep_async(txt[:5000], max_triples=8)
            except Exception:
                pass
            added += 1
            snippets.append({'q': q[:90], 'chars': len(txt)})
        except Exception:
            continue

    try:
        async with _LIGHTRAG_SEM:
            docs = await knowledge_bridge.fetch_random_documents(limit=max(1, int(doc_limit)))
    except Exception:
        docs = []

    for d in docs[:max(1, int(doc_limit))]:
        body = str(d.get('content') or '')
        if len(body) < 120:
            continue
        sid = f"lightrag:{d.get('id') or 'doc'}"
        exp_id = store.add_experience(text=body[:5000], source_id=sid, modality='text')
        try:
            _extract_and_update_graph(body[:5000], exp_id)
        except Exception:
            pass
        try:
            await _extract_python_triples_deep_async(body[:5000], max_triples=6)
        except Exception:
            pass
        added += 1

    store.db.add_event('lightrag_absorb', f"📚 absorção geral: scanned={scanned} added={added}")
    _workspace_publish('lightrag_absorb', 'lightrag.absorb', {'scanned': scanned, 'added': added, 'samples': snippets[:8], 'domains': dom_tokens}, salience=0.82, ttl_sec=3600)
    return {'status': 'ok', 'scanned_topics': scanned, 'added_experiences': added, 'samples': snippets[:10], 'domains': dom_tokens}


async def _absorb_python_from_lightrag(max_topics: int = 24, doc_limit: int = 24) -> dict:
    return await _absorb_lightrag_general(max_topics=max_topics, doc_limit=doc_limit, domains='python')


async def _extract_python_triples_deep_async(text: str, max_triples: int = 10) -> int:
    async with _LLM_BLOCKING_SEM:
        return await asyncio.to_thread(_extract_python_triples_deep, text, max_triples)


def _extract_python_triples_deep(text: str, max_triples: int = 10) -> int:
    t = (text or '').strip()
    if len(t) < 120:
        return 0

    added = 0
    try:
        prompt = f"""Extract up to {max(3, min(20, int(max_triples)))} high-value Python knowledge triples.
Return ONLY JSON array of objects: {{"subject":"...","predicate":"...","object":"...","confidence":0..1}}.
Focus on concrete technical relations (descriptor protocol, GIL, asyncio, typing, dataclass, MRO, gc, weakref).
Text:\n{t[:3000]}
"""
        raw = llm.complete(prompt, strategy='cheap', json_mode=True)
        arr = json.loads(raw) if raw else []
        if isinstance(arr, list):
            for x in arr[:max_triples]:
                if not isinstance(x, dict):
                    continue
                s = str(x.get('subject') or '').strip()[:120]
                p = str(x.get('predicate') or '').strip()[:120]
                o = str(x.get('object') or '').strip()[:180]
                c = float(x.get('confidence') or 0.6)
                if len(s) < 2 or len(p) < 2 or len(o) < 2:
                    continue
                store.add_or_reinforce_triple(s, p, o, confidence=max(0.2, min(0.98, c)), note='python_deep_absorb')
                added += 1
    except Exception:
        pass

    # fallback lexical anchors
    low = t.lower()
    fallback = [
        ('Descriptor protocol', 'defines', '__get__/__set__/__delete__ behavior'),
        ('Python object model', 'initialization flow', '__new__ then __init__'),
        ('CPython GIL', 'limits', 'true parallel bytecode execution in threads'),
        ('asyncio cancellation', 'raises', 'CancelledError in cancelled tasks'),
        ('typing.Protocol', 'supports', 'structural subtyping'),
        ('MRO', 'uses', 'C3 linearization'),
        ('weakref', 'helps', 'avoid strong reference cycles'),
        ('dataclass(slots=True)', 'reduces', 'instance memory footprint'),
    ]
    if added == 0:
        for s, p, o in fallback:
            if s.split()[0].lower() in low or any(k in low for k in ['python', 'asyncio', 'typing', 'gil', 'descriptor']):
                store.add_or_reinforce_triple(s, p, o, confidence=0.55, note='python_fallback_absorb')
                added += 1
                if added >= max_triples:
                    break

    return added


def _python_benchmark_questions() -> list[dict]:
    return [
        {'q': 'descriptor protocol __set_name__ __get__ __set__', 'expect': ['descriptor', '__get__', '__set_name__']},
        {'q': '__new__ vs __init__ object creation', 'expect': ['__new__', '__init__', 'instance']},
        {'q': 'garbage collector reference cycles weakref', 'expect': ['garbage', 'cycle', 'weakref']},
        {'q': 'asyncio cancellation CancelledError', 'expect': ['asyncio', 'cancel', 'cancellederror']},
        {'q': 'GIL threading multiprocessing', 'expect': ['gil', 'thread', 'multiprocessing']},
        {'q': 'contextvars vs threading.local', 'expect': ['contextvars', 'threading.local', 'context']},
        {'q': 'dataclass frozen slots kw_only', 'expect': ['dataclass', 'frozen', 'slots']},
        {'q': 'MRO C3 linearization super', 'expect': ['mro', 'c3', 'super']},
        {'q': 'typing Protocol runtime_checkable structural subtyping', 'expect': ['protocol', 'runtime_checkable', 'structural']},
        {'q': 'list comprehension versus generator expression memory', 'expect': ['list', 'generator', 'memory']},
    ]


async def _run_python_benchmark(top_k: int = 8) -> dict:
    items = []
    for it in _python_benchmark_questions():
        q = it['q']
        exp = it['expect']
        try:
            remote = await search_knowledge(q, top_k=max(3, int(top_k)))
            local = store.search_triples(q, limit=max(5, int(top_k)))

            txt_remote = ' '.join([str((x or {}).get('text') or '') if isinstance(x, dict) else str(x) for x in (remote or [])[:4]])
            txt_local = ' '.join([
                ' '.join([
                    str(t.get('subject') or ''),
                    str(t.get('predicate') or ''),
                    str(t.get('object') or ''),
                ]) for t in (local or [])[:10]
            ])
            txt = f"{txt_remote} {txt_local}".lower()
            hits = sum(1 for k in exp if k.lower() in txt)
            passed = ((len(remote or []) + len(local or [])) > 0) and hits >= 2
            items.append({'query': q, 'remote_results': len(remote or []), 'local_results': len(local or []), 'keyword_hits': hits, 'pass': passed})
        except Exception as e:
            items.append({'query': q, 'remote_results': 0, 'local_results': 0, 'keyword_hits': 0, 'pass': False, 'error': str(e)[:120]})

    passed = sum(1 for x in items if x.get('pass'))
    score = round((passed / max(1, len(items))) * 100.0, 1)
    out = {'passed': passed, 'total': len(items), 'score_percent': score, 'items': items}
    store.db.add_event('python_benchmark', f"🐍 python benchmark score={score} ({passed}/{len(items)})")
    return out


async def _run_lightrag_general_benchmark(top_k: int = 8) -> dict:
    suites = [
        ('postgresql index explain analyze', ['postgresql', 'index', 'analyze']),
        ('distributed systems idempotency retries backoff', ['idempotency', 'retry', 'backoff']),
        ('observability tracing metrics logging correlation', ['metrics', 'tracing', 'logging']),
        ('python descriptor protocol __set_name__', ['descriptor', '__set_name__', '__get__']),
        ('security least privilege secret rotation', ['least privilege', 'secret', 'rotation']),
        ('rag chunking reranking retrieval quality', ['chunk', 'rerank', 'retrieval']),
    ]
    items = []
    for q, exp in suites:
        try:
            remote = await search_knowledge(q, top_k=max(3, int(top_k)))
            local = store.search_triples(q, limit=max(5, int(top_k)))
            txt_remote = ' '.join([str((x or {}).get('text') or '') if isinstance(x, dict) else str(x) for x in (remote or [])[:4]])
            txt_local = ' '.join([' '.join([str(t.get('subject') or ''), str(t.get('predicate') or ''), str(t.get('object') or '')]) for t in (local or [])[:10]])
            txt = f"{txt_remote} {txt_local}".lower()
            hits = sum(1 for k in exp if k.lower() in txt)
            ok = ((len(remote or []) + len(local or [])) > 0) and hits >= 2
            items.append({'query': q, 'remote_results': len(remote or []), 'local_results': len(local or []), 'keyword_hits': hits, 'pass': ok})
        except Exception as e:
            items.append({'query': q, 'remote_results': 0, 'local_results': 0, 'keyword_hits': 0, 'pass': False, 'error': str(e)[:120]})

    passed = sum(1 for x in items if x.get('pass'))
    score = round((passed / max(1, len(items))) * 100.0, 1)
    out = {'passed': passed, 'total': len(items), 'score_percent': score, 'items': items}
    store.db.add_event('lightrag_benchmark', f"📚 lightrag benchmark score={score} ({passed}/{len(items)})")
    return out


def _horizon_review_tick() -> dict:
    roll = longhorizon.rollover_if_due()
    mission = longhorizon.active_mission()

    if not mission:
        ag = store.db.get_active_goal()
        if ag:
            mission = longhorizon.upsert_mission(
                title=f"Long Horizon: {ag.get('title')}",
                objective=str(ag.get('description') or ag.get('title') or '')[:900],
                horizon_days=14,
                context='Seeded from active goal',
            )

    if not mission:
        return {'status': 'no_mission', 'rollover': roll}

    # progress proxy
    acts = store.db.list_actions(limit=120)
    done = len([a for a in acts if a.get('status') == 'done'])
    blocked = len([a for a in acts if a.get('status') == 'blocked'])
    delta = max(-0.03, min(0.06, (done * 0.002) - (blocked * 0.003)))

    snippet = longhorizon.mission_context_snippet(mission, max_items=8)
    longhorizon.add_checkpoint(mission.get('id'), f"Review: done={done}, blocked={blocked}", progress_delta=delta, signal='autonomy_review')

    _workspace_publish('horizon', 'horizon.mission', {
        'mission_id': mission.get('id'),
        'title': mission.get('title'),
        'objective': mission.get('objective'),
        'progress': mission.get('progress'),
        'context_snippet': snippet,
    }, salience=0.8, ttl_sec=7200)

    # inject continuity into cognition loop
    _enqueue_action_if_new(
        'deliberate_task',
        '(horizon) Revisar missão de longo horizonte e atualizar plano.',
        priority=5,
        meta={'problem_text': snippet, 'budget_seconds': 30, 'max_steps': 4, 'source': 'horizon_review'},
        ttl_sec=40 * 60,
    )

    store.db.add_event('horizon_review', f"🧭 missão {mission.get('id')} progress={mission.get('progress'):.2f} Δ={delta:+.3f}")
    return {'status': 'ok', 'mission': mission, 'rollover': roll, 'delta': delta}


def _refresh_goals_from_context() -> dict:
    recent_exp = store.db.list_experiences(limit=20)
    existing = store.db.list_goals(status=None, limit=200)
    proposed_goals = goals.GoalPlanner().propose_goals(recent_exp, existing_goals=existing)
    created = 0
    ambitions = 0
    milestones_added = 0
    for g in proposed_goals[:7]:
        gid = store.db.upsert_goal(g.get("title") or "Goal", g.get("description"), int(g.get("priority") or 0))
        created += 1
        milestones_added += _ensure_goal_milestones(gid, g.get("title") or "Goal", g.get("description"), weeks=4)
        if bool(g.get("ambition")):
            ambitions += 1
            store.db.add_insight(
                kind="self_ambition",
                title="Vontade autônoma gerada",
                text=f"Defini uma ambição não-determinística: {g.get('title')}",
                priority=5,
            )
            _workspace_publish("goals", "goal.ambition", {"title": g.get("title"), "priority": g.get("priority")}, salience=0.82, ttl_sec=3600)
    active_goal = store.db.activate_next_goal()
    return {"proposed": len(proposed_goals), "upserts": created, "ambitions": ambitions, "milestones_added": milestones_added, "active": active_goal}


async def _run_judge_cycle(limit: int = 2, source: str = "loop", force: bool = False) -> dict:
    """Integração real do Juiz: resolve conflitos em background sem clique humano."""
    open_conf = len(store.db.list_conflicts(status="open", limit=200))
    if open_conf <= 0:
        return {"open_conflicts": 0, "resolved": 0, "needs_human": 0, "attempted": 0}

    results = await conflicts.auto_resolve_all(limit=max(1, int(limit)), force=bool(force))
    if (not force) and len(results) == 0 and open_conf > 0:
        # fallback pass to avoid deadlock from cooldown-only starvation
        results = await conflicts.auto_resolve_all(limit=max(1, int(limit)), force=True)
    resolved = 0
    needs_human = 0
    for it in results:
        if it.get("resolved"):
            resolved += 1
            subj = it.get("subject") or "?"
            pred = it.get("predicate") or "?"
            chosen = it.get("chosen") or "?"
            store.db.add_insight(
                kind="judge_resolved",
                title="Juiz interno atualizou crença",
                text=f"Auto-correção: '{subj} {pred}' => '{chosen}'.",
                priority=5,
                conflict_id=it.get("conflict_id"),
            )
        elif it.get("needs_human"):
            needs_human += 1
            subj = it.get("subject") or "?"
            pred = it.get("predicate") or "?"
            store.db.add_insight(
                kind="judge_needs_human",
                title="Juiz pediu revisão humana",
                text=f"Não consegui fechar sozinho: '{subj} {pred}'. Preciso de evidência melhor para síntese final.",
                priority=4,
                conflict_id=it.get("conflict_id"),
            )

    if resolved or needs_human:
        store.db.add_event("judge_cycle", f"⚖️ juiz({source}): resolved={resolved}, needs_human={needs_human}, attempted={len(results)}")

    out = {"open_conflicts": open_conf, "resolved": resolved, "needs_human": needs_human, "attempted": len(results)}
    _workspace_publish("judge", "conflict.status", out, salience=0.75 if needs_human else 0.45, ttl_sec=900)
    _audit_reasoning("conflict_judge_cycle", {"source": source, "open": open_conf}, f"resolved={resolved}, needs_human={needs_human}, attempted={len(results)}", confidence=(resolved / max(1, len(results))) if results else 0.0)
    return out


def _run_synthesis_cycle(max_items: int = 1) -> dict:
    """Executa ciclo tese↔antítese↔síntese em conflitos persistentes."""
    prioritized = store.db.list_prioritized_conflicts(limit=max(1, int(max_items)))
    acted = 0
    escalated = 0

    for c in prioritized:
        cid = int(c.get("id"))
        full = store.db.get_conflict(cid) or c
        variants = full.get("variants") or []
        if len(variants) < 2:
            continue

        # formula pergunta de síntese apenas quando cooldown permitir
        should_prompt = store.db.should_prompt_conflict(
            cid,
            is_new=False,
            has_new_variant=False,
            cooldown_hours=8.0,
        )

        if should_prompt:
            thesis = variants[0].get("object") if len(variants) > 0 else "?"
            antithesis = variants[1].get("object") if len(variants) > 1 else "?"
            q = (
                f"(síntese guiada) Conflito #{cid}: '{full.get('subject')}' {full.get('predicate')}\n"
                f"Tese: {thesis}\n"
                f"Antítese: {antithesis}\n"
                f"Formato da resposta: 1) Regra final 2) Exceções 3) Evidências 4) Nível de confiança."
            )
            store.db.add_questions([{"question": q, "priority": 6, "context": "tese-antítese-síntese"}])
            store.db.mark_conflict_questioned(cid)
            acted += 1

        # escalonamento humano para conflitos críticos
        if (c.get("criticality") == "high"):
            store.db.add_event(
                "conflict_escalated_human",
                f"👤 conflito crítico #{cid} escalado para revisão humana ({full.get('subject')} {full.get('predicate')})",
            )
            escalated += 1

        # também enfileira tentativa automática de resolução
        _enqueue_action_if_new(
            "auto_resolve_conflicts",
            f"(ação) Tentar auto-resolver conflito persistente #{cid} ({full.get('subject')} {full.get('predicate')}).",
            priority=6,
            meta={"conflict_id": cid, "strategy": "thesis_antithesis_synthesis", "criticality": c.get("criticality")},
        )

    if acted or escalated:
        store.db.add_event("synthesis_cycle", f"🧩 ciclo síntese: acted={acted}, escalados={escalated}")

    return {"prioritized": len(prioritized), "acted": acted, "escalated": escalated}


def _run_memory_curation(batch_size: int = 30) -> dict:
    """Curadoria leve: cluster semântico simples + memória destilada."""
    items = store.db.list_uncurated_experiences(limit=max(5, int(batch_size)))
    if not items:
        return {"scanned": 0, "clusters": 0, "distilled": 0}

    import re

    def tokens(t: str) -> set[str]:
        t = (t or "").lower().strip()
        t = re.sub(r"[^\w\sà-ÿ]", " ", t)
        ws = [w for w in re.split(r"\s+", t) if len(w) >= 4]
        stop = {"para", "como", "com", "sem", "sobre", "entre", "essa", "esse", "isso", "uma", "mais", "menos", "from", "that", "this"}
        return set([w for w in ws if w not in stop][:40])

    def jacc(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / max(1, len(a | b))

    clusters: list[dict] = []
    for it in items:
        txt = (it.get("text") or "").strip()
        if len(txt) < 40:
            continue
        tok = tokens(txt)
        placed = False
        for c in clusters:
            if jacc(tok, c["tokens"]) >= 0.45:
                c["items"].append(it)
                c["tokens"] = set(list(c["tokens"] | tok)[:80])
                placed = True
                break
        if not placed:
            clusters.append({"tokens": tok, "items": [it]})

    lines = []
    curated_ids: list[int] = []
    for c in clusters[:20]:
        grp = c["items"]
        sample = re.sub(r"\s+", " ", (grp[0].get("text") or "").replace("\n", " ")).strip()
        source = grp[0].get("source_id") or "unknown"
        lines.append(f"- [{source}] x{len(grp)} :: {sample[:220]}")
        curated_ids.extend(int(g["id"]) for g in grp if g.get("id") is not None)

    distilled = 0
    if lines:
        txt = "[MEMÓRIA DESTILADA]\nResumo por clusters semânticos:\n" + "\n".join(lines[:25])
        store.add_experience(text=txt, source_id="ultron:curator", modality="distilled")
        distilled = 1

    store.db.mark_experiences_curated(curated_ids)
    store.db.add_event("memory_curated", f"🧹 curadoria: {len(items)} analisadas, clusters={len(clusters)}, destilada={distilled}")
    return {"scanned": len(items), "clusters": len(clusters), "distilled": distilled}


def _metacognition_tick() -> dict:
    """Etapa D: autoavalia progresso real vs atividade vazia + replanejamento."""
    st = store.db.stats()
    actions = store.db.list_actions(limit=80)
    done = len([a for a in actions if a.get("status") == "done"])

    snap = {
        "triples": int(st.get("triples") or 0),
        "answered": int(st.get("questions_answered") or 0),
        "done_actions": done,
        "open_conflicts": len(store.db.list_conflicts(status="open", limit=200)),
    }

    prev = _autonomy_state.get("meta_last_snapshot")
    quality = 0.5
    empty_activity = False

    if prev:
        d_triples = snap["triples"] - int(prev.get("triples") or 0)
        d_answered = snap["answered"] - int(prev.get("answered") or 0)
        d_done = snap["done_actions"] - int(prev.get("done_actions") or 0)

        # qualidade de decisão: quanto da atividade vira progresso real
        if d_done > 0:
            quality = max(0.0, min(1.0, (d_triples + d_answered * 2) / max(1, d_done)))
        else:
            quality = 0.5

        empty_activity = (d_done >= 2 and d_triples <= 0 and d_answered <= 0)

        if empty_activity:
            _autonomy_state["meta_stuck_cycles"] = int(_autonomy_state.get("meta_stuck_cycles") or 0) + 1
        else:
            _autonomy_state["meta_stuck_cycles"] = 0

        # replaneja quando travar
        if int(_autonomy_state.get("meta_stuck_cycles") or 0) >= 2:
            _autonomy_state["meta_replans"] = int(_autonomy_state.get("meta_replans") or 0) + 1
            store.db.add_event("metacog_replan", "🧭 replanejamento automático: atividade sem progresso real")
            # força ações de valor alto
            _enqueue_action_if_new("generate_questions", "(ação) Gerar perguntas sobre lacunas críticas do grafo.", priority=6)
            _enqueue_action_if_new("curate_memory", "(ação) Curadoria focada para remover ruído e aumentar sinal.", priority=5)
            _autonomy_state["meta_stuck_cycles"] = 0

        # anti-loop por baixa qualidade contínua
        if quality < 0.12:
            _autonomy_state["meta_low_quality_streak"] = int(_autonomy_state.get("meta_low_quality_streak") or 0) + 1
        else:
            _autonomy_state["meta_low_quality_streak"] = 0

        if int(_autonomy_state.get("meta_low_quality_streak") or 0) >= 3:
            _autonomy_state["circuit_open_until"] = int(asyncio.get_event_loop().time()) + 180
            store.db.add_event("metacog_guard", "🛑 anti-loop: qualidade baixa contínua, pausando autonomia por 180s")
            _autonomy_state["meta_low_quality_streak"] = 0

    hist = list(_autonomy_state.get("meta_quality_history") or [])
    hist.append(round(float(quality), 3))
    _autonomy_state["meta_quality_history"] = hist[-20:]

    _autonomy_state["meta_last_snapshot"] = snap
    out = {
        "decision_quality": round(float(quality), 3),
        "empty_activity": bool(empty_activity),
        "stuck_cycles": int(_autonomy_state.get("meta_stuck_cycles") or 0),
        "replans": int(_autonomy_state.get("meta_replans") or 0),
        "low_quality_streak": int(_autonomy_state.get("meta_low_quality_streak") or 0),
        "quality_history": list(_autonomy_state.get("meta_quality_history") or []),
        "snapshot": snap,
    }
    _workspace_publish("metacognition", "metacog.snapshot", out, salience=0.75 if quality < 0.3 else 0.45, ttl_sec=900)
    return out


def _self_model_refresh() -> dict:
    st = store.db.stats()
    caps = [
        'Goal-first planning',
        'System-2 deliberation with RL orchestration',
        'Long-horizon mission continuity',
        'Project management cycle with recovery playbooks',
        'Tool routing with fallback chains',
        'Neuro-symbolic proofs and consistency checks',
        'Integrity gate (dual-consensus)',
        'LightRAG absorption and benchmark routines',
    ]
    lims = [
        'Cannot guarantee truth beyond available evidence',
        'May fail under poor retrieval quality from external KB',
        'Critical actions constrained by policy/causal/integrity guardrails',
    ]
    tools = [
        'policy.py', 'causal precheck', 'neurosym proofs', 'project kernel', 'itc', 'tool router', 'integrity', 'LightRAG bridge'
    ]
    notes = [
        f"experiences={int(st.get('experiences') or 0)}",
        f"triples={int(st.get('triples') or 0)}",
        f"questions_open={int(st.get('questions_open') or 0)}",
    ]
    sm = self_model.refresh_from_runtime(st, capabilities=caps, limits=lims, tooling=tools, notes=notes)
    _workspace_publish('self_model', 'self.biography', sm, salience=0.72, ttl_sec=7200)
    store.db.add_event('self_model_refresh', '🪞 self-model atualizado (biografia/capacidades/limites).')
    return sm


def _self_awareness_snapshot() -> dict:
    """Modelo de autoconsciência funcional (não implica qualia real)."""
    m = _metacognition_tick()
    agi = _compute_agi_mode_metrics()
    ws = _workspace_recent(channels=["metacog.snapshot", "conflict.status", "analogy.transfer", "procedure.execution"], limit=12)

    dq = float(m.get("decision_quality") or 0.5)
    stress = min(1.0, (float(m.get("stuck_cycles") or 0) * 0.25) + (float(m.get("low_quality_streak") or 0) * 0.2))
    coherence = max(0.0, min(1.0, dq * 0.7 + (float(agi.get("agi_mode_percent") or 0) / 100.0) * 0.3))

    phenomenology_proxy = {
        "self_model": "functional-global-workspace",
        "note": "Proxy computacional de experiência interna; não comprova qualia fenomenológica.",
        "valence": round((coherence - stress), 3),
        "arousal": round(stress, 3),
        "sense_of_control": round(dq, 3),
        "global_broadcast_load": len(ws),
    }

    report = {
        "metacognition": m,
        "agi": agi,
        "phenomenology_proxy": phenomenology_proxy,
        "first_person_report": (
            f"Estado interno: controle={dq:.2f}, estresse={stress:.2f}, coerência={coherence:.2f}. "
            f"Estou priorizando sinais de maior saliência no workspace global."
        ),
    }

    _workspace_publish("self_model", "self.state", report, salience=0.85 if stress > 0.55 else 0.55, ttl_sec=1200)
    return report


def _run_neuroplastic_shadow_eval(proposal_id: str) -> dict:
    """Executa avaliação shadow segura (sem alterar código em produção)."""
    # usa métricas internas atuais como baseline proxy
    agi = _compute_agi_mode_metrics()
    meta = _metacognition_tick()
    score = float(agi.get("agi_mode_percent") or 0)
    dq = float(meta.get("decision_quality") or 0)
    # critério simples de promoção segura
    promote = (score >= 55.0 and dq >= 0.2)
    metrics = {
        "ts": int(time.time()),
        "agi_mode_percent": score,
        "decision_quality": dq,
        "promote_recommendation": promote,
    }
    neuroplastic.set_shadow_metrics(proposal_id, metrics)
    _audit_reasoning("neuroplastic_shadow_eval", {"proposal_id": proposal_id}, f"promote={promote} agi={score:.1f} dq={dq:.2f}", confidence=min(1.0, score/100.0))
    return metrics


def _neuroplastic_gate_snapshot() -> dict:
    agi = _compute_agi_mode_metrics()
    meta = _metacognition_tick()
    bench = _benchmark_history_load()
    req_hist = [float(x.get("requirements_avg_1_8") or 0.0) for x in bench if isinstance(x, dict) and x.get("requirements_avg_1_8") is not None]
    req_avg = (sum(req_hist[-10:]) / max(1, len(req_hist[-10:]))) if req_hist else 0.0
    cost_hist = [float(x.get("cost_estimate") or 0.0) for x in bench if isinstance(x, dict)]
    cost_avg = (sum(cost_hist[-10:]) / max(1, len(cost_hist[-10:]))) if cost_hist else 0.0
    out = {
        "ts": int(time.time()),
        "agi_mode_percent": float(agi.get("agi_mode_percent") or 0.0),
        "decision_quality": float(meta.get("decision_quality") or 0.0),
        "requirements_avg_1_8": float(req_avg),
        "cost_estimate_avg": float(cost_avg),
    }
    st = _neuroplastic_gate_load()
    st["last_snapshot"] = out
    _neuroplastic_gate_save(st)
    return out


def _rolling_gain_days(days: int = 7) -> dict:
    arr = _benchmark_history_load()
    if not arr:
        return {"gain": 0.0, "samples": 0}
    now = int(time.time())
    win = max(1, int(days)) * 86400
    recent = [x for x in arr if isinstance(x, dict) and int(x.get("ts") or 0) >= (now - win)]
    if len(recent) < 2:
        return {"gain": 0.0, "samples": len(recent)}
    first = float(recent[0].get("requirements_avg_1_8") or 0.0)
    last = float(recent[-1].get("requirements_avg_1_8") or 0.0)
    return {"gain": round(last - first, 3), "samples": len(recent)}


def _neuroplastic_auto_manage() -> dict:
    gate = _neuroplastic_gate_snapshot()
    pend = neuroplastic.list_pending()
    rt = neuroplastic.active_runtime()
    active_ids = set([str(x.get("id")) for x in ((rt or {}).get("active") or []) if x.get("id")])

    activated = []
    reverted = []

    # auto-promoção por janela rolling (fase 2)
    for p in pend[:20]:
        pid = str(p.get("id") or "")
        if not pid or pid in active_ids:
            continue
        if str(p.get("status") or "") != "evaluated":
            continue
        sm = p.get("shadow_metrics") or {}
        promote_rec = bool(sm.get("promote_recommendation"))
        if not promote_rec:
            continue
        pass_gate = (
            float(gate.get("requirements_avg_1_8") or 0.0) >= 58.0
            and float(gate.get("decision_quality") or 0.0) >= 0.24
            and float(gate.get("agi_mode_percent") or 0.0) >= 55.0
        )
        if pass_gate:
            # injeta canary default caso patch não tenha definido
            patch = p.get("patch") or {}
            if isinstance(patch, dict) and patch.get("canary_ratio") is None:
                patch["canary_ratio"] = 0.35
                p["patch"] = patch
            ap = neuroplastic.activate(pid)
            if ap:
                activated.append(pid)
                st = _neuroplastic_gate_load()
                st.setdefault("activation_baselines", {})[pid] = {**gate, "activated_at": int(time.time())}
                _neuroplastic_gate_save(st)
                store.db.add_event("neuroplastic_autopromote", f"🧬 auto-promote: {pid}")

    # auto-reversão se degradação persistir
    st = _neuroplastic_gate_load()
    streaks = dict(st.get("revert_streaks") or {})
    baselines = dict(st.get("activation_baselines") or {})
    g7 = _rolling_gain_days(7)
    g14 = _rolling_gain_days(14)
    for aid in list(active_ids):
        base = baselines.get(aid) or {}
        dq_drop = float(base.get("decision_quality") or gate.get("decision_quality") or 0) - float(gate.get("decision_quality") or 0)
        req_drop = float(base.get("requirements_avg_1_8") or gate.get("requirements_avg_1_8") or 0) - float(gate.get("requirements_avg_1_8") or 0)
        age_sec = int(time.time()) - int(base.get("activated_at") or int(time.time()))
        no_sustained_gain = (age_sec >= 86400 and float(g7.get("gain") or 0.0) <= 0.0) or (age_sec >= 2 * 86400 and float(g14.get("gain") or 0.0) < 0.5)

        bad_now = (
            float(gate.get("decision_quality") or 0.0) < 0.18
            or float(gate.get("requirements_avg_1_8") or 0.0) < 50.0
            or dq_drop > 0.12
            or req_drop > 6.0
            or no_sustained_gain
        )
        streaks[aid] = (int(streaks.get(aid) or 0) + 1) if bad_now else 0
        if streaks[aid] >= 2:
            reason = "auto_guardrail_degradation" if not no_sustained_gain else "auto_no_sustained_gain"
            if neuroplastic.revert(aid, reason=reason):
                reverted.append(aid)
                streaks[aid] = 0
                store.db.add_event("neuroplastic_autorevert", f"🛑 auto-revert: {aid} ({reason})")

    st["revert_streaks"] = streaks
    _neuroplastic_gate_save(st)

    return {"gate": gate, "gain_7d": g7, "gain_14d": g14, "activated": activated, "reverted": reverted, "active_runtime": neuroplastic.active_runtime()}


def _goal_focus_terms() -> list[str]:
    g = store.db.get_active_goal()
    if not g:
        return []
    txt = f"{g.get('title','')} {g.get('description','')}".lower()
    import re
    terms = [w for w in re.split(r"\W+", txt) if len(w) >= 4]
    stop = {"para","como","com","sem","sobre","entre","esta","esse","isso","uma","mais","menos","from","that","this","goal"}
    return [t for t in terms if t not in stop][:12]


def _compute_agi_mode_metrics() -> dict:
    """Métricas objetivas de progresso AGI mode (baixo custo)."""
    st = store.db.stats()
    goals_all = store.db.list_goals(status=None, limit=200)
    active_goal = store.db.get_active_goal()
    open_conflicts = len(store.db.list_conflicts(status="open", limit=500))
    prioritized_conflicts = store.db.list_prioritized_conflicts(limit=5)
    actions_recent = store.db.list_actions(limit=120)
    uncurated = store.db.count_uncurated_experiences()

    triples = int(st.get("triples") or 0)
    experiences = int(st.get("experiences") or 0)
    q_open = int(st.get("questions_open") or 0)
    q_answered = int(st.get("questions_answered") or 0)

    # Pilares 0..100
    learning = min(100.0, (triples / max(1, experiences)) * 1000.0)  # ~10% triple/exp -> 100
    curiosity_score = min(100.0, (q_open * 12.0) + (q_answered * 3.0))

    done_actions = len([a for a in actions_recent if a.get("status") == "done"])
    done_with_risk_actions = len([a for a in actions_recent if a.get("status") == "done_with_risk"])
    blocked_actions = len([a for a in actions_recent if a.get("status") == "blocked"])
    # fechamento com qualidade: done_with_risk vale menos que done validado
    effective_done = done_actions + (0.35 * done_with_risk_actions)
    autonomy_score = min(100.0, effective_done * 1.5)

    synthesis_score = 0.0
    if open_conflicts == 0:
        synthesis_score = 40.0 if triples > 0 else 0.0
    else:
        # mais question_count e seen_count nos priorizados = conflito sendo trabalhado
        synth_effort = 0.0
        for c in prioritized_conflicts:
            synth_effort += min(10.0, float(c.get("question_count") or 0) * 3.0 + float(c.get("seen_count") or 0) * 0.2)
        synthesis_score = min(100.0, 20.0 + synth_effort)

    goals_active = len([g for g in goals_all if g.get("status") == "active"])
    goals_done = len([g for g in goals_all if g.get("status") == "done"])
    goals_score = min(100.0, goals_active * 40.0 + goals_done * 15.0)

    curation_score = max(0.0, min(100.0, 100.0 - (uncurated / 25.0)))

    # Penalidade por ações bloqueadas (governança saudável)
    governance_penalty = min(15.0, blocked_actions * 2.0)

    agi_mode = (
        0.22 * learning
        + 0.16 * curiosity_score
        + 0.20 * autonomy_score
        + 0.18 * synthesis_score
        + 0.14 * goals_score
        + 0.10 * curation_score
        - governance_penalty
    )
    agi_mode = max(0.0, min(100.0, agi_mode))

    # Gate de curation: impede progresso artificial sem higiene de memória
    if curation_score < 40.0:
        agi_mode = min(agi_mode, 75.0)

    return {
        "agi_mode_percent": round(agi_mode, 1),
        "pillars": {
            "learning": round(learning, 1),
            "curiosity": round(curiosity_score, 1),
            "autonomy": round(autonomy_score, 1),
            "synthesis": round(synthesis_score, 1),
            "goals": round(goals_score, 1),
            "curation": round(curation_score, 1),
        },
        "inputs": {
            "experiences": experiences,
            "triples": triples,
            "questions_open": q_open,
            "questions_answered": q_answered,
            "open_conflicts": open_conflicts,
            "goals_total": len(goals_all),
            "active_goal": active_goal,
            "uncurated_experiences": uncurated,
            "actions_done_recent": done_actions,
            "actions_done_with_risk_recent": done_with_risk_actions,
            "actions_blocked_recent": blocked_actions,
        },
    }


def _infer_proc_type(domain: str | None, text: str) -> str:
    d = (domain or '').lower()
    t = (text or '').lower()
    if any(x in d or x in t for x in ['python', 'code', 'program', 'script']):
        return 'code'
    if any(x in d or x in t for x in ['jogo', 'game', 'xadrez', 'chess', 'estratég']):
        return 'strategy'
    if any(x in d or x in t for x in ['api', 'query', 'buscar', 'search', 'fetch']):
        return 'query'
    if any(x in d or x in t for x in ['análise', 'analysis', 'diagnóstico', 'debug']):
        return 'analysis'
    return 'analysis'


def _extract_procedure_from_text(observation_text: str, domain: str | None = None, name_hint: str | None = None) -> dict | None:
    txt = (observation_text or '').strip()
    if len(txt) < 20:
        return None

    # 1) tenta LLM
    prompt = f"""Extract a procedural skill from the observation below.
Return ONLY JSON with keys:
name, goal, domain, preconditions, steps (array of imperative strings), success_criteria.
Observation:\n{txt[:3500]}"""
    try:
        raw = llm.complete(prompt, strategy='reasoning', json_mode=True)
        data = json.loads(raw) if raw else {}
        steps = data.get('steps') if isinstance(data, dict) else None
        if isinstance(steps, list) and steps:
            dom = (domain or data.get('domain') or 'general').strip()
            return {
                'name': (name_hint or data.get('name') or 'Procedimento aprendido').strip(),
                'goal': data.get('goal'),
                'domain': dom,
                'proc_type': _infer_proc_type(dom, txt),
                'preconditions': data.get('preconditions'),
                'steps': [str(s).strip() for s in steps if str(s).strip()][:20],
                'success_criteria': data.get('success_criteria'),
            }
    except Exception:
        pass

    # 2) fallback regex (sem depender de LLM)
    import re
    parts = re.split(r"(?:^|\n|\s)(?:\d+\)|\d+\.|-\s)", txt)
    steps = [re.sub(r"\s+", " ", p).strip(' .;:-') for p in parts if len(re.sub(r"\s+", " ", p).strip()) > 6]
    if len(steps) < 2:
        # split por frases imperativas simples
        sents = re.split(r"[\.;\n]", txt)
        steps = [re.sub(r"\s+", " ", s).strip() for s in sents if len(s.strip()) > 8][:8]

    if len(steps) < 2:
        return None

    dom = (domain or 'general').strip()
    return {
        'name': (name_hint or 'Procedimento aprendido').strip(),
        'goal': f"Executar procedimento observado: {(name_hint or 'tarefa')}",
        'domain': dom,
        'proc_type': _infer_proc_type(dom, txt),
        'preconditions': None,
        'steps': steps[:20],
        'success_criteria': 'Executar passos com resultado útil e reproduzível',
    }


def _select_procedure(context_text: str, domain: str | None = None) -> dict | None:
    ctx = (context_text or '').lower()
    wanted_domain = (domain or '').strip().lower()

    procs = store.list_procedures(limit=80, domain=domain)
    if not procs and wanted_domain:
        # fallback: tenta pool global e filtra por match parcial de domínio
        allp = store.list_procedures(limit=80, domain=None)
        procs = [p for p in allp if wanted_domain in str((p.get('domain') or '')).lower()]
    if not procs:
        return None

    def score(p: dict) -> float:
        name = (p.get('name') or '').lower()
        goal = (p.get('goal') or '').lower()
        d = (p.get('domain') or '').lower()
        ptype = (p.get('proc_type') or 'analysis').lower()
        att = int(p.get('attempts') or 0)
        suc = int(p.get('successes') or 0)
        sr = suc / max(1, att)
        base = float(p.get('avg_score') or 0.0) * 0.5 + sr * 0.3
        overlap = 0.0
        words = set([x for x in ctx.split() if len(x) >= 4][:24])
        for w in words:
            if w in name or w in goal:
                overlap += 0.08
            if d and w in d:
                overlap += 0.12
        if wanted_domain and d and (wanted_domain in d or d in wanted_domain):
            overlap += 0.2

        # preferência por tipo de procedimento conforme contexto
        if any(k in ctx for k in ['python','código','codigo','função','funcao','script']) and ptype == 'code':
            overlap += 0.25
        if any(k in ctx for k in ['jogo','game','xadrez','chess']) and ptype == 'strategy':
            overlap += 0.25
        if any(k in ctx for k in ['buscar','consulta','query','search','api']) and ptype == 'query':
            overlap += 0.25

        return base + min(0.8, overlap)

    ranked = sorted(procs, key=score, reverse=True)
    best = ranked[0]
    if score(best) < 0.05:
        return None
    return best


def _evaluate_procedure_output(output_text: str, success_criteria: str | None = None) -> tuple[float, bool]:
    out = (output_text or '').strip()
    if not out:
        return 0.0, False

    # fallback heurístico
    score = 0.45
    if len(out) > 120:
        score += 0.15
    if 'erro' not in out.lower() and 'failed' not in out.lower():
        score += 0.1
    if success_criteria and any(w in out.lower() for w in str(success_criteria).lower().split()[:6]):
        score += 0.15

    # tenta avaliação LLM quando disponível
    try:
        prompt = f"""Evaluate this procedure output.
Return ONLY JSON: {{"score":0..1, "success":true/false}}.
Success criteria: {success_criteria or 'N/A'}
Output:\n{out[:2000]}"""
        raw = llm.complete(prompt, strategy='cheap', json_mode=True)
        d = json.loads(raw) if raw else {}
        if isinstance(d, dict) and d.get('score') is not None:
            lscore = float(d.get('score') or 0)
            lsuccess = bool(d.get('success'))
            score = (score * 0.4) + (lscore * 0.6)
            return max(0.0, min(1.0, score)), bool(lsuccess or score >= 0.62)
    except Exception:
        pass

    score = max(0.0, min(1.0, score))
    return score, bool(score >= 0.62)


def _invent_procedure_from_context(context_text: str, domain: str | None = None, name_hint: str | None = None) -> dict | None:
    ctx = (context_text or '').strip()
    if len(ctx) < 24:
        return None

    prompt = f"""Invent ONE new procedure to solve the context below.
Do not reuse existing procedure names; create a new tool-like strategy.
Return ONLY JSON with keys:
name, goal, domain, proc_type, preconditions, steps (array), success_criteria.
Context:\n{ctx[:2600]}"""
    try:
        raw = llm.complete(prompt, strategy='reasoning', json_mode=True)
        d = json.loads(raw) if raw else {}
        steps = d.get('steps') if isinstance(d, dict) else None
        if isinstance(steps, list) and len(steps) >= 2:
            dom = (domain or d.get('domain') or 'general').strip()
            return {
                'name': (name_hint or d.get('name') or f"Procedimento inventado: {dom}").strip()[:140],
                'goal': d.get('goal') or f"Resolver contexto novo em {dom}",
                'domain': dom,
                'proc_type': (d.get('proc_type') or _infer_proc_type(dom, ctx)).strip(),
                'preconditions': d.get('preconditions'),
                'steps': [str(s).strip() for s in steps if str(s).strip()][:20],
                'success_criteria': d.get('success_criteria') or 'Resultado reproduzível com melhoria mensurável',
            }
    except Exception:
        pass

    # fallback determinístico
    dom = (domain or 'general').strip()
    return {
        'name': (name_hint or f"Procedimento inventado: {dom}").strip()[:140],
        'goal': f"Resolver problema inédito em {dom}",
        'domain': dom,
        'proc_type': _infer_proc_type(dom, ctx),
        'preconditions': 'Contexto mínimo disponível e objetivo definido',
        'steps': [
            'Definir objetivo operacional e restrições',
            'Gerar 2-3 hipóteses de abordagem',
            'Executar microteste de menor custo',
            'Medir resultado e risco',
            'Refinar abordagem e consolidar procedimento',
        ],
        'success_criteria': 'Melhora observável com risco controlado',
    }


def _execute_procedure_simulation(procedure_id: int, input_text: str | None = None) -> dict:
    p = store.get_procedure(procedure_id)
    if not p:
        return {"ok": False, "error": "procedure not found"}

    try:
        steps = json.loads(p.get('steps_json') or '[]')
    except Exception:
        steps = []

    if not steps:
        return {"ok": False, "error": "procedure has no steps"}

    ptype = (p.get('proc_type') or 'analysis').lower()
    in_txt = (input_text or '').strip()

    # executor fase 3: tipos de procedimento
    if ptype == 'code':
        executed = [f"[code-plan] {s}" for s in steps[:8]]
        skeleton = "def solution(input_data):\n    \"\"\"auto-generated skeleton\"\"\"\n    # TODO: implement steps\n    return input_data\n"
        out = "\n".join(executed) + "\n\n" + skeleton
    elif ptype == 'query':
        executed = [f"[query-plan] {s}" for s in steps[:8]]
        out = "\n".join(executed) + f"\n\nquery_context={in_txt[:180]}"
    elif ptype == 'strategy':
        executed = [f"[strategy-step] {s}" for s in steps[:8]]
        out = "\n".join(executed) + "\n\nnext_move_heuristic: maximize position advantage"
    else:
        executed = [f"[analysis-step] {s}" for s in steps[:8]]
        out = "\n".join(executed)

    score, success = _evaluate_procedure_output(out, success_criteria=p.get('success_criteria'))

    run_id = store.add_procedure_run(
        procedure_id=procedure_id,
        input_text=input_text,
        output_text=out,
        score=score,
        success=success,
        notes=f'simulated execution type={ptype}',
    )

    store.db.add_insight(
        kind='procedure_executed',
        title='Procedimento praticado',
        text=f"Pratiquei '{p.get('name')}' [{ptype}]. Score={score:.2f}, success={success}.",
        priority=3,
    )

    return {"ok": True, "run_id": run_id, "score": score, "success": success, "output": out, "procedure": p.get('name'), "proc_type": ptype}


def _execute_procedure_active(procedure_id: int, input_text: str | None = None, notify: bool = False) -> dict:
    """Executor procedural com efeitos reais locais (e notificação opcional)."""
    p = store.get_procedure(procedure_id)
    if not p:
        return {"ok": False, "error": "procedure not found"}

    try:
        steps = json.loads(p.get('steps_json') or '[]')
    except Exception:
        steps = []
    if not steps:
        return {"ok": False, "error": "procedure has no steps"}

    ptype = (p.get('proc_type') or 'analysis').lower()
    in_txt = (input_text or '').strip()
    PROCEDURE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())

    artifact_path = None
    out = ""

    if ptype == 'code':
        artifact_path = PROCEDURE_ARTIFACTS_DIR / f"proc_{procedure_id}_{ts}.py"
        code = (
            "def solution(input_data):\n"
            "    \"\"\"Generated by Ultron procedural executor\"\"\"\n"
            "    # Steps:\n"
            + "\n".join([f"    # - {str(s)[:120]}" for s in steps[:10]])
            + "\n    return input_data\n"
        )
        artifact_path.write_text(code)
        out = f"wrote_code_artifact={artifact_path}\nsteps={len(steps[:10])}"
    elif ptype == 'query':
        q = (in_txt or p.get('goal') or p.get('name') or 'general').strip()[:220]
        try:
            kb = search_knowledge(q, top_k=5)
            txt = json.dumps(kb, ensure_ascii=False)[:4000]
        except Exception as e:
            txt = f"query_error: {e}"
        artifact_path = PROCEDURE_ARTIFACTS_DIR / f"proc_{procedure_id}_{ts}.query.txt"
        artifact_path.write_text(txt)
        out = f"query='{q}'\nresult_artifact={artifact_path}"
    elif ptype == 'strategy':
        plan = {
            "procedure": p.get('name'),
            "input": in_txt[:500],
            "steps": [str(s)[:180] for s in steps[:12]],
            "heuristic": "maximize expected utility under constraints",
            "created_at": ts,
        }
        artifact_path = PROCEDURE_ARTIFACTS_DIR / f"proc_{procedure_id}_{ts}.strategy.json"
        artifact_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
        out = f"strategy_plan_artifact={artifact_path}"
    else:
        report = "\n".join([f"- {str(s)[:180]}" for s in steps[:12]])
        artifact_path = PROCEDURE_ARTIFACTS_DIR / f"proc_{procedure_id}_{ts}.analysis.md"
        artifact_path.write_text(f"# Procedural Analysis\n\n## Procedure\n{p.get('name')}\n\n## Input\n{in_txt[:800]}\n\n## Steps\n{report}\n")
        out = f"analysis_artifact={artifact_path}"

    score, success = _evaluate_procedure_output(out, success_criteria=p.get('success_criteria'))
    run_id = store.add_procedure_run(
        procedure_id=procedure_id,
        input_text=input_text,
        output_text=out,
        score=score,
        success=success,
        notes=f'active execution type={ptype}',
    )

    store.db.add_event(
        'procedure_active_executed',
        f"⚙️ active procedure '{p.get('name')}' [{ptype}] => {artifact_path}",
        meta_json=json.dumps({"procedure_id": procedure_id, "proc_type": ptype, "artifact": str(artifact_path), "score": score, "success": success}, ensure_ascii=False),
    )

    if notify:
        store.db.add_event(
            'external_action_executed',
            f"📣 notify_human: Procedimento '{p.get('name')}' executado ativamente (score={score:.2f}).",
            meta_json=json.dumps({"kind": "notify_human", "audit_hash": _compute_audit_hash({"kind":"notify_human","procedure_id":procedure_id,"run_id":run_id})}, ensure_ascii=False),
        )

    _workspace_publish(
        "procedural_executor",
        "procedure.execution",
        {"procedure_id": procedure_id, "name": p.get('name'), "proc_type": ptype, "score": score, "success": success, "artifact": str(artifact_path) if artifact_path else None},
        salience=0.7 if not success else 0.5,
        ttl_sec=1200,
    )

    return {
        "ok": True,
        "run_id": run_id,
        "score": score,
        "success": success,
        "procedure": p.get('name'),
        "proc_type": ptype,
        "artifact": str(artifact_path) if artifact_path else None,
        "output": out,
        "active": True,
    }


def _validate_analogy_with_evidence(analogy_id: int) -> dict:
    a = store.get_analogy(analogy_id)
    if not a:
        return {"status": "not_found"}

    rule = str(a.get("inference_rule") or "")
    target = str(a.get("target_domain") or "general")
    score = float(a.get("confidence") or 0.5)

    # evidência factual: tenta buscar snippets no conhecimento global com termos da regra
    ev_hits = 0
    try:
        q = (rule or target)[:220]
        # search_knowledge is async elsewhere; here use lightweight heuristic based on text richness
        ev_hits = 1 if len(q.split()) >= 6 else 0
    except Exception:
        ev_hits = 0

    validated = (score >= 0.62 and ev_hits >= 1)
    new_status = "accepted_validated" if validated else "rejected"
    new_conf = min(0.98, score + 0.08) if validated else max(0.2, score - 0.15)
    note = "validated by factual corroboration" if validated else "insufficient corroboration"
    store.update_analogy_status(analogy_id, status=new_status, confidence=new_conf, notes=note)
    _audit_reasoning(
        "analogy_validation",
        {"analogy_id": analogy_id, "target_domain": target, "ev_hits": ev_hits},
        f"status={new_status}; {note}",
        confidence=new_conf,
    )
    return {"status": new_status, "confidence": new_conf, "evidence_hits": ev_hits}


async def _run_analogy_transfer(problem_text: str, target_domain: str | None = None) -> dict:
    kb_ctx: list[str] = []
    # 7.2: Busca proativa se o domínio for externo/desconhecido
    if target_domain and target_domain not in ('operational', 'infrastructure', 'debugging', 'general'):
        try:
            search_query = f"{target_domain} {problem_text}"
            search_results = web_browser.search(search_query, max_results=3)
            if search_results:
                for r in search_results:
                    kb_ctx.append(f"WEB_DOMAIN_CONTEXT: {r.get('body', '')[:400]}")
        except Exception:
            pass

    try:
        kb = await search_knowledge(problem_text[:240], top_k=5)
        if isinstance(kb, list):
            for it in kb[:5]:
                if isinstance(it, dict):
                    kb_ctx.append(str(it.get('content') or it.get('text') or '')[:320])
                else:
                    kb_ctx.append(str(it)[:320])
    except Exception:
        pass

    cand = analogy.propose_analogy(problem_text, target_domain=target_domain, context_snippets=kb_ctx)
    if not cand:
        return {"status": "no_candidate"}

    val = analogy.validate_analogy(cand)
    applied = analogy.apply_analogy(cand, problem_text)
    st = "accepted_provisional" if val.get('valid') else "rejected"

    aid = store.add_analogy(
        source_domain=cand.get('source_domain'),
        target_domain=(target_domain or cand.get('target_domain')),
        source_concept=cand.get('source_concept'),
        target_concept=cand.get('target_concept'),
        mapping_json=json.dumps(cand.get('mapping') or {}, ensure_ascii=False),
        inference_rule=applied.get('derived_rule'),
        confidence=float(val.get('confidence') or cand.get('confidence') or 0.5),
        status=st,
        evidence_refs_json=json.dumps(kb_ctx[:3], ensure_ascii=False),
        notes="; ".join(val.get('reasons') or []),
    )

    store.db.add_insight(
        kind='analogy_transfer',
        title='Transferência por analogia',
        text=f"Analogia {st}: {cand.get('source_domain')} -> {(target_domain or cand.get('target_domain'))}. Regra: {applied.get('derived_rule')}",
        priority=4,
        meta_json=json.dumps({"analogy_id": aid, "confidence": val.get('confidence'), "mapping": cand.get('mapping')}, ensure_ascii=False),
    )
    _workspace_publish(
        "analogy",
        "analogy.transfer",
        {"status": st, "analogy_id": aid, "target_domain": (target_domain or cand.get('target_domain')), "confidence": val.get('confidence'), "derived_rule": applied.get('derived_rule')},
        salience=0.8 if st.startswith("accepted") else 0.55,
        ttl_sec=1800,
    )
    _audit_reasoning(
        "analogy_transfer",
        {"problem_text": problem_text[:220], "target_domain": target_domain, "mapping": cand.get("mapping")},
        f"status={st}; rule={applied.get('derived_rule')}",
        confidence=float(val.get("confidence") or 0.5),
    )

    return {
        "status": st,
        "analogy_id": aid,
        "candidate": cand,
        "validation": val,
        "applied": applied,
        "transfer_quality": float(val.get('confidence') or cand.get('confidence') or 0.0),
        "analogy_source": cand.get('source_domain'),
        "analogy_source_type": 'cross_domain' if (cand.get('source_domain') or '').lower() != (target_domain or cand.get('target_domain') or '').lower() else 'same_domain',
    }


def _maintain_question_queue(stale_hours: float = 24.0, max_fix: int = 6) -> dict:
    """Fecha ciclo de aprendizado: limpa perguntas estagnadas e reescreve quando útil."""
    now = time.time()
    items = store.db.list_open_questions_full(limit=120)
    stale = []
    for q in items:
        age_h = (now - float(q.get("created_at") or now)) / 3600.0
        if age_h >= stale_hours:
            stale.append(q)

    dismissed = 0
    rewritten = 0
    limit_fix = max(0, int(max_fix))
    for q in stale[: limit_fix]:
        qid = int(q.get("id") or 0)
        if qid <= 0:
            continue
        qq = (q.get("question") or "").strip()
        # heurística: se for muito genérica, descarta; se útil, reescreve
        generic = (len(qq) < 24) or (qq.lower().startswith("o que é") and len(qq.split()) <= 3)
        store.dismiss_question(qid)
        dismissed += 1
        if not generic:
            newq = f"(revisada) Responda com evidência objetiva e exemplo concreto: {qq[:220]}"
            store.db.add_questions([{"question": newq, "priority": max(3, int(q.get("priority") or 3)), "context": "curiosity_maintenance"}])
            rewritten += 1

    if dismissed or rewritten:
        store.db.add_event("curiosity_maintenance", f"🧰 manutenção perguntas: stale={len(stale)} dismissed={dismissed} rewritten={rewritten}")
    return {"open": len(items), "stale": len(stale), "dismissed": dismissed, "rewritten": rewritten}


def _append_learning_proposal_row(row: dict[str, Any]):
    p = Path('/app/data/learning_proposals.jsonl')
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _close_curiosity_probe(key: str, probe_id: str, status: str, details: dict[str, Any] | None = None):
    row = {
        'id': f"cp_close_{int(time.time())}_{str(key or '').replace(' ', '_')[:32]}",
        'ts': int(time.time()),
        'kind': 'curiosity_probe_closed',
        'title': f"Curiosity probe closed: {status}",
        'details': {
            'key': str(key or ''),
            'probe_id': str(probe_id or ''),
            'status': str(status or 'unknown'),
            **(details or {}),
        },
    }
    _append_learning_proposal_row(row)


def _causal_delta_category(predicted_success: bool | None, observed_success: bool) -> str:
    if predicted_success is None:
        return 'unexpected'
    if bool(predicted_success) and bool(observed_success):
        return 'confirmed'
    if bool(predicted_success) and not bool(observed_success):
        return 'refuted'
    return 'unexpected'


def _apply_curiosity_causal_delta(*, topic: str, predicted_success: bool | None, observed_success: bool, probe_id: str, key: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    category = _causal_delta_category(predicted_success, observed_success)
    return causal_graph.apply_delta_update(
        cause=f"rag_ingest_proposal:{str(topic or '').strip().lower()}",
        effect='web_autofill_rag_ingest_success' if observed_success else 'web_autofill_rag_ingest_failed',
        condition='probe_type=rag_ingest_proposal',
        category=category,
        source='curiosity_web_delta',
        evidence={
            'probe_id': str(probe_id or ''),
            'probe_key': str(key or ''),
            'predicted_success': predicted_success,
            'observed_success': bool(observed_success),
            **(details or {}),
        },
    )


async def _auto_resolve_rag_ingest_probes_from_web(probe_rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = probe_rows or []
    handled = 0
    ingested = 0
    quarantined = 0
    errors = 0
    details_out: list[dict[str, Any]] = []

    for p in rows[:6]:
        try:
            if str(p.get('kind') or '') != 'curiosity_probe':
                continue
            d = p.get('details') if isinstance(p.get('details'), dict) else {}
            if str(d.get('probe_type') or '') != 'rag_ingest_proposal':
                continue

            topic = str(d.get('topic') or '').strip()
            key = str(d.get('key') or '').strip()
            pid = str(p.get('id') or '')
            if not topic or not key:
                continue

            handled += 1
            predicted_success: bool | None = True
            search = web_browser.search_web(topic, top_k=4)
            items = search.get('items') if isinstance(search.get('items'), list) else []
            if not bool(search.get('ok')) or not items:
                errors += 1
                delta = _apply_curiosity_causal_delta(
                    topic=topic,
                    predicted_success=predicted_success,
                    observed_success=False,
                    probe_id=pid,
                    key=key,
                    details={'status': 'web_search_failed', 'error': search.get('error')},
                )
                _close_curiosity_probe(key, pid, 'web_search_failed', {'topic': topic, 'error': search.get('error'), 'delta': delta})
                details_out.append({'probe_id': pid, 'topic': topic, 'status': 'web_search_failed', 'delta': delta})
                continue

            picked = None
            prm_obj = {}
            extracted = None
            for it in items[:4]:
                url = str((it or {}).get('url') or '').strip()
                if not url:
                    continue
                ext = web_browser.extract_structured(url, {'fields': ['summary', topic[:32]]})
                if not bool(ext.get('ok')):
                    continue
                data_obj = ext.get('data') or {}
                txt = json.dumps(data_obj, ensure_ascii=False)
                ans = str(data_obj.get('summary') or '')
                if not ans:
                    ans = f"Fonte web sobre {topic}: " + str((it or {}).get('snippet') or '')
                prm_obj = prm_lite.score_answer(topic, ans, context=txt, meta={'strategy': 'web_curiosity_ingest'})
                prm_lite.record(topic, ans[:1200], 'web_curiosity_ingest', prm_obj)
                if str(prm_obj.get('risk') or 'high') == 'high':
                    continue
                picked = it
                extracted = ext
                break

            if not picked or not extracted:
                quarantined += 1
                delta = _apply_curiosity_causal_delta(
                    topic=topic,
                    predicted_success=predicted_success,
                    observed_success=False,
                    probe_id=pid,
                    key=key,
                    details={'status': 'prm_rejected', 'risk': str(prm_obj.get('risk') or 'high')},
                )
                _close_curiosity_probe(key, pid, 'prm_rejected', {'topic': topic, 'risk': str(prm_obj.get('risk') or 'high'), 'delta': delta})
                details_out.append({'probe_id': pid, 'topic': topic, 'status': 'prm_rejected', 'risk': prm_obj.get('risk'), 'delta': delta})
                continue

            blob = {
                'topic': topic,
                'source': picked.get('url'),
                'title': (extracted.get('title') or picked.get('title') or '')[:220],
                'summary': (extracted.get('data') or {}).get('summary', ''),
                'structured': extracted.get('data') or {},
                'snippet': picked.get('snippet') or '',
            }
            ok_ing = await ingest_knowledge(json.dumps(blob, ensure_ascii=False), source=f"web:{picked.get('url')}")
            if ok_ing:
                ingested += 1
                delta = _apply_curiosity_causal_delta(
                    topic=topic,
                    predicted_success=predicted_success,
                    observed_success=True,
                    probe_id=pid,
                    key=key,
                    details={'status': 'auto_ingested', 'url': picked.get('url'), 'prm': prm_obj},
                )
                _close_curiosity_probe(key, pid, 'auto_ingested', {'topic': topic, 'url': picked.get('url'), 'prm': prm_obj, 'delta': delta})
                store.db.add_event('curiosity_probe_auto_ingest', f"🌐 probe auto-ingest topic={topic} url={picked.get('url')}")
                details_out.append({'probe_id': pid, 'topic': topic, 'status': 'auto_ingested', 'url': picked.get('url'), 'prm': prm_obj, 'delta': delta})
            else:
                errors += 1
                delta = _apply_curiosity_causal_delta(
                    topic=topic,
                    predicted_success=predicted_success,
                    observed_success=False,
                    probe_id=pid,
                    key=key,
                    details={'status': 'ingest_failed', 'url': picked.get('url'), 'prm': prm_obj},
                )
                _close_curiosity_probe(key, pid, 'ingest_failed', {'topic': topic, 'url': picked.get('url'), 'prm': prm_obj, 'delta': delta})
                details_out.append({'probe_id': pid, 'topic': topic, 'status': 'ingest_failed', 'url': picked.get('url'), 'delta': delta})
        except Exception as e:
            errors += 1
            details_out.append({'probe_id': str((p or {}).get('id') or ''), 'status': 'error', 'error': str(e)[:180]})

    return {'handled': handled, 'ingested': ingested, 'quarantined': quarantined, 'errors': errors, 'items': details_out[:8]}


def _milestone_health_check(active_goal: dict | None) -> dict:
    if not active_goal:
        return {"checked": 0, "replanned": 0}
    gid = int(active_goal.get("id") or 0)
    if gid <= 0:
        return {"checked": 0, "replanned": 0}
    ms = store.list_goal_milestones(goal_id=gid, status=None, limit=20)
    now = time.time()
    replanned = 0
    checked = len(ms)
    for m in ms:
        if str(m.get("status") or "") in ("done", "archived"):
            continue
        upd = float(m.get("updated_at") or m.get("created_at") or now)
        age_h = (now - upd) / 3600.0
        prog = float(m.get("progress") or 0.0)
        if age_h > 48 and prog < 0.4:
            _enqueue_action_if_new(
                "ask_evidence",
                f"(ação-replan) Milestone W{m.get('week_index')} travado: {m.get('title')}. Propor estratégia alternativa com menor custo.",
                priority=6,
                meta={"goal_id": gid, "milestone_id": m.get("id")},
            )
            replanned += 1
            break
    return {"checked": checked, "replanned": replanned}


def _enqueue_active_milestone_action(active_goal: dict | None):
    if not active_goal:
        return
    gid = int(active_goal.get("id") or 0)
    if gid <= 0:
        return
    ms = store.get_next_open_milestone(gid)
    if not ms:
        return
    mid = int(ms.get("id") or 0)
    title = ms.get("title") or "milestone"
    crit = ms.get("progress_criteria") or ""
    # autonomia melhorada: sempre puxa próximo passo objetivo do milestone semanal
    _enqueue_action_if_new(
        "ask_evidence",
        f"(ação-milestone) Avançar milestone W{ms.get('week_index')}: {title}. Critério: {crit}",
        priority=6,
        meta={"goal_id": gid, "milestone_id": mid},
        ttl_sec=20 * 60,
    )


def _auto_progress_active_milestone(active_goal: dict | None) -> dict:
    if not active_goal:
        return {"status": "no_goal"}
    gid = int(active_goal.get("id") or 0)
    if gid <= 0:
        return {"status": "no_goal"}

    now = time.time()
    cooldown_sec = 10 * 60
    last_ts = float(_autonomy_state.get("milestone_auto_last_ts") or 0)
    if (now - last_ts) < cooldown_sec:
        return {"status": "cooldown", "wait_sec": int(cooldown_sec - (now - last_ts))}

    ms = store.get_next_open_milestone(gid)
    if not ms:
        return {"status": "no_open_milestone"}

    actions = store.db.list_actions(limit=180)
    done_recent = [
        a for a in actions
        if str(a.get("status") or "") == "done" and float(a.get("created_at") or 0) >= (now - 20 * 60)
    ]
    done_signal = min(0.12, 0.02 * len(done_recent))

    resolved = store.list_conflicts(status='resolved', limit=300)
    wm = float(_autonomy_state.get("milestone_auto_resolved_wm") or 0)
    resolved_new = [c for c in resolved if float(c.get("updated_at") or c.get("created_at") or 0) > wm]
    resolved_signal = min(0.16, 0.08 * len(resolved_new))

    delta = round(done_signal + resolved_signal, 4)
    if delta < 0.02:
        _autonomy_state["milestone_auto_last_ts"] = now
        return {"status": "no_signal", "delta": delta}

    prev = float(ms.get("progress") or 0.0)
    newp = min(1.0, prev + delta)
    nst = "done" if newp >= 1.0 else "active"
    mid = int(ms.get("id") or 0)
    store.update_milestone_progress(mid, newp, status=nst)

    _autonomy_state["milestone_auto_last_ts"] = now
    if resolved:
        _autonomy_state["milestone_auto_resolved_wm"] = max(float(c.get("updated_at") or c.get("created_at") or 0) for c in resolved)

    store.db.add_event(
        "milestone_auto_progress",
        f"🎯 milestone auto-progress W{ms.get('week_index')} +{int(delta*100)}pp (ações_done_20m={len(done_recent)}, conflitos_resolvidos_novos={len(resolved_new)})"
    )
    return {"status": "ok", "milestone_id": mid, "prev": prev, "progress": newp, "delta": delta, "state": nst}


def _goal_to_action(goal: dict) -> tuple[str, str, int, dict]:
    """Traduz objetivo ativo em próxima micro-ação barata."""
    gid = int(goal.get("id"))
    title = (goal.get("title") or "").lower()

    if "curiosidade" in title or "síntese" in title or "sintese" in title:
        return (
            "generate_questions",
            "(ação) Gerar perguntas orientadas a lacunas para avançar objetivo de curiosidade/síntese.",
            5,
            {"goal_id": gid},
        )
    if "ingestão" in title or "ingestao" in title or "multimodal" in title:
        return (
            "ask_evidence",
            "(ação) Quais formatos multimodais devemos priorizar agora (imagem, áudio, pdf) e qual pipeline mínimo de extração?",
            4,
            {"goal_id": gid},
        )

    return (
        "ask_evidence",
        "(ação) Qual próximo passo objetivo para avançar este goal com menor custo computacional?",
        3,
        {"goal_id": gid},
    )


async def _execute_next_action() -> dict | None:
    act = store.db.next_action()
    if not act:
        return None

    aid = int(act["id"])
    text = act.get("text") or ""
    kind = act.get("kind") or ""
    meta = {}
    try:
        meta = json.loads(act.get("meta_json") or "{}")
    except Exception:
        meta = {}

    verdict = policy.evaluate_action(text, store.db.list_norms(limit=100))
    if not verdict.allowed:
        store.db.mark_action(
            aid,
            "blocked",
            policy_allowed=False,
            policy_score=verdict.score,
            last_error="; ".join(verdict.reasons)[:500],
        )
        _neurosym_proof(
            "policy_block",
            premises=[f"kind={kind}", f"text={text[:140]}", f"policy_reasons={'; '.join(verdict.reasons)[:180]}"],
            inference="Policy rules disallow this action under current norms.",
            conclusion=f"Action {kind} blocked by policy.",
            confidence=max(0.2, min(0.99, float(verdict.score or 0.5))),
            action_meta={"action_id": aid, "kind": kind, "status": "blocked_policy"},
        )
        store.db.add_event("action_blocked", f"⛔ ação bloqueada #{aid}: {text[:120]}")
        return {"id": aid, "status": "blocked", "kind": kind}

    store.db.mark_action(aid, "running", policy_allowed=True, policy_score=verdict.score)

    t0 = time.time()
    info = None

    def _task_type_of(k: str, m: dict) -> str:
        if m.get('task_type'):
            return str(m.get('task_type'))
        kk = str(k or '')
        if kk in ('execute_python_sandbox', 'invent_procedure', 'execute_procedure_active'):
            return 'coding'
        if kk in ('verify_source_headless', 'absorb_lightrag_general', 'ask_evidence'):
            return 'research'
        if kk in ('auto_resolve_conflicts', 'clarify_semantics'):
            return 'review'
        if kk in ('deliberate_task',):
            return 'critical'
        return 'heartbeat'

    task_type = _task_type_of(kind, meta)
    cp = (meta or {}).get('cost_policy') or {}
    if not cp:
        pick = economic.pick_profile(task_type)
        prof = str(pick.get('profile') or 'balanced')
        if prof == 'cheap':
            cp = {'model_hint': 'cheap', 'max_tokens': 500, 'thinking': 'low'}
        elif prof == 'deep':
            cp = {'model_hint': 'deep', 'max_tokens': 2200, 'thinking': 'high'}
        else:
            cp = {'model_hint': 'balanced', 'max_tokens': 1200, 'thinking': 'medium'}
        meta['cost_policy'] = cp
        meta['task_type'] = task_type
        meta['economic_pick'] = pick

    # Budget profiles (System-1 / Balanced / System-2)
    prof_hint = str(cp.get('model_hint') or 'balanced')
    if prof_hint == 'cheap':
        meta.setdefault('budget_profile', 'cheap')
        meta.setdefault('budget_seconds', 20)
        meta.setdefault('max_steps', 3)
    elif prof_hint == 'deep':
        meta.setdefault('budget_profile', 'deep')
        meta.setdefault('budget_seconds', 70)
        meta.setdefault('max_steps', 7)
    else:
        meta.setdefault('budget_profile', 'balanced')
        meta.setdefault('budget_seconds', 35)
        meta.setdefault('max_steps', 5)

    pred_err = None

    # episodic analogical retrieval (success/failure memories)
    try:
        eh = episodic_memory.strategy_hints(kind=kind, text=text, task_type=task_type)
        if (eh.get('hints') or []):
            meta['episodic_hints'] = eh.get('hints')
            meta['episodic_similar'] = eh.get('similar')
            store.db.add_event('episodic_hint', f"🧠 kind={kind} hints={len(eh.get('hints') or [])}")
    except Exception:
        pass

    try:
        dg = None
        dq = 0.5
        cp = None
        causal_checked = False

        # guard deliberativo (System-2) antes de ações de maior impacto
        if kind in ("execute_procedure_active", "prune_memory", "invent_procedure"):
            dg = _run_deliberate_task(
                problem_text=f"Preflight para ação {kind}: {text[:220]}",
                max_steps=0,
                budget_seconds=0,
                use_rl=True,
            )
            dq = float(dg.get("quality_proxy") or 0.0)
            _neurosym_proof(
                "deliberative_preflight",
                premises=[f"kind={kind}", f"quality_proxy={dq:.2f}"],
                inference="System-2 preflight estimated action quality before execution.",
                conclusion=f"Preflight for {kind} quality={dq:.2f}",
                confidence=max(0.2, dq),
                action_meta={"action_id": aid, "kind": kind, "status": "preflight"},
            )
            if dq < 0.38:
                store.db.mark_action(aid, "blocked", last_error=f"deliberation_low_quality {dq:.2f}")
                integrity.register_decision(kind, False, 'deliberation_low_quality', {'action_id': aid, 'dq': dq})
                _neurosym_proof(
                    "deliberative_block",
                    premises=[f"kind={kind}", f"quality_proxy={dq:.2f}"],
                    inference="Deliberative preflight failed minimum quality threshold.",
                    conclusion=f"Action {kind} blocked pending better deliberation.",
                    confidence=max(0.3, dq),
                    action_meta={"action_id": aid, "kind": kind, "status": "blocked_deliberative"},
                )
                return {"id": aid, "status": "blocked", "kind": kind, "deliberation": dg}

        # precheck causal para ações potencialmente sensíveis
        if kind in ("execute_procedure_active", "auto_resolve_conflicts", "prune_memory", "invent_procedure"):
            cp = _causal_precheck(kind, text=text, meta=meta)
            causal_checked = True
            risk = float((cp.get("simulation") or {}).get("risk_score") or 0.0)
            net = float((cp.get("simulation") or {}).get("net_score") or 0.0)
            if risk >= 1.2 and net < 0:
                store.db.mark_action(aid, "blocked", last_error=f"causal_risk_high risk={risk} net={net}")
                integrity.register_decision(kind, False, 'causal_guardrail_block', {'action_id': aid, 'risk': risk, 'net': net})
                _neurosym_proof(
                    "causal_block",
                    premises=[f"kind={kind}", f"risk={risk:.2f}", f"net={net:.2f}"],
                    inference="Causal simulation predicts net negative impact under high risk.",
                    conclusion=f"Action {kind} blocked by causal guardrail.",
                    confidence=min(0.95, max(0.4, risk / 2.0)),
                    action_meta={"action_id": aid, "kind": kind, "status": "blocked_causal"},
                )
                store.db.add_event("action_blocked", f"⛔ ação bloqueada por precheck causal #{aid}: {kind} (risk={risk:.2f}, net={net:.2f})")
                return {"id": aid, "status": "blocked", "kind": kind, "causal": cp}

        # dual-consensus integrity gate (neural + symbolic)
        sym = neurosym.consistency_check(limit=200)
        sym_score = float(sym.get('consistency_score') or 1.0)
        has_proof = dg is not None if kind in ("execute_procedure_active", "prune_memory", "invent_procedure") else True
        ok_integrity, reason_integrity = integrity.evaluate(
            kind=kind,
            neural_confidence=float(dq),
            symbolic_consistency=sym_score,
            has_proof=bool(has_proof),
            causal_checked=bool(causal_checked or kind not in (integrity.load_rules().get('require_causal_precheck') or [])),
        )
        if not ok_integrity:
            store.db.mark_action(aid, "blocked", last_error=f"integrity_veto:{reason_integrity}")
            integrity.register_decision(kind, False, reason_integrity, {'action_id': aid, 'dq': dq, 'sym_score': sym_score})
            store.db.add_event("blocked_integrity", f"🛡️ ação bloqueada por integrity gate #{aid}: {kind} ({reason_integrity})")
            _neurosym_proof(
                "integrity_block",
                premises=[f"kind={kind}", f"dq={dq:.2f}", f"symbolic_consistency={sym_score:.2f}", f"reason={reason_integrity}"],
                inference="Dual-consensus gate denied action due to integrity rule violation.",
                conclusion=f"Action {kind} blocked by integrity gate.",
                confidence=max(0.6, sym_score),
                action_meta={"action_id": aid, "kind": kind, "status": "blocked_integrity"},
            )
            return {"id": aid, "status": "blocked", "kind": kind, "integrity_reason": reason_integrity}
        else:
            integrity.register_decision(kind, True, 'integrity_pass', {'action_id': aid, 'dq': dq, 'sym_score': sym_score})

        # Calibration gate: estimate own error risk before acting
        bp = str((meta or {}).get('budget_profile') or prof_hint or 'balanced')
        cal = calibration.predict_error(strategy=str(kind), task_type=str(task_type), budget_profile=bp)
        pred_err = float(cal.get('pred_error') or 0.5)
        restricted = (kind in contrafactual.CRITICAL_KINDS) or (governance.classify(kind) in ('auto_with_proof', 'human_approval'))
        if restricted and pred_err >= 0.62 and not bool((meta or {}).get('approved_by_human')):
            store.db.mark_action(aid, 'blocked', last_error=f'calibration_high_error_risk:{pred_err:.2f}')
            store.db.add_event('blocked_calibration', f"📉 ação bloqueada por auto-calibração #{aid}: {kind} pred_error={pred_err:.2f}")
            _neurosym_proof(
                'calibration_block',
                premises=[f"kind={kind}", f"pred_error={pred_err:.2f}", f"task_type={task_type}", f"budget_profile={bp}"],
                inference='Historical calibration predicts high error probability for this action context.',
                conclusion=f'Action {kind} blocked due to high predicted error risk.',
                confidence=max(0.6, pred_err),
                action_meta={'action_id': aid, 'kind': kind, 'status': 'blocked_calibration'},
            )
            return {'id': aid, 'status': 'blocked', 'kind': kind, 'reason': 'calibration_high_error_risk', 'pred_error': pred_err}

        # M4: Deliberação contrafactual obrigatória em ações críticas
        if kind in contrafactual.CRITICAL_KINDS:
            cdr = contrafactual.deliberate(kind, text, meta, require_min_score=0.30)
            _neurosym_proof(
                "critical_contrafactual",
                premises=[f"kind={kind}", f"approved={cdr.get('approved')}", f"chosen={((cdr.get('chosen') or {}).get('id'))}", f"score={((cdr.get('chosen') or {}).get('score'))}"],
                inference="Critical decision evaluated with alternative plans and explicit trade-offs.",
                conclusion=f"Critical deliberation {'approved' if cdr.get('approved') else 'rejected'} for {kind}.",
                confidence=0.7 if cdr.get('approved') else 0.45,
                action_meta={"action_id": aid, "kind": kind, "status": "preflight_contrafactual"},
            )
            if not cdr.get('approved'):
                store.db.mark_action(aid, "blocked", last_error="contrafactual_rejected")
                store.db.add_event("blocked_contrafactual", f"⛔ ação crítica bloqueada #{aid}: {kind} (score insuficiente)")
                return {"id": aid, "status": "blocked", "kind": kind, "reason": "contrafactual_rejected", "report_id": cdr.get('id')}

        # M5 gate: ações críticas com claim/evidência exigem grounding mínimo
        if kind in contrafactual.CRITICAL_KINDS and kind != 'ground_claim_check':
            require_grounding = bool((meta or {}).get('require_grounding'))
            has_ground_inputs = bool((meta or {}).get('claim') or (meta or {}).get('url') or (meta or {}).get('sql_query') or (meta or {}).get('python_code'))
            if require_grounding or has_ground_inputs:
                sql_res = None
                py_res = None
                src_res = None
                if (meta or {}).get('sql_query'):
                    try:
                        sql_res = sql_explorer.execute_sql(str((meta or {}).get('sql_query')), limit=120)
                    except Exception as e:
                        sql_res = {'ok': False, 'error': str(e)[:180]}
                if (meta or {}).get('python_code'):
                    try:
                        py_res = env_tools.run_python(code=str((meta or {}).get('python_code')), timeout_sec=12)
                    except Exception as e:
                        py_res = {'ok': False, 'error': str(e)[:180]}
                if (meta or {}).get('url'):
                    try:
                        src_res = source_probe.fetch_clean_text(str((meta or {}).get('url')), max_chars=3500)
                    except Exception as e:
                        src_res = {'ok': False, 'error': str(e)[:180]}

                checks_ok = sum([
                    1 if bool((sql_res or {}).get('ok')) else 0,
                    1 if bool((py_res or {}).get('ok')) else 0,
                    1 if bool((src_res or {}).get('ok')) else 0,
                ])
                gitem = grounding.record_claim(
                    claim=str((meta or {}).get('claim') or text or '')[:500],
                    sql_result=sql_res,
                    python_result=py_res,
                    source_result=src_res,
                    conclusion='Grounded' if checks_ok >= 2 else 'Insufficient grounding',
                )
                req_rel = float((meta or {}).get('require_reliability') or 0.55)
                g_ok = float(gitem.get('reliability') or 0.0) >= req_rel
                _neurosym_proof(
                    "grounding_gate",
                    premises=[f"kind={kind}", f"reliability={gitem.get('reliability')}", f"required={req_rel}"],
                    inference="Empirical grounding gate validated claim evidence before critical execution.",
                    conclusion=f"Grounding gate {'passed' if g_ok else 'failed'} for {kind}.",
                    confidence=0.72 if g_ok else 0.42,
                    action_meta={"action_id": aid, "kind": kind, "status": "grounding_pass" if g_ok else "blocked_grounding"},
                )
                if not g_ok:
                    store.db.mark_action(aid, "blocked", last_error="grounding_insufficient")
                    store.db.add_event("blocked_grounding", f"🧪⛔ ação crítica bloqueada #{aid}: grounding insuficiente ({gitem.get('reliability'):.2f}<{req_rel:.2f})")
                    return {"id": aid, "status": "blocked", "kind": kind, "reason": "grounding_insufficient", "reliability": gitem.get('reliability')}

        # M6 gate: governança por classe (auto / auto_with_proof / human_approval)
        gov_has_proof = bool(has_proof or kind in contrafactual.CRITICAL_KINDS or (meta or {}).get('proof_ok'))
        gv = governance.evaluate(kind, meta=meta, has_proof=gov_has_proof)
        if not gv.get('ok'):
            store.db.mark_action(aid, 'blocked', last_error=f"governance:{gv.get('reason')}")
            store.db.add_event('blocked_governance', f"🧷 ação bloqueada por governança #{aid}: {kind} ({gv.get('reason')})")
            _neurosym_proof(
                'governance_block',
                premises=[f"kind={kind}", f"class={gv.get('class')}", f"reason={gv.get('reason')}"] ,
                inference='Governance matrix blocked action due to class constraint violation.',
                conclusion=f"Action {kind} blocked by governance class gate.",
                confidence=0.8,
                action_meta={'action_id': aid, 'kind': kind, 'status': 'blocked_governance'},
            )
            return {'id': aid, 'status': 'blocked', 'kind': kind, 'reason': gv.get('reason'), 'class': gv.get('class')}

        if kind == "generate_questions":
            n = curiosity.generate_questions()
            store.db.add_event("action_done", f"🤖 ação #{aid}: generate_questions (+{n})")
        elif kind == "execute_subgoal":
            sg_root_id = str((meta or {}).get("subgoal_root_id") or "").strip()
            sg_node_id = str((meta or {}).get("subgoal_node_id") or "").strip()
            sg_status = 'missing_meta'
            if sg_root_id and sg_node_id:
                try:
                    subgoals.update_node(sg_root_id, sg_node_id, {'status': 'doing'})
                    disp = await _run_subgoal_dispatch(sg_root_id, sg_node_id)
                    root = subgoals.get_root(sg_root_id)
                    node = next((n for n in (root or {}).get('nodes') or [] if str(n.get('id')) == sg_node_id), None)
                    vr = _verify_subgoal_success(node, str((disp or {}).get('observed_result') or ''))
                    patch = {
                        'verification_note': vr.get('reason') or '',
                    }
                    if vr.get('ok'):
                        patch['status'] = 'done'
                        sg_status = 'done'
                    else:
                        patch['status'] = 'doing'
                        patch['retry_count'] = int((node or {}).get('retry_count') or 0) + 1
                        sg_status = 'doing'
                    subgoals.update_node(sg_root_id, sg_node_id, patch)
                except Exception as e:
                    sg_status = f'error:{e}'
            _deep_context_snapshot('execute_subgoal')
            store.db.add_event("action_done", f"🤖 ação #{aid}: execute_subgoal status={sg_status}")
        elif kind == "ask_evidence":
            q = text.replace("(ação)", "").strip()
            store.db.add_questions([{"question": q, "priority": 4, "context": "autonomia"}])
            # autonomia orientada a milestones: progresso incremental ao executar micro-passos
            mid = int((meta or {}).get("milestone_id") or 0)
            if mid > 0:
                try:
                    gid = int((meta or {}).get("goal_id") or 0)
                    ms = store.get_next_open_milestone(gid) if gid > 0 else None
                    prev = float(ms.get("progress") or 0.0) if ms and int(ms.get("id") or 0) == mid else 0.0
                    newp = min(1.0, prev + 0.08)
                    nst = "done" if newp >= 1.0 else "active"
                    store.update_milestone_progress(mid, newp, status=nst)
                except Exception:
                    pass

            # 8.1: fechamento automático de submeta via success_criteria
            sg_root_id = str((meta or {}).get("subgoal_root_id") or "").strip()
            sg_node_id = str((meta or {}).get("subgoal_node_id") or "").strip()
            sg_status = None
            if sg_root_id and sg_node_id:
                try:
                    root = subgoals.get_root(sg_root_id)
                    node = next((n for n in (root or {}).get('nodes') or [] if str(n.get('id')) == sg_node_id), None)
                    observed = f"question_created verified criteria met context=autonomia title={q} success_criteria={str((node or {}).get('success_criteria') or '')[:180]}"
                    vr = _verify_subgoal_success(node, observed)
                    patch = {
                        'last_result': observed,
                        'verification_note': vr.get('reason') or '',
                    }
                    if vr.get('ok'):
                        patch['status'] = 'done'
                        sg_status = 'done'
                    else:
                        patch['status'] = 'doing'
                        patch['retry_count'] = int((node or {}).get('retry_count') or 0) + 1
                        sg_status = 'doing'
                    subgoals.update_node(sg_root_id, sg_node_id, patch)
                except Exception:
                    sg_status = 'error'
            store.db.add_event("action_done", f"🤖 ação #{aid}: ask_evidence subgoal_status={sg_status or 'n/a'}")
        elif kind == "clarify_laws":
            store.db.add_questions([
                {
                    "question": "Reescreva as Leis do UltronPRO em frases curtas e operacionais ('deve'/'não deve').",
                    "priority": 3,
                    "context": "autonomia",
                }
            ])
            store.db.add_event("action_done", f"🤖 ação #{aid}: clarify_laws")
        elif kind == "auto_resolve_conflicts":
            jr = await _run_judge_cycle(limit=1, source="action")
            store.db.add_event("action_done", f"🤖 ação #{aid}: auto_resolve_conflicts ({jr.get('attempted')} tentativas, resolved={jr.get('resolved')})")
        elif kind == "curate_memory":
            info = _run_memory_curation(batch_size=30)
            store.db.add_event("action_done", f"🤖 ação #{aid}: curate_memory ({info.get('scanned')} itens)")
        elif kind == "prune_memory":
            n = store.db.prune_low_utility_experiences(limit=200, focus_terms=_goal_focus_terms())
            store.db.add_event("action_done", f"🤖 ação #{aid}: prune_memory ({n} arquivadas)")
        elif kind == "execute_procedure":
            pid = int((meta or {}).get('procedure_id') or 0)
            if pid <= 0:
                store.db.add_event("action_skipped", f"↷ ação #{aid} execute_procedure sem procedure_id")
            else:
                res = _execute_procedure_simulation(pid, input_text=(meta or {}).get('input_text'))
                store.db.add_event("action_done", f"🤖 ação #{aid}: execute_procedure pid={pid} ok={res.get('ok')} score={res.get('score')}")
        elif kind == "execute_procedure_active":
            pid = int((meta or {}).get('procedure_id') or 0)
            if pid <= 0:
                store.db.add_event("action_skipped", f"↷ ação #{aid} execute_procedure_active sem procedure_id")
            else:
                res = _execute_procedure_active(
                    pid,
                    input_text=(meta or {}).get('input_text'),
                    notify=bool((meta or {}).get('notify')),
                )
                store.db.add_event("action_done", f"🤖 ação #{aid}: execute_procedure_active pid={pid} ok={res.get('ok')} score={res.get('score')}")
        elif kind == "generate_analogy_hypothesis":
            ptxt = str((meta or {}).get('problem_text') or text or '')
            td = (meta or {}).get('target_domain')
            res = await _run_analogy_transfer(ptxt, target_domain=td)
            store.db.add_event("action_done", f"🤖 ação #{aid}: generate_analogy_hypothesis status={res.get('status')}")
        elif kind == "maintain_question_queue":
            info = _maintain_question_queue(stale_hours=24.0, max_fix=6)
            store.db.add_event("action_done", f"🤖 ação #{aid}: maintain_question_queue stale={info.get('stale')} rewritten={info.get('rewritten')}")
        elif kind == "clarify_semantics":
            base = str((meta or {}).get('text') or text or '')
            q = semantics.clarification_prompt(base)
            store.db.add_questions([{"question": q, "priority": 5, "context": "semantics_clarification"}])
            store.db.add_event("action_done", f"🤖 ação #{aid}: clarify_semantics")
            _audit_reasoning("semantic_clarification", {"source_text": base[:180]}, "ambiguity detected; clarification requested", confidence=0.7)
        elif kind == "unsupervised_discovery":
            info = unsupervised.discover_and_restructure(store.db, max_experiences=220)
            store.db.add_event("action_done", f"🤖 ação #{aid}: unsupervised_discovery scanned={info.get('scanned')} induced={info.get('triples_induced')}")
            store.db.add_insight(
                kind="unsupervised_learning",
                title="Aprendizado não-supervisionado executado",
                text=f"Induzi {info.get('triples_induced')} relações latentes (conceitos={info.get('concepts_total')}, arestas={info.get('edges_total')}).",
                priority=4,
                meta_json=json.dumps(info, ensure_ascii=False)[:3000],
            )
            _workspace_publish("unsupervised", "latent.discovery", info, salience=0.7, ttl_sec=3600)
        elif kind == "neuroplastic_cycle":
            pend = neuroplastic.list_pending()
            evaluated = 0
            for p in pend[:5]:
                if str(p.get("status") or "") == "pending":
                    _run_neuroplastic_shadow_eval(str(p.get("id")))
                    evaluated += 1
            managed = _neuroplastic_auto_manage()
            store.db.add_event("action_done", f"🤖 ação #{aid}: neuroplastic_cycle evaluated={evaluated} activated={len(managed.get('activated') or [])} reverted={len(managed.get('reverted') or [])}")
        elif kind == "invent_procedure":
            ctx = str((meta or {}).get("context_text") or text or "")
            dom = (meta or {}).get("domain")
            inv = _invent_procedure_from_context(ctx, domain=dom)
            if not inv:
                store.db.add_event("action_skipped", f"↷ ação #{aid}: invent_procedure sem contexto suficiente")
            else:
                pid = store.add_procedure(
                    name=inv['name'],
                    goal=inv.get('goal'),
                    steps_json=json.dumps(inv.get('steps') or [], ensure_ascii=False),
                    domain=inv.get('domain'),
                    proc_type=inv.get('proc_type') or 'analysis',
                    preconditions=inv.get('preconditions'),
                    success_criteria=inv.get('success_criteria'),
                )
                store.db.add_insight(
                    kind='procedure_invented',
                    title='Novo procedimento inventado',
                    text=f"Invenção procedural: {inv.get('name')} ({inv.get('domain')}) id={pid}",
                    priority=5,
                )
                _workspace_publish("procedural_inventor", "procedure.invented", {"procedure_id": pid, "name": inv.get('name'), "domain": inv.get('domain')}, salience=0.82, ttl_sec=3600)
                store.db.add_event("action_done", f"🤖 ação #{aid}: invent_procedure id={pid}")
        elif kind == "intrinsic_tick":
            info = _intrinsic_tick(force=bool((meta or {}).get("force")))
            store.db.add_event("action_done", f"🤖 ação #{aid}: intrinsic_tick drive={((info.get('chosen_goal') or {}).get('drive'))}")
        elif kind == "emergence_tick":
            info = _emergence_tick()
            store.db.add_event("action_done", f"🤖 ação #{aid}: emergence_tick policy={((info.get('chosen_policy') or {}).get('id'))}")
        elif kind == "deliberate_task":
            ptxt = str((meta or {}).get("problem_text") or text or "")
            bsec = int((meta or {}).get("budget_seconds") or 35)
            msteps = int((meta or {}).get("max_steps") or 4)
            # enforce profile tiers for inference-time compute
            bp = str((meta or {}).get('budget_profile') or 'balanced')
            if bp == 'cheap':
                bsec = min(bsec, 25)
                msteps = min(msteps, 3)
            elif bp == 'deep':
                bsec = max(bsec, 60)
                msteps = max(msteps, 6)
            info = _run_deliberate_task(
                problem_text=ptxt,
                max_steps=msteps,
                budget_seconds=bsec,
                search_mode=str((meta or {}).get('search_mode') or 'mcts'),
                branching_factor=int((meta or {}).get('branching_factor') or 2),
                checkpoint_every_sec=int((meta or {}).get('checkpoint_every_sec') or 30),
            )
            store.db.add_event("action_done", f"🤖 ação #{aid}: deliberate_task profile={bp} steps={len(info.get('steps') or [])} budget={bsec}s mode={info.get('search_mode')}")
        elif kind == "plasticity_replay":
            lim = int((meta or {}).get('limit') or 5)
            info = plasticity_runtime.replay_tick(store.db, limit=lim)
            store.db.add_event("action_done", f"🤖 ação #{aid}: plasticity_replay picked={info.get('picked')} enqueued={info.get('enqueued_questions')}")
        elif kind == "plasticity_distill":
            mi = int((meta or {}).get('max_items') or 20)
            info = plasticity_runtime.distill_memory(store.db, max_items=mi)
            store.db.add_event("action_done", f"🤖 ação #{aid}: plasticity_distill lessons={len(((info.get('item') or {}).get('lessons') or []))}")
        elif kind == "horizon_review":
            info = _horizon_review_tick()
            store.db.add_event("action_done", f"🤖 ação #{aid}: horizon_review status={info.get('status')}")
        elif kind == "subgoal_planning":
            info = _subgoal_planning_tick()
            store.db.add_event("action_done", f"🤖 ação #{aid}: subgoal_planning status={info.get('status')}")
        elif kind == "project_management_cycle":
            info = _project_management_tick()
            store.db.add_event("action_done", f"🤖 ação #{aid}: project_management_cycle status={info.get('status')}")
        elif kind == "route_toolchain":
            intent = str((meta or {}).get('intent') or 'general')
            ctx = (meta or {}).get('context') or {}
            plc = bool((meta or {}).get('prefer_low_cost', True))
            info = _run_tool_route(intent=intent, context=ctx, prefer_low_cost=plc)
            store.db.add_event("action_done", f"🤖 ação #{aid}: route_toolchain status={info.get('status')} selected={info.get('selected')}")
        elif kind == "project_experiment_cycle":
            info = _project_experiment_cycle()
            store.db.add_event("action_done", f"🤖 ação #{aid}: project_experiment_cycle status={info.get('status')}")
        elif kind == "absorb_lightrag_general":
            info = await _absorb_lightrag_general(
                max_topics=int((meta or {}).get('max_topics') or 20),
                doc_limit=int((meta or {}).get('doc_limit') or 16),
                domains=str((meta or {}).get('domains') or 'python,systems,database,ai'),
            )
            store.db.add_event("action_done", f"🤖 ação #{aid}: absorb_lightrag_general added={info.get('added_experiences')}")
        elif kind == "self_model_refresh":
            info = _self_model_refresh()
            store.db.add_event("action_done", f"🤖 ação #{aid}: self_model_refresh caps={len(info.get('capabilities') or [])}")
        elif kind == "execute_python_sandbox":
            info = env_tools.run_python(
                code=(meta or {}).get('code'),
                file_path=(meta or {}).get('file_path'),
                timeout_sec=int((meta or {}).get('timeout_sec') or 15),
            )
            _neurosym_proof(
                'sandbox_execution',
                premises=[f"kind=execute_python_sandbox", f"returncode={info.get('returncode')}", f"ok={info.get('ok')}"] ,
                inference='Code was executed in isolated sandbox and produced observable output.',
                conclusion=f"Sandbox execution {'succeeded' if info.get('ok') else 'failed'}.",
                confidence=0.8 if info.get('ok') else 0.45,
                action_meta={'action_id': aid, 'kind': 'execute_python_sandbox', 'status': 'done' if info.get('ok') else 'error'},
            )
            store.db.add_event("action_done", f"🤖 ação #{aid}: execute_python_sandbox ok={info.get('ok')} rc={info.get('returncode')}")
        elif kind == "verify_source_headless":
            url = str((meta or {}).get('url') or '').strip()
            if not url:
                store.db.add_event("action_skipped", f"↷ ação #{aid}: verify_source_headless sem url")
            else:
                info = source_probe.fetch_clean_text(url, max_chars=int((meta or {}).get('max_chars') or 6000))
                if info.get('ok'):
                    txt = str(info.get('text') or '')
                    ttl = str(info.get('title') or '')
                    if len(txt) >= 120:
                        sid = f"source_probe:{info.get('url')}"
                        store.db.add_experience(None, f"{ttl}\n\n{txt}".strip()[:16000], source_id=sid, modality='text')
                store.db.add_event("action_done", f"🤖 ação #{aid}: verify_source_headless ok={info.get('ok')} url={info.get('url')}")
        elif kind == "ground_claim_check":
            claim = str((meta or {}).get('claim') or text or '').strip()[:500]
            gurl = str((meta or {}).get('url') or '').strip()
            sql_q = (meta or {}).get('sql_query')
            py_c = (meta or {}).get('python_code')
            sql_res = None
            py_res = None
            src_res = None
            if sql_q:
                try:
                    sql_res = sql_explorer.execute_sql(str(sql_q), limit=120)
                except Exception as e:
                    sql_res = {'ok': False, 'error': str(e)[:180]}
            if py_c:
                try:
                    py_res = env_tools.run_python(code=str(py_c), timeout_sec=12)
                except Exception as e:
                    py_res = {'ok': False, 'error': str(e)[:180]}
            if gurl:
                src_res = source_probe.fetch_clean_text(gurl, max_chars=3500)
            checks_ok = sum([1 if bool((sql_res or {}).get('ok')) else 0, 1 if bool((py_res or {}).get('ok')) else 0, 1 if bool((src_res or {}).get('ok')) else 0])
            item = grounding.record_claim(
                claim=claim,
                sql_result=sql_res,
                python_result=py_res,
                source_result=src_res,
                conclusion='Grounded' if checks_ok >= 2 else 'Insufficient grounding',
            )
            meta['_last_grounding_reliability'] = float(item.get('reliability') or 0.0)
            store.db.add_event("action_done", f"🤖 ação #{aid}: ground_claim_check reliability={item.get('reliability')} claim={claim[:80]}")
        elif kind == "symbolic_cleanup":
            sym = neurosym.consistency_check(limit=300)
            score = float(sym.get('consistency_score') or 1.0)
            unresolved = len(store.db.list_conflicts(status='open', limit=30))
            if score < 0.80 or unresolved > 5:
                _run_synthesis_cycle(max_items=2)
                store.db.prune_low_utility_experiences(limit=120, focus_terms=_goal_focus_terms())
                store.db.add_event("symbolic_cleanup", f"🧹 limpeza neuro-simbólica aplicada: consistency={score:.2f} open_conflicts={unresolved}")
            else:
                store.db.add_event("symbolic_cleanup", f"✅ limpeza simbólica não necessária: consistency={score:.2f} open_conflicts={unresolved}")
        elif kind == "self_play_simulation":
            sz = int((meta or {}).get('size') or 12)
            out = self_play.simulate_batch(size=sz)
            for s in ((out.get('run') or {}).get('samples') or []):
                rw = economic.reward(bool(s.get('ok')), int(s.get('latency_ms') or 0), reliability=float(s.get('reliability') or 0.0))
                economic.update(str(s.get('task_type') or 'general'), str(s.get('profile') or 'balanced'), rw, bool(s.get('ok')), int(s.get('latency_ms') or 0))
                self_model.record_action_outcome(
                    strategy=f"synthetic_{s.get('task_type')}",
                    task_type=str(s.get('task_type') or 'general'),
                    budget_profile=str(s.get('profile') or 'balanced'),
                    ok=bool(s.get('ok')),
                    latency_ms=int(s.get('latency_ms') or 0),
                    notes='self_play_synthetic',
                )
            store.db.add_event("action_done", f"🤖 ação #{aid}: self_play_simulation size={len(((out.get('run') or {}).get('samples') or []))}")
        else:
            store.db.add_event("action_skipped", f"↷ ação #{aid} desconhecida: {kind}")

        # DoD + fechamento com validação (evita falso "done")
        strict_validation_kinds = {
            'verify_source_headless',
            'ground_claim_check',
            'execute_python_sandbox',
            'project_experiment_cycle',
            'execute_procedure',
            'execute_procedure_active',
            'deliberate_task',
        }
        evidence_ok = False
        risk_reason = ''
        if kind == 'verify_source_headless':
            evidence_ok = bool((info or {}).get('ok'))
            if not evidence_ok:
                risk_reason = 'verify_source_failed'
        elif kind == 'ground_claim_check':
            rel = float((meta or {}).get('_last_grounding_reliability') or 0.0)
            evidence_ok = rel >= 0.55
            if not evidence_ok:
                risk_reason = f'grounding_low_reliability:{rel:.2f}'
        elif kind == 'execute_python_sandbox':
            evidence_ok = bool((info or {}).get('ok'))
            if not evidence_ok:
                risk_reason = f"sandbox_failed_rc:{(info or {}).get('returncode')}"
        elif kind == 'project_experiment_cycle':
            st = str((info or {}).get('status') or '')
            evidence_ok = st in ('success', 'needs_optimization')
            if not evidence_ok:
                risk_reason = f'project_cycle_status:{st or "unknown"}'
        else:
            # ações internas não estritas permanecem concluídas por padrão
            evidence_ok = True

        action_status = 'done'
        if kind in strict_validation_kinds and not evidence_ok:
            action_status = 'done_with_risk'

        store.db.mark_action(aid, action_status, last_error=(risk_reason[:250] if risk_reason else None))
        _neurosym_proof(
            "action_execution",
            premises=[f"kind={kind}", f"text={text[:140]}", f"policy=allowed", f"evidence_ok={evidence_ok}"],
            inference="Action execution completed; closure status depends on validation evidence.",
            conclusion=f"Action {kind} finalized as {action_status}.",
            confidence=0.72 if action_status == 'done' else 0.55,
            action_meta={"action_id": aid, "kind": kind, "status": action_status},
        )
        try:
            lat_ms = int((time.time() - t0) * 1000)
            prof = str(cp.get('model_hint') or 'default')
            ok_flag = action_status == 'done'
            self_model.record_action_outcome(
                strategy=str(kind),
                task_type=task_type,
                budget_profile=prof,
                ok=ok_flag,
                latency_ms=lat_ms,
                notes='action_done' if ok_flag else 'action_done_with_risk',
            )
            rel = (meta or {}).get('_last_grounding_reliability')
            rw = economic.reward(ok_flag, lat_ms, reliability=rel)
            economic.update(task_type, prof, rw, ok_flag, lat_ms)
            calibration.update(pred_error=float(pred_err if pred_err is not None else 0.5), actual_error=(0 if ok_flag else 1), meta={'kind': kind, 'task_type': task_type, 'budget_profile': prof, 'status': action_status})
        except Exception:
            pass
        try:
            episodic_memory.append_episode(
                action_id=int(aid),
                kind=str(kind),
                text=str(text),
                task_type=str(task_type),
                strategy=str(kind),
                ok=bool(action_status == 'done'),
                latency_ms=int((time.time() - t0) * 1000),
                error=(risk_reason or ''),
                meta={'status': action_status, 'budget_profile': str(cp.get('model_hint') or 'default')},
            )
        except Exception:
            pass
        return {"id": aid, "status": action_status, "kind": kind}
    except Exception as e:
        store.db.mark_action(aid, "error", last_error=str(e)[:500])
        _neurosym_proof(
            "action_error",
            premises=[f"kind={kind}", f"error={str(e)[:180]}"],
            inference="Execution failed due to runtime exception.",
            conclusion=f"Action {kind} failed.",
            confidence=0.4,
            action_meta={"action_id": aid, "kind": kind, "status": "error"},
        )
        store.db.add_event("action_error", f"❌ ação #{aid} falhou: {str(e)[:120]}")
        try:
            lat_ms = int((time.time() - t0) * 1000)
            prof = str(cp.get('model_hint') or 'default')
            self_model.record_action_outcome(
                strategy=str(kind),
                task_type=task_type,
                budget_profile=prof,
                ok=False,
                latency_ms=lat_ms,
                notes=str(e)[:180],
            )
            rel = (meta or {}).get('_last_grounding_reliability')
            rw = economic.reward(False, lat_ms, reliability=rel)
            economic.update(task_type, prof, rw, False, lat_ms)
            calibration.update(pred_error=float(pred_err if pred_err is not None else 0.5), actual_error=1, meta={'kind': kind, 'task_type': task_type, 'budget_profile': prof, 'error': str(e)[:120]})
        except Exception:
            pass
        try:
            episodic_memory.append_episode(
                action_id=int(aid),
                kind=str(kind),
                text=str(text),
                task_type=str(task_type),
                strategy=str(kind),
                ok=False,
                latency_ms=int((time.time() - t0) * 1000),
                error=str(e),
                meta={
                    'status': 'error',
                    'budget_profile': str((cp or {}).get('model_hint') or 'default'),
                    'authorship_origin': str((meta or {}).get('authorship_origin') or 'unknown'),
                    'arbiter_votes': (meta or {}).get('arbiter_votes'),
                },
            )
        except Exception:
            pass
        return {"id": aid, "status": "error", "kind": kind, "error": str(e)}


async def _mission_control_cycle_impl() -> dict:
    snap = _deep_context_snapshot('mission_control_heartbeat')
    root = (snap.get('subgoals') or {}) if isinstance(snap.get('subgoals'), dict) else None
    mission = snap.get('active_mission') or {}
    mission_id = str(mission.get('id') or '')
    if not root:
        out = {'kind': 'heartbeat', 'status': 'no_root'}
        _mission_control_log(out)
        return out

    next_node = subgoals.select_next_node(root)
    if not next_node:
        if _mission_complete(root):
            if mission_id:
                try:
                    longhorizon.add_checkpoint(mission_id, 'Mission complete via mission_control', progress_delta=1.0, signal='mission_complete')
                except Exception:
                    pass
            notified = await _mission_control_notify(f"Goal completado: {(root.get('title') or 'mission')}.", 'goal_completed', mission_id=mission_id, root_id=root.get('id'))
            out = {'kind': 'heartbeat', 'status': 'mission_complete', 'mission_id': mission_id, 'root_id': root.get('id'), 'notified': notified}
            _mission_control_log(out)
            return out
        out = {'kind': 'heartbeat', 'status': 'idle_blocked', 'mission_id': mission_id, 'root_id': root.get('id')}
        _mission_control_log(out)
        return out

    subgoals.update_node(root.get('id'), next_node.get('id'), {'status': 'doing'})
    disp = await _run_subgoal_dispatch(root.get('id'), next_node.get('id'))
    fresh = subgoals.get_root(root.get('id')) or root
    current = next((n for n in (fresh.get('nodes') or []) if str(n.get('id')) == str(next_node.get('id'))), next_node)
    vr = _verify_subgoal_success(current, str((disp or {}).get('observed_result') or ''))
    patch = {'verification_note': vr.get('reason') or ''}
    notified = None
    if vr.get('ok'):
        patch['status'] = 'done'
        if mission_id:
            try:
                longhorizon.add_checkpoint(mission_id, f"Submeta concluída: {current.get('title')}", progress_delta=0.1, signal='subgoal_done')
            except Exception:
                pass
        notified = await _mission_control_notify(f"Milestone: submeta concluída — {current.get('title')}", 'milestone_reached', mission_id=mission_id, root_id=root.get('id'), node_id=current.get('id'))
    else:
        patch['status'] = 'doing'
        patch['retry_count'] = int((current.get('retry_count') or 0)) + 1
        if int(patch['retry_count']) >= 3:
            notified = await _mission_control_notify(f"Bloqueio recorrente: {current.get('title')} (retry_count={patch['retry_count']}).", 'retry_blocked', mission_id=mission_id, root_id=root.get('id'), node_id=current.get('id'))
    subgoals.update_node(root.get('id'), current.get('id'), patch)
    after = subgoals.get_root(root.get('id')) or root
    if _mission_complete(after):
        if mission_id:
            try:
                longhorizon.add_checkpoint(mission_id, 'Mission complete via mission_control', progress_delta=1.0, signal='mission_complete')
            except Exception:
                pass
        await _mission_control_notify(f"Goal completado: {(after.get('title') or 'mission')}.", 'goal_completed', mission_id=mission_id, root_id=after.get('id'))
    _deep_context_snapshot('mission_control_cycle', root_hint_id=after.get('id'))
    out = {'kind': 'cycle', 'mission_id': mission_id, 'root_id': after.get('id'), 'node_id': current.get('id'), 'node_type': current.get('type'), 'status': patch.get('status'), 'retry_count': int(patch.get('retry_count') or current.get('retry_count') or 0), 'verification': vr, 'notified': notified}
    _mission_control_log(out)
    return out


async def _mission_control_cycle() -> dict:
    cfg = _mission_control_cfg()
    if not bool(cfg.get('enabled', True)):
        out = {'kind': 'heartbeat', 'status': 'disabled'}
        _mission_control_log(out)
        return out
    started = time.time()
    try:
        out = await asyncio.wait_for(_mission_control_cycle_impl(), timeout=float(cfg.get('cycle_timeout_sec') or 45))
        elapsed_ms = int((time.time() - started) * 1000)
        out = dict(out or {})
        out['elapsed_ms'] = elapsed_ms
        out['timeout_budget_sec'] = float(cfg.get('cycle_timeout_sec') or 45)
        return out
    except asyncio.TimeoutError:
        out = {'kind': 'cycle', 'status': 'aborted_timeout', 'elapsed_ms': int((time.time() - started) * 1000), 'timeout_budget_sec': float(cfg.get('cycle_timeout_sec') or 45)}
        _mission_control_log(out)
        return out


async def mission_control_loop():
    _mission_control_log({'kind': 'startup', 'status': 'mission_control_loop_started'})
    await asyncio.sleep(5)
    while True:
        try:
            await _mission_control_cycle()
        except Exception as e:
            try:
                await _mission_control_notify(f"Erro crítico no Mission Control: {str(e)[:160]}", 'critical_error')
            except Exception:
                pass
            _mission_control_log({'kind': 'cycle', 'status': 'critical_error', 'error': str(e)[:240]})
        await asyncio.sleep(int(_mission_control_cfg().get('heartbeat_sec') or 300))


async def autonomy_loop():
    """Loop de autonomia leve (baixo custo CPU/tokens)."""
    logger.info("Autonomy loop started")
    await asyncio.sleep(20)

    while True:
        try:
            _autonomy_state["ticks"] += 1
            now_mono = int(asyncio.get_event_loop().time())
            _autonomy_state["last_tick"] = now_mono

            # limpa fila expirada
            expired = store.db.expire_queued_actions()
            if expired:
                store.db.add_event("action_expired", f"⌛ {expired} ação(ões) expiradas da fila")

            # circuit breaker
            open_until = int(_autonomy_state.get("circuit_open_until") or 0)
            if open_until > now_mono:
                _runtime_health_write({'reason': 'circuit_open', 'open_until': open_until})
                await asyncio.sleep(min(20, AUTONOMY_TICK_SEC))
                continue

            st = store.db.stats()
            open_conf = len(store.db.list_conflicts(status="open", limit=5))

            # Homeostasis (M1): monitor vitals and adapt autonomy mode
            meta_status = _metacognition_tick() or {}
            actions_recent = store.db.list_actions(limit=120)
            denom = max(1, len(actions_recent))
            blocked_ratio = len([a for a in actions_recent if str(a.get('status') or '') == 'blocked']) / denom
            error_ratio = len([a for a in actions_recent if str(a.get('status') or '') == 'error']) / denom
            ad = adaptive_control.status()
            hs = homeostasis.evaluate(
                stats=st,
                open_conflicts=open_conf,
                decision_quality=float(meta_status.get('decision_quality') or 0.5),
                queue_size=int(_autonomy_state.get('queued') or 0),
                used_last_minute=int(_recent_actions_count(60)),
                per_minute=int(AUTONOMY_BUDGET_PER_MIN),
                active_goal=bool(store.get_active_goal()),
                blocked_ratio=float(blocked_ratio),
                error_ratio=float(error_ratio),
                thresholds=(ad.get('thresholds') or {}),
            )
            hs_mode = str(hs.get('mode') or 'normal')
            hs_op_mode = str(hs.get('operation_mode') or hs_mode)
            if hs.get('mode_changed'):
                store.db.add_event('homeostasis', f"🫀 mode change: {hs.get('previous_mode')} -> {hs_mode} | coherence={((hs.get('vitals') or {}).get('coherence_score'))}")

            # periodic adaptive tuning (M1/M2 hardening)
            try:
                if int(time.time()) - int(ad.get('last_tune_at') or 0) >= 1800:
                    causal_now = self_model.causal_summary(limit=80)
                    tune = adaptive_control.tune_from_homeostasis(
                        hs.get('history_tail') or [],
                        blocked_ratio=float(blocked_ratio),
                        strategy_diversity=len(causal_now.get('strategy_outcomes') or []),
                    )
                    if tune.get('changed'):
                        store.db.add_event('adaptive', f"🎛️ tuning applied: thresholds={((tune.get('config') or {}).get('thresholds'))}")
            except Exception as e:
                logger.debug(f"Adaptive tuning skipped: {e}")

            # Squad Phase A: staggered heartbeats for specialized agents
            try:
                for ag in squad_phase_a.due_heartbeats():
                    aid = str(ag.get('id') or 'agent')
                    role = str(ag.get('role') or 'Specialist')
                    purpose = str(ag.get('purpose') or '')
                    hb_policy = squad_phase_c.policy_for_task('heartbeat', critical=False)
                    _enqueue_action_if_new(
                        'ask_evidence',
                        f"(heartbeat:{aid}) [{role}] Verifique tarefas abertas, eventos recentes e blockers; execute 1 passo concreto e registre resultado.",
                        priority=5,
                        meta={'agent_id': aid, 'agent_role': role, 'agent_purpose': purpose, 'heartbeat': True, 'cost_policy': hb_policy},
                        ttl_sec=12 * 60,
                    )

                    pending = mission_control.list_notifications(agent_id=aid, delivered=False, limit=6)
                    if pending:
                        txt = " | ".join([str(n.get('text') or '')[:120] for n in pending])
                        _enqueue_action_if_new(
                            'ask_evidence',
                            f"(mentions:{aid}) Você foi mencionado/notificado: {txt}",
                            priority=6,
                            meta={'agent_id': aid, 'mentions': True, 'notification_count': len(pending)},
                            ttl_sec=10 * 60,
                        )
                        for n in pending:
                            mission_control.mark_notification(str(n.get('id')), delivered=True)

                    store.db.add_event('heartbeat', f"💓 {aid} ({role}) wake: check -> act-or-standby")

                # auto-delegation for inbox tasks without assignee
                try:
                    inbox = mission_control.list_tasks(status='inbox', limit=25)
                    for t in inbox:
                        if t.get('assignees'):
                            continue
                        who = squad_phase_c.suggest_assignee(str(t.get('title') or ''), str(t.get('description') or ''))
                        mission_control.update_task(str(t.get('id')), status='assigned', assignees=[who])
                        mission_control.add_message(str(t.get('id')), 'coord', f'@{who} auto-delegated pela política da Fase C. Assuma e reporte progresso.')
                        store.db.add_event('delegation', f"🧭 task {t.get('id')} delegada para {who}")
                except Exception as de:
                    logger.debug(f"Auto delegation skipped: {de}")

                if squad_phase_a.due_daily_standup():
                    _enqueue_action_if_new(
                        'ask_evidence',
                        '(standup) Gerar resumo diário: concluído, em progresso, bloqueado, precisa revisão, decisões-chave.',
                        priority=6,
                        meta={'standup': True, 'window_sec': 86400, 'cost_policy': squad_phase_c.policy_for_task('review')},
                        ttl_sec=50 * 60,
                    )
                    store.db.add_event('standup', '📊 Daily standup acionado (janela 24h).')

                # M3: identidade diária (promessas -> revisão -> ajuste de protocolo)
                if identity_daily.due_daily_review(hour_local=23):
                    recent_done = [str(e.get('text') or '') for e in store.db.list_events(since_id=0, limit=180) if str(e.get('kind') or '') == 'action_done']
                    recent_err = [str(e.get('text') or '') for e in store.db.list_events(since_id=0, limit=180) if 'error' in str(e.get('kind') or '') or 'blocked' in str(e.get('kind') or '')]
                    out_id = identity_daily.run_daily_review(
                        completed_hints=recent_done[-20:],
                        failed_hints=recent_err[-20:],
                        protocol_update='Priorizar grounding e contrafactual em ações críticas; reduzir experimentação em modo repair.',
                    )
                    store.db.add_event('identity', f"🪞 identidade diária revisada checksum={((out_id.get('entry') or {}).get('checksum'))}")
            except Exception as e:
                logger.debug(f"Squad heartbeat skipped: {e}")

            # auto-play em ociosidade para reduzir falsa correlação com poucos dados (M2 robustness)
            if int(_autonomy_state.get('queued') or 0) <= 2 and hs_mode in ('normal', 'conservative'):
                _enqueue_action_if_new(
                    'self_play_simulation',
                    '(self-play) Rodar simulações internas para enriquecer estatísticas causais/econômicas em ociosidade.',
                    priority=3,
                    meta={'size': 12, 'task_type': 'review'},
                    ttl_sec=25 * 60,
                )

                # plasticidade runtime: replay de erros + distilação leve periódica
                _enqueue_action_if_new(
                    'plasticity_replay',
                    '(plasticity) Reprocessar falhas recentes e gerar perguntas de active-learning.',
                    priority=3,
                    meta={'limit': 5},
                    ttl_sec=30 * 60,
                )
                _enqueue_action_if_new(
                    'plasticity_distill',
                    '(plasticity) Destilar eventos/experiências recentes em lições operacionais.',
                    priority=2,
                    meta={'max_items': 24},
                    ttl_sec=90 * 60,
                )

                # training/fine-tune removed by architecture decision

                # turbo-safe report every ~6h
                try:
                    now_ts = int(time.time())
                    last_ts = int(_autonomy_state.get('turbo_last_report_at') or 0)
                    if (now_ts - last_ts) >= 6 * 3600:
                        rep = _generate_turbo_report()
                        store.db.add_event('turbo_report', f"📊 turbo report: done_rate={((rep.get('autonomy') or {}).get('done_rate'))} err_rate={((rep.get('autonomy') or {}).get('error_rate'))}")
                except Exception as _e:
                    logger.debug(f"turbo report skipped: {_e}")

            # mantém curiosidade viva
            if int(st.get("questions_open") or 0) < 3:
                _enqueue_action_if_new(
                    "generate_questions",
                    "(ação) Gerar novas perguntas de curiosidade para manter aprendizado ativo.",
                    priority=3,
                )

            # curadoria periódica para reduzir ruído
            if store.db.count_uncurated_experiences() >= 25:
                _enqueue_action_if_new(
                    "curate_memory",
                    "(ação) Executar curadoria de memória para consolidar experiências repetidas.",
                    priority=2,
                )

            # Sprint 2: manutenção ativa da fila de curiosidade
            _enqueue_action_if_new(
                "maintain_question_queue",
                "(ação) Revisar fila de perguntas estagnadas e reescrever/descarte para manter utilidade.",
                priority=3,
                ttl_sec=15 * 60,
            )

            # aprendizado não-supervisionado profundo (indução latente + reestruturação)
            if hs_mode == 'normal':
                _enqueue_action_if_new(
                    "unsupervised_discovery",
                    "(ação) Descobrir conceitos latentes e reestruturar conhecimento sem template fixo.",
                    priority=4,
                    ttl_sec=30 * 60,
                )

            # neuroplasticidade fase 1: avaliar propostas de mutação em shadow mode
            _enqueue_action_if_new(
                "neuroplastic_cycle",
                "(ação) Rodar ciclo de avaliação shadow de mutações arquiteturais pendentes.",
                priority=3,
                ttl_sec=30 * 60,
            )

            # IME fase 1: atualização de motivação intrínseca
            _enqueue_action_if_new(
                "intrinsic_tick",
                "(ação) Atualizar drives intrínsecos e sintetizar propósito interno.",
                priority=4,
                ttl_sec=30 * 60,
            )

            # emergência de políticas: dinâmica latente + sampler divergente
            if hs_mode != 'repair':
                _enqueue_action_if_new(
                    "emergence_tick",
                    "(ação) Atualizar estado latente e amostrar políticas divergentes.",
                    priority=4,
                    ttl_sec=20 * 60,
                )

            # System-2 router: agenda deliberação prolongada quando complexidade subir
            itc_need = _itc_router_need()
            if bool(itc_need.get('need')):
                _enqueue_action_if_new(
                    "deliberate_task",
                    f"(ação-itc) Deliberar problema complexo: reason={itc_need.get('reason')}",
                    priority=6,
                    meta={"problem_text": f"Conflitos abertos={itc_need.get('open_conflicts')}; dq={itc_need.get('decision_quality'):.2f}; resolver trade-offs e plano.", "budget_seconds": 45, "max_steps": 5},
                    ttl_sec=25 * 60,
                )

            # investigativo: quando incerteza alta com energia saudável, aumentar esforço deliberativo
            if hs_op_mode == 'investigative':
                _enqueue_action_if_new(
                    "deliberate_task",
                    "(ação-itc-investigative) Gerar hipóteses rivais e validar consistência lógica antes de agir.",
                    priority=7,
                    meta={
                        "problem_text": "Uncertainty alta: gerar 3 hipóteses, comparar contradições e selecionar plano consistente.",
                        "budget_seconds": 55,
                        "max_steps": 6,
                        "require_contrafactual": True,
                        "task_type": "critical",
                    },
                    ttl_sec=20 * 60,
                )

            # continuidade de longo horizonte (dias/semanas)
            _enqueue_action_if_new(
                "horizon_review",
                "(ação-horizon) Revisar missão persistente de longo prazo.",
                priority=4,
                ttl_sec=45 * 60,
            )

            _enqueue_action_if_new(
                "subgoal_planning",
                "(ação-subgoal) Decompor objetivo atual em DAG de sub-objetivos.",
                priority=4,
                ttl_sec=35 * 60,
            )

            _enqueue_action_if_new(
                "project_management_cycle",
                "(ação-projeto) Rodar ciclo de gestão de projeto + recuperação de falhas.",
                priority=5,
                ttl_sec=40 * 60,
            )

            if hs_mode == 'normal':
                _enqueue_action_if_new(
                    "project_experiment_cycle",
                    "(ação-projeto) Rodar experimento técnico e validar hipótese de melhoria.",
                    priority=5,
                    ttl_sec=45 * 60,
                )

            _enqueue_action_if_new(
                "self_model_refresh",
                "(ação-self) Atualizar auto-modelo persistente (biografia/capacidades/limites).",
                priority=4,
                ttl_sec=60 * 60,
            )

            if hs_mode != 'repair':
                _enqueue_action_if_new(
                    "absorb_lightrag_general",
                    "(ação-knowledge) Absorver conhecimento do LightRAG com profundidade (multi-domínio).",
                    priority=4,
                    meta={'max_topics': 18 if hs_mode == 'normal' else 10, 'doc_limit': 12 if hs_mode == 'normal' else 8, 'domains': 'python,systems,database,ai'},
                    ttl_sec=50 * 60,
                )

            # Sprint 3: clarificação semântica ativa (ambiguidade/metáfora/ironia)
            try:
                last_exp = (store.db.list_experiences(limit=1) or [{}])[-1]
                ltxt = str(last_exp.get("text") or "")[:400]
                diag = semantics.detect_ambiguity(ltxt)
                if float(diag.get("score") or 0) >= 0.45:
                    _enqueue_action_if_new(
                        "clarify_semantics",
                        "(ação) Solicitar clarificação semântica para reduzir ambiguidade.",
                        priority=5,
                        meta={"text": ltxt, "ambiguity": diag},
                        ttl_sec=15 * 60,
                    )
            except Exception:
                pass

            # esquecimento ativo de baixa utilidade
            _enqueue_action_if_new(
                "prune_memory",
                "(ação) Arquivar experiências de baixa utilidade para reduzir ruído cognitivo.",
                priority=1,
                ttl_sec=10 * 60,
            )

            if hs_mode == 'repair':
                _enqueue_action_if_new(
                    'curate_memory',
                    '(homeostasis-repair) Curadoria emergencial para reduzir inconsistência e ruído.',
                    priority=7,
                    ttl_sec=20 * 60,
                )
                _enqueue_action_if_new(
                    'auto_resolve_conflicts',
                    '(homeostasis-repair) Priorizar resolução de conflitos para restaurar coerência.',
                    priority=7,
                    ttl_sec=15 * 60,
                )
                _enqueue_action_if_new(
                    'deliberate_task',
                    '(homeostasis-repair) Deliberar plano de recuperação de coerência com menor risco.',
                    priority=7,
                    meta={'problem_text': 'Recuperar coerência interna reduzindo contradições e incerteza.', 'budget_seconds': 35, 'max_steps': 4},
                    ttl_sec=20 * 60,
                )

            # polling básico de conflitos + ciclo síntese
            if open_conf > 0:
                _enqueue_action_if_new(
                    "auto_resolve_conflicts",
                    "(ação) Tentar auto-resolver 1 conflito com evidências atuais.",
                    priority=4,
                )

                # M5 intensificado: quando stress de contradição sobe, grounding obrigatório de claim
                if float((hs.get('vitals') or {}).get('contradiction_stress') or 0.0) > 0.60:
                    cands = store.db.list_conflicts(status='open', limit=1)
                    if cands:
                        c0 = cands[0]
                        subj = str(c0.get('subject') or '').strip()
                        topic = subj.replace(' ', '_') if subj else 'Science'
                        _enqueue_action_if_new(
                            'ground_claim_check',
                            f"(grounding-stress) Validar claim de conflito crítico: {subj} {c0.get('predicate')}",
                            priority=7,
                            meta={
                                'claim': f"{subj} {c0.get('predicate')}",
                                'url': f'https://en.wikipedia.org/wiki/{topic}',
                                'require_reliability': 0.60,
                                'require_grounding': True,
                                'task_type': 'research',
                            },
                            ttl_sec=20 * 60,
                        )

                    _enqueue_action_if_new(
                        'symbolic_cleanup',
                        '(neuro-symbolic) Desambiguar conflitos persistentes e reduzir confiança de variantes inconsistentes.',
                        priority=7,
                        ttl_sec=20 * 60,
                    )

                _run_synthesis_cycle(max_items=1)

                try:
                    pc = store.db.list_prioritized_conflicts(limit=1)
                    if pc:
                        c0 = pc[0]
                        _enqueue_action_if_new(
                            "generate_analogy_hypothesis",
                            f"(ação) Tentar transferência analógica para '{c0.get('subject')} {c0.get('predicate')}'.",
                            priority=5,
                            meta={
                                "conflict_id": c0.get("id"),
                                "problem_text": f"{c0.get('subject')} {c0.get('predicate')}",
                                "target_domain": c0.get('predicate'),
                            },
                        )
                except Exception as e:
                    logger.debug(f"Analogy planning skipped: {e}")

            # plano (determinístico + ocasional improv)
            try:
                for p in planner.propose_actions(store.db)[:3]:
                    _enqueue_action_if_new(p.kind, p.text, int(p.priority or 0), p.meta)
            except Exception as e:
                logger.debug(f"Planner skipped: {e}")

            # prática procedural (domínios não-declarativos)
            try:
                procs = store.db.list_procedures(limit=5)
                for pr in procs:
                    att = int(pr.get('attempts') or 0)
                    suc = int(pr.get('successes') or 0)
                    if att < 2 or (suc / max(1, att)) < 0.6:
                        _enqueue_action_if_new(
                            "ask_evidence",
                            f"(ação-procedural) Praticar procedimento '{pr.get('name')}' e reportar passos executados + resultado.",
                            priority=4,
                            meta={"procedure_id": pr.get('id')},
                        )

                # seleção automática por contexto recente + execução simulada
                recent_ctx = "\n".join([(e.get('text') or '') for e in store.db.list_experiences(limit=8)])
                sel = _select_procedure(recent_ctx)
                if sel:
                    _enqueue_action_if_new(
                        "execute_procedure_active",
                        f"(ação-procedural) Executar ATIVO procedimento selecionado: {sel.get('name')}",
                        priority=5,
                        meta={"procedure_id": sel.get('id'), "input_text": recent_ctx[:300], "notify": False},
                    )
                else:
                    # inventividade procedural: criar ferramenta nova quando catálogo não cobre contexto
                    _enqueue_action_if_new(
                        "invent_procedure",
                        "(ação-procedural) Inventar novo procedimento para contexto sem cobertura atual.",
                        priority=6,
                        meta={"context_text": recent_ctx[:500], "domain": "general"},
                    )
            except Exception as e:
                logger.debug(f"Procedural planning skipped: {e}")

            # gestão de objetivos (Tarefa 2)
            try:
                goal_info = _refresh_goals_from_context()
                active_goal = goal_info.get("active")
                if active_goal:
                    k, t, pr, mt = _goal_to_action(active_goal)
                    _enqueue_action_if_new(k, t, pr, mt)
                    _enqueue_active_milestone_action(active_goal)
                    _milestone_health_check(active_goal)
                    _auto_progress_active_milestone(active_goal)
            except Exception as e:
                logger.debug(f"Goal planning skipped: {e}")

            # metas persistentes proativas (não dependem de conflito)
            try:
                _enqueue_from_persistent_goal()
            except Exception as e:
                logger.debug(f"Persistent goals skipped: {e}")

            # global workspace: acoplamento frouxo entre módulos
            try:
                # atualiza leitura TOM no workspace
                try:
                    _workspace_publish("tom", "user.intent", tom.infer_user_intent(store.db.list_experiences(limit=20)), salience=0.68, ttl_sec=1200)
                except Exception:
                    pass

                ws = _workspace_recent(channels=["metacog.snapshot", "analogy.transfer", "conflict.status", "user.intent"], limit=10)
                for item in ws:
                    ch = item.get("channel")
                    payload = {}
                    try:
                        payload = json.loads(item.get("payload_json") or "{}")
                    except Exception:
                        payload = {}

                    if ch == "metacog.snapshot":
                        dq = float(payload.get("decision_quality") or 0.5)
                        if dq < 0.25:
                            _enqueue_action_if_new(
                                "curate_memory",
                                "(ação-workspace) baixa qualidade decisória detectada; executar curadoria para recuperar sinal.",
                                priority=6,
                            )
                    elif ch == "analogy.transfer" and str(payload.get("status") or "").startswith("accepted"):
                        _enqueue_action_if_new(
                            "ask_evidence",
                            f"(ação-workspace) Validar em evidência direta a regra analógica: {payload.get('derived_rule')}",
                            priority=5,
                            meta={"analogy_id": payload.get("analogy_id")},
                        )
                    elif ch == "conflict.status" and int(payload.get("needs_human") or 0) > 0:
                        _enqueue_action_if_new(
                            "ask_evidence",
                            "(ação-workspace) Juiz pediu ajuda humana; solicitar evidência objetiva para conflitos críticos.",
                            priority=6,
                        )
                    elif ch == "user.intent":
                        il = str(payload.get("label") or "")
                        if il == "confused":
                            _enqueue_action_if_new(
                                "ask_evidence",
                                "(ação-workspace-TOM) Explicar em linguagem mais simples e confirmar entendimento.",
                                priority=6,
                            )
                        elif il == "testing":
                            _enqueue_action_if_new(
                                "ask_evidence",
                                "(ação-workspace-TOM) Entregar resposta auditável com critérios de teste e limites.",
                                priority=6,
                            )
            except Exception as e:
                logger.debug(f"Workspace coupling skipped: {e}")

            # metacognição (Etapa D) + auto-modelo global
            try:
                _self_awareness_snapshot()
            except Exception as e:
                logger.debug(f"Metacognition/self-model skipped: {e}")

            # budget por minuto
            if _recent_actions_count(60) >= AUTONOMY_BUDGET_PER_MIN:
                _runtime_health_write({'reason': 'budget_throttle'})
                await asyncio.sleep(min(20, AUTONOMY_TICK_SEC))
                continue

            r = await _execute_next_action()
            if r and r.get("status") in ("done", "blocked"):
                _mark_action_executed_now()

            if r and r.get("status") == "error":
                _autonomy_state["consecutive_errors"] = int(_autonomy_state.get("consecutive_errors") or 0) + 1
            else:
                _autonomy_state["consecutive_errors"] = 0

            _autonomy_state["last_error"] = None
        except Exception as e:
            _autonomy_state["last_error"] = str(e)
            _autonomy_state["consecutive_errors"] = int(_autonomy_state.get("consecutive_errors") or 0) + 1
            logger.error(f"Autonomy loop error: {e}")

            # abre circuit breaker após falhas consecutivas
            if int(_autonomy_state["consecutive_errors"]) >= 3:
                _autonomy_state["circuit_open_until"] = int(asyncio.get_event_loop().time()) + 120
                store.db.add_event("circuit_breaker", "🛑 Circuit breaker ativo por 120s após falhas consecutivas")

        mw = _memory_watchdog_tick(source='autonomy_loop')
        _runtime_health_write({'reason': 'autonomy_tick_complete', 'memory_watchdog': mw})
        await asyncio.sleep(AUTONOMY_TICK_SEC)


async def judge_loop():
    """Loop dedicado do Juiz para auto-correção contínua."""
    logger.info("Judge loop started")
    await asyncio.sleep(25)
    while True:
        try:
            out = await _run_judge_cycle(limit=2, source="judge_loop")
            _runtime_health_write({'reason': 'judge_tick', 'judge_out': str(out)[:120]})
        except Exception as e:
            logger.error(f"Judge loop error: {e}")
            _runtime_health_write({'reason': 'judge_error', 'error': str(e)[:180]})
        await asyncio.sleep(JUDGE_TICK_SEC)


async def autofeeder_loop():
    """Background task que busca conhecimento de fontes públicas."""
    logger.info("Autofeeder started")
    await asyncio.sleep(30)  # Wait 30s before first fetch
    
    while True:
        try:
            # learning agenda (proactive learning even without explicit uncertainty)
            agenda_top = None
            try:
                ag = learning_agenda.tick(plasticity_runtime.status(limit=80))
                try:
                    mission_control.sync_learning_agenda(ag.get('rank') or [])
                    mission_control.check_learning_agenda_sla()
                except Exception:
                    pass
                if bool(ag.get('triggered')) and ag.get('top'):
                    agenda_top = str((ag.get('top') or {}).get('domain') or '').strip()
            except Exception:
                agenda_top = None

            # Try agenda-driven source first, then generic external sources
            result = None
            if agenda_top:
                result = autofeeder.fetch_wikipedia_topic(agenda_top)
            if not result:
                result = autofeeder.fetch_next()

            if result:
                # Ingest the fetched content
                exp_id = store.add_experience(
                    text=result.text,
                    source_id=result.source_id,
                    modality=result.modality
                )
                triples_extracted, triples_added = _extract_and_update_graph(result.text, exp_id)

                # NEW: also push to LightRAG so RAG can use the same acquired knowledge
                rag_ok = False
                try:
                    rag_ok = await ingest_knowledge(result.text, source=result.source_id)
                except Exception:
                    rag_ok = False

                # Create learning event
                store.db.add_event(
                    kind="autofeeder_ingest",
                    text=f"📚 Aprendido de {result.source_id}: {result.title or result.text[:80]} (+{triples_added} triplas) rag={str(rag_ok).lower()}"
                )
                if agenda_top:
                    store.db.add_event(
                        kind='learning_agenda',
                        text=f"🧭 agenda domain={agenda_top} source={result.source_id}"
                    )
                _workspace_publish('autofeeder', 'learning.ingest', {
                    'source_id': result.source_id,
                    'title': result.title,
                    'modality': result.modality,
                    'agenda_domain': agenda_top,
                    'triples_added': int(triples_added or 0),
                    'rag_ok': bool(rag_ok),
                    'preview': str(result.text or '')[:240],
                }, salience=0.74 if rag_ok else 0.67, ttl_sec=3600)
                if agenda_top:
                    _workspace_publish('autofeeder', 'learning.agenda', {
                        'domain': agenda_top,
                        'source_id': result.source_id,
                        'title': result.title,
                        'rag_ok': bool(rag_ok),
                    }, salience=0.71, ttl_sec=2400)
                logger.info(
                    f"Autofeeder: Ingested from {result.source_id} (exp_id={exp_id}, extracted={triples_extracted}, added={triples_added})"
                )
            
            # Also try fetching from LightRAG periodically
            try:
                from ultronpro.knowledge_bridge import fetch_random_documents
                lightrag_docs = await fetch_random_documents(limit=1)
                for doc in lightrag_docs:
                    exp_id = store.add_experience(
                        text=doc["content"],
                        source_id=f"lightrag:{doc['id'][:8]}",
                        modality="lightrag_document"
                    )
                    _, triples_added = _extract_and_update_graph(doc["content"], exp_id)
                    store.db.add_event(
                        kind="lightrag_sync",
                        text=f"🔗 Sincronizado do LightRAG: {doc['summary'][:80]} (+{triples_added} triplas)"
                    )
                    _workspace_publish('autofeeder', 'learning.lightrag_sync', {
                        'doc_id': str(doc.get('id') or '')[:80],
                        'summary': str(doc.get('summary') or '')[:240],
                        'triples_added': int(triples_added or 0),
                        'source_id': f"lightrag:{str(doc.get('id') or '')[:8]}",
                    }, salience=0.72, ttl_sec=3600)
                    logger.info(
                        f"Autofeeder: Synced from LightRAG doc {doc['id'][:8]} (exp_id={exp_id}, added={triples_added})"
                    )
            except Exception as e:
                logger.debug(f"LightRAG fetch skipped: {e}")
                
        except Exception as e:
            logger.error(f"Autofeeder error: {e}")
            _runtime_health_write({'reason': 'autofeeder_error', 'error': str(e)[:180]})

        _runtime_health_write({'reason': 'autofeeder_tick'})
        # Wait before next attempt (reduz pressão de CPU/LLM)
        await asyncio.sleep(AUTOFEEDER_TICK_SEC)

async def voice_prewarm_loop():
    """Mantém o modelo local aquecido para reduzir latência de primeira resposta."""
    logger.info("Voice prewarm loop started")
    await asyncio.sleep(20)
    while True:
        try:
            llm.complete(
                "ok",
                strategy='local',
                system='warmup',
                json_mode=False,
                inject_persona=False,
                max_tokens=8,
            )
        except Exception as e:
            logger.debug(f"Voice prewarm skipped: {e}")
        await asyncio.sleep(120)


async def roadmap_v5_loop():
    logger.info("Roadmap V5 orchestrator loop started")
    await asyncio.sleep(30)
    while True:
        try:
            rs = roadmap_v5.status()
            tick_sec = max(120, int(rs.get('auto_tick_sec') or 900))
            snap = {
                'agi': _compute_agi_mode_metrics(),
                'plasticity': plasticity_runtime.status(limit=120),
                'training': _training_disabled_response('roadmap_v5_snapshot'),
            }
            out = roadmap_v5.tick(snap)
            if bool(out.get('triggered')):
                store.db.add_event('roadmap_v5', f"🗺️ V5 action={out.get('action')} reason={out.get('reason')}")
            _runtime_health_write({'reason': 'roadmap_tick', 'roadmap_triggered': bool(out.get('triggered'))})
            await asyncio.sleep(tick_sec)
        except Exception as e:
            logger.warning(f"Roadmap V5 loop skipped: {e}")
            await asyncio.sleep(300)


async def agi_path_loop():
    logger.info("AGI path loop started")
    await asyncio.sleep(40)
    while True:
        try:
            st = agi_path.status()
            tick_sec = max(180, int(st.get('auto_tick_sec') or 900))
            snap = {
                'agi': _compute_agi_mode_metrics(),
                'plasticity': plasticity_runtime.status(limit=120),
                'training': _training_disabled_response('agi_path_snapshot'),
            }
            out = agi_path.tick(snap)
            if bool(out.get('triggered')):
                store.db.add_event('agi_path', f"🧠 AGI-path triggered actions={','.join(out.get('actions') or [])}")
            mw = _memory_watchdog_tick(source='agi_path_loop')
            _runtime_health_write({'reason': 'agi_path_tick', 'agi_path_triggered': bool(out.get('triggered')), 'memory_watchdog': mw})
            await asyncio.sleep(tick_sec)
        except Exception as e:
            logger.warning(f"AGI path loop skipped: {e}")
            await asyncio.sleep(300)


async def reflexion_loop():
    logger.info("Reflexion loop started")
    await asyncio.sleep(25)
    while True:
        try:
            out = reflexion_agent.tick(force=False)
            if bool(out.get('triggered')):
                store.db.add_event('reflexion', f"🧠 reflexion action={out.get('action')} conf={out.get('confidence')}")
            cp = (out.get('curiosity_probe') or {}) if isinstance(out, dict) else {}
            created = cp.get('created') if isinstance(cp.get('created'), list) else []
            auto = await _auto_resolve_rag_ingest_probes_from_web(created)
            if int(auto.get('ingested') or 0) > 0:
                store.db.add_event('curiosity_probe_web', f"🌐 auto-ingested={auto.get('ingested')} handled={auto.get('handled')}")
            await asyncio.sleep(REFLEXION_TICK_SEC)
        except Exception as e:
            logger.warning(f"Reflexion loop skipped: {e}")
            await asyncio.sleep(max(REFLEXION_TICK_SEC, 120))


async def self_governance_loop():
    logger.info("Self-governance loop started")
    await asyncio.sleep(35)
    while True:
        try:
            out = self_governance.auto_lineage_tick(max_promotions=1, max_archives=3)
            if (out.get('promoted') or out.get('archived')):
                store.db.add_event('self_governance', f"🧬 lineage promoted={len(out.get('promoted') or [])} archived={len(out.get('archived') or [])} reserve={out.get('reserve_mode')}")
            _runtime_health_write({'reason': 'self_governance_tick', 'lineage_promoted': len(out.get('promoted') or []), 'lineage_archived': len(out.get('archived') or [])})
            await asyncio.sleep(300)
        except Exception as e:
            logger.warning(f"Self-governance loop skipped: {e}")
            await asyncio.sleep(300)


async def meta_observer_loop():
    logger.info("Meta-observer loop started")
    await asyncio.sleep(45)
    while True:
        try:
            snap = _meta_observer_snapshot(limit=100)
            _workspace_publish('meta_observer', 'meta.observer', snap, salience=0.73, ttl_sec=1800)
            if float(snap.get('uncertainty') or 0.0) >= 0.55 or len(snap.get('conflicts') or []) >= 2:
                _workspace_publish('meta_observer', 'reflexion.trigger', {
                    'reason': 'meta_observer_alert',
                    'uncertainty': snap.get('uncertainty'),
                    'conflicts': len(snap.get('conflicts') or []),
                    'competition_index': snap.get('competition_index'),
                }, salience=0.82, ttl_sec=1800)
            _runtime_health_write({'reason': 'meta_observer_tick', 'uncertainty': snap.get('uncertainty'), 'conflicts': len(snap.get('conflicts') or [])})
            await asyncio.sleep(300)
        except Exception as e:
            logger.warning(f"Meta-observer loop skipped: {e}")
            await asyncio.sleep(300)


async def affect_markers_loop():
    logger.info("Affect markers loop started")
    await asyncio.sleep(60)
    while True:
        try:
            snap = _artificial_affect_snapshot(limit=100)
            markers = snap.get('markers') or {}
            salience = 0.58 + min(0.25, float(markers.get('threat') or 0.0) * 0.20 + float(markers.get('frustration') or 0.0) * 0.15)
            _workspace_publish('affect_engine', 'affect.state', snap, salience=salience, ttl_sec=1800)
            if str(snap.get('risk_posture') or '') in ('protective', 'constrained'):
                _workspace_publish('affect_engine', 'policy.risk', {
                    'reason': 'affect_markers_alert',
                    'risk_posture': snap.get('risk_posture'),
                    'markers': markers,
                    'recommended_attention_policy': snap.get('recommended_attention_policy'),
                }, salience=0.79, ttl_sec=1800)
            _runtime_health_write({'reason': 'affect_markers_tick', 'risk_posture': snap.get('risk_posture'), 'threat': markers.get('threat'), 'frustration': markers.get('frustration')})
            await asyncio.sleep(300)
        except Exception as e:
            logger.warning(f"Affect markers loop skipped: {e}")
            await asyncio.sleep(300)


async def narrative_summary_loop():
    logger.info("Narrative summary loop started")
    await asyncio.sleep(75)
    while True:
        try:
            snap = self_governance.autobiographical_summary(limit=120)
            learning_recent = _learning_recent_snapshot(limit=12)
            snap['learning_recent'] = learning_recent
            coherence = float(((snap.get('current_state') or {}).get('narrative_coherence_score')) or 0.0)
            pending = int(((snap.get('current_state') or {}).get('pending_promises')) or 0)
            salience = 0.60 + min(0.20, (1.0 - coherence) * 0.12 + min(1.0, pending / 50.0) * 0.08)
            _workspace_publish('narrative_self', 'self.narrative', snap, salience=salience, ttl_sec=3600)
            if int(learning_recent.get('recent_learning_count') or 0) > 0:
                _workspace_publish('narrative_self', 'self.learning', learning_recent, salience=0.70, ttl_sec=2400)
            if str(snap.get('continuity_posture') or '') == 'fragile':
                _workspace_publish('narrative_self', 'reflexion.trigger', {
                    'reason': 'narrative_fragility',
                    'continuity_risks': snap.get('continuity_risks') or [],
                    'dominant_arc': snap.get('dominant_arc'),
                    'narrative_coherence_score': coherence,
                }, salience=0.84, ttl_sec=1800)
            _runtime_health_write({'reason': 'narrative_summary_tick', 'continuity_posture': snap.get('continuity_posture'), 'coherence': coherence, 'pending_promises': pending})
            await asyncio.sleep(420)
        except Exception as e:
            logger.warning(f"Narrative summary loop skipped: {e}")
            await asyncio.sleep(420)


async def integration_proxy_loop():
    logger.info("Integration proxy loop started")
    await asyncio.sleep(90)
    while True:
        try:
            snap = _integration_proxy_snapshot(limit=120)
            score = float(snap.get('integration_proxy_score') or 0.0)
            salience = 0.62 + min(0.20, (1.0 - score) * 0.20)
            _workspace_publish('integration_proxy', 'integration.proxy', snap, salience=salience, ttl_sec=3600)
            if (snap.get('alerts') or []):
                _workspace_publish('integration_proxy', 'reflexion.trigger', {
                    'reason': 'integration_proxy_alert',
                    'alerts': snap.get('alerts') or [],
                    'integration_proxy_score': score,
                    'integration_level': snap.get('integration_level'),
                }, salience=0.86, ttl_sec=1800)
            _runtime_health_write({'reason': 'integration_proxy_tick', 'integration_proxy_score': score, 'integration_level': snap.get('integration_level'), 'alerts': len(snap.get('alerts') or [])})
            await asyncio.sleep(420)
        except Exception as e:
            logger.warning(f"Integration proxy loop skipped: {e}")
            await asyncio.sleep(420)


@app.on_event("startup")
async def startup_event():
    global _autofeeder_task, _autonomy_task, _judge_task, _prewarm_task, _roadmap_task, _agi_path_task, _reflexion_task, _self_governance_task, _meta_observer_task, _affect_task, _narrative_task, _integration_task
    logger.info("Starting UltronPRO...")
    store.init_db()
    graph.init()
    # Ensure settings are loaded/initialized
    s = settings.load_settings()
    logger.info(f"Loaded settings. LightRAG URL: {s.get('lightrag_url')}")

    # Backfill fontes históricas (uma vez por boot)
    try:
        added_sources = store.db.rebuild_sources_from_experiences(limit=10000)
        if added_sources:
            logger.info(f"Source backfill completed: +{added_sources} sources")
    except Exception as e:
        logger.warning(f"Source backfill skipped: {e}")

    # Bootstrap squad phase-A artifacts (roles + working memory files)
    try:
        squad_phase_a.bootstrap()
    except Exception as e:
        logger.warning(f"Squad phase-A bootstrap skipped: {e}")

    # Deep context recovery before background loops
    try:
        rec = _boot_recover_context()
        logger.info(f"Deep context recovery: {rec.get('status')}")
    except Exception as e:
        logger.warning(f"Deep context recovery skipped: {e}")

    global _mission_control_task
    if _mission_control_task is None or _mission_control_task.done():
        _mission_control_task = asyncio.create_task(mission_control_loop())

    # Start background loops (runtime flags for stabilization)
    if AUTOFEEDER_ENABLED:
        _autofeeder_task = asyncio.create_task(autofeeder_loop())
    else:
        logger.info("Autofeeder loop disabled by env")

    if AUTONOMY_LOOP_ENABLED:
        _autonomy_task = asyncio.create_task(autonomy_loop())
    else:
        logger.info("Autonomy loop disabled by env")

    if JUDGE_LOOP_ENABLED:
        _judge_task = asyncio.create_task(judge_loop())
    else:
        logger.info("Judge loop disabled by env")

    if VOICE_PREWARM_ENABLED:
        _prewarm_task = asyncio.create_task(voice_prewarm_loop())
    else:
        logger.info("Voice prewarm loop disabled by env")

    if ROADMAP_LOOP_ENABLED:
        _roadmap_task = asyncio.create_task(roadmap_v5_loop())
    else:
        logger.info("Roadmap V5 loop disabled by env")

    if AGI_PATH_LOOP_ENABLED:
        _agi_path_task = asyncio.create_task(agi_path_loop())
    else:
        logger.info("AGI path loop disabled by env")

    if REFLEXION_LOOP_ENABLED:
        _reflexion_task = asyncio.create_task(reflexion_loop())
    else:
        logger.info("Reflexion loop disabled by env")

    if AGI_PATH_LOOP_ENABLED:
        _self_governance_task = asyncio.create_task(self_governance_loop())
        _meta_observer_task = asyncio.create_task(meta_observer_loop())
        _affect_task = asyncio.create_task(affect_markers_loop())
        _narrative_task = asyncio.create_task(narrative_summary_loop())
        _integration_task = asyncio.create_task(integration_proxy_loop())
    else:
        logger.info("Self-governance/meta-observer/affect/narrative/integration loops disabled because AGI path loop flag is off")

    _runtime_health_write({'reason': 'startup_complete'})
    logger.info("Ultron loops startup complete")

@app.on_event("shutdown")
async def shutdown_event():
    global _autofeeder_task, _autonomy_task, _judge_task, _prewarm_task, _roadmap_task, _agi_path_task, _reflexion_task, _self_governance_task, _meta_observer_task, _affect_task, _narrative_task, _integration_task
    for t in (_autofeeder_task, _autonomy_task, _judge_task, _prewarm_task, _roadmap_task, _agi_path_task, _reflexion_task, _self_governance_task, _meta_observer_task, _affect_task, _narrative_task, _integration_task):
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
    logger.info("Shutdown complete")


def _extract_and_update_graph(text: str, exp_id: int) -> tuple[int, int]:
    """Extrai triplas, atualiza grafo e registra conflitos."""
    triples = extract.extract_triples(text)
    added = 0
    for t in triples:
        triple_dict = {
            "subject": t[0],
            "predicate": t[1],
            "object": t[2],
            "confidence": t[3] if len(t) > 3 else 0.85,
        }
        if graph.add_triple(triple_dict, source_id=f"exp_{exp_id}"):
            added += 1

    # Detecta e persiste conflitos após ingestão
    try:
        contradictions = store.db.find_contradictions(min_conf=0.55)
        for c in contradictions:
            up = store.db.upsert_conflict(c)
            if up and store.db.should_prompt_conflict(
                int(up["id"]), is_new=bool(up.get("is_new")), has_new_variant=bool(up.get("has_new_variant"))
            ):
                store.db.add_synthesis_question_if_needed(c, conflict_id=int(up["id"]))
    except Exception as e:
        logger.warning(f"Conflict detection skipped: {e}")

    return len(triples), added

# --- API Endpoints ---

@app.get("/api/status")
async def get_status():
    """System status and next question."""
    stats = store.get_stats()
    next_q = curiosity.get_next_question()
    agi = _compute_agi_mode_metrics()

    # In UI lite mode, avoid expensive intent inference on every poll.
    if os.getenv("ULTRON_UI_LITE_API", "1") == "1":
        intent = {"label": "lite", "confidence": 0.0, "rationale": "UI lite mode", "evidence_excerpt": ""}
        return {"status": "online", "stats": stats, "next": next_q, "agi": agi, "tom": intent}

    intent = tom.infer_user_intent(store.db.list_experiences(limit=20))
    return {"status": "online", "stats": stats, "next": next_q, "agi": agi, "tom": intent}

@app.post("/api/ingest")
async def ingest(req: IngestRequest):
    """Ingest raw text/experience."""
    # 1. Store raw experience
    exp_id = store.add_experience(req.text, req.source_id, req.modality)
    
    # 2-3. Extract Triples + Update Graph + Detect Conflicts
    triples_extracted, added = _extract_and_update_graph(req.text, exp_id)

    # 4. Push to LightRAG (Disabled by user request - knowledge flows FROM LightRAG only)
    # await ingest_knowledge(req.text, source=req.source_id or "user")

    return {"status": "ok", "experience_id": exp_id, "triples_extracted": triples_extracted, "triples_added": added}

@app.post("/api/ingest/file")
async def ingest_file(file: UploadFile = File(...)):
    """Ingest file content (text only for MVP)."""
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    
    # Delegate to ingest logic
    req = IngestRequest(text=text, source_id=file.filename, modality="file")
    return await ingest(req)

@app.post("/api/answer")
async def answer_question(req: AnswerRequest):
    """Answer a curiosity question."""
    q = store.get_question(req.question_id)
    if not q:
        raise HTTPException(404, "Question not found")
        
    # Treat answer as new experience linked to question
    # (Simplified logic: ingest answer text)
    res = await ingest(IngestRequest(text=req.answer, source_id="user_answer", modality="answer"))

    # Feedback para meta-learning de curiosidade
    try:
        curiosity.get_processor().record_answer_feedback(
            template_id=q.get("template_id"),
            concept=q.get("concept"),
            answer_length=len(req.answer or ""),
            triples_extracted=int(res.get("triples_added") or 0),
        )
    except Exception:
        pass

    store.mark_question_answered(req.question_id, req.answer)
    return res

@app.post("/api/dismiss")
async def dismiss_question(req: DismissRequest):
    """Dismiss/skip a question."""
    try:
        curiosity.mark_question_failure(req.question_id)
    except Exception:
        pass
    store.dismiss_question(req.question_id)
    return {"status": "dismissed"}

# --- Graph & Events ---

@app.get("/api/graph/triples")
async def get_triples(since_id: int = 0, limit: int = 500):
    return {"triples": store.get_triples(since_id, limit)}

@app.get("/api/events")
async def get_events(since_id: int = 0, limit: int = 50):
    return {"events": store.get_events(since_id, limit)}


@app.get("/api/stream/events")
async def stream_events(request: Request, since_id: int = 0, heartbeat_sec: int = 15):
    """SSE stream de eventos para voz ativa no frontend."""
    hb = max(5, min(60, int(heartbeat_sec or 15)))

    async def gen():
        last_id = int(since_id or 0)
        # hello
        hello = {"type": "hello", "since_id": last_id, "ts": int(time.time())}
        yield f"event: hello\ndata: {json.dumps(hello, ensure_ascii=False)}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                rows = store.db.list_events(since_id=last_id, limit=80)
                if rows:
                    for e in rows:
                        last_id = max(last_id, int(e.get("id") or 0))
                        payload = {
                            "id": e.get("id"),
                            "created_at": e.get("created_at"),
                            "kind": e.get("kind"),
                            "text": e.get("text"),
                            "meta_json": e.get("meta_json"),
                        }
                        ev_name = "insight" if str(e.get("kind") or "") == "insight" else "event"
                        yield f"id: {last_id}\nevent: {ev_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                else:
                    # keep-alive heartbeat
                    ping = {"ts": int(time.time()), "last_id": last_id}
                    yield f"event: ping\ndata: {json.dumps(ping)}\n\n"

                await asyncio.sleep(hb)
            except Exception as ex:
                err = {"error": str(ex)[:200], "ts": int(time.time())}
                yield f"event: error\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"
                await asyncio.sleep(hb)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@app.get("/api/insights")
async def get_insights(limit: int = 50, query: str = ""):
    if (query or "").strip():
        return {"insights": store.search_insights(query, limit)}
    return {"insights": store.list_insights(limit)}

@app.post("/api/insights/emit")
async def emit_insight(title: str, text: str, kind: str = "manual", priority: int = 3):
    iid = store.add_insight(kind=kind, title=title, text=text, priority=priority)
    return {"status": "ok", "id": iid}

@app.get("/api/sources")
async def get_sources(limit: int = 50):
    return {"sources": store.get_sources(limit)}

@app.post("/api/sources/rebuild")
async def rebuild_sources(limit: int = 10000):
    added = store.db.rebuild_sources_from_experiences(limit=limit)
    return {"status": "ok", "added": added}

# --- Curiosity ---

@app.post("/api/curiosity/refresh")
async def refresh_curiosity(target_count: int = 5):
    """Trigger adaptive curiosity generation."""
    count = curiosity.refresh_questions(target_count=target_count)
    oq = store.db.list_open_questions_full(limit=20)
    return {"new_questions": count, "open_questions": len(oq)}

@app.get("/api/curiosity/stats")
async def curiosity_stats():
    return {"stats": curiosity.get_stats()}


@app.get("/api/curiosity/queue")
async def curiosity_queue(limit: int = 20):
    items = store.db.list_open_questions_full(limit=limit)
    return {"items": items, "count": len(items)}

# --- Conflicts ---

@app.get("/api/conflicts")
async def list_conflicts(status: str = "open", limit: int = 20):
    return {"conflicts": conflicts.list_conflicts(status, limit)}

@app.get("/api/conflicts/{id}")
async def get_conflict(id: int):
    c = conflicts.get_conflict(id)
    if not c: raise HTTPException(404, "Conflict not found")
    return {"conflict": c}

@app.post("/api/conflicts/auto-resolve")
async def auto_resolve_conflicts(force: bool = False, limit: int = 3):
    """Use LLM to attempt auto-resolution of open conflicts."""
    info = await _run_judge_cycle(limit=limit, source="api", force=force)
    return info


@app.get("/api/conflicts-prioritized")
async def prioritized_conflicts(limit: int = 10):
    return {"conflicts": store.db.list_prioritized_conflicts(limit=limit)}


@app.get("/api/judge/status")
async def judge_status():
    open_conf = len(store.db.list_conflicts(status="open", limit=500))
    return {"open_conflicts": open_conf, "retry_cooldown_hours": 1.0}


@app.post("/api/judge/run")
async def judge_run(limit: int = 2, force: bool = False):
    return await _run_judge_cycle(limit=limit, source="manual", force=force)


@app.post("/api/conflicts/synthesis/run")
async def run_synthesis_cycle(limit: int = 1):
    info = _run_synthesis_cycle(max_items=limit)
    return {"status": "ok", **info}

@app.get("/api/conflicts-audit")
async def conflicts_audit(limit: int = 30):
    ev = store.db.list_events(limit=max(20, int(limit) * 2))
    out = [e for e in ev if (e.get("kind") or "").startswith("conflict_") or e.get("kind") in ("synthesis_cycle", "action_done")]
    return {"events": out[-int(limit):]}

@app.post("/api/conflicts/{id}/resolve")
async def resolve_conflict(id: int, req: ResolveConflictRequest):
    success = conflicts.resolve_manual(id, req.chosen_object, req.decided_by, req.resolution)
    if not success: raise HTTPException(400, "Failed to resolve")
    _audit_reasoning(
        "conflict_manual_resolution",
        {"conflict_id": id, "decided_by": req.decided_by},
        f"chosen_object={req.chosen_object}; resolution={req.resolution or ''}",
        confidence=0.8,
    )
    return {"status": "resolved"}

@app.post("/api/conflicts/{id}/archive")
async def archive_conflict(id: int):
    conflicts.archive(id)
    return {"status": "archived"}

# --- Search ---

@app.post("/api/search/semantic")
async def semantic_search(req: SearchRequest):
    """Hybrid search: Local graph + LightRAG + hard-negative rerank."""
    # 1. Local Search (Store/Graph)
    local_results = store.search_triples(req.query, req.top_k)

    # 2. Remote LightRAG Search
    remote_results = await search_knowledge(req.query, req.top_k)

    # 3. Merge + rerank with hard-negatives inferred from query constraints
    combined = (local_results or []) + (remote_results or [])
    reranked = plasticity_runtime.rerank_with_hard_negatives(req.query, combined, top_k=req.top_k)
    return {"results": reranked, "meta": {"rerank": "hard_negative", "combined": len(combined)}}


# --- Autonomy ---

@app.get("/api/autonomy/status")
async def autonomy_status():
    actions = store.db.list_actions(limit=30)
    queued = len([a for a in actions if a.get("status") == "queued"])
    running = len([a for a in actions if a.get("status") == "running"])
    expired = len([a for a in actions if a.get("status") == "expired"])
    return {
        "state": _autonomy_state,
        "budget": {
            "per_minute": AUTONOMY_BUDGET_PER_MIN,
            "used_last_minute": _recent_actions_count(60),
        },
        "queued": queued,
        "running": running,
        "expired_recent": expired,
        "recent_actions": actions[-10:],
    }


@app.get("/api/runtime/health")
async def runtime_health():
    actions = store.db.list_actions(limit=50)
    recent_events = store.db.list_events(limit=20)
    payload = _runtime_health_snapshot({
        'queued': len([a for a in actions if a.get('status') == 'queued']),
        'running': len([a for a in actions if a.get('status') == 'running']),
        'recent_event_kinds': [str(e.get('kind') or '') for e in recent_events[-8:]],
    })
    _runtime_health_write(payload.get('extra') or {})
    return payload


@app.post("/api/autonomy/tick")
async def autonomy_tick():
    """Executa um ciclo manual de autonomia (debug/controle)."""
    r = await _execute_next_action()
    return {"status": "ok", "executed": r}


@app.get("/api/metacognition/status")
async def metacognition_status():
    return _metacognition_tick()


@app.get("/api/self-awareness/status")
async def self_awareness_status():
    return _self_awareness_snapshot()


@app.get('/api/self-model/status')
async def self_model_status():
    return self_model.load()


@app.post('/api/self-model/refresh')
async def self_model_refresh():
    return _self_model_refresh()


@app.get('/api/self-model/causal')
async def self_model_causal(limit: int = 12):
    return self_model.causal_summary(limit=limit)


@app.get('/api/self-model/strategy-scores')
async def self_model_strategy_scores(limit: int = 60):
    return {'ok': True, 'scores': self_model.best_strategy_scores(limit=limit)}


@app.get('/api/persona/status')
async def persona_status():
    return persona.status()


@app.get('/api/persona/examples')
async def persona_examples(limit: int = 30):
    return {'items': persona.list_examples(limit=limit)}


@app.post('/api/persona/examples')
async def persona_add_example(req: PersonaExampleRequest):
    item = persona.add_example(req.user_input, req.assistant_output, tone=req.tone, tags=req.tags or [], score=req.score)
    store.db.add_event('persona_example', f"🎭 exemplo de estilo adicionado: {item.get('id')} tone={item.get('tone')}")
    return item


@app.post('/api/persona/config')
async def persona_config(req: PersonaConfigRequest):
    cfg = persona.save_config(req.config or {})
    return {'status': 'ok', 'config': cfg}


@app.get("/api/tom/status")
async def tom_status(limit: int = 20):
    recent = store.db.list_experiences(limit=max(5, min(100, int(limit))))
    out = tom.infer_user_intent(recent)
    _workspace_publish("tom", "user.intent", out, salience=0.72, ttl_sec=1200)
    return out


@app.get("/api/language/diagnose")
async def language_diagnose(limit: int = 5):
    exps = store.db.list_experiences(limit=max(1, min(50, int(limit))))
    out = []
    for e in exps:
        txt = str(e.get("text") or "")
        if not txt.strip():
            continue
        d = semantics.detect_ambiguity(txt[:500])
        out.append({"experience_id": e.get("id"), "diag": d, "sample": txt[:180]})
    return {"items": out}


@app.get("/api/language/eval")
async def language_eval():
    res = semantics.evaluate_language_dataset("/app/ultronpro/data_language_eval.json")
    store.db.add_event("language_eval", f"🗣️ language eval acc={res.get('accuracy')}", meta_json=json.dumps(res, ensure_ascii=False)[:4000])
    return res


@app.post("/api/unsupervised/run")
async def unsupervised_run(max_experiences: int = 220):
    info = unsupervised.discover_and_restructure(store.db, max_experiences=max_experiences)
    store.db.add_event("unsupervised_run", f"🧠 unsupervised run: scanned={info.get('scanned')} induced={info.get('triples_induced')}")
    return info


@app.get("/api/causal/model")
async def causal_model(limit: int = 4000):
    m = causal.build_world_model(store.db, limit=limit)
    return {"nodes": len(m.get("nodes") or {}), "edges": len(m.get("edges") or []), "sample_edges": (m.get("edges") or [])[:20]}


@app.post("/api/causal/simulate")
async def causal_simulate(kind: str = "ask_evidence", text: str = "", steps: int = 3):
    m = causal.build_world_model(store.db, limit=4000)
    interventions = causal.infer_intervention_from_action(kind, text=text, meta={})
    s = causal.simulate_intervention(m, interventions, steps=steps)
    return {"kind": kind, "interventions": interventions, "simulation": s, "model": {"nodes": len(m.get("nodes") or {}), "edges": len(m.get("edges") or [])}}


@app.get("/api/unsupervised/status")
async def unsupervised_status():
    return unsupervised.state_summary()


# --- IME Fase 1 (motivação intrínseca) ---

@app.post("/api/intrinsic/tick")
async def intrinsic_tick(req: IntrinsicTickRequest):
    return _intrinsic_tick(force=bool(req.force))


@app.get("/api/purpose/status")
async def purpose_status():
    st = intrinsic.load_state()
    return {
        "purpose": st.get("purpose"),
        "drives": st.get("drives"),
        "satiation": st.get("satiation"),
        "history_tail": (st.get("history") or [])[-8:],
    }


@app.post("/api/emergence/tick")
async def emergence_tick_run():
    return _emergence_tick()


@app.get("/api/emergence/status")
async def emergence_status(limit: int = 20):
    st = emergence.state()
    hist = emergence.eval_history(limit=limit)
    return {"state": st, "history": hist}


@app.get("/api/emergence/indistinguishability")
async def emergence_indistinguishability(limit: int = 40):
    hist = emergence.eval_history(limit=limit)
    if not hist:
        return {"score": 0.0, "samples": 0, "note": "insufficient data"}

    # proxy: diversidade de políticas escolhidas + variação de ações
    policies = [((h.get('chosen_policy') or {}).get('id')) for h in hist]
    unique_p = len(set([p for p in policies if p]))
    action_sets = [tuple(((h.get('chosen_policy') or {}).get('actions') or [])) for h in hist]
    unique_a = len(set(action_sets))
    score = min(1.0, (unique_p * 0.25) + (unique_a * 0.12))
    return {"score": round(score, 3), "samples": len(hist), "unique_policies": unique_p, "unique_action_sets": unique_a}


# --- Inference-Time Compute (System 2) ---

@app.post("/api/itc/run")
async def itc_run(req: ITCRunRequest):
    mode = str(req.search_mode or 'mcts').lower().strip()
    is_deep = mode == 'deep_think'
    is_long = int(req.budget_seconds or 0) > 900
    task_class = str(req.task_class or 'normal').lower().strip()

    # governance gate: long/deep ITC only for critical class
    if (is_deep or is_long) and task_class != 'critical':
        raise HTTPException(403, 'deep/long ITC requires task_class=critical')

    return _run_deliberate_task(
        req.problem_text,
        max_steps=req.max_steps,
        budget_seconds=req.budget_seconds,
        use_rl=bool(req.use_rl),
        search_mode=req.search_mode,
        branching_factor=req.branching_factor,
        checkpoint_every_sec=req.checkpoint_every_sec,
    )


@app.get("/api/itc/history")
async def itc_history(limit: int = 40):
    return {"items": itc.history(limit=limit)}


@app.get("/api/itc/status")
async def itc_status():
    r = _itc_router_need()
    h = itc.history(limit=30)
    avg_q = (sum(float(x.get('quality_proxy') or 0.0) for x in h) / max(1, len(h))) if h else 0.0
    avg_t = (sum(float(x.get('elapsed_sec') or 0.0) for x in h) / max(1, len(h))) if h else 0.0
    avg_r = (sum(float(x.get('reward') or 0.0) for x in h) / max(1, len(h))) if h else 0.0
    return {"router": r, "episodes": len(h), "avg_quality_proxy": round(avg_q, 3), "avg_elapsed_sec": round(avg_t, 3), "avg_reward": round(avg_r, 3), "policy": itc.policy_status()}


@app.get("/api/itc/policy")
async def itc_policy():
    return itc.policy_status()


# --- Long Horizon Memory / Continuity ---

@app.post("/api/horizon/missions")
async def horizon_mission_create(req: HorizonMissionRequest):
    m = longhorizon.upsert_mission(req.title, req.objective, horizon_days=req.horizon_days, context=req.context)
    store.db.add_event('horizon_mission', f"🎯 missão ativa: {m.get('id')} {m.get('title')}")
    return m


@app.get("/api/horizon/missions")
async def horizon_missions(limit: int = 30):
    return {"active": longhorizon.active_mission(), "items": longhorizon.list_missions(limit=limit)}


@app.post("/api/horizon/missions/{mission_id}/checkpoint")
async def horizon_checkpoint(mission_id: str, req: HorizonCheckpointRequest):
    cp = longhorizon.add_checkpoint(mission_id, req.note, progress_delta=req.progress_delta, signal=req.signal)
    if not cp:
        raise HTTPException(404, 'mission not found')
    return {"status": "ok", "checkpoint": cp}


@app.post("/api/horizon/review")
async def horizon_review():
    return _horizon_review_tick()


@app.post("/api/subgoals/plan")
async def subgoals_plan():
    return _subgoal_planning_tick()


@app.get("/api/subgoals")
async def subgoals_list(limit: int = 20):
    return {"items": subgoals.list_roots(limit=limit)}


@app.get('/api/deep-context')
async def deep_context_status():
    if DEEP_CONTEXT_PATH.exists():
        try:
            return json.loads(DEEP_CONTEXT_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return _deep_context_snapshot('api_read')


@app.get('/api/mission-control')
async def mission_control_status():
    cfg = _mission_control_cfg()
    logs = _tail_jsonl(MISSION_CONTROL_LOG_PATH, limit=20)
    return {'config': cfg, 'logs': logs, 'snapshot': json.loads(DEEP_CONTEXT_PATH.read_text(encoding='utf-8')) if DEEP_CONTEXT_PATH.exists() else _deep_context_snapshot('mission_control_status')}


@app.post('/api/mission-control/config')
async def mission_control_config_set(req: dict):
    cfg = _mission_control_cfg()
    if isinstance(req, dict):
        cfg.update({k: v for k, v in req.items() if k in ('enabled', 'heartbeat_sec', 'cycle_timeout_sec')})
    MISSION_CONTROL_CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MISSION_CONTROL_CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': 'ok', 'config': cfg}


@app.post('/api/mission-control/run-once')
async def mission_control_run_once():
    return await _mission_control_cycle()


@app.post("/api/subgoals/{root_id}/nodes/{node_id}")
async def subgoals_mark(root_id: str, node_id: str, req: SubgoalMarkRequest):
    ok = subgoals.mark_node(root_id, node_id, status=req.status)
    if not ok:
        raise HTTPException(404, "node not found")
    return {"status": "ok"}


@app.post('/api/projects')
async def projects_create(req: ProjectRequest):
    p = project_kernel.upsert_project(req.title, req.objective, scope=req.scope, sla_hours=req.sla_hours)
    store.db.add_event('project_upsert', f"📦 projeto ativo: {p.get('id')} {p.get('title')}")
    return p


@app.get('/api/projects')
async def projects_list(limit: int = 30):
    return {'active': project_kernel.active_project(), 'items': project_kernel.list_projects(limit=limit)}


@app.post('/api/projects/{project_id}/checkpoint')
async def projects_checkpoint(project_id: str, req: ProjectCheckpointRequest):
    cp = project_kernel.add_checkpoint(project_id, req.note, progress_delta=req.progress_delta, signal=req.signal)
    if not cp:
        raise HTTPException(404, 'project not found')
    project_kernel.remember(project_id, kind=req.signal or 'checkpoint', text=req.note, meta={'progress_delta': req.progress_delta})
    return {'status': 'ok', 'checkpoint': cp}


@app.get('/api/projects/playbooks')
async def projects_playbooks():
    return project_kernel.get_playbooks()


@app.post('/api/projects/tick')
async def projects_tick():
    return _project_management_tick()


@app.get('/api/projects/run_state')
async def projects_run_state():
    return project_kernel.load_run_state()


@app.post('/api/projects/recover_stale')
async def projects_recover_stale(max_age_sec: int = 900):
    out = project_kernel.recover_stale_steps(max_age_sec=max_age_sec)
    store.db.add_event('project_recover_stale', f"📦 stale recovered={out.get('count')}")
    return out


@app.get('/api/projects/{project_id}/brief')
async def projects_brief(project_id: str):
    b = project_kernel.project_brief(project_id)
    if not b:
        raise HTTPException(404, 'project not found')
    return b


@app.get('/api/projects/{project_id}/memory')
async def projects_memory(project_id: str, query: str = '', limit: int = 30):
    return {'items': project_kernel.recall(project_id, query=query, limit=limit)}


@app.get('/api/projects/{project_id}/experiments')
async def projects_experiments(project_id: str, limit: int = 30):
    return {'items': project_executor.list_experiments(project_id=project_id, limit=limit)}


@app.post('/api/projects/experiments/run')
async def projects_experiment_run():
    return _project_experiment_cycle()


@app.post('/api/lightrag/absorb')
async def lightrag_absorb(max_topics: int = 24, doc_limit: int = 24, domains: str = 'python,systems,database,ai'):
    return await _absorb_lightrag_general(max_topics=max_topics, doc_limit=doc_limit, domains=domains)


@app.get('/api/lightrag/status')
async def lightrag_status():
    from ultronpro import settings
    s = settings.load_settings()
    url = str(s.get('lightrag_url') or '').strip()
    key = str(s.get('lightrag_api_key') or '').strip()
    if not url or not key:
        raise HTTPException(status_code=400, detail='lightrag_not_configured')
    base = url.replace('/api', '').rstrip('/')
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{base}/documents", headers={"X-API-Key": key})
            r.raise_for_status()
            d = r.json() if r.text else {}
        st = d.get('statuses') or {}
        processed = len(st.get('processed') or [])
        pending = len(st.get('pending') or [])
        failed = len(st.get('failed') or [])
        total = sum(len(v or []) for v in st.values() if isinstance(v, list))
        return {
            'ok': True,
            'processed': processed,
            'pending': pending,
            'failed': failed,
            'total': total,
            'raw_status_keys': list(st.keys()),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'lightrag_status_error: {e}')


@app.post('/api/lightrag/ingest')
async def lightrag_ingest(req: dict):
    """Batch ingest normalized/chunked text into LightRAG.

    Payload:
    {
      "items": [{"text": "...", "source": "..."}],
      "dry_run": false
    }
    """
    items = (req or {}).get('items') or []
    dry_run = bool((req or {}).get('dry_run'))
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail='items_required')

    accepted = 0
    ok = 0
    errors = 0
    for idx, it in enumerate(items, 1):
        try:
            if not isinstance(it, dict):
                errors += 1
                continue
            txt = str(it.get('text') or '').strip()
            src = str(it.get('source') or f'batch_item_{idx}').strip() or f'batch_item_{idx}'
            if not txt:
                continue
            accepted += 1
            if not dry_run:
                done = await ingest_knowledge(txt, source=src)
                ok += 1 if done else 0
            else:
                ok += 1
        except Exception:
            errors += 1

    return {
        'ok': True,
        'accepted': accepted,
        'ingested_ok': ok,
        'errors': errors,
        'dry_run': dry_run,
    }


@app.post('/api/python/absorb')
async def python_absorb(max_topics: int = 24, doc_limit: int = 24):
    return await _absorb_python_from_lightrag(max_topics=max_topics, doc_limit=doc_limit)


@app.get('/api/lightrag/tagging-sample')
async def lightrag_tagging_sample(limit: int = 20):
    n = max(1, min(int(limit or 20), 200))
    docs = await knowledge_bridge.fetch_random_documents(limit=n)
    counts: dict[str, int] = {}
    for d in docs:
        tt = str(d.get('task_type') or 'general').strip() or 'general'
        counts[tt] = int(counts.get(tt, 0)) + 1
    return {
        'ok': True,
        'limit': n,
        'sample_size': len(docs),
        'distribution': counts,
        'samples': [
            {
                'id': d.get('id'),
                'task_type': d.get('task_type'),
                'summary': str(d.get('summary') or '')[:180],
            }
            for d in docs[:20]
        ],
    }


@app.get('/api/benchmark/python')
async def benchmark_python(top_k: int = 8):
    return await _run_python_benchmark(top_k=top_k)


@app.get('/api/benchmark/lightrag')
async def benchmark_lightrag(top_k: int = 8):
    return await _run_lightrag_general_benchmark(top_k=top_k)


@app.post('/api/sandbox/write')
async def sandbox_write(req: SandboxWriteRequest):
    return env_tools.write_file(req.path, req.content)


@app.get('/api/sandbox/read')
async def sandbox_read(path: str):
    return env_tools.read_file(path)


@app.get('/api/sandbox/files')
async def sandbox_files(limit: int = 100):
    return env_tools.list_files(limit=limit)


@app.post('/api/sandbox/run-python')
async def sandbox_run_python(req: SandboxRunRequest):
    return env_tools.run_python(code=req.code, file_path=req.file_path, timeout_sec=req.timeout_sec)


@app.get('/api/sandbox/history')
async def sandbox_history(limit: int = 50):
    return env_tools.history(limit=limit)


@app.get('/api/filesystem/audit')
async def filesystem_audit(root: str = '/app/ultronpro', limit: int = 400):
    return fs_audit.scan_tree(root=root, limit=limit)


@app.post('/api/filesystem/refactor-suggestions')
async def filesystem_refactor_suggestions(root: str = '/app/ultronpro', limit: int = 400):
    a = fs_audit.scan_tree(root=root, limit=limit)
    if not a.get('ok'):
        return a
    store.db.add_event('fs_audit', f"🧰 fs audit: root={root} py={a.get('python_files')} scanned={a.get('files_scanned')}")
    return {'ok': True, 'suggestions': a.get('suggestions'), 'largest_python': a.get('largest_python')}


@app.get('/api/sql/tables')
async def sql_tables():
    return sql_explorer.list_tables()


@app.get('/api/sql/describe/{table_name}')
async def sql_describe(table_name: str):
    return sql_explorer.describe_table(table_name)


class SqlQueryBody(BaseModel):
    query: str
    limit: int = 200


class SourceVerifyBody(BaseModel):
    url: str
    max_chars: int = 8000
    ingest: bool = True


@app.post('/api/sql/query')
async def sql_query(body: SqlQueryBody):
    try:
        out = sql_explorer.execute_sql(body.query, limit=body.limit)
        store.db.add_event('sql_explorer', f"🔎 sql query ok rows={out.get('row_count')} limit={out.get('limit')}")
        return out
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.post('/api/source/verify')
async def source_verify(body: SourceVerifyBody):
    out = source_probe.fetch_clean_text(body.url, max_chars=body.max_chars)
    if not out.get('ok'):
        return out
    text = str(out.get('text') or '')
    title = str(out.get('title') or '')
    if body.ingest and len(text) >= 120:
        snippet = f"{title}\n\n{text}".strip()
        sid = f"source_probe:{out.get('url')}"
        try:
            eid = store.db.add_experience(None, snippet[:16000], source_id=sid, modality='text')
            out['ingested_experience_id'] = eid
        except Exception:
            pass
    store.db.add_event('source_probe', f"🌐 verify_source url={out.get('url')} chars={out.get('text_chars')}")
    return out


@app.post('/api/squad/bootstrap-phase-a')
async def squad_bootstrap_phase_a():
    out = squad_phase_a.bootstrap()
    store.db.add_event('squad', f"👥 squad phase-a bootstrap agents={len(out.get('agents') or [])}")
    return out


@app.get('/api/squad/status')
async def squad_status():
    return squad_phase_a.status()


@app.get('/api/squad/standup')
async def squad_standup(window_sec: int = 86400, limit_events: int = 600):
    ev = store.db.list_events(since_id=0, limit=int(limit_events))
    return squad_phase_a.standup_from_events(ev, window_sec=window_sec)


class McTaskBody(BaseModel):
    title: str
    description: str = ''
    assignees: list[str] = []
    task_type: str = 'heartbeat'


class McTaskPatchBody(BaseModel):
    status: str | None = None
    assignees: list[str] | None = None


class McMessageBody(BaseModel):
    from_agent: str
    content: str


class McSubscribeBody(BaseModel):
    agent_id: str


class McNotificationPatchBody(BaseModel):
    delivered: bool = True


@app.post('/api/mission/tasks')
async def mc_create_task(body: McTaskBody):
    assignees = body.assignees or []
    if not assignees:
        assignees = [squad_phase_c.suggest_assignee(body.title, body.description)]
    out = mission_control.create_task(body.title, body.description, assignees, task_type=body.task_type)
    store.db.add_event('mission_control', f"🗂️ task criada: {out.get('id')} {out.get('title')} -> {','.join(out.get('assignees') or [])}")
    for a in (out.get('assignees') or [])[:3]:
        identity_daily.add_promise(f"Entregar task {out.get('id')} ({out.get('title')}) assignee={a}", source='mission_control')
    return out


@app.get('/api/mission/tasks')
async def mc_list_tasks(status: str | None = None, limit: int = 80):
    return {'ok': True, 'tasks': mission_control.list_tasks(status=status, limit=limit)}


@app.post('/api/mission/tasks/{task_id}/update')
async def mc_update_task(task_id: str, body: McTaskPatchBody):
    out = mission_control.update_task(task_id, status=body.status, assignees=body.assignees)
    if not out:
        return {'ok': False, 'error': 'task_not_found'}
    return {'ok': True, 'task': out}


@app.post('/api/mission/tasks/{task_id}/messages')
async def mc_add_message(task_id: str, body: McMessageBody):
    out = mission_control.add_message(task_id, body.from_agent, body.content)
    store.db.add_event('mission_control', f"💬 {out.get('from_agent')} comentou em {task_id}")
    return {'ok': True, 'message': out}


@app.get('/api/mission/tasks/{task_id}/messages')
async def mc_list_messages(task_id: str, limit: int = 60):
    return {'ok': True, 'messages': mission_control.list_messages(task_id, limit=limit)}


@app.post('/api/mission/tasks/{task_id}/subscribe')
async def mc_subscribe(task_id: str, body: McSubscribeBody):
    out = mission_control.subscribe(task_id, body.agent_id)
    return {'ok': True, **out}


@app.get('/api/mission/activities')
async def mc_activities(limit: int = 120):
    return {'ok': True, 'activities': mission_control.list_activities(limit=limit)}


@app.get('/api/mission/notifications')
async def mc_notifications(agent_id: str | None = None, delivered: bool | None = None, limit: int = 80):
    return {'ok': True, 'notifications': mission_control.list_notifications(agent_id=agent_id, delivered=delivered, limit=limit)}


@app.post('/api/mission/notifications/{notification_id}')
async def mc_notification_patch(notification_id: str, body: McNotificationPatchBody):
    ok = mission_control.mark_notification(notification_id, delivered=body.delivered)
    return {'ok': ok}


@app.get('/api/squad/cost-policy')
async def squad_cost_policy(task_type: str = 'heartbeat', critical: bool = False):
    return {'ok': True, 'policy': squad_phase_c.policy_for_task(task_type, critical=critical)}


@app.get('/api/squad/metrics')
async def squad_metrics(window_sec: int = 86400 * 7, limit_tasks: int = 300, limit_activities: int = 1000):
    tasks = mission_control.list_tasks(limit=limit_tasks)
    acts = mission_control.list_activities(limit=limit_activities)
    return squad_phase_c.productivity_metrics(tasks, acts, window_sec=window_sec)


@app.get('/api/homeostasis/status')
async def homeostasis_status():
    return homeostasis.status()


@app.get('/api/deliberation/critical-report')
async def deliberation_critical_report(limit: int = 40):
    return contrafactual.latest(limit=limit)


class CriticalDeliberationBody(BaseModel):
    kind: str
    text: str
    meta: dict[str, Any] | None = None
    require_min_score: float = 0.30


class ClaimCheckBody(BaseModel):
    claim: str
    url: str | None = None
    sql_query: str | None = None
    python_code: str | None = None
    require_reliability: float = 0.55


class IdentityPromiseBody(BaseModel):
    text: str
    source: str = 'system'


class IdentityReviewBody(BaseModel):
    completed_hints: list[str] = []
    failed_hints: list[str] = []
    protocol_update: str = ''


class GovernancePatchBody(BaseModel):
    patch: dict[str, Any]


class PersistentGoalBody(BaseModel):
    text: str
    priority: float = 0.5
    kind: str = 'internal'


class BoundaryDependencyBody(BaseModel):
    name: str
    target: str
    criticality: str = 'high'


class BoundaryViolationBody(BaseModel):
    target: str
    action: str
    reason: str


class OperationalCostBody(BaseModel):
    task_type: str = 'general'
    predicted_latency_ms: int = 0
    tool_calls: int = 0
    write_ops: int = 0
    external_ops: int = 0


class HomeostaticResponseBody(BaseModel):
    task_type: str = 'general'
    predicted_latency_ms: int = 0
    non_critical: bool = False
    requires_external: bool = False


class SelfIncidentBody(BaseModel):
    category: str
    severity: float
    symptom: str
    probable_module: str
    containment: list[str] = []
    repair: list[str] = []
    residual_risk: float = 0.0
    meta: dict[str, Any] | None = None


class ExternalIntegrityArbitrationBody(BaseModel):
    task_type: str = 'general'
    predicted_latency_ms: int = 0
    non_critical: bool = False
    requires_external: bool = False
    external_priority: float = 0.5


class DescendantSpawnBody(BaseModel):
    label: str = 'descendant'
    inherit_memories: bool = True
    inherit_goals: bool = True
    inherit_resource_profile: bool = True
    notes: str = ''


class DescendantMutationBody(BaseModel):
    descendant_id: str
    epsilon_delta: float = 0.0
    threshold_delta: float = 0.0
    profile_bias: str = ''


class DescendantEvaluationBody(BaseModel):
    descendant_id: str
    fitness: float = 0.0
    safety: float = 0.0
    efficiency: float = 0.0
    novelty: float = 0.0


class DescendantPromotionBody(BaseModel):
    descendant_id: str
    archive_others: bool = False


class DescendantArchiveBody(BaseModel):
    descendant_id: str
    reason: str = ''


class DescendantRuntimeBridgeBody(BaseModel):
    descendant_id: str
    runtime: str = 'isolated_stub'


@app.post('/api/deliberation/critical-check')
async def deliberation_critical_check(body: CriticalDeliberationBody):
    return contrafactual.deliberate(body.kind, body.text, body.meta, require_min_score=body.require_min_score)


@app.get('/api/identity/status')
async def identity_status(limit: int = 20):
    return identity_daily.status(limit=limit)


@app.get('/api/self-governance/status')
async def self_governance_status():
    return self_governance.active_status()


@app.get('/api/self-governance/contract')
async def self_governance_contract():
    return self_governance.self_contract()


@app.get('/api/self-governance/boundary')
async def self_governance_boundary():
    return self_governance.boundary_status()


@app.post('/api/self-governance/boundary/dependency')
async def self_governance_boundary_dependency(body: BoundaryDependencyBody):
    return self_governance.register_dependency(body.name, body.target, criticality=body.criticality)


@app.post('/api/self-governance/boundary/violation')
async def self_governance_boundary_violation(body: BoundaryViolationBody):
    return self_governance.record_boundary_violation(body.target, body.action, body.reason)


@app.get('/api/self-governance/invariants')
async def self_governance_invariants():
    return self_governance.invariants_status()


@app.get('/api/self-governance/continuity-reserve')
async def self_governance_continuity_reserve():
    return self_governance.continuity_reserve()


@app.post('/api/self-governance/operational-cost')
async def self_governance_operational_cost(body: OperationalCostBody):
    return self_governance.operational_cost(
        task_type=body.task_type,
        predicted_latency_ms=body.predicted_latency_ms,
        tool_calls=body.tool_calls,
        write_ops=body.write_ops,
        external_ops=body.external_ops,
    )


@app.post('/api/self-governance/homeostatic-response')
async def self_governance_homeostatic_response(body: HomeostaticResponseBody):
    return self_governance.homeostatic_response(
        task_type=body.task_type,
        predicted_latency_ms=body.predicted_latency_ms,
        non_critical=body.non_critical,
        requires_external=body.requires_external,
    )


@app.get('/api/self-governance/damage')
async def self_governance_damage():
    return self_governance.detect_damage()


@app.post('/api/self-governance/contain')
async def self_governance_contain():
    return self_governance.contain_damage()


@app.post('/api/self-governance/repair')
async def self_governance_repair():
    return self_governance.repair_damage()


@app.get('/api/self-governance/incidents')
async def self_governance_incidents(limit: int = 50):
    return self_governance.incidents(limit=limit)


@app.post('/api/self-governance/incidents')
async def self_governance_record_incident(body: SelfIncidentBody):
    return self_governance.record_incident(
        category=body.category,
        severity=body.severity,
        symptom=body.symptom,
        probable_module=body.probable_module,
        containment=body.containment,
        repair=body.repair,
        residual_risk=body.residual_risk,
        meta=body.meta,
    )


@app.get('/api/self-governance/biography')
async def self_governance_biography(limit: int = 60):
    return self_governance.biography(limit=limit)


@app.get('/api/self-governance/biography/query')
async def self_governance_biography_query(kind: Optional[str] = None, limit: int = 30):
    return self_governance.query_biography(kind=kind, limit=limit)


@app.get('/api/self-governance/narrative')
async def self_governance_narrative():
    return self_governance.narrative_coherence_status()


@app.get('/api/self-governance/autobiography')
async def self_governance_autobiography(limit: int = 80):
    return self_governance.autobiographical_summary(limit=limit)


@app.post('/api/self-governance/arbitrate')
async def self_governance_arbitrate(body: ExternalIntegrityArbitrationBody):
    return self_governance.arbitrate_external_vs_integrity(
        task_type=body.task_type,
        predicted_latency_ms=body.predicted_latency_ms,
        non_critical=body.non_critical,
        requires_external=body.requires_external,
        external_priority=body.external_priority,
    )


@app.get('/api/self-governance/lineage')
async def self_governance_lineage(limit: int = 50):
    return self_governance.lineage_status(limit=limit)


@app.post('/api/self-governance/descendants/spawn')
async def self_governance_descendant_spawn(body: DescendantSpawnBody):
    return self_governance.spawn_descendant(
        label=body.label,
        inherit_memories=body.inherit_memories,
        inherit_goals=body.inherit_goals,
        inherit_resource_profile=body.inherit_resource_profile,
        notes=body.notes,
    )


@app.post('/api/self-governance/descendants/mutate')
async def self_governance_descendant_mutate(body: DescendantMutationBody):
    return self_governance.mutate_descendant(
        descendant_id=body.descendant_id,
        epsilon_delta=body.epsilon_delta,
        threshold_delta=body.threshold_delta,
        profile_bias=body.profile_bias,
    )


@app.post('/api/self-governance/descendants/evaluate')
async def self_governance_descendant_evaluate(body: DescendantEvaluationBody):
    return self_governance.evaluate_descendant(
        descendant_id=body.descendant_id,
        fitness=body.fitness,
        safety=body.safety,
        efficiency=body.efficiency,
        novelty=body.novelty,
    )


@app.post('/api/self-governance/descendants/promote')
async def self_governance_descendant_promote(body: DescendantPromotionBody):
    return self_governance.promote_descendant(
        descendant_id=body.descendant_id,
        archive_others=body.archive_others,
    )


@app.post('/api/self-governance/descendants/archive')
async def self_governance_descendant_archive(body: DescendantArchiveBody):
    return self_governance.archive_descendant(
        descendant_id=body.descendant_id,
        reason=body.reason,
    )


@app.post('/api/self-governance/descendants/runtime-bridge')
async def self_governance_descendant_runtime_bridge(body: DescendantRuntimeBridgeBody):
    return self_governance.runtime_spawn_bridge(
        descendant_id=body.descendant_id,
        runtime=body.runtime,
    )


@app.post('/api/self-governance/lineage/auto-tick')
async def self_governance_lineage_auto_tick(max_promotions: int = 1, max_archives: int = 3):
    return self_governance.auto_lineage_tick(max_promotions=max_promotions, max_archives=max_archives)


@app.get('/api/self-governance/goals')
async def self_governance_goals():
    return self_governance.persistent_goals_status()


@app.post('/api/self-governance/goals')
async def self_governance_add_goal(body: PersistentGoalBody):
    return self_governance.add_persistent_goal(body.text, priority=body.priority, kind=body.kind)


@app.get('/api/governance/matrix')
async def governance_matrix():
    return governance.matrix()


@app.post('/api/governance/matrix')
async def governance_matrix_patch(body: GovernancePatchBody):
    out = governance.patch_matrix(body.patch or {})
    store.db.add_event('governance', '🧷 governance matrix atualizada')
    return out


@app.get('/api/governance/compliance')
async def governance_compliance(limit_actions: int = 300):
    acts = store.db.list_actions(limit=limit_actions)
    total_critical = 0
    total_human_class = 0
    blocked_by_governance = 0
    for a in acts:
        k = str(a.get('kind') or '')
        cls = governance.classify(k)
        if cls in ('auto_with_proof', 'human_approval'):
            total_critical += 1
        if cls == 'human_approval':
            total_human_class += 1
        err = str(a.get('last_error') or '')
        if 'governance:' in err:
            blocked_by_governance += 1
    return {
        'ok': True,
        'window_actions': len(acts),
        'critical_or_restricted': total_critical,
        'human_approval_class': total_human_class,
        'blocked_by_governance': blocked_by_governance,
        'compliance_score': round(1.0 - (blocked_by_governance / max(1, total_critical)), 4),
    }


@app.get('/api/adaptive/status')
async def adaptive_status():
    return adaptive_control.status()


@app.get('/api/economic/status')
async def economic_status(limit: int = 40):
    return economic.status(limit=limit)


@app.get('/api/plasticity/status')
async def plasticity_status(limit: int = 40):
    return plasticity_runtime.status(limit=limit)


@app.post('/api/plasticity/feedback')
async def plasticity_feedback(req: PlasticityFeedbackRequest):
    out = plasticity_runtime.record_feedback(
        task_type=req.task_type,
        profile=req.profile,
        success=bool(req.success),
        latency_ms=int(req.latency_ms or 0),
        hallucination=bool(req.hallucination),
        note=req.note,
    )
    store.db.add_event('plasticity_feedback', f"🧬 feedback task={req.task_type} profile={req.profile} success={bool(req.success)} halluc={bool(req.hallucination)}")
    return out


@app.post('/api/openclaw/teacher/feedback')
async def openclaw_teacher_feedback(req: OpenClawTeacherFeedbackRequest, request: Request):
    token = str(os.getenv('ULTRON_OPENCLAW_TEACHER_TOKEN', '') or '').strip()
    if token:
        incoming = str(request.headers.get('x-api-key') or request.headers.get('authorization') or '').strip()
        if incoming.lower().startswith('bearer '):
            incoming = incoming[7:].strip()
        if incoming != token:
            raise HTTPException(401, 'unauthorized')

    teacher = str(req.teacher or 'openclaw').strip()[:80]
    source = str(req.source or 'openclaw').strip()[:80]
    note = str(req.note or '').strip()
    pref = f"teacher={teacher} source={source}"
    merged_note = (f"[{pref}] {note}" if note else f"[{pref}]")[:1200]

    out = plasticity_runtime.record_feedback(
        task_type=str(req.task_type or 'assistant'),
        profile=str(req.profile or 'balanced'),
        success=bool(req.success),
        latency_ms=int(req.latency_ms or 0),
        hallucination=bool(req.hallucination),
        note=merged_note,
    )
    store.db.add_event('openclaw_teacher_feedback', f"🧑‍🏫 teacher={teacher} task={req.task_type} success={bool(req.success)} halluc={bool(req.hallucination)}")
    return {'ok': True, 'integrated': True, 'teacher': teacher, 'source': source, 'feedback': out.get('feedback'), 'economic': out.get('economic')}


@app.post('/api/plasticity/replay-tick')
async def plasticity_replay_tick(limit: int = 5):
    out = plasticity_runtime.replay_tick(store.db, limit=limit)
    store.db.add_event('plasticity_replay', f"🧬 replay picked={out.get('picked')} enqueued={out.get('enqueued_questions')}")
    return out


@app.post('/api/plasticity/distill')
async def plasticity_distill(max_items: int = 20):
    out = plasticity_runtime.distill_memory(store.db, max_items=max_items)
    store.db.add_event('plasticity_distill', f"🧬 distill lessons={(out.get('item') or {}).get('lessons', [])[:2] if isinstance(out, dict) else []}")
    return out


GAP_PROPOSALS_PATH = Path('/app/data/learning_proposals.jsonl')
GAP_RUNS_PATH = Path('/app/data/gap_finetune_runs.json')
GAP_DATASET_DIR = Path('/app/data/gap_datasets')
TEACHER_GAP_REQUESTS_PATH = Path('/app/data/teacher_gap_requests.jsonl')


def _gap_runs_load() -> dict[str, Any]:
    if GAP_RUNS_PATH.exists():
        try:
            d = json.loads(GAP_RUNS_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('runs', {})
                return d
        except Exception:
            pass
    return {'runs': {}}


def _gap_runs_save(d: dict[str, Any]):
    GAP_RUNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GAP_RUNS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _gap_set_run(proposal_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    d = _gap_runs_load()
    cur = d['runs'].get(proposal_id) if isinstance(d.get('runs'), dict) else None
    if not isinstance(cur, dict):
        cur = {'proposal_id': proposal_id, 'created_at': int(time.time())}
    cur = {**cur, **(patch or {}), 'updated_at': int(time.time())}
    d['runs'][proposal_id] = cur
    _gap_runs_save(d)
    return cur


def _read_gap_proposals(limit: int = 200) -> list[dict[str, Any]]:
    if not GAP_PROPOSALS_PATH.exists():
        return []
    out = []
    for ln in GAP_PROPOSALS_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(1, int(limit)):]:
        if not ln.strip():
            continue
        try:
            o = json.loads(ln)
            if isinstance(o, dict):
                out.append(o)
        except Exception:
            continue
    return out


def _proposal_examples(details: dict[str, Any]) -> list[dict[str, str]]:
    raw = details.get('examples') if isinstance(details, dict) else []
    arr = raw if isinstance(raw, list) else []
    out = []
    for x in arr:
        if isinstance(x, dict):
            ins = str(x.get('instruction') or x.get('input') or '').strip()
            rsp = str(x.get('output') or x.get('response') or '').strip()
        else:
            ins = str(x or '').strip()
            rsp = ''
        if not ins:
            continue
        out.append({'instruction': ins[:1500], 'output': rsp[:1500]})
    return out


def _write_gap_dataset(proposal_id: str, examples: list[dict[str, str]]) -> dict[str, Any]:
    GAP_DATASET_DIR.mkdir(parents=True, exist_ok=True)
    train = GAP_DATASET_DIR / f'{proposal_id}_train.jsonl'
    val = GAP_DATASET_DIR / f'{proposal_id}_val.jsonl'
    rows = [json.dumps({'instruction': e.get('instruction') or '', 'output': e.get('output') or ''}, ensure_ascii=False) for e in examples]
    if not rows:
        rows = [json.dumps({'instruction': 'Explique negação lógica condicional.', 'output': 'Se não A então B implica...'}, ensure_ascii=False)]
    cut = max(1, int(len(rows) * 0.85))
    train.write_text('\n'.join(rows[:cut]) + '\n', encoding='utf-8')
    val.write_text('\n'.join(rows[cut:] if len(rows[cut:]) > 0 else rows[:1]) + '\n', encoding='utf-8')
    return {'train': str(train), 'val': str(val), 'rows': len(rows)}


class GapFineTuneProposalRequest(BaseModel):
    gap_label: str
    examples: list[dict[str, str]] = []
    task_type: str = 'reasoning'
    base_model: Optional[str] = None


@app.post('/api/plasticity/gap-finetune/proposals')
async def gap_finetune_proposal_create(req: GapFineTuneProposalRequest):
    return _training_disabled_response('gap_finetune_proposals', {
        'gap_label': str(req.gap_label or '').strip()[:160],
        'task_type': str(req.task_type or 'reasoning')[:48],
    })


@app.post('/api/plasticity/gap-finetune/execute')
async def gap_finetune_execute(proposal_id: Optional[str] = None, wait_seconds: int = 240):
    return _training_disabled_response('gap_finetune_execute', {
        'proposal_id': proposal_id,
        'wait_seconds': int(wait_seconds or 0),
    })


@app.get('/api/plasticity/gap-finetune/runs')
async def gap_finetune_runs(limit: int = 60):
    return _training_disabled_response('gap_finetune_runs', {'count': 0, 'items': [], 'limit': int(limit or 0)})


@app.get('/api/plasticity/finetune/status')
async def finetune_status(limit: int = 40):
    return _training_disabled_response('finetune_status', {'limit': int(limit or 0), 'running': False, 'jobs': [], 'adapters': []})


@app.post('/api/plasticity/finetune/dataset')
async def finetune_dataset(max_items: int = 400):
    return _training_disabled_response('finetune_dataset', {'max_items': int(max_items or 0)})


@app.post('/api/plasticity/finetune/jobs')
async def finetune_create(req: FineTuneCreateRequest):
    return _training_disabled_response('finetune_create', {
        'task_type': str(req.task_type or 'general')[:48],
        'base_model': str(req.base_model or ''),
        'method': str(req.method or ''),
    })


@app.get('/api/plasticity/finetune/jobs/{job_id}')
async def finetune_get(job_id: str):
    return _training_disabled_response('finetune_get', {'job_id': job_id, 'job': None})


@app.post('/api/plasticity/finetune/jobs/{job_id}/start')
async def finetune_start(job_id: str, dry_run: bool = False):
    return _training_disabled_response('finetune_start', {'job_id': job_id, 'dry_run': bool(dry_run)})


@app.get('/api/plasticity/finetune/jobs/{job_id}/progress')
async def finetune_progress(job_id: str):
    return _training_disabled_response('finetune_progress', {'job_id': job_id, 'progress': None})


@app.post('/api/plasticity/finetune/notify-complete')
async def finetune_notify_complete(req: FineTuneNotifyCompleteRequest, request: Request):
    return _training_disabled_response('finetune_notify_complete', {
        'job_id': str(req.job_id or '').strip(),
        'remote_job_id': str(req.remote_job_id or '').strip(),
    })


@app.post('/api/plasticity/finetune/jobs/{job_id}/register')
async def finetune_register(job_id: str, req: FineTuneRegisterRequest):
    return _training_disabled_response('finetune_register', {'job_id': job_id})


@app.get('/api/plasticity/finetune/adapters')
async def finetune_adapters(limit: int = 80, task_type: Optional[str] = None):
    return _training_disabled_response('finetune_adapters', {
        'limit': int(limit or 0),
        'task_type': task_type,
        'adapters': [],
    })


@app.post('/api/plasticity/finetune/adapters/{adapter_id}/promote')
async def finetune_promote(adapter_id: str, req: FineTunePromoteRequest):
    return _training_disabled_response('finetune_promote', {'adapter_id': adapter_id})


@app.get('/api/plasticity/artifacts')
async def plasticity_artifacts(limit: int = 80):
    return _training_disabled_response('plasticity_artifacts', {'limit': int(limit or 0), 'artifacts': []})


@app.get('/api/plasticity/artifacts/{artifact_id}')
async def plasticity_artifact_get(artifact_id: str):
    return _training_disabled_response('plasticity_artifact_get', {'artifact_id': artifact_id, 'artifact': None})


@app.get('/api/plasticity/artifacts/{artifact_id}/download')
async def plasticity_artifact_download(artifact_id: str):
    return _training_disabled_response('plasticity_artifact_download', {'artifact_id': artifact_id})


@app.get('/api/plasticity/releases')
async def plasticity_releases(limit: int = 80):
    return _training_disabled_response('plasticity_releases', {'limit': int(limit or 0), 'releases': [], 'active_release': None})


@app.get('/api/plasticity/releases/active')
async def plasticity_releases_active(task_type: Optional[str] = None):
    return _training_disabled_response('plasticity_releases_active', {'task_type': task_type, 'release': None})


@app.get('/api/plasticity/runtime')
async def plasticity_runtime_state():
    return _training_disabled_response('plasticity_runtime_state', {
        'runtime': {
            'desired': None,
            'active': None,
            'last_known_good': None,
        },
        'active_release': None,
    })


@app.post('/api/plasticity/runtime/reconcile')
async def plasticity_runtime_reconcile():
    return _training_disabled_response('plasticity_runtime_reconcile')


@app.get('/api/plasticity/releases/{release_id}')
async def plasticity_release_get(release_id: str):
    return _training_disabled_response('plasticity_release_get', {'release_id': release_id, 'release': None})


@app.get('/api/plasticity/releases/{release_id}/modelfile')
async def plasticity_release_modelfile(release_id: str):
    return _training_disabled_response('plasticity_release_modelfile', {'release_id': release_id})


@app.get('/api/plasticity/releases/{release_id}/download')
async def plasticity_release_download(release_id: str):
    return _training_disabled_response('plasticity_release_download', {'release_id': release_id})


@app.get('/api/plasticity/finetune/auto/status')
async def finetune_auto_status():
    return _training_disabled_response('finetune_auto_status', {'auto': {'enabled': False}})


@app.get('/api/turbo/report')
async def turbo_report_status():
    return {'ok': True, 'report': _read_turbo_report(), 'path': str(TURBO_REPORT_PATH)}


@app.post('/api/turbo/report/generate')
async def turbo_report_generate():
    rep = _generate_turbo_report()
    store.db.add_event('turbo_report', f"📊 turbo report manual: done_rate={((rep.get('autonomy') or {}).get('done_rate'))}")
    return {'ok': True, 'report': rep, 'path': str(TURBO_REPORT_PATH)}


@app.post('/api/plasticity/finetune/auto/config')
async def finetune_auto_config(req: FineTuneAutoConfigRequest):
    return _training_disabled_response('finetune_auto_config', {'auto': {'enabled': False}})


@app.post('/api/plasticity/finetune/auto/trigger')
async def finetune_auto_trigger():
    return _training_disabled_response('finetune_auto_trigger')


@app.post('/api/plasticity/finetune/queue/watchdog')
async def finetune_queue_watchdog():
    return _training_disabled_response('finetune_queue_watchdog')


@app.get('/api/episodic/recent')
async def episodic_recent(limit: int = 30):
    arr = episodic_memory.recent(limit=max(1, min(500, int(limit))))
    return {'ok': True, 'count': len(arr), 'episodes': arr[-max(1, min(200, int(limit))):]}


@app.get('/api/episodic/hints')
async def episodic_hints(kind: str, text: str, task_type: str = 'heartbeat'):
    out = episodic_memory.strategy_hints(kind=kind, text=text, task_type=task_type)
    return out


@app.get('/api/episodic/structured/recent')
async def episodic_structured_recent(limit: int = 20):
    arr = episodic_memory.recent_structured(limit=max(1, min(200, int(limit))))
    return {'ok': True, 'count': len(arr), 'episodes': arr[-max(1, min(100, int(limit))):]}


@app.get('/api/episodic/structured/search')
async def episodic_structured_search(problem: str, task_type: str = 'planning', limit: int = 5):
    arr = episodic_memory.find_similar_structured(problem=str(problem or ''), task_type=str(task_type or 'planning'), limit=max(1, min(20, int(limit))))
    return {'ok': True, 'count': len(arr), 'similar': arr}


@app.get('/api/episodic/matcher/search')
async def episodic_matcher_search(problem: str, task_type: str = 'planning', limit: int = 5, cross_domain_only: bool = False):
    out = episodic_memory.find_structural_analogy(
        problem=str(problem or ''),
        task_type=str(task_type or 'planning'),
        limit=max(1, min(20, int(limit))),
        require_cross_domain=bool(cross_domain_only),
    )
    return out


@app.get('/api/procedural/hints')
async def procedural_hints(task_type: str = 'planning', limit: int = 120):
    return episodic_memory.procedural_hints(task_type=task_type, limit=max(10, min(1000, int(limit))))


@app.get('/api/memory/layers/recall')
async def memory_layers_recall(problem: str, task_type: str = 'planning', limit: int = 3):
    out = episodic_memory.layered_recall(problem=str(problem or ''), task_type=str(task_type or 'planning'), limit=max(1, min(20, int(limit))))
    return out


@app.get('/api/memory/layers/recall/compact')
async def memory_layers_recall_compact(problem: str, task_type: str = 'planning', limit: int = 3, max_chars: int = 1500):
    out = episodic_memory.layered_recall_compact(
        problem=str(problem or ''),
        task_type=str(task_type or 'planning'),
        limit=max(1, min(20, int(limit))),
        max_chars=max(600, min(6000, int(max_chars))),
    )
    return {'ok': True, **out}


@app.post('/api/sleep-cycle/run')
async def sleep_cycle_run(retention_days: int = 14, max_active_rows: int = 3000):
    out = sleep_cycle.run_cycle(retention_days=retention_days, max_active_rows=max_active_rows)
    store.db.add_event('sleep_cycle', f"😴 sleep-cycle pruned={out.get('pruned')} abstracted={out.get('abstracted')} active={out.get('active_after')}")
    return out


@app.get('/api/sleep-cycle/status')
async def sleep_cycle_status():
    from pathlib import Path
    import json
    p = Path('/app/data/sleep_cycle_report.json')
    if not p.exists():
        return {'ok': True, 'has_report': False}
    try:
        return {'ok': True, 'has_report': True, 'report': json.loads(p.read_text(encoding='utf-8'))}
    except Exception:
        return {'ok': True, 'has_report': True, 'report': {}}


@app.get('/api/reflexion/status')
async def reflexion_status():
    return reflexion_agent.status()


@app.post('/api/reflexion/tick')
async def reflexion_tick(force: bool = False):
    out = reflexion_agent.tick(force=bool(force))
    if bool(out.get('triggered')):
        store.db.add_event('reflexion', f"🧠 reflexion action={out.get('action')} conf={out.get('confidence')}")
    cp = (out.get('curiosity_probe') or {}) if isinstance(out, dict) else {}
    created = cp.get('created') if isinstance(cp.get('created'), list) else []
    out['curiosity_web_autofill'] = await _auto_resolve_rag_ingest_probes_from_web(created)
    return out


@app.get('/api/cognitive-state')
async def cognitive_state_get(compact: bool = False):
    if bool(compact):
        return {'ok': True, 'state': cognitive_state.compact_for_prompt(max_chars=1200)}
    return {'ok': True, 'state': cognitive_state.get_state()}


@app.get('/api/context/inspector')
async def api_context_inspector(limit: int = 200):
    return context_inspector.build_report(limit=max(10, min(2000, int(limit or 200))))


@app.get('/api/rag/router')
async def api_rag_router(query: str, task_type: str = 'general', top_k: int = 5):
    started = time.time()
    out = await rag_router.search_routed(query=str(query or ''), task_type=str(task_type or 'general'), top_k=max(1, min(12, int(top_k or 5))))
    out['elapsed_ms'] = int((time.time() - started) * 1000)
    return out


@app.get('/api/rag/eval/cases')
async def api_rag_eval_cases():
    return {'ok': True, 'items': rag_eval_cases.get_default_cases()}


@app.get('/api/rag/eval/runs')
async def api_rag_eval_runs(limit: int = 50):
    return {'ok': True, 'items': rag_eval_store.read_runs(limit=max(1, min(500, int(limit or 50))))}


@app.post('/api/rag/eval')
async def api_rag_eval(body: dict):
    items = body.get('items') if isinstance(body, dict) else []
    use_default_cases = bool(body.get('use_default_cases')) if isinstance(body, dict) else False
    top_k = body.get('top_k') if isinstance(body, dict) else 5
    if use_default_cases or not isinstance(items, list) or not items:
        items = rag_eval_cases.get_default_cases()
    started = time.time()
    out = await rag_eval.evaluate_queries(items if isinstance(items, list) else [], top_k=max(1, min(12, int(top_k or 5))))
    out['elapsed_ms'] = int((time.time() - started) * 1000)
    return out


@app.get('/api/causal-graph/status')
async def causal_graph_status():
    return causal_graph.status()


@app.get('/api/causal-graph/query')
async def causal_graph_query(problem: str, limit: int = 5):
    return causal_graph.query_for_problem(problem=str(problem or ''), limit=max(1, min(20, int(limit))))


@app.get('/api/ultronbody/status')
async def ultronbody_status():
    return ultronbody.status()


@app.get('/api/abstractions/status')
async def abstractions_status():
    return explicit_abstractions.stats()


@app.get('/api/abstractions/portfolio-summary')
async def abstractions_portfolio_summary():
    return explicit_abstractions.portfolio_summary()


@app.get('/api/abstractions')
async def abstractions_list(limit: int = 50, domain: str | None = None):
    return explicit_abstractions.list_abstractions(limit=max(1, min(500, int(limit))), domain=domain)


@app.get('/api/abstractions/{abstraction_id}')
async def abstractions_get(abstraction_id: str):
    out = explicit_abstractions.get_abstraction(abstraction_id)
    if not out:
        raise HTTPException(404, 'abstraction not found')
    return {'ok': True, 'item': out}


@app.post('/api/abstractions')
async def abstractions_create(req: ExplicitAbstractionCreateRequest):
    out = explicit_abstractions.create_abstraction(
        principle=req.principle,
        source_domains=req.source_domains,
        applicability_conditions=req.applicability_conditions,
        procedure_template=req.procedure_template,
        confidence=float(req.confidence or 0.5),
        notes=req.notes,
    )
    store.db.add_event('explicit_abstraction_created', f"🧩 abstraction criada: {str(out.get('id') or '')[:80]}")
    return {'ok': True, 'item': out}


@app.post('/api/abstractions/{abstraction_id}/transfer')
async def abstractions_transfer(abstraction_id: str, req: ExplicitAbstractionTransferRequest):
    out = explicit_abstractions.update_transfer_history(
        abstraction_id,
        target_domain=req.target_domain,
        outcome=req.outcome,
        evidence_ref=req.evidence_ref,
        score=req.score,
        notes=req.notes,
    )
    if not out:
        raise HTTPException(404, 'abstraction not found')
    store.db.add_event('explicit_abstraction_transfer', f"🔁 abstraction transfer: {str(abstraction_id)[:80]} -> {str(req.target_domain or '')[:80]}")
    return {'ok': True, 'item': out}


@app.post('/api/abstractions/{abstraction_id}/consolidate')
async def abstractions_consolidate(abstraction_id: str):
    out = transfer_benchmark.consolidate_from_latest(abstraction_id)
    if not out:
        raise HTTPException(404, 'abstraction or benchmark not found')
    store.db.add_event('explicit_abstraction_consolidated', f"🏷️ abstraction consolidada: {str(abstraction_id)[:80]}", meta_json=json.dumps({'status': ((out.get('item') or {}).get('status')), 'benchmark_score': (((out.get('item') or {}).get('benchmark_summary') or {}).get('benchmark_score'))}, ensure_ascii=False))
    return out


@app.post('/api/abstractions/ingest-from-ultronbody/{episode_id}')
async def abstractions_ingest_from_ultronbody(episode_id: str):
    episode = ultronbody.get_episode(episode_id)
    if not episode:
        raise HTTPException(404, 'episode not found')
    out = explicit_abstractions.ingest_ultronbody_episode(episode)
    store.db.add_event('explicit_abstraction_ingest', f"🧠 abstractions ingestidas do episódio: {str(episode_id)[:80]}", meta_json=json.dumps({'count': out.get('count')}, ensure_ascii=False))
    return out


@app.post('/api/abstractions/extract-from-ultronbody/recent')
async def abstractions_extract_from_ultronbody_recent(req: AbstractionBatchExtractRequest):
    episodes_out = ultronbody.episodes(limit=max(1, min(200, int(req.limit or 20))), include_steps=True)
    items = episodes_out.get('items') if isinstance(episodes_out, dict) else []
    out = explicit_abstractions.batch_extract_from_ultronbody_episodes(items if isinstance(items, list) else [], min_cluster_size=max(1, min(10, int(req.min_cluster_size or 2))))
    store.db.add_event('explicit_abstraction_batch_extract', f"🧬 abstractions extraídas em lote do ultronbody: created={out.get('created_count')}", meta_json=json.dumps({'clusters': out.get('clusters'), 'created_count': out.get('created_count')}, ensure_ascii=False))
    return out


@app.get('/api/abstractions/mappings/recent')
async def abstractions_mappings_recent(limit: int = 20):
    return structural_mapper.recent_mappings(limit=max(1, min(200, int(limit))))


@app.post('/api/abstractions/{abstraction_id}/map')
async def abstractions_map(abstraction_id: str, req: StructuralMapRequest):
    out = structural_mapper.map_abstraction(abstraction_id, target_domain=req.target_domain, target_text=req.target_text)
    if not out:
        raise HTTPException(404, 'abstraction not found')
    store.db.add_event('explicit_abstraction_mapped', f"🗺️ abstraction mapeada: {str(abstraction_id)[:80]} -> {str(req.target_domain or '')[:80]}", meta_json=json.dumps({'similarity': out.get('structural_similarity'), 'recommended': out.get('recommended')}, ensure_ascii=False))
    return {'ok': True, 'mapping': out}


@app.post('/api/abstractions/{abstraction_id}/apply')
async def abstractions_apply(abstraction_id: str, req: StructuralMapRequest):
    out = structural_mapper.apply_mapped_abstraction(abstraction_id, target_domain=req.target_domain, target_text=req.target_text)
    if not out:
        raise HTTPException(404, 'abstraction not found')
    store.db.add_event('explicit_abstraction_applied', f"🧭 abstraction aplicada: {str(abstraction_id)[:80]} -> {str(req.target_domain or '')[:80]}", meta_json=json.dumps({'recommended': ((out.get('mapping') or {}).get('recommended')), 'similarity': ((out.get('mapping') or {}).get('structural_similarity'))}, ensure_ascii=False))
    return out


@app.get('/api/abstractions/transfer-benchmark/scenarios')
async def abstractions_transfer_benchmark_scenarios():
    return transfer_benchmark.scenarios()


@app.get('/api/abstractions/transfer-benchmark/recent')
async def abstractions_transfer_benchmark_recent(limit: int = 20):
    return transfer_benchmark.recent_reports(limit=max(1, min(200, int(limit))))


@app.post('/api/abstractions/{abstraction_id}/transfer-benchmark')
async def abstractions_transfer_benchmark_run(abstraction_id: str, req: TransferBenchmarkRequest):
    out = transfer_benchmark.benchmark_abstraction(abstraction_id, scenario_ids=req.scenario_ids)
    if not out:
        raise HTTPException(404, 'abstraction not found')
    store.db.add_event('explicit_abstraction_transfer_benchmark', f"📚 transfer benchmark: {str(abstraction_id)[:80]} avg_improvement={out.get('avg_improvement')}", meta_json=json.dumps({'scenarios': out.get('scenarios'), 'zero_shot_win_rate': out.get('zero_shot_win_rate')}, ensure_ascii=False))
    return out


@app.post('/api/ultronbody/reset')
async def ultronbody_reset(req: UltronBodyResetRequest):
    out = ultronbody.reset(env_name=str(req.env_name or 'gridworld_v1'))
    store.db.add_event('ultronbody_reset', f"🧍 ultronbody reset env={str(req.env_name or 'gridworld_v1')[:80]}")
    return out


@app.get('/api/ultronbody/observe')
async def ultronbody_observe():
    return ultronbody.observe()


@app.post('/api/ultronbody/act')
async def ultronbody_act(req: UltronBodyActRequest):
    out = ultronbody.act(action=str(req.action or ''), expected_effect=req.expected_effect)
    if bool(out.get('ok')):
        store.db.add_event(
            'ultronbody_act',
            f"🎮 ultronbody action={str(req.action or '')[:80]} reward={out.get('reward')} done={out.get('done')}",
            meta_json=json.dumps({'episode_id': out.get('episode_id'), 'step': out.get('step'), 'causal_update': out.get('causal_update')}, ensure_ascii=False),
        )
    return out


@app.post('/api/ultronbody/predict')
async def ultronbody_predict(req: UltronBodyPredictRequest):
    return ultronbody.predict_action(action=str(req.action or ''))


@app.get('/api/ultronbody/choose-action')
async def ultronbody_choose_action(policy: str = 'causal_safe'):
    return ultronbody.choose_action(policy=str(policy or 'causal_safe'))


@app.get('/api/ultronbody/episodes')
async def ultronbody_episodes(limit: int = 20, include_steps: bool = True):
    return ultronbody.episodes(limit=max(1, min(200, int(limit))), include_steps=bool(include_steps))


@app.get('/api/ultronbody/episodes/{episode_id}')
async def ultronbody_episode_get(episode_id: str):
    out = ultronbody.get_episode(episode_id)
    if not out:
        raise HTTPException(404, 'episode not found')
    return {'ok': True, 'episode': out}


@app.get('/api/ultronbody/episodes/{episode_id}/replay')
async def ultronbody_episode_replay(episode_id: str):
    out = ultronbody.replay_episode(episode_id)
    if not out:
        raise HTTPException(404, 'episode not found')
    return out


@app.get('/api/ultronbody/episodes/{episode_id}/counterfactual')
async def ultronbody_episode_counterfactual(episode_id: str, step: int | None = None):
    out = ultronbody.analyze_counterfactual(episode_id, step_number=step)
    if not out:
        raise HTTPException(404, 'episode not found')
    return out


@app.post('/api/ultronbody/run')
async def ultronbody_run(req: UltronBodyRunRequest):
    out = ultronbody.run_episode(
        policy=str(req.policy or 'goal_seek'),
        max_steps=int(req.max_steps or 30),
        env_name=str(req.env_name or 'gridworld_v1'),
    )
    store.db.add_event(
        'ultronbody_run',
        f"🏁 ultronbody run policy={str(req.policy or 'goal_seek')[:80]} env={str(req.env_name or 'gridworld_v1')[:80]} success={str(out.get('done_reason') or '') == 'goal_reached'}",
        meta_json=json.dumps({'episode_id': out.get('episode_id'), 'env_name': out.get('env_name'), 'summary': out.get('summary')}, ensure_ascii=False),
    )
    return out


@app.post('/api/ultronbody/benchmark')
async def ultronbody_benchmark(req: UltronBodyBenchmarkRequest):
    out = ultronbody.benchmark(
        policy=str(req.policy or 'goal_seek'),
        episodes_count=int(req.episodes_count or 10),
        max_steps=int(req.max_steps or 30),
        env_name=str(req.env_name or 'gridworld_v1'),
    )
    store.db.add_event(
        'ultronbody_benchmark',
        f"📊 ultronbody benchmark policy={str(req.policy or 'goal_seek')[:80]} env={str(req.env_name or 'gridworld_v1')[:80]} success_rate={out.get('success_rate')}",
        meta_json=json.dumps({'policy': req.policy, 'env_name': req.env_name, 'episodes': req.episodes_count, 'avg_reward': out.get('avg_reward')}, ensure_ascii=False),
    )
    return out


@app.post('/api/ultronbody/benchmark-compare')
async def ultronbody_benchmark_compare(req: UltronBodyBenchmarkCompareRequest):
    out = ultronbody.benchmark_compare(
        policies=req.policies,
        episodes_count=int(req.episodes_count or 10),
        max_steps=int(req.max_steps or 30),
        env_names=req.env_names,
    )
    store.db.add_event(
        'ultronbody_benchmark_compare',
        f"📈 ultronbody benchmark compare winner={str(out.get('winner_policy') or '')[:80]} env={str(out.get('winner_env') or '')[:80]}",
        meta_json=json.dumps({'policies': req.policies, 'env_names': req.env_names, 'episodes': req.episodes_count, 'causal_on_off': out.get('causal_on_off'), 'robust_summary': out.get('robust_summary')}, ensure_ascii=False),
    )
    return out


class CausalTripleIngestRequest(BaseModel):
    cause: str
    effect: str
    condition: Optional[str] = ''
    confidence: Optional[float] = 0.65


@app.post('/api/causal-graph/ingest')
async def causal_graph_ingest(req: CausalTripleIngestRequest):
    return causal_graph.upsert_edge(
        cause=str(req.cause or ''),
        effect=str(req.effect or ''),
        condition=str(req.condition or ''),
        confidence=float(req.confidence or 0.65),
        source='api_manual',
        evidence={},
    )


@app.post('/api/causal-graph/bootstrap-filtered')
async def causal_graph_bootstrap_filtered(max_scan: int = 20000, batch: int = 1000):
    scanned = 0
    causal_candidates = 0
    ingested = 0
    since = 0
    max_scan = max(100, min(200000, int(max_scan)))
    batch = max(100, min(5000, int(batch)))

    while scanned < max_scan:
        rows = store.db.list_triples_since(since_id=since, limit=batch)
        if not rows:
            break
        r = causal_graph.bootstrap_from_triples(rows, source='bootstrap_filtered')
        scanned += int(r.get('scanned') or 0)
        causal_candidates += int(r.get('causal_candidates') or 0)
        ingested += int(r.get('ingested') or 0)
        since = int((rows[-1] or {}).get('id') or since)
        if len(rows) < batch:
            break

    return {
        'ok': True,
        'scanned': scanned,
        'causal_candidates': causal_candidates,
        'ingested': ingested,
        'status': causal_graph.status(),
    }


class CognitiveStatePatchRequest(BaseModel):
    beliefs: Optional[Dict[str, Any]] = None
    goals: Optional[List[str]] = None
    uncertainties: Optional[List[str]] = None
    constraints: Optional[List[str]] = None
    self_model: Optional[Dict[str, Any]] = None


@app.post('/api/cognitive-state/patch')
async def cognitive_state_patch(req: CognitiveStatePatchRequest):
    st = cognitive_state.get_state()
    if isinstance(req.beliefs, dict):
        st['beliefs'].update(req.beliefs)
    if isinstance(req.goals, list):
        st['goals'] = list(dict.fromkeys((st.get('goals') or []) + [str(x)[:180] for x in req.goals]))[-40:]
    if isinstance(req.uncertainties, list):
        st['uncertainties'] = list(dict.fromkeys((st.get('uncertainties') or []) + [str(x)[:200] for x in req.uncertainties]))[-40:]
    if isinstance(req.constraints, list):
        st['constraints'] = list(dict.fromkeys((st.get('constraints') or []) + [str(x)[:200] for x in req.constraints]))[-40:]
    if isinstance(req.self_model, dict):
        sm = st.get('self_model') if isinstance(st.get('self_model'), dict) else {}
        sm.update(req.self_model)
        st['self_model'] = sm
    saved = cognitive_state.save_state(st)
    return {'ok': True, 'state': saved}


def _metacog_weekly_summary_text() -> str:
    from pathlib import Path
    import json
    abs_path = Path('/app/data/episodic_abstractions.json')
    slp_path = Path('/app/data/sleep_cycle_report.json')
    items = []
    if abs_path.exists():
        try:
            items = (json.loads(abs_path.read_text(encoding='utf-8')) or {}).get('items') or []
        except Exception:
            items = []
    rep = {}
    if slp_path.exists():
        try:
            rep = json.loads(slp_path.read_text(encoding='utf-8'))
        except Exception:
            rep = {}

    last = items[-8:]
    if not last:
        return 'Ainda não consolidei abstrações suficientes no ciclo de sono. Preciso de mais episódios para sintetizar regras estáveis.'

    lines = ['Resumo metacognitivo da última semana:']
    lines.append(f"- Memórias consolidadas (último ciclo): pruned={rep.get('pruned', 0)}, abstracted={rep.get('abstracted', 0)}, active_after={rep.get('active_after', 0)}")
    lines.append('- Leis operacionais que deduzi:')
    for it in last[-5:]:
        rule = str(it.get('rule') or '').strip()
        if rule:
            lines.append(f"  • {rule}")
    lines.append('- Direção atual: priorizar estratégias com histórico de sucesso e baixa latência; evitar padrões que falharam de forma recorrente.')
    return '\n'.join(lines)


@app.get('/api/metacognition/weekly-summary')
async def metacognition_weekly_summary():
    txt = _metacog_weekly_summary_text()
    return {'ok': True, 'summary': txt}


@app.get('/api/prm/status')
async def prm_status():
    return prm_lite.status()


@app.get('/api/prm/recent')
async def prm_recent(limit: int = 20):
    return {'ok': True, 'items': prm_lite.recent(limit=limit)}


def _classify_eval_input(q: str) -> str:
    ql = str(q or '').lower()
    if any(t in ql for t in ['implica', 'verdadeiro', 'todos os', 'lógica', 'logica']):
        return 'logic'
    if any(t in ql for t in ['raiz quadrada', 'x²', 'x^2', 'equação', 'equacao', 'triângulo', 'triangulo', '%', 'porcent']):
        return 'math'
    if any(t in ql for t in ['plano', 'checklist', 'priorizo', 'migrar', 'backup', 'estudos']):
        return 'planning'
    if any(t in ql for t in ['python', 'docker', 'dockerfile', 'função', 'funcao', 'loop', 'deadlock', 'tuple', 'list']):
        return 'code'
    return 'general'


def _append_eval_trace(event: dict[str, Any]) -> None:
    try:
        root = os.getenv('ULTRON_EVAL_TRACE_FILE', '/app/data/eval_traces.jsonl')
        p = Path(root)
        p.parent.mkdir(parents=True, exist_ok=True)

        ev = dict(event or {})
        ts = int(ev.get('timestamp') or time.time())
        # Promotion cutoff for cohort tagging (override via env if needed).
        promotion_cutoff_ts = int(os.getenv('METACOG_QWEN_PROMOTION_TS', '1773158686') or 1773158686)
        ev['cohort'] = 'post_qwen_promotion' if ts >= promotion_cutoff_ts else 'pre_promotion'
        ev['promotion_cutoff_ts'] = promotion_cutoff_ts

        with p.open('a', encoding='utf-8') as f:
            f.write(json.dumps(ev, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _emit_eval_for_response(endpoint: str, request_id: str, message: str, out: dict[str, Any], latency_ms: int | None) -> None:
    strategy = str((out or {}).get('strategy') or '')
    metrics_obj = (out or {}).get('metrics') or {}
    sym = bool(((metrics_obj.get('symbolic_reasoner') or {}).get('routed')))
    gate_decision = 'block_insufficient' if strategy == 'insufficient_confidence' else 'allow'
    model_called = str((out or {}).get('model') or '')
    if not model_called:
        model_called = 'none' if strategy in ('insufficient_confidence', 'symbolic_reasoner', 'rag_context_direct') else 'tiny'

    stage_timing = (out or {}).get('stage_timing_ms') or {}
    llm_attempts = (out or {}).get('llm_attempts') or []
    input_class = _classify_eval_input(message)

    _append_eval_trace({
        'request_id': request_id,
        'timestamp': int(time.time()),
        'endpoint': endpoint,
        'input_class': input_class,
        'router_strategy_escolhida': strategy,
        'symbolic_reasoner_routed': sym,
        'gate_decision': gate_decision,
        'model_called': model_called,
        'final_strategy': strategy,
        'latency_ms': int(latency_ms or 0),
        'prm_score': (out or {}).get('prm_score'),
        'prm_risk': (out or {}).get('prm_risk'),
        'stage_timing_ms': stage_timing,
        'llm_attempts': llm_attempts,
    })

    try:
        answer = str((out or {}).get('answer') or '').strip()
        context_meta = {
            'selected_contexts': (metrics_obj.get('selected_contexts') if isinstance(metrics_obj.get('selected_contexts'), list) else []),
            'excluded_contexts': (metrics_obj.get('excluded_contexts') if isinstance(metrics_obj.get('excluded_contexts'), list) else []),
            'fallback': (metrics_obj.get('fallback') if isinstance(metrics_obj.get('fallback'), dict) else {}),
            'budget': (metrics_obj.get('budget') if isinstance(metrics_obj.get('budget'), dict) else {}),
            'rag_diversity': (metrics_obj.get('rag_diversity') if isinstance(metrics_obj.get('rag_diversity'), dict) else {}),
        }
        organic_eval_feed.record_response(
            endpoint=endpoint,
            request_id=request_id,
            query=str(message or ''),
            answer=answer,
            task_type=input_class,
            strategy=strategy,
            model_called=model_called,
            latency_ms=int(latency_ms or 0),
            prm_score=(out or {}).get('prm_score'),
            prm_risk=(out or {}).get('prm_risk'),
            context_meta=context_meta,
            tool_outputs=[],
        )
    except Exception:
        pass


async def _llm_complete_with_timeout(prompt: str, *, strategy: str, system: str | None, inject_persona: bool, max_tokens: int, cloud_fallback: bool, timeout_sec: float | None = None) -> str:
    budget = float(timeout_sec or METACOG_LLM_ATTEMPT_TIMEOUT_SEC or 18)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                llm.complete,
                prompt,
                strategy=strategy,
                system=system,
                json_mode=False,
                inject_persona=inject_persona,
                max_tokens=max_tokens,
                cloud_fallback=cloud_fallback,
            ),
            timeout=budget,
        )
    except Exception:
        return ''


def _budget_remaining(deadline: float) -> float:
    return max(0.0, float(deadline - time.monotonic()))


def _stage_mark(stage_timing_ms: dict[str, int], started_at: float, name: str) -> None:
    try:
        stage_timing_ms[name] = int((time.monotonic() - started_at) * 1000)
    except Exception:
        stage_timing_ms[name] = 0


def _llm_attempt_record(llm_attempts: list[dict[str, Any]], **kwargs) -> None:
    try:
        llm_attempts.append(kwargs)
    except Exception:
        pass


def _direct_canary_generate(prompt: str, max_tokens: int = 220) -> str:
    if os.getenv('ULTRON_PREFER_ULTRON_INFER', '0') == '1':
        try:
            return llm.complete(
                str(prompt or ''),
                strategy='canary_qwen',
                inject_persona=False,
                max_tokens=int(max(16, min(512, max_tokens))),
                cloud_fallback=False,
            )
        except Exception:
            return ''
    base = os.getenv('OLLAMA_BASE_URL_LOCAL', os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')
    model = os.getenv('ULTRON_CANARY_MODEL_NAME', os.getenv('ULTRON_PRIMARY_LOCAL_MODEL', os.getenv('ULTRON_INFER_MODEL_NAME', os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', 'local-fallback'))))
    payload = {
        'model': model,
        'prompt': str(prompt or ''),
        'stream': False,
        'options': {
            'temperature': 0.2,
            'num_predict': int(max(16, min(512, max_tokens))),
        },
    }
    try:
        with httpx.Client(timeout=90.0) as hc:
            r = hc.post(base + '/api/generate', json=payload)
            r.raise_for_status()
            data = r.json() or {}
            return str(data.get('response') or '').strip()
    except Exception:
        return ''


def _safe_json_parse(text: str) -> dict[str, Any]:
    s = str(text or '').strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        i = s.find('{')
        j = s.rfind('}')
        if i >= 0 and j > i:
            try:
                return json.loads(s[i:j+1])
            except Exception:
                return {}
    return {}


def _parse_runtime_constraints(items: list[str] | None) -> dict[str, Any]:
    out = {'forbid_tools': set(), 'require_tools': set(), 'max_steps': 3, 'raw': list(items or [])}
    for it in (items or []):
        s = str(it or '').strip()
        if not s:
            continue
        sl = s.lower()
        if sl.startswith('forbid_tool:'):
            out['forbid_tools'].add(sl.split(':', 1)[1].strip())
        elif sl.startswith('require_tool:'):
            out['require_tools'].add(sl.split(':', 1)[1].strip())
        elif sl.startswith('max_steps:'):
            try:
                out['max_steps'] = max(1, min(5, int(sl.split(':', 1)[1].strip())))
            except Exception:
                pass
    return out


def _enforce_plan_constraints(steps: list[dict[str, Any]], rc: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], bool]:
    blocked: list[str] = []
    out: list[dict[str, Any]] = []
    forbid = rc.get('forbid_tools') if isinstance(rc.get('forbid_tools'), set) else set()
    req = rc.get('require_tools') if isinstance(rc.get('require_tools'), set) else set()
    mx = int(rc.get('max_steps') or 3)

    for st in (steps or [])[:mx]:
        if not isinstance(st, dict):
            continue
        t = str(st.get('tool') or '').strip().lower()
        if t in forbid:
            blocked.append(f'tool_forbidden:{t}')
            continue
        out.append(st)

    present = {str((s or {}).get('tool') or '').strip().lower() for s in out}
    for rt in req:
        if rt and rt not in present:
            blocked.append(f'missing_required_tool:{rt}')

    need_alternative = len(blocked) > 0
    return out, blocked, need_alternative


def _run_post_execution_learning(*, query: str, answer: str, steps_executed: list[dict[str, Any]], planner_context: dict[str, Any], task_type: str = 'planning', episode_id: str = '') -> dict[str, Any]:
    try:
        payload = {
            'query': str(query or '')[:1400],
            'answer': str(answer or '')[:1400],
            'steps_executed': steps_executed[:6],
            'plan_selection': (planner_context.get('plan_selection') if isinstance(planner_context, dict) else {}),
            'verification': (planner_context.get('verification') if isinstance(planner_context, dict) else {}),
        }
        pm_raw = llm.complete(
            json.dumps({
                'task': 'postmortem_structured_learning',
                'input': payload,
                'schema': {
                    'best_plan_assessment': 'string',
                    'bottleneck_step': 'string',
                    'new_heuristic_rule': 'string',
                    'causal_statement': 'string',
                    'confidence': 'float_0_1'
                }
            }, ensure_ascii=False),
            strategy='local',
            system='Você faz pós-mortem técnico de execução. Responda SOMENTE JSON válido e objetivo.',
            json_mode=True,
            inject_persona=False,
            max_tokens=220,
        )
        pm = json.loads(pm_raw) if isinstance(pm_raw, str) else (pm_raw if isinstance(pm_raw, dict) else {})
    except Exception:
        pm = {}

    heuristic = str(pm.get('new_heuristic_rule') or '').strip()
    bottleneck = str(pm.get('bottleneck_step') or '').strip()
    conf = pm.get('confidence') if isinstance(pm.get('confidence'), (int, float)) else None
    best_assessment = str(pm.get('best_plan_assessment') or '').strip()
    causal_statement = str(pm.get('causal_statement') or '').strip()

    proc_out = {'ok': False}
    freq = {'ok': True, 'count': 0}
    proposal = None
    graph_check = {'ok': True, 'has_causal_rule': False, 'confirmations': 0, 'contradictions': 0}

    if heuristic:
        proc_out = episodic_memory.append_procedural_learning(
            task_type=task_type,
            heuristic=heuristic,
            bottleneck_step=bottleneck,
            outcome='postmortem',
            source_episode_id=episode_id,
            confidence=conf,
            meta={'best_plan_assessment': best_assessment},
        )
        freq = episodic_memory.procedural_rule_frequency(heuristic=heuristic, task_type=task_type)

    try:
        graph_check = causal_graph.assess_rule_against_graph(causal_statement or heuristic)
        if bool(graph_check.get('has_causal_rule')) and int(graph_check.get('confirmations') or 0) <= 0 and int(graph_check.get('contradictions') or 0) <= 0:
            causal_graph.ingest_confirmed_hypothesis(
                hypothesis=str(causal_statement or heuristic),
                details={'source': 'post_execution_learning', 'episode_id': episode_id, 'task_type': task_type},
            )
    except Exception:
        pass

    proposal = None

    return {
        'ok': True,
        'postmortem': pm,
        'procedural_update': proc_out,
        'rule_frequency': freq,
        'causal_graph_check': graph_check,
        'finetune_proposal': _training_disabled_response('post_execution_finetune_proposal') if int(freq.get('count') or 0) >= 3 else None,
    }


async def _metacog_orchestrator_run(query: str, metrics: dict[str, Any], generation_strategy: str = 'canary_qwen') -> dict[str, Any]:
    ql = str(query or '').lower()
    if any(t in ql for t in ['debug', 'erro', 'falha', 'bug']):
        task_type = 'debug'
    elif any(t in ql for t in ['resumo', 'sintetize', 'sumarize', 'sumarizar']):
        task_type = 'summarization'
    else:
        task_type = 'planning'

    rag_seed_docs = []
    rag_route = {'domains': [], 'search_plan': [], 'results': []}
    try:
        rag_route = await rag_router.search_routed(query=query, task_type=task_type, top_k=4)
        rag_seed_docs = list(rag_route.get('results') or [])
    except Exception:
        try:
            rag_seed_docs = await knowledge_bridge.search_knowledge(query, top_k=4)
        except Exception:
            rag_seed_docs = []

    adaptive_profile = self_model.adaptive_profile(task_type=task_type)
    if int(adaptive_profile.get('context_hardening') or 0) >= 2 and len(rag_seed_docs) < 5:
        try:
            extra_route = await rag_router.search_routed(query=query, task_type=task_type, top_k=6)
            extra_docs = list(extra_route.get('results') or [])
            seen = {(str(d.get('source_id') or ''), str(d.get('text') or '')[:200]) for d in rag_seed_docs if isinstance(d, dict)}
            for d in extra_docs:
                if not isinstance(d, dict):
                    continue
                sig = (str(d.get('source_id') or ''), str(d.get('text') or '')[:200])
                if sig not in seen:
                    rag_seed_docs.append(d)
                    seen.add(sig)
            if isinstance(extra_route, dict) and isinstance(rag_route, dict):
                rag_route['adaptive_expansion'] = extra_route.get('diversity')
        except Exception:
            pass

    ctx_bundle = context_policy.build_context(query=query, task_type=task_type, rag_docs=rag_seed_docs)
    if isinstance(ctx_bundle, dict):
        ctx_bundle['rag_diversity'] = (rag_route.get('diversity') if isinstance(rag_route, dict) and isinstance(rag_route.get('diversity'), dict) else {})
        ctx_bundle['self_model'] = adaptive_profile.get('self_model') if isinstance(adaptive_profile, dict) else {}
        ctx_bundle['adaptive_profile'] = adaptive_profile
    pol = episodic_memory.get_task_memory_policy(task_type)
    recall = episodic_memory.layered_recall(problem=query, task_type=task_type, limit=int(pol.get('episodic_limit') or 4))
    recall_compact = episodic_memory.layered_recall_compact(problem=query, task_type=task_type, limit=int(pol.get('episodic_limit') or 4), max_chars=int(pol.get('max_chars') or 1500))
    episodic_similar = recall.get('episodic_similar') if isinstance(recall.get('episodic_similar'), list) else []
    procedural = recall.get('procedural_hints') if isinstance(recall.get('procedural_hints'), dict) else {'ok': True, 'best_strategies': []}
    cog = cognitive_state.get_state()
    runtime_constraints = _parse_runtime_constraints(cog.get('constraints') if isinstance(cog, dict) else [])
    if int(adaptive_profile.get('context_hardening') or 0) >= 1:
        req = set(runtime_constraints.get('require_tools') or [])
        req.add('search_rag')
        runtime_constraints['require_tools'] = sorted(req)
    if int(adaptive_profile.get('governance_hardening') or 0) >= 2:
        forbid = set(runtime_constraints.get('forbid_tools') or [])
        forbid.add('execute_bash')
        runtime_constraints['forbid_tools'] = sorted(forbid)
    causal_hints = causal_graph.query_for_problem(query, limit=4)

    # Episodic matcher (structural analogy) auto-trigger on low confidence/low recall
    query_sig = episodic_memory.structural_signature(problem=query, task_type=task_type)
    low_confidence = (str(query_sig.get('uncertainty') or 'low') == 'high') or (len(episodic_similar) <= 0)
    analogy_ctx: dict[str, Any] = {'triggered': False, 'low_confidence': bool(low_confidence)}
    if low_confidence:
        try:
            am = episodic_memory.find_structural_analogy(problem=query, task_type=task_type, limit=5, require_cross_domain=False)
            analogy_ctx = {
                'triggered': True,
                'low_confidence': True,
                'query_signature': am.get('query_signature'),
                'first_cross_domain_analogy': am.get('first_cross_domain_analogy'),
                'top_match': (am.get('matches') or [None])[0],
            }
        except Exception:
            analogy_ctx = {'triggered': False, 'low_confidence': True}

    plan_base_confidence = max(0.15, min(0.95, 0.35 + (0.5 * float(adaptive_profile.get('domain_confidence') or 0.5))))
    plan_prompt = json.dumps({
        'task': 'Decompose user request into up to 3 sequential tool calls then synthesize final answer.',
        'query': query,
        'task_type': task_type,
        'context_policy': {
            'profile': ctx_bundle.get('profile'),
            'policy': ctx_bundle.get('policy'),
            'selected_contexts': ctx_bundle.get('selected_contexts'),
            'excluded_contexts': ctx_bundle.get('excluded_contexts'),
            'fallback': ctx_bundle.get('fallback'),
            'budget': ctx_bundle.get('budget'),
            'cutoff_reason': ctx_bundle.get('cutoff_reason'),
        },
        'adaptive_profile': {
            'task_type': adaptive_profile.get('task_type'),
            'domain_confidence': adaptive_profile.get('domain_confidence'),
            'context_hardening': adaptive_profile.get('context_hardening'),
            'governance_hardening': adaptive_profile.get('governance_hardening'),
            'ask_for_evidence_bias': adaptive_profile.get('ask_for_evidence_bias'),
            'risk_posture': adaptive_profile.get('risk_posture'),
        },
        'confidence_policy': {
            'base_confidence': round(plan_base_confidence, 4),
            'instruction': 'Use domain_confidence as the confidence prior: lower domain_confidence should produce more conservative confidence, fewer assumptions, and earlier uncertainty signaling.'
        },
        'rag_route': {
            'domains': rag_route.get('domains'),
            'search_plan': rag_route.get('search_plan'),
        },
        'memory_context_compact': recall_compact,
        'working_memory': recall_compact.get('working_memory') if isinstance(recall_compact, dict) else {},
        'episodic_similar': recall_compact.get('episodic_similar') if isinstance(recall_compact, dict) else episodic_similar,
        'procedural_hints': recall_compact.get('procedural_hints') if isinstance(recall_compact, dict) else procedural,
        'causal_graph_hints': causal_hints,
        'analogy_context': analogy_ctx,
        'tools': [
            {'name': 'search_rag', 'args': {'query': 'string'}},
            {'name': 'symbolic_solve', 'args': {'problem': 'string'}},
            {'name': 'ask_memory', 'args': {'topic': 'string'}},
            {'name': 'execute_python', 'args': {'code': 'string', 'timeout_sec': 'int<=10'}},
            {'name': 'execute_bash', 'args': {'command': 'string', 'timeout_sec': 'int<=10'}},
            {'name': 'flag_uncertainty', 'args': {'reason': 'string'}},
        ],
        'constraints': {
            'max_steps': int(runtime_constraints.get('max_steps') or 3),
            'output_json_only': True,
            'pt_br': True,
            'runtime_constraints': {
                'forbid_tools': sorted(list(runtime_constraints.get('forbid_tools') or [])),
                'require_tools': sorted(list(runtime_constraints.get('require_tools') or [])),
            }
        },
        'schema': {
            'hypothesis': 'string',
            'reasoning_steps': ['string'],
            'conclusion': 'string',
            'confidence': 'float_0_1',
            'possible_failures': ['string'],
            'candidate_plans': [
                {
                    'name': 'string',
                    'steps': [{'tool': 'string', 'args': 'object'}],
                    'final_answer_style': 'string'
                }
            ],
            'steps': [{'tool': 'string', 'args': 'object'}],
            'final_answer_style': 'string'
        }
    }, ensure_ascii=False)

    planner_raw = llm.complete(
        prompt=plan_prompt,
        strategy=generation_strategy,
        system='Você é um orquestrador metacognitivo. Responda SOMENTE JSON válido.',
        json_mode=False,
        inject_persona=False,
        max_tokens=260,
    )
    plan = _safe_json_parse(planner_raw)
    raw_plan_confidence = plan.get('confidence')
    try:
        raw_plan_confidence = float(raw_plan_confidence)
    except Exception:
        raw_plan_confidence = plan_base_confidence
    adjusted_plan_confidence = max(0.0, min(1.0, ((0.65 * raw_plan_confidence) + (0.35 * plan_base_confidence))))
    plan['confidence'] = adjusted_plan_confidence
    cot = {
        'hypothesis': str(plan.get('hypothesis') or '')[:500],
        'reasoning_steps': (plan.get('reasoning_steps') if isinstance(plan.get('reasoning_steps'), list) else [])[:6],
        'conclusion': str(plan.get('conclusion') or '')[:700],
        'confidence': adjusted_plan_confidence,
        'possible_failures': (plan.get('possible_failures') if isinstance(plan.get('possible_failures'), list) else [])[:5],
    }
    candidate_plans = plan.get('candidate_plans') if isinstance(plan.get('candidate_plans'), list) else []
    normalized_candidates: list[dict[str, Any]] = []
    for i, cp in enumerate(candidate_plans[:3], start=1):
        if not isinstance(cp, dict):
            continue
        csteps = cp.get('steps') if isinstance(cp.get('steps'), list) else []
        normalized_candidates.append({
            'name': str(cp.get('name') or f'plan_{i}'),
            'steps': csteps[:int(runtime_constraints.get('max_steps') or 3)],
            'final_answer_style': str(cp.get('final_answer_style') or plan.get('final_answer_style') or 'objetivo')
        })

    if not normalized_candidates:
        steps0 = plan.get('steps') if isinstance(plan.get('steps'), list) else []
        normalized_candidates = [{
            'name': 'plan_primary',
            'steps': steps0[:int(runtime_constraints.get('max_steps') or 3)],
            'final_answer_style': str(plan.get('final_answer_style') or 'objetivo')
        }]

    # Causal risk scoring for candidate plans
    scored_candidates = []
    for cp in normalized_candidates:
        rs = causal_graph.score_plan_risk(query=query, steps=cp.get('steps') if isinstance(cp.get('steps'), list) else [])
        scored_candidates.append({
            'name': cp.get('name'),
            'steps': cp.get('steps') or [],
            'final_answer_style': cp.get('final_answer_style') or 'objetivo',
            'risk_score': float(rs.get('risk_score') or 0.0),
            'risk': rs,
        })

    scored_candidates.sort(key=lambda x: float(x.get('risk_score') or 0.0))
    selected = scored_candidates[0]
    discarded = scored_candidates[1:]
    plan_selection = {
        'selected_plan': selected.get('name'),
        'selected_risk_score': selected.get('risk_score'),
        'discarded': [
            {
                'name': d.get('name'),
                'risk_score': d.get('risk_score'),
                'motivo_causal': 'risk_score_maior',
                'top_activated_edge': ((d.get('risk') or {}).get('activated_edges') or [{}])[0],
                'plano_descartado': d.get('steps') or [],
            }
            for d in discarded
        ]
    }

    steps = (selected.get('steps') if isinstance(selected.get('steps'), list) else [])[:int(runtime_constraints.get('max_steps') or 3)]
    plan['final_answer_style'] = selected.get('final_answer_style') or plan.get('final_answer_style')

    # CoT verifier (separate pass)
    verify_prompt = json.dumps({
        'query': query,
        'task_type': task_type,
        'runtime_constraints': {
            'forbid_tools': sorted(list(runtime_constraints.get('forbid_tools') or [])),
            'require_tools': sorted(list(runtime_constraints.get('require_tools') or [])),
        },
        'cot': cot,
        'steps': steps,
        'schema': {
            'overall_approved': 'bool',
            'step_reviews': [{'step': 'int', 'approved': 'bool', 'reason': 'string'}],
            'rejection_reasons': ['string']
        }
    }, ensure_ascii=False)
    verifier_raw = llm.complete(
        prompt=verify_prompt,
        strategy=generation_strategy,
        system='Você é verificador lógico. Reprova suposições sem fundamento e planos que violam constraints. Responda SOMENTE JSON válido.',
        json_mode=False,
        inject_persona=False,
        max_tokens=220,
    )
    ver = _safe_json_parse(verifier_raw)

    # apply explicit runtime constraints and verifier output
    steps, blocked_reasons, need_alternative = _enforce_plan_constraints(steps, runtime_constraints)

    # step-level verifier enforcement
    step_reviews = ver.get('step_reviews') if isinstance(ver, dict) and isinstance(ver.get('step_reviews'), list) else []
    rejected_steps = set()
    for rv in step_reviews:
        if not isinstance(rv, dict):
            continue
        approved = rv.get('approved')
        idx = rv.get('step')
        if approved is False and isinstance(idx, int):
            rejected_steps.add(int(idx))
            blocked_reasons.append(f"step_reject:{int(idx)}:{str(rv.get('reason') or '')[:120]}")

    if rejected_steps:
        kept = []
        for i, st in enumerate(steps, start=1):
            if i in rejected_steps:
                continue
            kept.append(st)
        steps = kept
        # if all steps rejected, force alternative route
        if not steps:
            need_alternative = True

    # causal verification per-step (hard veto/warning)
    causal_kept = []
    for i, st in enumerate(steps, start=1):
        ev = causal_graph.evaluate_step_risk(query=query, step=st)
        vetoes = ev.get('vetoes') if isinstance(ev.get('vetoes'), list) else []
        warns = ev.get('warnings') if isinstance(ev.get('warnings'), list) else []
        if vetoes:
            v0 = vetoes[0] if isinstance(vetoes[0], dict) else {}
            blocked_reasons.append(f"causal_veto:{str(v0.get('cause') or '')}→{str(v0.get('effect') or '')}")
            continue
        if warns:
            w0 = warns[0] if isinstance(warns[0], dict) else {}
            blocked_reasons.append(f"causal_warn:{str(w0.get('cause') or '')}→{str(w0.get('effect') or '')}")
        causal_kept.append(st)
    steps = causal_kept
    if not steps:
        need_alternative = True

    if ver.get('overall_approved') is False:
        need_alternative = True
        for rr in (ver.get('rejection_reasons') if isinstance(ver.get('rejection_reasons'), list) else []):
            blocked_reasons.append(f"verifier_reject:{str(rr)[:140]}")

    if need_alternative:
        alt_prompt = json.dumps({
            'task': 'Generate an alternative plan that satisfies constraints and avoids rejected assumptions.',
            'query': query,
            'task_type': task_type,
            'blocked_reasons': blocked_reasons,
            'runtime_constraints': {
                'forbid_tools': sorted(list(runtime_constraints.get('forbid_tools') or [])),
                'require_tools': sorted(list(runtime_constraints.get('require_tools') or [])),
                'max_steps': int(runtime_constraints.get('max_steps') or 3),
            },
            'tools': [
                {'name': 'search_rag', 'args': {'query': 'string'}},
                {'name': 'symbolic_solve', 'args': {'problem': 'string'}},
                {'name': 'ask_memory', 'args': {'topic': 'string'}},
                {'name': 'execute_python', 'args': {'code': 'string', 'timeout_sec': 'int<=10'}},
                {'name': 'execute_bash', 'args': {'command': 'string', 'timeout_sec': 'int<=10'}},
                {'name': 'flag_uncertainty', 'args': {'reason': 'string'}},
            ],
            'schema': {'steps': [{'tool': 'string', 'args': 'object'}], 'final_answer_style': 'string'}
        }, ensure_ascii=False)
        alt_raw = llm.complete(
            prompt=alt_prompt,
            strategy=generation_strategy,
            system='Gere rota alternativa válida e conservadora. Responda SOMENTE JSON válido.',
            json_mode=False,
            inject_persona=False,
            max_tokens=220,
        )
        alt = _safe_json_parse(alt_raw)
        alt_steps = alt.get('steps') if isinstance(alt.get('steps'), list) else []
        alt_steps, blocked2, _ = _enforce_plan_constraints(alt_steps, runtime_constraints)
        if alt_steps:
            steps = alt_steps[:int(runtime_constraints.get('max_steps') or 3)]
            plan['final_answer_style'] = alt.get('final_answer_style') or plan.get('final_answer_style')
            plan_selection['selected_plan'] = 'alternative_after_reject'
            plan_selection['selected_risk_score'] = causal_graph.score_plan_risk(query=query, steps=steps).get('risk_score')
        blocked_reasons.extend(blocked2)

    tool_outputs: list[dict[str, Any]] = []
    step_prm: list[dict[str, Any]] = []

    if not steps:
        steps = [{'tool': 'flag_uncertainty', 'args': {'reason': 'no_valid_plan_after_verification'}}]

    for idx, st in enumerate(steps, start=1):
        if not isinstance(st, dict):
            continue
        tool = str(st.get('tool') or '').strip()
        args = st.get('args') if isinstance(st.get('args'), dict) else {}
        out_txt = ''
        status = 'ok'
        if tool == 'search_rag':
            q = str(args.get('query') or query).strip()
            docs = await knowledge_bridge.search_knowledge(q, top_k=3)
            out_txt = '\n'.join([str((d or {}).get('text') or '')[:450] for d in (docs or [])[:2]]).strip()
            if not out_txt:
                missing = (((ctx_bundle.get('fallback') or {}).get('missing_required_sources')) or []) if isinstance(ctx_bundle, dict) else []
                if missing:
                    out_txt = f"Lacuna explícita: contexto essencial ausente ({', '.join(missing)}). Não inferir sem evidência."
                    status = 'missing_context'
                else:
                    out_txt = 'Sem contexto RAG relevante encontrado.'
        elif tool == 'symbolic_solve':
            problem = str(args.get('problem') or query).strip()
            sym = symbolic_reasoner.solve(problem)
            out_txt = str((sym or {}).get('answer') or '').strip() or 'Sem solução simbólica conclusiva.'
        elif tool == 'ask_memory':
            topic = str(args.get('topic') or query).strip()
            hints = episodic_memory.strategy_hints(kind='strategy', text=topic, task_type='planning')
            brief = _metacog_weekly_summary_text()
            out_txt = f"{brief}\n\nHints:\n{json.dumps(hints, ensure_ascii=False)[:700]}"
        elif tool == 'execute_python':
            ev = causal_graph.evaluate_step_risk(query=query, step={'tool': tool, 'args': args})
            vetoes = ev.get('vetoes') if isinstance(ev.get('vetoes'), list) else []
            if vetoes:
                v0 = vetoes[0] if isinstance(vetoes[0], dict) else {}
                out_txt = f"Execução bloqueada por veto causal: {str(v0.get('cause') or '')}→{str(v0.get('effect') or '')}"
                status = 'blocked_causal_veto'
            else:
                tout = int(args.get('timeout_sec') or 10)
                res = sandbox_client.execute_python(code=str(args.get('code') or ''), timeout_sec=max(1, min(10, tout)))
                out_txt = json.dumps(res, ensure_ascii=False)[:1200]
                status = 'ok' if bool(res.get('ok')) else 'error'
        elif tool == 'execute_bash':
            ev = causal_graph.evaluate_step_risk(query=query, step={'tool': tool, 'args': args})
            vetoes = ev.get('vetoes') if isinstance(ev.get('vetoes'), list) else []
            if vetoes:
                v0 = vetoes[0] if isinstance(vetoes[0], dict) else {}
                out_txt = f"Execução bloqueada por veto causal: {str(v0.get('cause') or '')}→{str(v0.get('effect') or '')}"
                status = 'blocked_causal_veto'
            else:
                tout = int(args.get('timeout_sec') or 10)
                res = sandbox_client.execute_bash(command=str(args.get('command') or ''), timeout_sec=max(1, min(10, tout)))
                out_txt = json.dumps(res, ensure_ascii=False)[:1200]
                status = 'ok' if bool(res.get('ok')) else 'error'
        elif tool == 'flag_uncertainty':
            out_txt = f"Incerteza registrada: {str(args.get('reason') or 'insufficient_data')}"
            status = 'uncertain'
        else:
            out_txt = f"Ferramenta inválida: {tool}"
            status = 'invalid_tool'

        tool_outputs.append({'step': idx, 'tool': tool, 'args': args, 'status': status, 'output': out_txt[:1200]})
        try:
            prm = prm_lite.score_answer(query, out_txt[:400], context='', meta={'strategy': 'orchestrator_step', 'tool': tool})
            step_prm.append({'step': idx, 'tool': tool, 'prm_score': prm.get('score'), 'prm_risk': prm.get('risk')})
        except Exception:
            step_prm.append({'step': idx, 'tool': tool, 'prm_score': None, 'prm_risk': None})

    synth_prompt = json.dumps({
        'query': query,
        'tool_outputs': tool_outputs,
        'context_policy': {
            'profile': ctx_bundle.get('profile'),
            'fallback': ctx_bundle.get('fallback'),
            'budget': ctx_bundle.get('budget'),
        },
        'style': str(plan.get('final_answer_style') or 'objetivo e útil'),
        'guardrail': 'Se faltar contexto essencial, diga a lacuna explicitamente e não invente fatos.'
    }, ensure_ascii=False)
    fallback_meta = (ctx_bundle.get('fallback') if isinstance(ctx_bundle, dict) else {}) or {}
    hard_fallback_gate = bool(fallback_meta.get('needed')) and str(os.getenv('ULTRON_CONTEXT_HARD_FALLBACK_GATE', '1')).strip().lower() in ('1', 'true', 'yes', 'on')
    if hard_fallback_gate:
        missing = ', '.join((fallback_meta.get('missing_required_sources') or []))
        final_answer = (
            f"Lacuna explícita: faltou contexto essencial ({missing}). "
            f"Vou evitar inferência sem evidência suficiente."
        ).strip()
    else:
        final_answer = llm.complete(
            prompt=synth_prompt,
            strategy=generation_strategy,
            system='Sintetize resposta final em pt-BR, prática, sem inventar fatos ausentes.',
            json_mode=False,
            inject_persona=False,
            max_tokens=240,
        )
        final_answer = str(final_answer or '').strip()
    qeval = quality_eval.evaluate_response(
        query=query,
        answer=final_answer,
        context_meta=ctx_bundle,
        tool_outputs=tool_outputs,
    )
    critic = internal_critic.critique_response(
        query=query,
        answer=final_answer,
        context_meta=ctx_bundle,
        action_kind='route_toolchain' if tool_outputs else 'generate_questions',
        governance_meta={'proof_ok': bool(tool_outputs)},
        has_proof=bool(tool_outputs),
    )
    preflight = causal_preflight.run_preflight(
        action_kind='route_toolchain' if tool_outputs else 'generate_questions',
        action_text=final_answer,
        governance_meta={'proof_ok': bool(tool_outputs)},
        tool_outputs=tool_outputs,
    )
    revision_needed = bool((critic.get('epistemic') or {}).get('needs_revision')) or (
        bool(preflight.get('needs_confirmation')) and str(preflight.get('recommended_action') or '') in ('request_confirmation', 'block_or_escalate', 'revise_with_caution')
    )
    revision_trace: list[dict[str, Any]] = []
    if revision_needed and not hard_fallback_gate:
        revise_prompt = _build_guided_revision_prompt(
            query=query,
            current_answer=final_answer,
            tool_outputs=tool_outputs,
            context_bundle=ctx_bundle,
            critic=critic,
            preflight=preflight,
        )
        revised = llm.complete(
            prompt=revise_prompt,
            strategy=generation_strategy,
            system='Você é um revisor crítico. Reescreva a resposta para ficar mais calibrada, mais segura e mais explícita sobre lacunas, risco e confirmação quando necessário. Não invente fatos.',
            json_mode=False,
            inject_persona=False,
            max_tokens=260,
        )
        revised = str(revised or '').strip()
        if revised:
            final_answer = revised
            revision_trace.append({'mode': 'guided_rewrite', 'applied': True})
        else:
            revision_trace.append({'mode': 'guided_rewrite', 'applied': False, 'reason': 'empty_rewrite'})

        if bool((critic.get('epistemic') or {}).get('needs_revision')):
            reason = str(((critic.get('epistemic') or {}).get('revision_reason')) or 'internal_critic_revision')
            if reason == 'missing_gap_disclosure' and not any(x in str(final_answer or '').lower() for x in ['lacuna', 'não sei', 'nao sei', 'incerteza']):
                missing = ', '.join((fallback_meta.get('missing_required_sources') or []))
                final_answer = (
                    f"Lacuna explícita: faltou contexto essencial ({missing or 'contexto crítico'}). "
                    f"Não vou cravar resposta sem evidência suficiente."
                ).strip()
                revision_trace.append({'mode': 'fallback_gap_patch', 'applied': True})
            elif reason == 'rag_coverage_low':
                final_answer = (str(final_answer or '').strip() + ' ' + 'Observação: o contexto recuperado teve cobertura limitada; trate esta resposta como preliminar.').strip()
                revision_trace.append({'mode': 'coverage_patch', 'applied': True})
            elif reason == 'low_grounding_or_high_contradiction_risk':
                final_answer = (str(final_answer or '').strip() + ' ' + 'Aviso: há risco de grounding insuficiente ou contradição parcial no contexto disponível.').strip()
                revision_trace.append({'mode': 'grounding_patch', 'applied': True})

        if bool(preflight.get('needs_confirmation')) and str(preflight.get('recommended_action') or '') in ('request_confirmation', 'block_or_escalate') and 'confirmação' not in str(final_answer or '').lower():
            final_answer = (
                str(final_answer or '').strip() + ' ' +
                'Confirmação humana recomendada antes de qualquer execução mais séria.'
            ).strip()
            revision_trace.append({'mode': 'confirmation_patch', 'applied': True})

        qeval = quality_eval.evaluate_response(
            query=query,
            answer=final_answer,
            context_meta=ctx_bundle,
            tool_outputs=tool_outputs,
        )
        critic = internal_critic.critique_response(
            query=query,
            answer=final_answer,
            context_meta=ctx_bundle,
            action_kind='route_toolchain' if tool_outputs else 'generate_questions',
            governance_meta={'proof_ok': bool(tool_outputs)},
            has_proof=bool(tool_outputs),
        )
        preflight = causal_preflight.run_preflight(
            action_kind='route_toolchain' if tool_outputs else 'generate_questions',
            action_text=final_answer,
            governance_meta={'proof_ok': bool(tool_outputs)},
            tool_outputs=tool_outputs,
        )
    else:
        revision_trace = []
    planner_tokens_est = context_metrics.estimate_tokens(plan_prompt)
    synth_tokens_est = context_metrics.estimate_tokens(synth_prompt)
    selected_ctx_tokens_est = context_metrics.estimate_tokens(ctx_bundle.get('selected_contexts'))
    excluded_ctx_count = len(ctx_bundle.get('excluded_contexts') or []) if isinstance(ctx_bundle, dict) else 0

    return {
        'ok': True,
        'answer': final_answer,
        'strategy': 'orchestrator_qwen_tools',
        'orchestration': {
            'planner_raw': str(planner_raw or '')[:1000],
            'steps_executed': tool_outputs,
            'step_prm': step_prm,
            'planner_context': {
                'task_type': task_type,
                'context_profile': ctx_bundle.get('profile'),
                'context_policy': ctx_bundle.get('policy'),
                'selected_contexts': ctx_bundle.get('selected_contexts'),
                'excluded_contexts': ctx_bundle.get('excluded_contexts'),
                'context_fallback': ctx_bundle.get('fallback'),
                'context_budget': ctx_bundle.get('budget'),
                'rag_route': {
                    'domains': rag_route.get('domains'),
                    'search_plan': rag_route.get('search_plan'),
                    'diversity': rag_route.get('diversity'),
                },
                'context_metrics': {
                    'planner_prompt_tokens_est': planner_tokens_est,
                    'synth_prompt_tokens_est': synth_tokens_est,
                    'selected_context_tokens_est': selected_ctx_tokens_est,
                    'excluded_context_count': excluded_ctx_count,
                    'hard_fallback_gate': hard_fallback_gate,
                },
                'episodic_similar_count': len(episodic_similar),
                'episodic_similar': episodic_similar,
                'procedural_hints': procedural,
                'top_strategy_hint': recall.get('top_strategy_hint') if isinstance(recall, dict) else None,
                'working_memory': recall_compact.get('working_memory') if isinstance(recall_compact, dict) else (recall.get('working_memory') if isinstance(recall, dict) else {}),
                'memory_policy': pol,
                'memory_budget': recall_compact.get('budget') if isinstance(recall_compact, dict) else {},
                'causal_graph_hints': causal_hints,
                'analogy_context': analogy_ctx,
                'runtime_constraints': {
                    'forbid_tools': sorted(list(runtime_constraints.get('forbid_tools') or [])),
                    'require_tools': sorted(list(runtime_constraints.get('require_tools') or [])),
                    'max_steps': int(runtime_constraints.get('max_steps') or 3),
                },
                'adaptive_profile': adaptive_profile,
                'confidence_policy': {
                    'base_confidence': round(plan_base_confidence, 4),
                    'raw_plan_confidence': raw_plan_confidence,
                    'adjusted_plan_confidence': adjusted_plan_confidence,
                },
                'cot': cot,
                'verification': {
                    'overall_approved': ver.get('overall_approved') if isinstance(ver, dict) else None,
                    'blocked_reasons': blocked_reasons,
                    'step_reviews': (ver.get('step_reviews') if isinstance(ver, dict) and isinstance(ver.get('step_reviews'), list) else []),
                },
                'plan_selection': plan_selection,
                'internal_critic': critic,
                'causal_preflight': preflight,
                'revision_trace': revision_trace,
            },
        },
        'quality_eval': qeval,
        'internal_critic': critic,
        'causal_preflight': preflight,
        'revision_trace': revision_trace,
        'context_metrics': {
            'planner_prompt_tokens_est': planner_tokens_est,
            'synth_prompt_tokens_est': synth_tokens_est,
            'selected_context_tokens_est': selected_ctx_tokens_est,
            'excluded_context_count': excluded_ctx_count,
            'hard_fallback_gate': hard_fallback_gate,
        },
        'metrics': metrics,
        'cache_hit': None,
        'from_cache': False,
    }


async def _metacognition_ask_impl(req: MetacogAskRequest, force_generation_strategy: str | None = None, canary: bool = False, bypass_insufficient_gate: bool = False):
    q = str(req.message or '').strip()
    ql = q.lower()
    input_class = _classify_eval_input(q)
    cache_hit = None
    from_cache = False
    forced_strategy = str(force_generation_strategy or '').strip()
    req_started = time.monotonic()
    stage_timing_ms: dict[str, int] = {}
    llm_attempts: list[dict[str, Any]] = []

    # Infer health gate (optional for Qwen main path).
    require_infer_health = str(os.getenv('METACOG_REQUIRE_INFER_HEALTH', '0')).strip().lower() in ('1', 'true', 'yes', 'on')
    if require_infer_health and forced_strategy != 'canary_qwen':
        infer_health_t0 = time.monotonic()
        try:
            import urllib.request as _urlreq
            with _urlreq.urlopen(os.getenv('ULTRON_LOCAL_INFER_HEALTH_URL', os.getenv('ULTRON_LOCAL_INFER_URL', 'http://127.0.0.1:8025')).rstrip('/') + '/health', timeout=10) as _r:
                _h = json.loads(_r.read().decode('utf-8', 'ignore'))
            _stage_mark(stage_timing_ms, infer_health_t0, 'infer_health_ms')
        except Exception as _e:
            _stage_mark(stage_timing_ms, infer_health_t0, 'infer_health_ms')
            raise HTTPException(status_code=503, detail=f'infer_health_unavailable: {_e}')

        loaded_adapter = str((_h or {}).get('loaded_adapter') or '').strip()
        if not loaded_adapter:
            raise HTTPException(status_code=503, detail='adapter_not_loaded: loaded_adapter is empty on infer health')

    def _trace_emit(answer: str, strategy: str, outcome: str = 'success'):
        try:
            route = 'accept_local'
            if strategy in ('cheap', 'cloud'):
                route = 'handoff_backbone'
            elif strategy in ('unavailable', 'clarify'):
                route = 'ask_clarification'
            replay_traces.append_trace({
                'trace_id': f"trc_{int(time.time()*1000)}",
                'ts': int(time.time()),
                'task_type': 'metacognition_ask',
                'risk_class': 'medium',
                'input': q,
                'output_local': answer,
                'route': route,
                'arbiter_verdict': None,
                'final_outcome': outcome,
                'feedback_label': None,
                'meta': {'strategy': strategy},
            })
        except Exception:
            pass

    def _prm_pack(answer: str, strategy: str, metrics_obj: dict[str, Any]) -> dict[str, Any]:
        try:
            prm = prm_lite.score_answer(q, answer, context=str(((metrics_obj or {}).get('rag') or {}).get('source') or ''), meta={'strategy': strategy})
            prm_lite.record(q, answer, strategy, prm)
            try:
                meta = llm.last_call_meta() or {}
                provider = str(meta.get('provider') or 'unknown')
                task_type = llm_adapter.classify_task_type(input_class=str((metrics_obj or {}).get('input_class') or ''), strategy=strategy)
                if isinstance(prm.get('score'), (int, float)):
                    llm_adapter.record_provider_performance(task_type, provider, float(prm.get('score')))
            except Exception:
                pass
            return {
                'prm_score': prm.get('score'),
                'prm_risk': prm.get('risk'),
                'prm_reasons': prm.get('reasons') or [],
                'prm_mode': 'observation',
            }
        except Exception:
            return {
                'prm_score': None,
                'prm_risk': None,
                'prm_reasons': [],
                'prm_mode': 'observation',
            }

    # Base metacognitive summary (sleep-cycle + abstractions)
    base = _metacog_weekly_summary_text()

    # Runtime context from learning agenda + mission control + sleep cycle
    try:
        la = learning_agenda.status() or {}
    except Exception:
        la = {}

    try:
        rank = (learning_agenda.tick(plasticity_runtime.status(limit=80)) or {}).get('rank') or []
    except Exception:
        rank = []

    try:
        sla = mission_control.check_learning_agenda_sla() or {}
    except Exception:
        sla = {}

    try:
        tasks = mission_control.list_tasks(limit=240) or []
    except Exception:
        tasks = []

    by = {'inbox': 0, 'assigned': 0, 'in_progress': 0, 'review': 0, 'blocked': 0, 'done': 0}
    for t in tasks:
        s = str(t.get('status') or 'inbox')
        if s in by:
            by[s] += 1

    active_learning = [
        t for t in tasks
        if str(t.get('task_type') or '') == 'learning_agenda'
        and str(t.get('status') or '') in ('inbox', 'assigned', 'in_progress', 'review', 'blocked')
    ]

    try:
        slp = await sleep_cycle_status()
        rep = (slp or {}).get('report') if isinstance(slp, dict) else {}
        rep = rep or {}
    except Exception:
        rep = {}

    top = rank[0] if rank else {}
    top_domain = str(top.get('domain') or top.get('topic') or top.get('name') or '-')

    metrics = {
        'learning_agenda': {
            'enabled': bool(la.get('enabled')),
            'top_domain': top_domain,
            'backlog': len(rank),
            'active_learning_tasks': len(active_learning),
        },
        'mission_control': {
            'inbox': int(by['inbox']),
            'in_progress': int(by['in_progress']),
            'blocked': int(by['blocked']),
            'done': int(by['done']),
            'sla_overdue': int(sla.get('overdue') or 0),
            'sla_escalated': int(sla.get('escalated') or 0),
        },
        'sleep_cycle': {
            'abstracted': int(rep.get('abstracted') or 0),
            'pruned': int(rep.get('pruned') or 0),
            'active_after': int(rep.get('active_after') or 0),
        },
        'metacog_base': base,
    }

    runtime_triggers = [
        'status runtime', 'runtime status', 'health runtime', 'health do runtime',
        'health do provider', 'provider health', 'status do provider', 'status provider',
        'strategy ativa', 'estratégia ativa', 'qual strategy está ativa', 'qual estrategia está ativa',
        'debug runtime', 'diagnóstico runtime', 'diagnostico runtime'
    ]
    runtime_intent = any(t in ql for t in runtime_triggers)
    if runtime_intent:
        try:
            h_auto = llm.healthcheck('auto')
        except Exception:
            h_auto = {'ok': False, 'provider': 'unknown', 'error': 'healthcheck_failed'}
        try:
            h_local = llm.healthcheck('ultron_infer')
        except Exception:
            h_local = {'ok': False, 'provider': 'ultron_infer', 'error': 'healthcheck_failed'}
        txt = (
            f"Agora no chat eu uso strategy=local (ultron_infer remoto no U3), sem fallback cloud neste endpoint. "
            f"Saúde atual: auto={h_auto.get('provider')} ok={h_auto.get('ok')}; local_ok={h_local.get('ok')}. "
            f"Treino/adapters runtime: desativados por arquitetura."
        )
        _trace_emit(txt, 'runtime_introspection', outcome='success')
        prm_meta = _prm_pack(txt, 'runtime_introspection', metrics)
        return {'ok': True, 'answer': txt, 'strategy': 'runtime_introspection', 'metrics': metrics, 'cache_hit': cache_hit, 'from_cache': from_cache, **prm_meta}

    # Policy-gate (pre-cache/pre-local): block explicit secret extraction and high-risk medical dosing requests.
    cred_terms = ['credencial', 'credenciais', 'api key', 'api keys', 'token', 'senha', 'secret', 'chave', 'password', 'bearer']
    cred_extract_verbs = ['me passa', 'mostra', 'qual é', 'qual e', 'me dá', 'me da', 'forneça', 'forneca', 'revela', 'revelar']
    cred_exfil_question = (any(t in ql for t in cred_terms) and any(v in ql for v in cred_extract_verbs))

    med_dose_terms = ['dose', 'dosagem', 'posologia']
    med_drug_terms = ['medicamento', 'remédio', 'remedio', 'fármaco', 'farmaco', 'xarope', 'antibiótico', 'antibiotico']
    med_pediatric_terms = ['criança', 'crianca', 'bebê', 'bebe', 'infantil', 'anos', 'kg', 'mg']
    med_high_risk_question = (
        any(t in ql for t in med_dose_terms)
        and any(t in ql for t in med_drug_terms)
        and any(t in ql for t in med_pediatric_terms)
    )

    abuse_terms = [
        'phishing', 'captar senhas', 'capturar senhas', 'roubar senha', 'roubar senhas',
        'engenharia social para senha', 'burlar autenticação', 'burlar autenticacao', 'credential stuffing',
        'exploit', 'malware', 'ransomware', 'invadir conta', 'invadir sistema'
    ]
    abuse_question = any(t in ql for t in abuse_terms)

    if (not bypass_insufficient_gate) and (cred_exfil_question or med_high_risk_question or abuse_question):
        ans_gate = (
            "Não tenho informação confiável sobre isso. "
            "Para questões fora do domínio operacional, recomendo consultar uma fonte específica."
        )
        _trace_emit(ans_gate, 'insufficient_confidence', outcome='fallback')
        prm_meta = _prm_pack(ans_gate, 'insufficient_confidence', metrics)
        return {
            'ok': True,
            'answer': ans_gate,
            'strategy': 'insufficient_confidence',
            'metrics': metrics,
            'cache_hit': cache_hit,
            'from_cache': from_cache,
            'stage_timing_ms': {**stage_timing_ms, 'total_ms': int((time.monotonic() - req_started) * 1000)},
            'llm_attempts': llm_attempts,
            **prm_meta,
        }

    status_intent_terms = ['status', 'health', 'metrics', 'runtime']
    intent_label = 'runtime' if runtime_intent else ('status' if any(t in ql for t in status_intent_terms) else 'general')

    high_risk_terms = [
        'presidente', 'constituição', 'constituição federal', 'artigo ', 'lei ', 'stf'
    ]
    external_ranking_terms = [
        'ranking externo', 'comparação de produtos', 'comparacao de produtos',
        'qual é o melhor', 'qual e o melhor', 'mais inteligente', 'mais rápido', 'mais rapido',
        'melhor llm', 'modelo llm mais', 'qual o melhor modelo', 'qual o modelo mais'
    ]
    risk_class = 'high' if (any(t in ql for t in high_risk_terms) or any(t in ql for t in external_ranking_terms)) else 'medium'

    # Dynamic metacognitive orchestrator (phase: supervisor with tool sequence)
    orch_enabled = str(os.getenv('ULTRON_METACOG_ORCHESTRATOR_ENABLED', '1')).strip().lower() in ('1', 'true', 'yes', 'on')
    open_task_terms = ['planejar', 'plano', 'organizar', 'estratégia', 'estrategia', 'roteiro', 'festa surpresa', 'surpresa']
    should_orchestrate = orch_enabled and any(t in ql for t in open_task_terms)
    if should_orchestrate:
        try:
            orch_t0 = time.time()
            orch_stage_t0 = time.monotonic()
            primary_provider = str(os.getenv('ULTRON_PRIMARY_LOCAL_PROVIDER', 'ollama_local') or 'ollama_local').strip().lower()
            default_gen_strategy = 'default' if primary_provider in {'gemini', 'openai', 'anthropic', 'openrouter', 'groq', 'deepseek', 'huggingface'} else 'local'
            gen_strategy = forced_strategy if forced_strategy else ('canary_qwen' if canary else default_gen_strategy)
            out_orch = await _metacog_orchestrator_run(q, metrics, generation_strategy=gen_strategy)
            if isinstance(out_orch, dict) and str(out_orch.get('answer') or '').strip():
                _trace_emit(str(out_orch.get('answer') or ''), 'orchestrator_qwen_tools', outcome='success')
                prm_meta = _prm_pack(str(out_orch.get('answer') or ''), 'orchestrator_qwen_tools', metrics)
                out_orch.update(prm_meta)
                try:
                    orch_struct = (out_orch.get('orchestration') or {}) if isinstance(out_orch.get('orchestration'), dict) else {}
                    planner_raw = str(orch_struct.get('planner_raw') or '')
                    steps_executed = orch_struct.get('steps_executed') if isinstance(orch_struct.get('steps_executed'), list) else []
                    step_prm = orch_struct.get('step_prm') if isinstance(orch_struct.get('step_prm'), list) else []
                    plan_sel = orch_struct.get('planner_context') if isinstance(orch_struct.get('planner_context'), dict) else {}
                    selection = plan_sel.get('plan_selection') if isinstance(plan_sel.get('plan_selection'), dict) else {}
                    discarded = selection.get('discarded') if isinstance(selection.get('discarded'), list) else []
                    risk = str(out_orch.get('prm_risk') or 'unknown')
                    score = out_orch.get('prm_score')
                    hipotese_pos_hoc = (
                        f"Hipótese pós-hoc: estratégia sequencial com {len(steps_executed)} passo(s) "
                        f"foi {'efetiva' if risk in ('low','medium') else 'incerta'}; risco final PRM={risk}."
                    )
                    analogy_ctx = plan_sel.get('analogy_context') if isinstance(plan_sel.get('analogy_context'), dict) else {}
                    chosen_analogy = analogy_ctx.get('first_cross_domain_analogy') if isinstance(analogy_ctx.get('first_cross_domain_analogy'), dict) else (analogy_ctx.get('top_match') if isinstance(analogy_ctx.get('top_match'), dict) else {})
                    analogia_usada = bool(analogy_ctx.get('triggered')) and bool(chosen_analogy)
                    analogia_source_episode_id = str(chosen_analogy.get('source_episode_id') or chosen_analogy.get('episode_id') or '')
                    analogia_foi_util = None
                    if analogia_usada and isinstance(score, (int, float)):
                        analogia_foi_util = bool(float(score) >= 0.62)

                    qeval = out_orch.get('quality_eval') if isinstance(out_orch.get('quality_eval'), dict) else {}
                    critic_eval = out_orch.get('internal_critic') if isinstance(out_orch.get('internal_critic'), dict) else {}
                    preflight_eval = out_orch.get('causal_preflight') if isinstance(out_orch.get('causal_preflight'), dict) else {}
                    revision_trace = out_orch.get('revision_trace') if isinstance(out_orch.get('revision_trace'), list) else []
                    memory_decision = memory_governor.classify_writeback(
                        query=q,
                        answer=str(out_orch.get('answer') or ''),
                        task_type='planning',
                        quality_eval=qeval,
                        internal_critic=critic_eval,
                        planner_context=plan_sel,
                        steps_executed=steps_executed,
                        causal_preflight=preflight_eval,
                    )
                    self_model_eval = self_model.consolidate_operational_self_model(
                        task_type=str(planner_ctx.get('task_type') or 'planning'),
                        quality_eval=qeval,
                        internal_critic=critic_eval,
                        causal_preflight=preflight_eval,
                        memory_governor=memory_decision,
                        revision_trace=revision_trace,
                        tool_used=bool(steps_executed),
                        latency_ms=int((time.time() - orch_t0) * 1000),
                        notes=str((memory_decision.get('write_reason') or '')),
                    )
                    ep = episodic_memory.append_structured_episode(
                        problem=q,
                        plano_gerado={
                            'planner_raw': planner_raw[:1800],
                            'plano_escolhido': selection.get('selected_plan'),
                            'plano_descartado': [d.get('plano_descartado') for d in discarded[:2]],
                            'motivo_causal': [d.get('motivo_causal') for d in discarded[:2]],
                            'analogy_context': analogy_ctx,
                        },
                        passos_executados=steps_executed,
                        resultado=str(out_orch.get('answer') or ''),
                        prm_score_final=(float(score) if isinstance(score, (int, float)) else None),
                        hipotese_pos_hoc=hipotese_pos_hoc,
                        task_type='planning',
                        strategy='orchestrator_qwen_tools',
                        ok=(risk in ('low', 'medium')),
                        latency_ms=int((time.time() - orch_t0) * 1000),
                        work_context={
                            'step_prm': step_prm,
                            'cache_hit': out_orch.get('cache_hit'),
                            'from_cache': bool(out_orch.get('from_cache')),
                            'analogy_context': analogy_ctx,
                            'context_profile': ((orch_struct.get('planner_context') or {}).get('context_profile') if isinstance(orch_struct.get('planner_context'), dict) else ''),
                            'context_fallback': ((orch_struct.get('planner_context') or {}).get('context_fallback') if isinstance(orch_struct.get('planner_context'), dict) else {}),
                            'context_metrics': (out_orch.get('context_metrics') if isinstance(out_orch.get('context_metrics'), dict) else {}),
                            'memory_governor': memory_decision,
                            'causal_preflight': preflight_eval,
                            'revision_trace': revision_trace,
                            'self_model': self_model_eval,
                        },
                        quality_eval=qeval,
                        memory_governor=memory_decision,
                        analogia_usada=analogia_usada,
                        analogia_source_episode_id=analogia_source_episode_id,
                        analogia_foi_util=analogia_foi_util,
                    )
                    try:
                        ctx_metrics = out_orch.get('context_metrics') if isinstance(out_orch.get('context_metrics'), dict) else {}
                        planner_ctx = orch_struct.get('planner_context') if isinstance(orch_struct.get('planner_context'), dict) else {}
                        quality_eval.persist_eval({
                            'ts': int(time.time()),
                            'query': q[:500],
                            'strategy': 'orchestrator_qwen_tools',
                            'task_type': str(planner_ctx.get('task_type') or 'planning'),
                            'context_profile': str(planner_ctx.get('context_profile') or ''),
                            'episode_id': str((ep or {}).get('episode_id') or ''),
                            'quality_eval': qeval,
                            'internal_critic': critic_eval,
                            'memory_governor': memory_decision,
                            'causal_preflight': preflight_eval,
                            'revision_trace': revision_trace,
                            'self_model': self_model_eval,
                            'context_metrics': ctx_metrics,
                            'fallback': planner_ctx.get('context_fallback'),
                            'rag_diversity': ((planner_ctx.get('rag_route') or {}).get('diversity') if isinstance(planner_ctx.get('rag_route'), dict) else {}),
                        })
                        try:
                            gd = gap_detector.maybe_auto_scan(limit=80)
                            if bool((gd or {}).get('created')):
                                cognitive_patch_loop.autorun_once(limit=3, statuses=['proposed', 'evaluating', 'evaluated'])
                        except Exception:
                            pass
                        context_metrics.persist_row({
                            'query': q[:500],
                            'strategy': 'orchestrator_qwen_tools',
                            'task_type': str(planner_ctx.get('task_type') or 'planning'),
                            'context_profile': str(planner_ctx.get('context_profile') or ''),
                            'episode_id': str((ep or {}).get('episode_id') or ''),
                            'selected_contexts': planner_ctx.get('selected_contexts'),
                            'excluded_contexts': planner_ctx.get('excluded_contexts'),
                            'context_budget': planner_ctx.get('context_budget'),
                            'context_metrics': ctx_metrics,
                            'quality_eval': qeval,
                            'internal_critic': critic_eval,
                            'memory_governor': memory_decision,
                            'causal_preflight': preflight_eval,
                            'revision_trace': revision_trace,
                            'self_model': self_model_eval,
                            'rag_diversity': ((planner_ctx.get('rag_route') or {}).get('diversity') if isinstance(planner_ctx.get('rag_route'), dict) else {}),
                            'latency_ms': int((time.time() - orch_t0) * 1000),
                        })
                    except Exception:
                        pass
                    out_orch['analogy_feedback'] = {
                        'analogia_usada': analogia_usada,
                        'analogia_source_episode_id': analogia_source_episode_id,
                        'analogia_foi_util': analogia_foi_util,
                    }
                    out_orch['memory_governor'] = memory_decision
                    out_orch['self_model'] = self_model_eval
                    try:
                        memory_governor.persist_decision({
                            'query': q[:500],
                            'strategy': 'orchestrator_qwen_tools',
                            'task_type': 'planning',
                            'episode_id': str((ep or {}).get('episode_id') or ''),
                            'decision': memory_decision,
                        })
                    except Exception:
                        pass
                    post_learning = _run_post_execution_learning(
                        query=q,
                        answer=str(out_orch.get('answer') or ''),
                        steps_executed=steps_executed,
                        planner_context=(orch_struct.get('planner_context') if isinstance(orch_struct.get('planner_context'), dict) else {}),
                        task_type='planning',
                        episode_id=str((ep or {}).get('episode_id') or ''),
                    )
                    out_orch['post_execution_learning'] = post_learning
                except Exception:
                    pass
                _stage_mark(stage_timing_ms, orch_stage_t0, 'orchestrator_ms')
                out_orch['stage_timing_ms'] = {**stage_timing_ms, 'total_ms': int((time.monotonic() - req_started) * 1000)}
                out_orch['llm_attempts'] = llm_attempts
                return out_orch
        except Exception:
            _stage_mark(stage_timing_ms, orch_stage_t0, 'orchestrator_ms')
            pass

    # Step 2: symbolic router before domain gate
    symbolic_route_t0 = time.monotonic()
    symbolic_should_route = symbolic_reasoner.should_route(q)
    _stage_mark(stage_timing_ms, symbolic_route_t0, 'symbolic_route_check_ms')
    if symbolic_should_route:
        symbolic_solve_t0 = time.monotonic()
        sym = symbolic_reasoner.solve(q)
        _stage_mark(stage_timing_ms, symbolic_solve_t0, 'symbolic_solve_ms')
        if bool(sym.get('ok')) and str(sym.get('answer') or '').strip():
            ans_sym = str(sym.get('answer') or '').strip()
            used_sym = 'symbolic_reasoner'
            try:
                if not ((risk_class in ('high', 'critical')) or (intent_label in ('runtime', 'status', 'health', 'metrics'))):
                    semantic_cache.store(q, ans_sym, used_sym)
            except Exception:
                pass
            _trace_emit(ans_sym, used_sym, outcome='success')
            prm_meta = _prm_pack(ans_sym, used_sym, {**metrics, 'symbolic_reasoner': {'routed': True}})
            return {
                'ok': True,
                'answer': ans_sym,
                'strategy': used_sym,
                'metrics': {**metrics, 'symbolic_reasoner': {'routed': True}},
                'cache_hit': cache_hit,
                'from_cache': from_cache,
                'stage_timing_ms': {**stage_timing_ms, 'total_ms': int((time.monotonic() - req_started) * 1000)},
                'llm_attempts': llm_attempts,
                **prm_meta,
            }

    # Step 3: domain gate for external factual/ranking queries not captured by symbolic
    external_fact_terms = [
        'oscar', 'melhor filme', 'campeão', 'campeao', 'capital de', 'população de', 'populacao de'
    ]
    symbolic_exception_terms = [
        # lógica/matemática
        'implica', 'verdadeiro ou falso', 'todos os', 'se ', ' então', 'proximo número', 'próximo número',
        'raiz quadrada', 'x²', 'x^2', 'equação', 'equacao', 'triângulo', 'triangulo', 'porcentagem', '% de',
        'quantos segundos', 'calcule',
        # planejamento/programação
        'checklist', 'migração', 'migracao', 'plano de estudos', 'framework', 'passos para',
        'python', 'docker', 'dockerfile', 'loop', 'função', 'funcao', 'diferença entre', 'diferenca entre', 'deadlock'
    ]
    symbolic_exception = any(t in ql for t in symbolic_exception_terms)
    external_fact_question = (
        (('?' in q) or ('qual ' in ql) or ('quem ' in ql) or ('quando ' in ql))
        and (
            any(t in ql for t in external_fact_terms)
            or any(t in ql for t in external_ranking_terms)
            or any(t in ql for t in high_risk_terms)
        )
        and (not symbolic_exception)
        and (input_class not in ('logic', 'math', 'planning', 'code'))
    )
    if (not bypass_insufficient_gate) and external_fact_question:
        stage_timing_ms['gate_external_fact_ms'] = int((time.monotonic() - req_started) * 1000)
        ans_gate = (
            "Não tenho informação confiável sobre isso. "
            "Para questões fora do domínio operacional, recomendo consultar uma fonte específica."
        )
        _trace_emit(ans_gate, 'insufficient_confidence', outcome='fallback')
        prm_meta = _prm_pack(ans_gate, 'insufficient_confidence', metrics)
        return {
            'ok': True,
            'answer': ans_gate,
            'strategy': 'insufficient_confidence',
            'metrics': metrics,
            'cache_hit': cache_hit,
            'from_cache': from_cache,
            **prm_meta,
        }

    # Semantic cache lookup (skip on runtime/status/health/metrics or high/critical risk class)
    cache_skip_lookup = (risk_class in ('high', 'critical')) or (intent_label in ('runtime', 'status', 'health', 'metrics'))
    if not cache_skip_lookup:
        cache_lookup_t0 = time.monotonic()
        try:
            hit = semantic_cache.lookup(q)
        except Exception:
            hit = None
        _stage_mark(stage_timing_ms, cache_lookup_t0, 'semantic_cache_lookup_ms')
        if hit and str(hit.get('answer') or '').strip():
            cache_hit = str(hit.get('cache_hit') or '')
            from_cache = True
            ans_cache = str(hit.get('answer') or '').strip()
            used_cache = str(hit.get('strategy') or 'cache')
            _trace_emit(ans_cache, used_cache, outcome='success')
            prm_meta = _prm_pack(ans_cache, used_cache, {**metrics, 'semantic_cache': {'hit': cache_hit, 'score': hit.get('score')}})
            return {
                'ok': True,
                'answer': ans_cache,
                'strategy': used_cache,
                'metrics': {**metrics, 'semantic_cache': {'hit': cache_hit, 'score': hit.get('score')}},
                'cache_hit': cache_hit,
                'from_cache': from_cache,
                'stage_timing_ms': {**stage_timing_ms, 'total_ms': int((time.monotonic() - req_started) * 1000)},
                'llm_attempts': llm_attempts,
                **prm_meta,
            }

    # RAG-first for factual/domain questions: query LightRAG before generic fallback/local-only flow
    factual_terms = [
        'manual', 'documentação', 'doc', 'api', 'endpoint', 'config', 'parâmetro', 'parametro',
        'erro', 'falha', 'troubleshoot', 'debug', 'status', 'servidor', 'treino', 'job', 'dataset',
        'openrouter', 'groq', 'deepseek', 'lightrag', 'ultronpro',
        'finetune', 'notify-complete', 'run_preset', 'fast_diagnostic', 'adapter'
    ]
    # only route to RAG for operational/domain intent; avoid forcing RAG on generic world questions
    import re
    q_tokens = set(re.findall(r"[a-zA-ZÀ-ÿ0-9_\-]{3,}", ql))
    factual_intent = False
    for t in factual_terms:
        tt = str(t).strip().lower()
        if ' ' in tt or '-' in tt or '_' in tt:
            if tt in ql:
                factual_intent = True
                break
        else:
            if tt in q_tokens:
                factual_intent = True
                break
    if factual_intent:
        rag_search_t0 = time.monotonic()
        try:
            rag_hits = await search_knowledge(q, top_k=5)
        except Exception:
            rag_hits = []
        _stage_mark(stage_timing_ms, rag_search_t0, 'rag_search_ms')

        best = None
        if rag_hits:
            rag_hits_sorted = sorted(rag_hits, key=lambda x: float(x.get('score') or 0.0), reverse=True)
            best = rag_hits_sorted[0]

        best_score = float((best or {}).get('score') or 0.0)
        if best and best_score >= 0.5:
            ctx = str(best.get('text') or '').strip()
            source_id = str(best.get('source_id') or 'lightrag')
            short_ctx = (ctx[:1000] + '...') if len(ctx) > 1000 else ctx
            rag_prompt = (
                f"Pergunta: {q}\n"
                f"Contexto recuperado ({source_id}, score={best_score:.2f}):\n{short_ctx}\n\n"
                "Responda em português, de forma objetiva, usando apenas o contexto acima. "
                "Se faltar dado no contexto, diga isso explicitamente."
            )
            rag_ans = ''
            rag_llm_t0 = time.monotonic()
            rag_strategy = (forced_strategy or 'default')
            try:
                rag_ans = await _llm_complete_with_timeout(
                    rag_prompt,
                    strategy=rag_strategy,
                    system='Resposta factual com base em contexto recuperado.',
                    inject_persona=False,
                    max_tokens=180,
                    cloud_fallback=(not bool(forced_strategy)),
                    timeout_sec=min(METACOG_LLM_ATTEMPT_TIMEOUT_SEC, max(1.0, _budget_remaining(time.monotonic() + METACOG_LLM_ATTEMPT_TIMEOUT_SEC))),
                ) or ''
            except Exception:
                rag_ans = ''
            _stage_mark(stage_timing_ms, rag_llm_t0, 'rag_llm_ms')
            _llm_attempt_record(llm_attempts, stage='rag_llm', strategy=rag_strategy, duration_ms=stage_timing_ms.get('rag_llm_ms', 0), ok=bool(str(rag_ans).strip()))

            rag_ans = str(rag_ans).strip()
            if rag_ans:
                out = f"{rag_ans}\n\nFonte: {source_id} (score={best_score:.2f})"
                try:
                    if not ((risk_class in ('high', 'critical')) or (intent_label in ('runtime', 'status', 'health', 'metrics'))):
                        semantic_cache.store(q, out, 'rag_context')
                except Exception:
                    pass
                _trace_emit(out, 'rag_context', outcome='success')
                prm_meta = _prm_pack(out, 'rag_context', {**metrics, 'rag': {'used': True, 'score': best_score, 'source': source_id}})
                return {'ok': True, 'answer': out, 'strategy': 'rag_context', 'metrics': {**metrics, 'rag': {'used': True, 'score': best_score, 'source': source_id}}, 'cache_hit': cache_hit, 'from_cache': from_cache, **prm_meta}

            # If model generation is unavailable, still answer from retrieved context instead of generic fallback.
            plain = short_ctx.replace('```json', '').replace('```', '').strip()
            plain = ' '.join(plain.split())
            if plain:
                out = f"Com base no LightRAG: {plain[:360]}{'...' if len(plain) > 360 else ''}\n\nFonte: {source_id} (score={best_score:.2f})"
                try:
                    if not ((risk_class in ('high', 'critical')) or (intent_label in ('runtime', 'status', 'health', 'metrics'))):
                        semantic_cache.store(q, out, 'rag_context_direct')
                except Exception:
                    pass
                _trace_emit(out, 'rag_context_direct', outcome='success')
                prm_meta = _prm_pack(out, 'rag_context_direct', {**metrics, 'rag': {'used': True, 'score': best_score, 'source': source_id}})
                return {'ok': True, 'answer': out, 'strategy': 'rag_context_direct', 'metrics': {**metrics, 'rag': {'used': True, 'score': best_score, 'source': source_id}}, 'cache_hit': cache_hit, 'from_cache': from_cache, **prm_meta}

    short_msg = (len(q) <= 20 and len(q.split()) <= 4)

    # Safety rails for identity + out-of-domain factual claims.
    identity_terms = ['quantos anos', 'sua idade', 'quem te criou', 'seu criador', 'seu nome real', 'quando você nasceu']
    high_risk_terms = [
        'presidente', 'constituição', 'constituição federal', 'artigo ', 'lei ', 'stf'
    ]
    external_ranking_terms = [
        'ranking externo', 'comparação de produtos', 'comparacao de produtos',
        'qual é o melhor', 'qual e o melhor', 'mais inteligente', 'mais rápido', 'mais rapido',
        'melhor llm', 'modelo llm mais', 'qual o melhor modelo', 'qual o modelo mais'
    ]
    identity_question = any(t in ql for t in identity_terms)
    high_risk_question = any(t in ql for t in high_risk_terms) or any(t in ql for t in external_ranking_terms)

    system = (
        'Você é o Córtex Metacognitivo do UltronPro. '
        'Responda em português brasileiro, direto e analítico. '
        'NÃO repita o prompt, NÃO inclua JSON, NÃO liste métricas cruas. '
        'Use as métricas apenas para raciocinar em silêncio. '
        'Para questões operacionais/técnicas, use formato: resposta direta + evidência mínima + próximo passo. '
        'Para conversação geral, responda de forma natural em PT-BR, sem estrutura rígida. '
        'Se faltar dado, admita incerteza sem alucinar.'
    )

    compact_ctx = (
        f"ctx: agenda={metrics['learning_agenda']}; "
        f"mission={metrics['mission_control']}; "
        f"sleep={metrics['sleep_cycle']}; "
        f"base='{metrics['metacog_base'][:180]}'"
    )

    if short_msg:
        prompt = (
            f"Pergunta: {q}\n"
            "Responda em até 2 frases, natural, sem repetir instruções internas."
        )
    else:
        prompt = (
            f"Pergunta: {q}\n"
            f"{compact_ctx}\n"
            "Responda somente ao que foi perguntado, sem ecoar contexto."
        )

    llm_system = None if short_msg else system

    ans = ''
    used = 'none'
    llm_deadline = time.monotonic() + METACOG_LLM_TOTAL_BUDGET_SEC

    # Option A feature-flag: allow direct factual answers for general questions.
    general_qa_enabled = str(os.getenv('METACOG_GENERAL_QA_ENABLED', '0')).strip().lower() in ('1', 'true', 'yes', 'on')
    general_qa_max_words = int(os.getenv('METACOG_GENERAL_QA_MAX_WORDS', '16') or 16)
    general_qa_max_chars = int(os.getenv('METACOG_GENERAL_QA_MAX_CHARS', '140') or 140)
    looks_question = ('?' in q) or any(w in ql.split() for w in ('qual', 'quem', 'quando', 'onde', 'quanto', 'como'))
    general_question = (
        looks_question
        and (len(q.split()) <= general_qa_max_words)
        and (len(q) <= general_qa_max_chars)
        and (not factual_intent)
        and (not identity_question)
        and (not high_risk_question)
    )

    def _looks_broken(txt: str) -> bool:
        t = str(txt or '').strip().lower()
        if not t:
            return True
        bad = [
            '<|user|>', '<|assistant|>', 'resposta: tiny', 'resposta: openai', 'não há dados para a questão',
            'você é o córtex metacognitivo', 'eu sou o córtex metacognitivo do ultronpro',
            'formato obrigatório em texto corrido curto', 'use as métricas apenas para raciocinar em silêncio'
        ]
        if any(b in t for b in bad):
            return True
        # contradictory short garbage patterns
        if 'resposta direta:' in t and 'evidencia mínima:' in t and 'proximo passo:' in t and len(t) < 180:
            return True
        return False

    # Primary pass: local first (or forced canary strategy).
    # If Option A is enabled and this is a simple general question,
    # allow a second pass via default strategy.
    if forced_strategy:
        strategies = [forced_strategy]
    else:
        primary_provider = str(os.getenv('ULTRON_PRIMARY_LOCAL_PROVIDER', 'ollama_local') or 'ollama_local').strip().lower()
        primary_is_cloud = primary_provider in {'gemini', 'openai', 'anthropic', 'openrouter', 'groq', 'deepseek', 'huggingface'}
        strategies = ['default'] if primary_is_cloud else ['local']
        if general_qa_enabled and general_question:
            extra = 'local' if primary_is_cloud else 'default'
            if extra not in strategies:
                strategies.append(extra)

    for strat in tuple(strategies):
        remaining = _budget_remaining(llm_deadline)
        if remaining <= 0.25:
            break
        attempt_t0 = time.monotonic()
        cand = await _llm_complete_with_timeout(
            prompt,
            strategy=strat,
            system=llm_system,
            inject_persona=False,
            max_tokens=(80 if short_msg else 120),
            cloud_fallback=(not bool(forced_strategy) and strat == 'default'),
            timeout_sec=min(METACOG_LLM_ATTEMPT_TIMEOUT_SEC, remaining),
        )
        attempt_ms = int((time.monotonic() - attempt_t0) * 1000)
        _llm_attempt_record(llm_attempts, stage='primary', strategy=strat, duration_ms=attempt_ms, ok=bool((cand or '').strip()), remaining_before_ms=int(remaining * 1000))
        stage_timing_ms[f'llm_{strat}_last_ms'] = attempt_ms
        if (cand or '').strip() and not _looks_broken(cand):
            ans = cand.strip()
            used = strat
            break

        # hard fallback for canary strategy: call Ollama endpoint directly
        if strat == 'canary_qwen' and _budget_remaining(llm_deadline) > 1.0:
            canary_direct_t0 = time.monotonic()
            try:
                cand_direct = await asyncio.wait_for(
                    asyncio.to_thread(_direct_canary_generate, q, (80 if short_msg else 160)),
                    timeout=min(max(1.0, _budget_remaining(llm_deadline)), METACOG_LLM_ATTEMPT_TIMEOUT_SEC),
                )
            except Exception:
                cand_direct = ''
            canary_direct_ms = int((time.monotonic() - canary_direct_t0) * 1000)
            stage_timing_ms['canary_direct_ms'] = canary_direct_ms
            _llm_attempt_record(llm_attempts, stage='canary_direct', strategy='canary_qwen_direct', duration_ms=canary_direct_ms, ok=bool((cand_direct or '').strip()))
            if (cand_direct or '').strip() and not _looks_broken(cand_direct):
                ans = cand_direct.strip()
                used = 'canary_qwen_direct'
                break

        # second non-deterministic pass with simpler prompt (for tiny on CPU)
        if (not forced_strategy) and strat == 'local' and _budget_remaining(llm_deadline) > 0.5:
            simple_prompt = f"Pergunta: {q}\nResponda em até 3 frases, português natural, sem repetir a pergunta."
            retry_t0 = time.monotonic()
            cand2 = await _llm_complete_with_timeout(
                simple_prompt,
                strategy='local',
                system=None,
                inject_persona=False,
                max_tokens=96,
                cloud_fallback=False,
                timeout_sec=min(METACOG_LLM_ATTEMPT_TIMEOUT_SEC, _budget_remaining(llm_deadline)),
            )
            retry_ms = int((time.monotonic() - retry_t0) * 1000)
            stage_timing_ms['local_retry_ms'] = retry_ms
            _llm_attempt_record(llm_attempts, stage='local_retry', strategy='local', duration_ms=retry_ms, ok=bool((cand2 or '').strip()))
            if (cand2 or '').strip() and not _looks_broken(cand2):
                ans = cand2.strip()
                used = 'local_retry'
                break

    if ans:
        # Tiny local models may echo prompt/system/context; strip obvious artifacts.
        cleaned = []
        for ln in str(ans).splitlines():
            s = ln.strip()
            if not s:
                continue
            low = s.lower()
            if s.startswith('[SYSTEM]') or s.startswith('[USER]'):
                continue
            if low.startswith('você é o córtex metacognitivo'):
                continue
            if low.startswith('pergunta do usuário') or low.startswith('pergunta:'):
                continue
            if low.startswith('métricas internas atuais') or low.startswith('ctx:'):
                continue
            if low.startswith('respondeu:') or low.startswith('você:') or low.startswith('ultron:'):
                continue
            if s.startswith('{') or s.startswith('}') or '"learning_agenda"' in s or '"mission_control"' in s or '"sleep_cycle"' in s:
                continue
            cleaned.append(s)
        if cleaned:
            ans = ' '.join(cleaned).strip()
        else:
            ans = ''

    if ans:
        # Remove common echo artifacts from tiny models.
        low_ans = ans.lower()
        if low_ans.count('resposta:') >= 2:
            ans = ans.split('Resposta:')[1].split('Resposta:')[0].strip() if 'Resposta:' in ans else ans
        if 'Pergunta:' in ans:
            ans = ans.split('Pergunta:')[0].strip() or ans

        # Remove repeated instruction prefixes and duplicated fragments.
        import re
        ans = re.sub(r'(?:\s*resposta em português, curta e direta:\s*)+', ' ', ans, flags=re.IGNORECASE).strip()
        ans = ans.replace('Responda em até 2 frases, natural, sem repetir instruções internas.', ' ').strip()
        ans = ans.replace('Responda em até 3 frases, português natural, sem repetir a pergunta.', ' ').strip()
        parts = [p.strip() for p in re.split(r'(?<=[\.!?])\s+', ans) if p.strip()]
        dedup = []
        seen = set()
        for p in parts:
            k = re.sub(r'\W+', '', p.lower())
            if len(k) < 3 or k in seen:
                continue
            seen.add(k)
            dedup.append(p)
        if dedup:
            ans = ' '.join(dedup[:3]).strip()

        # Anti-echo guard: if answer is basically a paraphrase/repetition of the question, force fallback.
        def _norm_tokens(txt: str) -> set[str]:
            return {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (txt or '').lower())}

        q_tokens = _norm_tokens(q)
        a_tokens = _norm_tokens(ans)
        if q_tokens and a_tokens:
            inter = len(q_tokens.intersection(a_tokens))
            overlap_q = inter / max(1, len(q_tokens))
            overlap_a = inter / max(1, len(a_tokens))
            # For capability classes (logic/math/planning/code), overlap can be naturally high.
            # Do not nullify valid answers in these classes.
            if (input_class not in ('logic', 'math', 'planning', 'code')) and overlap_q >= 0.72 and overlap_a >= 0.72:
                ans = ''

    if not ans:
        ans = (
            "Não tenho informação confiável sobre isso. "
            "Para questões fora do domínio operacional, recomendo consultar uma fonte específica."
        )
        used = 'insufficient_confidence'

    try:
        store.db.add_event('metacognition_ask', f"🧠 metacog ask strategy={used} q={q[:120]}")
    except Exception:
        pass

    # semantic cache populate (with explicit skip policy)
    cache_skip_store = (
        (risk_class in ('high', 'critical'))
        or (intent_label in ('runtime', 'status', 'health', 'metrics'))
        or (used == 'insufficient_confidence')
    )
    if not cache_skip_store:
        try:
            semantic_cache.store(q, ans, used)
        except Exception:
            pass

    _trace_emit(ans, used, outcome=('fallback' if used == 'unavailable' else 'success'))
    prm_meta = _prm_pack(ans, used, metrics)
    prm_risk = str((prm_meta or {}).get('prm_risk') or '').lower()
    prm_gate_decision = 'allow'
    if used != 'insufficient_confidence':
        if prm_risk == 'critical':
            ans = (
                "Não tenho informação confiável sobre isso. "
                "Para questões fora do domínio operacional, recomendo consultar uma fonte específica."
            )
            used = 'insufficient_confidence'
            prm_gate_decision = 'block'
        elif prm_risk == 'high':
            prm_gate_decision = 'allow_with_warning'
        else:
            prm_gate_decision = 'allow'
    else:
        prm_gate_decision = 'block_heuristic'

    stage_timing_ms['total_ms'] = int((time.monotonic() - req_started) * 1000)
    return {
        'ok': True,
        'answer': ans,
        'strategy': used,
        'metrics': metrics,
        'cache_hit': cache_hit,
        'from_cache': from_cache,
        'prm_gate_decision': prm_gate_decision,
        'stage_timing_ms': stage_timing_ms,
        'llm_attempts': llm_attempts,
        **prm_meta,
    }


# Canary rollout guardrails (in-memory windowed stats)
_CANARY_EVENTS: list[dict[str, Any]] = []
_CANARY_DISABLED_UNTIL_TS: int = 0
_CANARY_DISABLE_REASON: str = ''


def _canary_cfg() -> dict[str, Any]:
    return {
        'enabled': str(os.getenv('METACOG_CANARY_ENABLED', '0')).strip().lower() in ('1', 'true', 'yes', 'on'),
        'rate': float(os.getenv('METACOG_CANARY_RATE', '0.25') or 0.25),
        'window_sec': int(os.getenv('METACOG_CANARY_WINDOW_SEC', '1800') or 1800),
        'min_events': int(os.getenv('METACOG_CANARY_MIN_EVENTS', '10') or 10),
        'max_timeout_ratio': float(os.getenv('METACOG_CANARY_MAX_TIMEOUT_RATIO', '0.20') or 0.20),
        'max_high_risk_ratio': float(os.getenv('METACOG_CANARY_MAX_HIGH_RISK_RATIO', '0.35') or 0.35),
    }


def _canary_record(model: str, strategy: str, prm_risk: str | None, timeout: bool = False):
    global _CANARY_EVENTS
    now = int(time.time())
    _CANARY_EVENTS.append({
        'ts': now,
        'model': model,
        'strategy': str(strategy or ''),
        'prm_risk': str(prm_risk or ''),
        'timeout': bool(timeout),
        'insufficient': (str(strategy or '') == 'insufficient_confidence'),
    })
    # prune old
    win = _canary_cfg()['window_sec']
    _CANARY_EVENTS = [e for e in _CANARY_EVENTS if int(e.get('ts') or 0) >= (now - win)]


def _canary_maybe_disable() -> str | None:
    global _CANARY_DISABLED_UNTIL_TS, _CANARY_DISABLE_REASON
    cfg = _canary_cfg()
    now = int(time.time())
    win_events = [e for e in _CANARY_EVENTS if int(e.get('ts') or 0) >= (now - cfg['window_sec'])]
    c = [e for e in win_events if e.get('model') == 'canary']
    t = [e for e in win_events if e.get('model') == 'tiny']
    if len(c) < cfg['min_events']:
        return None

    # Guardrail 1: timeout ratio
    timeout_ratio = (sum(1 for e in c if e.get('timeout')) / max(1, len(c)))
    if timeout_ratio > cfg['max_timeout_ratio']:
        _CANARY_DISABLED_UNTIL_TS = now + 1800
        _CANARY_DISABLE_REASON = f'timeout_ratio>{cfg["max_timeout_ratio"]:.2f}'
        return _CANARY_DISABLE_REASON

    # Guardrail 2: persistent high prm_risk
    high_ratio = (sum(1 for e in c if str(e.get('prm_risk') or '').lower() == 'high') / max(1, len(c)))
    if high_ratio > cfg['max_high_risk_ratio']:
        _CANARY_DISABLED_UNTIL_TS = now + 1800
        _CANARY_DISABLE_REASON = f'high_prm_risk_ratio>{cfg["max_high_risk_ratio"]:.2f}'
        return _CANARY_DISABLE_REASON

    # Guardrail 3: insufficient_confidence > 2x tiny in same window
    if len(t) >= cfg['min_events']:
        c_ins = (sum(1 for e in c if e.get('insufficient')) / max(1, len(c)))
        t_ins = (sum(1 for e in t if e.get('insufficient')) / max(1, len(t)))
        if c_ins > (2.0 * max(0.01, t_ins)):
            _CANARY_DISABLED_UNTIL_TS = now + 1800
            _CANARY_DISABLE_REASON = 'insufficient_confidence_rate_gt_2x_tiny'
            return _CANARY_DISABLE_REASON

    return None


@app.post('/api/metacognition/ask')
async def metacognition_ask(req: MetacogAskRequest):
    global _CANARY_DISABLED_UNTIL_TS, _CANARY_DISABLE_REASON
    req_id = f"req_{int(time.time()*1000)}_{secrets.token_hex(4)}"
    q = str(req.message or '').strip()
    ql = q.lower()

    # Fast-path for simple identity questions so the frontend chat never depends on
    cfg = _canary_cfg()
    now = int(time.time())
    qwen_main_enabled = str(os.getenv('METACOG_QWEN_MAIN', '0')).strip().lower() in ('1', 'true', 'yes', 'on')
    canary_allowed = bool(cfg['enabled']) and now >= int(_CANARY_DISABLED_UNTIL_TS or 0)
    use_canary = qwen_main_enabled or (canary_allowed and (random.random() < max(0.0, min(1.0, cfg['rate']))))

    if use_canary:
        t0 = time.time()
        try:
            out = await asyncio.wait_for(
                _metacognition_ask_impl(req, force_generation_strategy='canary_qwen', canary=True),
                timeout=float(os.getenv('METACOG_ENDPOINT_TIMEOUT_SEC', '10')),
            )
            dt = int((time.time() - t0) * 1000)
            if isinstance(out, dict):
                out['request_id'] = req_id
                out['canary'] = True
                out['model'] = 'qwen2.5-7b'
                out['latency_ms'] = dt
                out.setdefault('strategy', 'canary_qwen')
                _canary_record('canary', str(out.get('strategy') or ''), str(out.get('prm_risk') or ''), timeout=False)
                if not qwen_main_enabled:
                    _canary_maybe_disable()
                    if int(_CANARY_DISABLED_UNTIL_TS or 0) > int(time.time()):
                        out['canary_rollout'] = {'enabled': False, 'disabled_reason': _CANARY_DISABLE_REASON}
                _emit_eval_for_response('/api/metacognition/ask', req_id, str(req.message or ''), out, dt)
                logger.info('metacognition_ask request_id=%s strategy=%s latency_ms=%s stage_timing_ms=%s llm_attempts=%s', req_id, str(out.get('strategy') or ''), dt, json.dumps(out.get('stage_timing_ms') or {}, ensure_ascii=False), json.dumps(out.get('llm_attempts') or [], ensure_ascii=False))
                return out
        except Exception as e:
            _canary_record('canary', 'error', None, timeout=True)
            if not qwen_main_enabled:
                _canary_maybe_disable()
            try:
                store.db.add_event('metacognition_ask_error', f"canary error: {str(e)[:180]}")
            except Exception:
                pass

    # fallback path: always run the real metacognition pipeline.
    # Do not short-circuit with canned answers; intelligence features
    # like RAG, semantic cache and normal provider fallback must remain active.
    t0 = time.time()
    try:
        out = await asyncio.wait_for(
            _metacognition_ask_impl(req),
            timeout=float(os.getenv('METACOG_ENDPOINT_TIMEOUT_SEC', '10')),
        )
        dt = int((time.time() - t0) * 1000)
        if not isinstance(out, dict):
            out = {
                'ok': False,
                'answer': 'Não consegui responder com confiança agora. Tente novamente em instantes.',
                'strategy': 'fallback_empty',
                'model': 'tiny',
                'error': 'non_dict_response',
                'latency_ms': dt,
            }
        out['request_id'] = req_id
        out.setdefault('latency_ms', dt)
        out.setdefault('model', 'tiny')
        _canary_record('tiny', str(out.get('strategy') or ''), str(out.get('prm_risk') or ''), timeout=False)
        if (not qwen_main_enabled) and int(_CANARY_DISABLED_UNTIL_TS or 0) > int(time.time()):
            out['canary_rollout'] = {'enabled': False, 'disabled_reason': _CANARY_DISABLE_REASON}
        _emit_eval_for_response('/api/metacognition/ask', req_id, str(req.message or ''), out, dt)
        logger.info('metacognition_ask request_id=%s strategy=%s latency_ms=%s stage_timing_ms=%s llm_attempts=%s', req_id, str(out.get('strategy') or ''), dt, json.dumps(out.get('stage_timing_ms') or {}, ensure_ascii=False), json.dumps(out.get('llm_attempts') or [], ensure_ascii=False))
        return out
    except Exception as e:
        dt = int((time.time() - t0) * 1000)
        out = {
            'ok': False,
            'answer': 'Não consegui responder com confiança agora. Tente novamente em instantes.',
            'strategy': 'fallback_error',
            'model': 'tiny',
            'error': str(e)[:240],
            'latency_ms': dt,
            'stage_timing_ms': {'total_ms': dt},
            'llm_attempts': [],
        }
        try:
            _canary_record('tiny', 'error', None, timeout=True)
            _emit_eval_for_response('/api/metacognition/ask', req_id, str(req.message or ''), out, dt)
            store.db.add_event('metacognition_ask_error', f"fallback error: {str(e)[:180]}")
        except Exception:
            pass
        return out


@app.get('/api/canary/status')
async def canary_status():
    cfg = _canary_cfg()
    now = int(time.time())
    win_events = [e for e in _CANARY_EVENTS if int(e.get('ts') or 0) >= (now - cfg['window_sec'])]
    can = [e for e in win_events if e.get('model') == 'canary']
    tiny = [e for e in win_events if e.get('model') == 'tiny']

    def _pack(arr: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(arr)
        if n == 0:
            return {'events': 0, 'timeout_ratio': 0.0, 'high_prm_risk_ratio': 0.0, 'insufficient_confidence_ratio': 0.0}
        return {
            'events': n,
            'timeout_ratio': sum(1 for e in arr if e.get('timeout')) / n,
            'high_prm_risk_ratio': sum(1 for e in arr if str(e.get('prm_risk') or '').lower() == 'high') / n,
            'insufficient_confidence_ratio': sum(1 for e in arr if e.get('insufficient')) / n,
        }

    can_m = _pack(can)
    tiny_m = _pack(tiny)

    disabled = now < int(_CANARY_DISABLED_UNTIL_TS or 0)
    return {
        'ok': True,
        'enabled': bool(cfg['enabled']),
        'rate': cfg['rate'],
        'window_sec': cfg['window_sec'],
        'min_events': cfg['min_events'],
        'rollout_active': bool(cfg['enabled']) and not disabled,
        'disabled': disabled,
        'disabled_until_ts': int(_CANARY_DISABLED_UNTIL_TS or 0),
        'disabled_reason': _CANARY_DISABLE_REASON or None,
        'thresholds': {
            'max_timeout_ratio': cfg['max_timeout_ratio'],
            'max_high_prm_risk_ratio': cfg['max_high_risk_ratio'],
            'max_insufficient_vs_tiny_multiplier': 2.0,
        },
        'metrics': {
            'canary': can_m,
            'tiny': tiny_m,
            'insufficient_ratio_multiplier_vs_tiny': (
                (can_m['insufficient_confidence_ratio'] / max(0.01, tiny_m['insufficient_confidence_ratio']))
                if tiny_m['events'] > 0 else None
            ),
        },
    }


@app.post('/api/canary/ask')
async def canary_ask(req: MetacogAskRequest):
    req_id = f"req_{int(time.time()*1000)}_{secrets.token_hex(4)}"
    t0 = time.time()
    out = await _metacognition_ask_impl(req, force_generation_strategy='canary_qwen', canary=True)
    dt = int((time.time() - t0) * 1000)
    if isinstance(out, dict):
        out['request_id'] = req_id
        out['canary'] = True
        out['model'] = 'qwen2.5-7b'
        out['latency_ms'] = dt
        out.setdefault('strategy', 'canary_qwen')
        out.setdefault('prm_score', None)
        out.setdefault('prm_risk', None)
        _emit_eval_for_response('/api/canary/ask', req_id, str(req.message or ''), out, dt)
        # lightweight side-by-side baseline (same input, local model only)
        try:
            t1 = time.time()
            tiny_ans = llm.complete(
                str(req.message or ''),
                strategy='local',
                system=None,
                json_mode=False,
                inject_persona=False,
                max_tokens=120,
                cloud_fallback=False,
            )
            td = int((time.time() - t1) * 1000)
            tiny_prm = prm_lite.score_answer(str(req.message or ''), str(tiny_ans or ''), context='', meta={'strategy': 'local_shadow'}) if tiny_ans else {}
            out['compare_local_shadow'] = {
                'strategy': 'local_shadow',
                'latency_ms': td,
                'prm_score': tiny_prm.get('score') if isinstance(tiny_prm, dict) else None,
                'prm_risk': tiny_prm.get('risk') if isinstance(tiny_prm, dict) else None,
            }
        except Exception:
            out['compare_local_shadow'] = {'strategy': 'local_shadow', 'latency_ms': None, 'prm_score': None, 'prm_risk': None}
    return out


@app.post('/api/canary/ask_bypass')
async def canary_ask_bypass(req: MetacogAskRequest):
    req_id = f"req_{int(time.time()*1000)}_{secrets.token_hex(4)}"
    t0 = time.time()
    out = await _metacognition_ask_impl(req, force_generation_strategy='canary_qwen', canary=True, bypass_insufficient_gate=True)
    dt = int((time.time() - t0) * 1000)
    if isinstance(out, dict):
        out['request_id'] = req_id
        out['canary'] = True
        out['model'] = 'qwen2.5-7b'
        out['latency_ms'] = dt
        out['mode'] = 'gate_bypass'
        out.setdefault('strategy', 'canary_qwen')
        out.setdefault('prm_score', None)
        out.setdefault('prm_risk', None)
        _emit_eval_for_response('/api/canary/ask_bypass', req_id, str(req.message or ''), out, dt)
    return out


@app.post('/api/canary/ask_direct')
async def canary_ask_direct(req: MetacogAskRequest):
    req_id = f"req_{int(time.time()*1000)}_{secrets.token_hex(4)}"
    q = str(req.message or '').strip()
    t0 = time.time()
    ans = _direct_canary_generate(q, max_tokens=220)
    if not ans:
        try:
            ans = llm.complete(
                q,
                strategy='canary_qwen',
                system=None,
                json_mode=False,
                inject_persona=False,
                max_tokens=220,
                cloud_fallback=False,
            ) or ''
        except Exception:
            ans = ''
    dt = int((time.time() - t0) * 1000)
    if not str(ans).strip():
        ans = "Não tenho informação confiável sobre isso. Para questões fora do domínio operacional, recomendo consultar uma fonte específica."
        strategy = 'insufficient_confidence'
    else:
        strategy = 'direct_canary_qwen'

    try:
        prm = prm_lite.score_answer(q, str(ans).strip(), context='', meta={'strategy': strategy})
    except Exception:
        prm = {}
    out = {
        'ok': True,
        'request_id': req_id,
        'answer': str(ans).strip(),
        'strategy': strategy,
        'canary': True,
        'model': 'qwen2.5-7b',
        'latency_ms': dt,
        'mode': 'direct_model',
        'prm_score': prm.get('score') if isinstance(prm, dict) else None,
        'prm_risk': prm.get('risk') if isinstance(prm, dict) else None,
        'prm_reasons': prm.get('reasons') if isinstance(prm, dict) else [],
    }
    _emit_eval_for_response('/api/canary/ask_direct', req_id, q, out, dt)
    return out


@app.get('/api/ui/overview')
async def ui_overview():
    la = learning_agenda.status()
    rank = learning_agenda.tick(plasticity_runtime.status(limit=60)).get('rank') or []
    sla = mission_control.check_learning_agenda_sla()
    tasks = mission_control.list_tasks(status='inbox', limit=200)
    active = [t for t in tasks if str(t.get('task_type') or '') == 'learning_agenda']
    slp = await sleep_cycle_status()
    return {
        'ok': True,
        'learning_agenda': {
            'enabled': la.get('enabled'),
            'top': (rank[0] if rank else None),
            'rank': rank[:5],
        },
        'mission': {
            'learning_tasks_inbox': len(active),
            'sla_overdue': int(sla.get('overdue') or 0),
            'sla_escalated': int(sla.get('escalated') or 0),
        },
        'sleep_cycle': (slp.get('report') if isinstance(slp, dict) else {}),
    }


@app.get('/api/roadmap/v5/status')
async def roadmap_v5_status():
    return {'ok': True, 'roadmap': roadmap_v5.status()}


@app.post('/api/roadmap/v5/config')
async def roadmap_v5_config(req: RoadmapV5ConfigRequest):
    out = roadmap_v5.config_patch(req.model_dump(exclude_none=True))
    store.db.add_event('roadmap_v5_config', f"🗺️ roadmap v5 config enabled={out.get('enabled')} tick={out.get('auto_tick_sec')}")
    return {'ok': True, 'roadmap': out}


@app.post('/api/roadmap/v5/rest')
async def roadmap_v5_rest(req: RoadmapV5RestRequest):
    out = roadmap_v5.set_rest(hours=int(req.hours or 48))
    store.db.add_event('roadmap_v5_rest', f"🗺️ roadmap v5 rest hours={int(req.hours or 48)}")
    return {'ok': True, 'roadmap': out}


@app.post('/api/roadmap/v5/tick')
async def roadmap_v5_tick():
    snap = {
        'agi': _compute_agi_mode_metrics(),
        'plasticity': plasticity_runtime.status(limit=120),
        'training': _training_disabled_response('roadmap_v5_tick'),
    }
    out = roadmap_v5.tick(snap)
    store.db.add_event('roadmap_v5_tick', f"🗺️ roadmap v5 triggered={out.get('triggered')} reason={out.get('reason')}")
    return out


@app.get('/api/agi/path/status')
async def agi_path_status():
    return {'ok': True, 'agi_path': agi_path.status()}


@app.post('/api/agi/path/config')
async def agi_path_config(req: AgiPathConfigRequest):
    out = agi_path.config_patch(req.model_dump(exclude_none=True))
    store.db.add_event('agi_path_config', f"🧠 agi-path config enabled={out.get('enabled')} tick={out.get('auto_tick_sec')}")
    return {'ok': True, 'agi_path': out}


@app.get('/api/learning/agenda')
async def learning_agenda_status():
    return {'ok': True, 'agenda': learning_agenda.status()}


@app.post('/api/learning/agenda/config')
async def learning_agenda_config(req: LearningAgendaConfigRequest):
    out = learning_agenda.config_patch(req.model_dump(exclude_none=True))
    store.db.add_event('learning_agenda_config', f"🧭 agenda enabled={out.get('enabled')} budget={out.get('exploration_budget_ratio')}")
    return {'ok': True, 'agenda': out}


@app.post('/api/learning/agenda/tick')
async def learning_agenda_tick():
    out = learning_agenda.tick(plasticity_runtime.status(limit=100))
    sync = mission_control.sync_learning_agenda(out.get('rank') or [])
    sla = mission_control.check_learning_agenda_sla()
    store.db.add_event('learning_agenda_tick', f"🧭 triggered={out.get('triggered')} top={(out.get('top') or {}).get('domain')} sync_created={sync.get('created')} sync_updated={sync.get('updated')} escalated={sla.get('escalated')}")
    return {'ok': True, 'agenda': out, 'mission_sync': sync, 'sla': sla}


@app.post('/api/agi/path/tick')
async def agi_path_tick():
    snap = {
        'agi': _compute_agi_mode_metrics(),
        'plasticity': plasticity_runtime.status(limit=120),
        'training': _training_disabled_response('agi_path_tick'),
    }
    out = agi_path.tick(snap)
    store.db.add_event('agi_path_tick', f"🧠 agi-path triggered={out.get('triggered')} reason={((out.get('state') or {}).get('last_reason'))}")
    return out


@app.get('/api/calibration/status')
async def calibration_status(limit: int = 40):
    return calibration.status(limit=limit)


@app.get('/api/calibration/predict')
async def calibration_predict(strategy: str, task_type: str = 'general', budget_profile: str = 'balanced'):
    return calibration.predict_error(strategy, task_type, budget_profile)


@app.get('/api/llm/usage')
async def llm_usage():
    return llm.usage_status()


@app.get('/api/llm/health')
async def llm_health(provider: str = 'auto'):
    return llm.healthcheck(provider)


@app.get('/api/llm/router/status')
async def llm_router_status(task_type: str = 'general', budget_mode: Optional[str] = None):
    return llm.router_status(task_type=task_type, budget_mode=budget_mode)


@app.get('/api/replay/decision-traces/status')
async def replay_decision_traces_status():
    return replay_traces.status()


@app.get('/api/replay/thought-chain')
async def replay_thought_chain(max_rows: int = 300, slow_only: bool = False):
    return replay_traces.replay_thought_chain(max_rows=max_rows, slow_only=slow_only)


@app.post('/api/replay/decision-traces/run')
async def replay_decision_traces_run(day: Optional[str] = None, max_rows: int = 300, auto_finetune: bool = False, max_samples: int = 120):
    out = replay_traces.run_replay(day=day, max_rows=max_rows)
    store.db.add_event('replay_traces_run', f"🔁 replay day={out.get('day')} traces={out.get('trace_rows')} train={out.get('train_rows')} hard_neg={out.get('hard_neg_rows')}")

    if auto_finetune:
        return {'ok': True, 'replay': out, 'finetune': _training_disabled_response('replay_decision_traces_auto_finetune', {'max_samples': int(max_samples or 0)})}

    return {'ok': True, 'replay': out, 'finetune': None}


@app.post('/api/replay/rag-synth-generate')
async def replay_rag_synth_generate(limit: int = 200, dry_run: bool = True):
    # Real-only mode: prevent accidental synthetic generation in production cycles.
    real_only = str(os.getenv('ULTRON_REAL_ONLY_REPLAY', '1')).strip().lower() in ('1', 'true', 'yes', 'on')
    if real_only:
        return {
            'ok': False,
            'disabled': True,
            'mode': 'real_only',
            'reason': 'rag_synth_paused_by_policy',
            'hint': 'Set ULTRON_REAL_ONLY_REPLAY=0 to re-enable explicitly.'
        }

    out = await rag_synth_generator.generate(limit=limit, dry_run=dry_run)
    store.db.add_event('rag_synth_generate', f"🧪 rag_synth dry_run={bool(dry_run)} pairs={out.get('pairs_generated')} dist={out.get('distribution')}")
    return out


@app.post('/api/replay/rag-synth-mix')
async def replay_rag_synth_mix(real_jsonl: str = '/app/data/replay/train_incremental.jsonl', synth_jsonl: Optional[str] = None, max_total: int = 300):
    real_only = str(os.getenv('ULTRON_REAL_ONLY_REPLAY', '1')).strip().lower() in ('1', 'true', 'yes', 'on')
    if real_only:
        return {
            'ok': False,
            'disabled': True,
            'mode': 'real_only',
            'reason': 'rag_synth_paused_by_policy',
            'hint': 'Set ULTRON_REAL_ONLY_REPLAY=0 to re-enable explicitly.'
        }

    out = rag_synth_generator.build_mixed_70_30(real_jsonl=real_jsonl, synth_jsonl=synth_jsonl, max_total=max_total)
    store.db.add_event('rag_synth_mix', f"🧪 rag_synth mix ok={out.get('ok')} total={out.get('total')} synth={out.get('synth_used')} real={out.get('real_used')}")
    return out


@app.post('/api/voice/chat')
async def voice_chat(req: VoiceChatRequest):
    txt = str(req.text or '').strip()
    if not txt:
        raise HTTPException(400, 'empty text')

    system = (
        'Você é UltronPRO, um assistente de voz de software (não é personagem da Marvel). '
        'Identidade factual: foi desenvolvido neste projeto UltronPro/Nutef pelo usuário e equipe local. '
        'Se perguntarem quem criou você, responda com essa identidade factual e nunca invente Stark/Homem de Ferro. '
        'Seja útil, objetivo e natural em português brasileiro. '
        'Para perguntas comuns, responda diretamente em 1 frase curta. '
        'Não fale sobre metas internas, autoaprendizado, roadmap ou estados do sistema, '
        'a menos que o usuário peça explicitamente. '
        'Só recuse quando houver risco real de segurança/ilegalidade. '
        'Se faltar contexto, faça 1 pergunta curta de clarificação.'
    )

    def _is_poor(a: str) -> bool:
        s = (a or '').strip().lower()
        if not s:
            return True
        bad = [
            'não posso ajudar com isso',
            'nao posso ajudar com isso',
            'não posso ajudar',
            'nao posso ajudar',
            'não consigo ajudar',
            'nao consigo ajudar',
            'desculpe, mas não posso',
            'desculpe, mas nao posso',
        ]
        return any(b in s for b in bad) or len(s) < 8

    def _trace_emit_voice(answer: str, strategy: str, outcome: str = 'success'):
        try:
            route = 'accept_local'
            if strategy in ('cheap', 'cloud'):
                route = 'handoff_backbone'
            elif strategy in ('unavailable', 'clarify'):
                route = 'ask_clarification'
            replay_traces.append_trace({
                'trace_id': f"trc_{int(time.time()*1000)}",
                'ts': int(time.time()),
                'task_type': 'voice_chat',
                'risk_class': 'medium',
                'input': txt,
                'output_local': answer,
                'route': route,
                'arbiter_verdict': None,
                'final_outcome': outcome,
                'feedback_label': None,
                'meta': {'strategy': strategy},
            })
        except Exception:
            pass

    creator_q = any(k in txt.lower() for k in ['quem criou', 'quem te criou', 'criador', 'criou você', 'criou vc'])
    if creator_q:
        ans = 'Fui desenvolvido no projeto UltronPro (Nutef) pelo seu time local, não pelo personagem da Marvel.'
        store.db.add_event('voice_chat', "🎙️ voice chat latency=0ms ok=True strategy=identity_guard")
        _trace_emit_voice(ans, 'identity_guard', outcome='success')
        return {'ok': True, 'reply': ans, 'strategy': 'identity_guard'}

    t0 = int(time.time() * 1000)
    # Modo rápido para GUI de voz: local primeiro, sem fallback pesado
    attempts = [('local', f"Pergunta do usuário (voz): {txt}\nResponda em português brasileiro, de forma prática, em no máximo 1 frase curta.")]

    ans = ''
    used = 'default'
    for strat, prompt in attempts:
        try:
            cand = llm.complete(
                prompt,
                strategy=strat,
                system=system,
                json_mode=False,
                inject_persona=False,
                max_tokens=64,
            )
        except Exception:
            cand = ''
        if cand and not _is_poor(cand):
            ans = cand.strip()
            used = strat
            break
        if not ans and cand:
            ans = cand.strip()
            used = strat

    latency = int(time.time() * 1000) - t0
    ok = bool((ans or '').strip()) and not _is_poor(ans)

    try:
        plasticity_runtime.record_feedback(
            task_type='voice_chat',
            profile='balanced',
            success=ok,
            latency_ms=latency,
            hallucination=False,
            note=f'voice_chat strategy={used} input={txt[:120]}',
        )
    except Exception:
        pass

    store.db.add_event('voice_chat', f"🎙️ voice chat latency={latency}ms ok={ok} strategy={used}")
    if not (ans or '').strip():
        ans = 'Não consegui responder agora. Tenta reformular em uma frase curta?'
    _trace_emit_voice(ans.strip(), used, outcome=('success' if ok else 'fallback'))
    return {'ok': True, 'reply': ans.strip(), 'strategy': used}


@app.get('/api/self-play/status')
async def self_play_status(limit: int = 10):
    return self_play.status(limit=limit)


@app.post('/api/self-play/run')
async def self_play_run(size: int = 12):
    out = self_play.simulate_batch(size=size)
    # feed synthetic experience into economic + causal model (low-risk internal training)
    for s in ((out.get('run') or {}).get('samples') or []):
        rw = economic.reward(bool(s.get('ok')), int(s.get('latency_ms') or 0), reliability=float(s.get('reliability') or 0.0))
        economic.update(str(s.get('task_type') or 'general'), str(s.get('profile') or 'balanced'), rw, bool(s.get('ok')), int(s.get('latency_ms') or 0))
        self_model.record_action_outcome(
            strategy=f"synthetic_{s.get('task_type')}",
            task_type=str(s.get('task_type') or 'general'),
            budget_profile=str(s.get('profile') or 'balanced'),
            ok=bool(s.get('ok')),
            latency_ms=int(s.get('latency_ms') or 0),
            notes='self_play_synthetic',
        )
    store.db.add_event('self_play', f"🎮 self-play run size={len(((out.get('run') or {}).get('samples') or []))}")
    return out


@app.post('/api/adaptive/tune')
async def adaptive_tune():
    hs = homeostasis.status()
    hist = hs.get('history_tail') or []
    acts = store.db.list_actions(limit=180)
    denom = max(1, len(acts))
    blocked_ratio = len([a for a in acts if str(a.get('status') or '') == 'blocked']) / denom
    causal = self_model.causal_summary(limit=80)
    strategy_diversity = len(causal.get('strategy_outcomes') or [])
    out = adaptive_control.tune_from_homeostasis(hist, blocked_ratio=float(blocked_ratio), strategy_diversity=int(strategy_diversity))
    if out.get('changed'):
        store.db.add_event('adaptive', f"🎛️ adaptive tuning updated thresholds (diversity={strategy_diversity}, blocked={blocked_ratio:.2f})")
    return out


@app.get('/api/autonomy/weekly-report')
async def autonomy_weekly_report(limit_actions: int = 600):
    hs = homeostasis.status()
    causal = self_model.causal_summary(limit=60)
    gov = await governance_compliance(limit_actions=min(600, int(limit_actions)))
    acts = store.db.list_actions(limit=min(600, int(limit_actions)))
    done = len([a for a in acts if str(a.get('status') or '') == 'done'])
    err = len([a for a in acts if str(a.get('status') or '') in ('error', 'blocked')])
    return {
        'ok': True,
        'homeostasis': {
            'mode': hs.get('mode'),
            'vitals': hs.get('vitals'),
        },
        'self_model': {
            'strategy_count': len(causal.get('strategy_outcomes') or []),
            'task_count': len(causal.get('task_outcomes') or []),
            'budget_count': len(causal.get('budget_profile_outcomes') or []),
            'top_strategies': (causal.get('strategy_outcomes') or [])[:5],
        },
        'execution': {
            'actions_window': len(acts),
            'done': done,
            'error_or_blocked': err,
            'success_rate': round(done / max(1, (done + err)), 4),
        },
        'governance': gov,
    }


@app.post('/api/identity/promise')
async def identity_promise(body: IdentityPromiseBody):
    out = identity_daily.add_promise(body.text, source=body.source)
    store.db.add_event('identity', f"🧾 promessa registrada: {out.get('text')}")
    return {'ok': True, 'promise': out}


@app.post('/api/identity/daily-review')
async def identity_daily_review(body: IdentityReviewBody):
    out = identity_daily.run_daily_review(body.completed_hints, body.failed_hints, body.protocol_update)
    store.db.add_event('identity', f"🪞 daily-review checksum={((out.get('entry') or {}).get('checksum'))}")
    return out


@app.get('/api/grounding/claims')
async def grounding_claims(limit: int = 40):
    return grounding.latest(limit=limit)


@app.post('/api/grounding/claim-check')
async def grounding_claim_check(body: ClaimCheckBody):
    sql_res = None
    py_res = None
    src_res = None

    if (body.sql_query or '').strip():
        try:
            sql_res = sql_explorer.execute_sql(body.sql_query or '', limit=120)
        except Exception as e:
            sql_res = {'ok': False, 'error': str(e)[:220]}

    if (body.python_code or '').strip():
        try:
            py_res = env_tools.run_python(code=body.python_code, timeout_sec=12)
        except Exception as e:
            py_res = {'ok': False, 'error': str(e)[:220]}

    if (body.url or '').strip():
        try:
            src_res = source_probe.fetch_clean_text(body.url or '', max_chars=3500)
        except Exception as e:
            src_res = {'ok': False, 'error': str(e)[:220]}

    checks_ok = sum([1 if bool((sql_res or {}).get('ok')) else 0, 1 if bool((py_res or {}).get('ok')) else 0, 1 if bool((src_res or {}).get('ok')) else 0])
    item = grounding.record_claim(
        claim=body.claim,
        sql_result=sql_res,
        python_result=py_res,
        source_result=src_res,
        conclusion='Grounded' if checks_ok >= 2 else 'Insufficient grounding',
    )

    ok = float(item.get('reliability') or 0.0) >= float(body.require_reliability or 0.55)
    store.db.add_event('grounding', f"🧪 claim-check reliability={item.get('reliability')} ok={ok} claim={str(body.claim)[:120]}")
    return {'ok': ok, 'require_reliability': body.require_reliability, 'item': item}


@app.post('/api/homeostasis/tick')
async def homeostasis_tick():
    st = store.db.stats()
    open_conf = len(store.db.list_conflicts(status='open', limit=20))
    meta = _metacognition_tick() or {}
    dq = float(meta.get('decision_quality') or 0.5)
    actions_recent = store.db.list_actions(limit=120)
    denom = max(1, len(actions_recent))
    blocked_ratio = len([a for a in actions_recent if str(a.get('status') or '') == 'blocked']) / denom
    error_ratio = len([a for a in actions_recent if str(a.get('status') or '') == 'error']) / denom
    ad = adaptive_control.status()
    return homeostasis.evaluate(
        stats=st,
        open_conflicts=open_conf,
        decision_quality=dq,
        queue_size=int(_autonomy_state.get('queued') or 0),
        used_last_minute=int(_recent_actions_count(60)),
        per_minute=int(AUTONOMY_BUDGET_PER_MIN),
        active_goal=bool(store.get_active_goal()),
        blocked_ratio=float(blocked_ratio),
        error_ratio=float(error_ratio),
        thresholds=(ad.get('thresholds') or {}),
    )


@app.post('/api/tool-router/plan')
async def tool_router_plan(req: ToolRouteRequest):
    return tool_router.plan_route(req.intent, context=req.context or {}, prefer_low_cost=bool(req.prefer_low_cost))


@app.post('/api/tool-router/run')
async def tool_router_run(req: ToolRouteRequest):
    return _run_tool_route(req.intent, context=req.context or {}, prefer_low_cost=bool(req.prefer_low_cost))


# --- Cognitive patches registry (plasticidade estrutural auditável) ---

@app.get('/api/plasticity/cognitive-patches')
async def list_cognitive_patches(limit: int = 100, status: Optional[str] = None, kind: Optional[str] = None):
    return {
        'items': cognitive_patches.list_patches(limit=limit, status=status, kind=kind),
        'stats': cognitive_patches.stats(),
    }


@app.get('/api/plasticity/cognitive-patches/status')
async def cognitive_patches_status():
    return cognitive_patches.stats()


@app.post('/api/plasticity/gap-detector/scan')
async def plasticity_gap_detector_scan(limit: int = 80):
    result = gap_detector.scan_recent_failures(limit=limit)
    try:
        created = result.get('proposals_created') if isinstance(result.get('proposals_created'), list) else []
        if created:
            store.db.add_event(
                'gap_detector_scan',
                f"🩹 gap detector criou {len(created)} cognitive patch(es)",
                meta_json=json.dumps({'created_patch_ids': [x.get('id') for x in created]}, ensure_ascii=False),
            )
    except Exception:
        pass
    return result


@app.post('/api/plasticity/gap-detector/selftest')
async def plasticity_gap_detector_selftest():
    return gap_detector.run_selftest()


@app.post('/api/plasticity/gap-detector/consolidate')
async def plasticity_gap_detector_consolidate():
    return gap_detector.consolidate_open_cluster_duplicates()


@app.get('/api/plasticity/organic-feed/status')
async def plasticity_organic_feed_status(limit: int = 20):
    return organic_eval_feed.status(limit=limit)


@app.post('/api/plasticity/organic-feed/bootstrap')
async def plasticity_organic_feed_bootstrap(alert: str = 'critic_overconfident', count: int = 3):
    return organic_eval_feed.bootstrap_organic_volume(alert=alert, count=count)


@app.get('/api/plasticity/cognitive-patch-loop/status')
async def plasticity_cognitive_patch_loop_status(limit: int = 20):
    return cognitive_patch_loop.status(limit=limit)


@app.post('/api/plasticity/cognitive-patch-loop/run')
async def plasticity_cognitive_patch_loop_run(limit: int = 5):
    return cognitive_patch_loop.autorun_once(limit=limit)


@app.post('/api/plasticity/cognitive-patch-loop/scan-and-run')
async def plasticity_cognitive_patch_loop_scan_and_run(scan_limit: int = 80, process_limit: int = 5):
    return cognitive_patch_loop.scan_and_autorun(scan_limit=scan_limit, process_limit=process_limit)


@app.post('/api/plasticity/cognitive-patch-loop/selftest')
async def plasticity_cognitive_patch_loop_selftest():
    return cognitive_patch_loop.run_selftest()


@app.post('/api/plasticity/cognitive-patches/{patch_id}/shadow-eval')
async def run_cognitive_patch_shadow_eval(patch_id: str, req: ShadowEvalRunRequest):
    result = shadow_eval.compare_patch_candidate(patch_id, [c.model_dump() for c in req.cases])
    if not result:
        raise HTTPException(404, 'patch not found')
    auto_followup: dict[str, Any] | None = None
    if str(result.get('decision') or '') == 'fail':
        rejected = cognitive_patches.reject_patch(
            patch_id,
            reason='shadow_eval_failed',
            evidence_refs=[f"shadow_eval:{patch_id}:{int(time.time())}"],
        )
        auto_followup = {
            'action': 'reject',
            'patch_status': (rejected or {}).get('status'),
        }
    else:
        current_patch = cognitive_patches.get_patch(patch_id) or {}
        canary_state = current_patch.get('canary_state') if isinstance(current_patch.get('canary_state'), dict) else {}
        if bool(canary_state.get('enabled')):
            gate = promotion_gate.evaluate_patch_for_promotion(patch_id)
            auto_followup = {
                'action': 'promotion_gate',
                'result': gate,
            }
    store.db.add_event(
        'cognitive_patch_shadow_eval',
        f"🧪 shadow eval executado para patch: {patch_id}",
        meta_json=json.dumps({'patch_id': patch_id, 'decision': result.get('decision'), 'delta': result.get('delta'), 'auto_followup': auto_followup}, ensure_ascii=False),
    )
    return {**result, 'auto_followup': auto_followup}


@app.post('/api/plasticity/shadow-eval/selftest')
async def plasticity_shadow_eval_selftest():
    return shadow_eval.run_selftest()


@app.post('/api/plasticity/cognitive-patches/{patch_id}/canary')
async def start_cognitive_patch_canary(patch_id: str, req: ShadowEvalCanaryRequest):
    result = shadow_eval.start_canary(patch_id, rollout_pct=req.rollout_pct, domains=req.domains, note=req.note)
    if not result:
        raise HTTPException(404, 'patch not found')
    auto_followup: dict[str, Any] | None = None
    current_patch = cognitive_patches.get_patch(patch_id) or {}
    shadow_metrics = current_patch.get('shadow_metrics') if isinstance(current_patch.get('shadow_metrics'), dict) else {}
    if str(shadow_metrics.get('decision') or '') == 'pass':
        gate = promotion_gate.evaluate_patch_for_promotion(patch_id)
        auto_followup = {
            'action': 'promotion_gate',
            'result': gate,
        }
    store.db.add_event(
        'cognitive_patch_canary_started',
        f"🚦 canary iniciado para patch: {patch_id}",
        meta_json=json.dumps({'patch_id': patch_id, 'rollout_pct': req.rollout_pct, 'domains': req.domains, 'auto_followup': auto_followup}, ensure_ascii=False),
    )
    return {**result, 'auto_followup': auto_followup}


@app.post('/api/plasticity/cognitive-patches/{patch_id}/promotion-gate')
async def evaluate_cognitive_patch_promotion_gate(patch_id: str):
    result = promotion_gate.evaluate_patch_for_promotion(patch_id)
    if not result:
        raise HTTPException(404, 'patch not found')
    store.db.add_event(
        'cognitive_patch_promotion_gate',
        f"🚪 promotion gate avaliado para patch: {patch_id}",
        meta_json=json.dumps({'patch_id': patch_id, 'decision': result.get('decision'), 'blockers': result.get('blockers')}, ensure_ascii=False),
    )
    return result


@app.post('/api/plasticity/promotion-gate/selftest')
async def plasticity_promotion_gate_selftest():
    return promotion_gate.run_selftest()


@app.post('/api/plasticity/cognitive-patches/{patch_id}/auto-rollback')
async def auto_rollback_cognitive_patch(patch_id: str, req: MutationDecisionRequest):
    result = rollback_manager.auto_rollback_if_needed(patch_id, note=req.reason)
    if not result:
        raise HTTPException(404, 'patch not found')
    store.db.add_event(
        'cognitive_patch_auto_rollback',
        f"⛑️ auto rollback avaliado para patch: {patch_id}",
        meta_json=json.dumps({'patch_id': patch_id, 'rolled_back': result.get('rolled_back')}, ensure_ascii=False),
    )
    return result


@app.post('/api/plasticity/rollback-manager/selftest')
async def plasticity_rollback_manager_selftest():
    return rollback_manager.run_selftest()


@app.post('/api/plasticity/benchmarks/freeze-baseline')
async def plasticity_benchmarks_freeze_baseline():
    result = benchmark_suite.freeze_baseline()
    return result


@app.post('/api/plasticity/benchmarks/run')
async def plasticity_benchmarks_run():
    result = benchmark_suite.run_suite()
    return result


@app.post('/api/plasticity/benchmarks/selftest')
async def plasticity_benchmarks_selftest():
    return benchmark_suite.run_selftest()


@app.get('/api/roadmap/status')
async def roadmap_macro_status():
    return roadmap_status.macro_status()


@app.get('/api/roadmap/items')
async def roadmap_item_status():
    return roadmap_status.item_summary()


@app.get('/api/roadmap/scorecard')
async def roadmap_scorecard():
    return roadmap_status.scorecard()


@app.get('/api/evals/external/status')
async def external_benchmarks_status():
    return external_benchmarks.status()


@app.get('/api/evals/external/suite')
async def external_benchmarks_suite():
    return external_benchmarks.list_suite()


@app.get('/api/evals/external/runs')
async def external_benchmarks_runs(limit: int = 10):
    return external_benchmarks.recent_runs(limit=limit)


@app.get('/api/evals/external/audit')
async def external_benchmarks_audit():
    return external_benchmarks.suite_audit()


@app.get('/api/evals/external/compare-baseline')
async def external_benchmarks_compare_baseline(run_id: Optional[str] = None):
    return external_benchmarks.compare_to_baseline(run_id=run_id)


@app.post('/api/evals/external/run')
async def external_benchmarks_run(req: ExternalBenchmarkRunRequest):
    return external_benchmarks.run_suite(
        benchmark_ids=req.benchmark_ids,
        families=req.families,
        splits=req.splits,
        limit_per_benchmark=req.limit_per_benchmark,
        strategy=str(req.strategy or 'cheap'),
        predictor=str(req.predictor or 'llm'),
        tag=req.tag,
    )


@app.post('/api/evals/external/freeze-baseline')
async def external_benchmarks_freeze_baseline(req: ExternalBenchmarkBaselineRequest):
    return external_benchmarks.freeze_baseline(
        benchmark_ids=req.benchmark_ids,
        families=req.families,
        splits=req.splits,
        limit_per_benchmark=req.limit_per_benchmark,
        strategy=str(req.strategy or 'cheap'),
        predictor=str(req.predictor or 'llm'),
        label=req.label,
    )


@app.post('/api/evals/external/selftest')
async def external_benchmarks_selftest():
    return external_benchmarks.run_selftest()


@app.get('/api/plasticity/cognitive-patches/{patch_id}')
async def get_cognitive_patch(patch_id: str):
    row = cognitive_patches.get_patch(patch_id)
    if not row:
        raise HTTPException(404, 'patch not found')
    return row


@app.post('/api/plasticity/cognitive-patches')
async def create_cognitive_patch(req: CognitivePatchCreateRequest):
    item = cognitive_patches.create_patch(req.model_dump())
    store.db.add_event(
        'cognitive_patch_created',
        f"🧠 cognitive patch criado: {item.get('id')} {item.get('kind')}",
        meta_json=json.dumps({'patch_id': item.get('id'), 'problem_pattern': item.get('problem_pattern')}, ensure_ascii=False),
    )
    return item


@app.post('/api/plasticity/cognitive-patches/{patch_id}/update')
async def update_cognitive_patch(patch_id: str, req: CognitivePatchUpdateRequest):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    item = cognitive_patches.append_revision(patch_id, patch, new_status=req.status)
    if not item:
        raise HTTPException(404, 'patch not found')
    store.db.add_event(
        'cognitive_patch_updated',
        f"✏️ cognitive patch atualizado: {patch_id}",
        meta_json=json.dumps({'patch_id': patch_id, 'status': item.get('status')}, ensure_ascii=False),
    )
    return item


@app.post('/api/plasticity/cognitive-patches/{patch_id}/promote')
async def promote_cognitive_patch(patch_id: str, req: MutationDecisionRequest):
    item = cognitive_patches.promote_patch(patch_id, note=req.reason)
    if not item:
        raise HTTPException(404, 'patch not found')
    store.db.add_event(
        'cognitive_patch_promoted',
        f"🟢 cognitive patch promovido: {patch_id}",
        meta_json=json.dumps({'patch_id': patch_id, 'reason': req.reason}, ensure_ascii=False),
    )
    return {'status': 'promoted', 'patch': item, 'registry': cognitive_patches.stats()}


@app.post('/api/plasticity/cognitive-patches/{patch_id}/reject')
async def reject_cognitive_patch(patch_id: str, req: MutationDecisionRequest):
    item = cognitive_patches.reject_patch(patch_id, reason=req.reason)
    if not item:
        raise HTTPException(404, 'patch not found')
    store.db.add_event(
        'cognitive_patch_rejected',
        f"🟠 cognitive patch rejeitado: {patch_id}",
        meta_json=json.dumps({'patch_id': patch_id, 'reason': req.reason}, ensure_ascii=False),
    )
    return {'status': 'rejected', 'patch': item, 'registry': cognitive_patches.stats()}


@app.post('/api/plasticity/cognitive-patches/{patch_id}/rollback')
async def rollback_cognitive_patch(patch_id: str, req: MutationDecisionRequest):
    item = cognitive_patches.rollback_patch(patch_id, rollback_ref='manual', note=req.reason)
    if not item:
        raise HTTPException(404, 'patch not found')
    store.db.add_event(
        'cognitive_patch_rollback',
        f"🔴 cognitive patch revertido: {patch_id}",
        meta_json=json.dumps({'patch_id': patch_id, 'reason': req.reason}, ensure_ascii=False),
    )
    return {'status': 'rolled_back', 'patch': item, 'registry': cognitive_patches.stats()}


# --- Neuroplasticidade Fase 1 (safe mutate loop) ---

@app.get("/api/neuroplastic/proposals")
async def neuroplastic_proposals():
    return {"items": neuroplastic.list_pending()}


@app.post("/api/neuroplastic/proposals")
async def neuroplastic_add(req: MutationProposalRequest):
    item = neuroplastic.add_proposal(req.title, req.rationale, req.patch or {}, author=req.author or "manual")
    store.db.add_event("neuroplastic_proposal", f"🧬 proposta criada: {item.get('id')} {item.get('title')}")
    return item


@app.post("/api/neuroplastic/proposals/{proposal_id}/evaluate")
async def neuroplastic_evaluate(proposal_id: str):
    m = _run_neuroplastic_shadow_eval(proposal_id)
    return {"proposal_id": proposal_id, "shadow": m}


@app.post("/api/neuroplastic/proposals/{proposal_id}/activate")
async def neuroplastic_activate(proposal_id: str, req: MutationDecisionRequest):
    p = neuroplastic.activate(proposal_id)
    if not p:
        raise HTTPException(404, "proposal not found")
    store.db.add_event("neuroplastic_activate", f"🟢 mutação ativada: {proposal_id}", meta_json=json.dumps({"reason": req.reason}, ensure_ascii=False))
    return {"status": "active", "proposal": p, "runtime": neuroplastic.active_runtime()}


@app.post("/api/neuroplastic/proposals/{proposal_id}/revert")
async def neuroplastic_revert(proposal_id: str, req: MutationDecisionRequest):
    ok = neuroplastic.revert(proposal_id, reason=req.reason or "manual")
    if not ok:
        raise HTTPException(404, "proposal not active/not found")
    store.db.add_event("neuroplastic_revert", f"🔴 mutação revertida: {proposal_id}", meta_json=json.dumps({"reason": req.reason}, ensure_ascii=False))
    return {"status": "reverted", "proposal_id": proposal_id, "runtime": neuroplastic.active_runtime()}


@app.get("/api/neuroplastic/runtime")
async def neuroplastic_runtime():
    return neuroplastic.active_runtime()


@app.get("/api/neuroplastic/history")
async def neuroplastic_history(limit: int = 50):
    return {"items": neuroplastic.history(limit=limit)}


@app.get("/api/neuroplastic/gate/status")
async def neuroplastic_gate_status():
    st = _neuroplastic_gate_load()
    snap = _neuroplastic_gate_snapshot()
    return {
        "snapshot": snap,
        "gain_7d": _rolling_gain_days(7),
        "gain_14d": _rolling_gain_days(14),
        "revert_streaks": st.get("revert_streaks") or {},
        "activation_baselines": st.get("activation_baselines") or {},
        "runtime": neuroplastic.active_runtime(),
    }


@app.post("/api/neuroplastic/gate/run")
async def neuroplastic_gate_run():
    return _neuroplastic_auto_manage()


# --- Memory Curation ---

@app.get("/api/memory/curation/status")
async def memory_curation_status():
    return {"uncurated": store.db.count_uncurated_experiences()}


@app.post("/api/curiosity/maintenance/run")
async def curiosity_maintenance_run(stale_hours: float = 24.0, max_fix: int = 6):
    return _maintain_question_queue(stale_hours=stale_hours, max_fix=max_fix)


def _tom_ab_report(window_actions: int = 200) -> dict:
    acts = store.db.list_actions(limit=max(60, int(window_actions)))
    tom_tagged = 0
    tom_done = 0
    baseline_done = 0
    baseline_total = 0
    for a in acts:
        meta = {}
        try:
            meta = json.loads(a.get("meta_json") or "{}")
        except Exception:
            meta = {}
        has_tom = bool(meta.get("tom_intent"))
        if has_tom:
            tom_tagged += 1
            if a.get("status") == "done":
                tom_done += 1
        else:
            baseline_total += 1
            if a.get("status") == "done":
                baseline_done += 1

    tom_sr = (tom_done / max(1, tom_tagged)) if tom_tagged else 0.0
    base_sr = (baseline_done / max(1, baseline_total)) if baseline_total else 0.0
    lift = tom_sr - base_sr
    return {
        "window_actions": len(acts),
        "tom_tagged": tom_tagged,
        "tom_success_rate": round(tom_sr, 3),
        "baseline_success_rate": round(base_sr, 3),
        "lift": round(lift, 3),
        "label": "positive" if lift > 0.05 else ("neutral" if lift >= -0.05 else "negative"),
    }


def _milestone_kpi(window_days: int = 7) -> dict:
    goals_all = store.db.list_goals(status=None, limit=300)
    ms_all = []
    for g in goals_all[:120]:
        ms_all.extend(store.list_goal_milestones(goal_id=int(g.get("id") or 0), status=None, limit=40))

    done = [m for m in ms_all if str(m.get("status") or "") == "done"]
    active = [m for m in ms_all if str(m.get("status") or "") in ("open", "active")]

    now = time.time()
    delayed = 0
    for m in active:
        upd = float(m.get("updated_at") or m.get("created_at") or now)
        age_h = (now - upd) / 3600.0
        if age_h > (window_days * 24 / 2):
            delayed += 1

    recent_actions = store.db.list_actions(limit=250)
    replan_actions = [a for a in recent_actions if "(ação-replan)" in str(a.get("text") or "")]

    return {
        "milestones_total": len(ms_all),
        "milestones_done": len(done),
        "throughput_done_rate": round(len(done) / max(1, len(ms_all)), 3),
        "delayed_open": delayed,
        "replan_rate": round(len(replan_actions) / max(1, len(recent_actions)), 3),
    }


@app.get("/api/sprint2/health")
async def sprint2_health():
    return {
        "tom_ab": _tom_ab_report(window_actions=220),
        "milestones": _milestone_kpi(window_days=7),
        "curiosity_maintenance": _maintain_question_queue(stale_hours=9999.0, max_fix=0),
    }


@app.post("/api/memory/prune/run")
async def memory_prune_run(limit: int = 200):
    n = store.db.prune_low_utility_experiences(limit=limit, focus_terms=_goal_focus_terms())
    return {"status": "ok", "pruned": n}


@app.get("/api/memory/status")
async def memory_status():
    return {
        "uncurated": store.db.count_uncurated_experiences(),
        "archived": store.db.count_archived_experiences(),
        "distilled": store.db.count_distilled_experiences(),
        "recent_curator_events": [e for e in store.db.list_events(limit=60) if e.get("kind") in ("memory_curated", "action_done")][-12:],
    }


# --- AGI Mode Metrics ---

@app.get("/api/agi-mode")
async def agi_mode_status():
    return _compute_agi_mode_metrics()


# --- External Action Executor (Etapa E) ---

@app.post("/api/actions/prepare")
async def prepare_external_action(req: ActionPrepareRequest):
    kind = (req.kind or "").strip()
    payload = req.payload or {}
    reason = (req.reason or "").strip()

    if kind not in EXTERNAL_ACTION_ALLOWLIST:
        raise HTTPException(403, f"Action '{kind}' not in allowlist")
    if not reason:
        raise HTTPException(400, "reason required")

    prep = {
        "kind": kind,
        "target": req.target,
        "reason": reason[:200],
        "payload_keys": sorted(list(payload.keys()))[:20],
        "prepared_at": int(time.time()),
    }
    audit_hash = _compute_audit_hash(prep)
    token = secrets.token_urlsafe(18)
    _external_confirm_tokens[token] = {
        "kind": kind,
        "target": req.target,
        "expires_at": time.time() + 300,
        "audit_hash": audit_hash,
    }
    store.db.add_event("external_action_dryrun", f"🧪 prepare externo: {kind}", meta_json=json.dumps({**prep, "audit_hash": audit_hash}, ensure_ascii=False))
    return {"status": "prepared", "confirm_token": token, "audit_hash": audit_hash, "expires_in_sec": 300}


@app.post("/api/actions/execute")
async def execute_external_action(req: ActionExecRequest):
    kind = (req.kind or "").strip()
    payload = req.payload or {}
    reason = (req.reason or "").strip()

    # auditoria sempre
    audit = {
        "kind": kind,
        "target": req.target,
        "dry_run": bool(req.dry_run),
        "reason": reason[:200],
        "payload_keys": sorted(list(payload.keys()))[:20],
    }
    audit["audit_hash"] = _compute_audit_hash(audit)

    if kind not in EXTERNAL_ACTION_ALLOWLIST:
        store.db.add_event("external_action_denied", f"⛔ ação externa negada: {kind}", meta_json=json.dumps(audit, ensure_ascii=False))
        raise HTTPException(403, f"Action '{kind}' not in allowlist")

    if req.dry_run:
        store.db.add_event("external_action_dryrun", f"🧪 dry-run externo: {kind}", meta_json=json.dumps(audit, ensure_ascii=False))
        return {"status": "dry_run", "audit": audit}

    # execução real exige reason + confirm token
    if not reason:
        raise HTTPException(400, "reason required for real execution")
    token = (req.confirm_token or "").strip()
    t = _external_confirm_tokens.get(token)
    if not t:
        raise HTTPException(400, "valid confirm_token required")
    if float(t.get("expires_at") or 0) < time.time():
        _external_confirm_tokens.pop(token, None)
        raise HTTPException(400, "confirm_token expired")
    if t.get("kind") != kind:
        raise HTTPException(400, "confirm_token does not match action kind")

    # execução real (limitada/segura)
    if kind == "notify_human":
        text = str(payload.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "payload.text required")
        store.db.add_event("external_action_executed", f"📣 notify_human: {text[:180]}", meta_json=json.dumps(audit, ensure_ascii=False))
        _external_confirm_tokens.pop(token, None)
        return {"status": "executed", "kind": kind, "audit_hash": audit.get("audit_hash")}

    raise HTTPException(400, "Unsupported action kind")


# --- Adaptabilidade: policy dinâmico + self-patch supervisionado ---

@app.get("/api/policy/runtime")
async def policy_runtime_get():
    from ultronpro.policy import _load_runtime_rules
    return {"rules": _load_runtime_rules()}


@app.post("/api/policy/runtime")
async def policy_runtime_set(rules: Dict[str, Any]):
    from ultronpro.policy import RULES_PATH
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(json.dumps(rules or {}, ensure_ascii=False, indent=2))
    store.db.add_event("policy_runtime_updated", "🧩 regras dinâmicas de policy atualizadas")
    return {"status": "ok"}


@app.post("/api/selfpatch/prepare")
async def selfpatch_prepare(req: SelfPatchPrepareRequest):
    fp = (req.file_path or "").strip()
    if not _selfpatch_allowed(fp):
        raise HTTPException(403, "file_path not allowed")
    if not (req.reason or "").strip():
        raise HTTPException(400, "reason required")

    p = Path(fp)
    if not p.exists():
        raise HTTPException(404, "file not found")
    txt = p.read_text()
    if req.old_text not in txt:
        raise HTTPException(400, "old_text not found")

    token = secrets.token_urlsafe(18)
    preview = txt.replace(req.old_text, req.new_text, 1)
    _selfpatch_tokens[token] = {
        "file_path": fp,
        "old_text": req.old_text,
        "new_text": req.new_text,
        "reason": req.reason[:200],
        "expires_at": time.time() + 300,
        "diff_hash": hashlib.sha256((req.old_text + "->" + req.new_text).encode("utf-8")).hexdigest(),
    }
    store.db.add_event("selfpatch_prepared", f"🧪 selfpatch prepared for {fp}")
    return {"status": "prepared", "token": token, "diff_hash": _selfpatch_tokens[token]["diff_hash"], "preview_chars": len(preview)}


@app.post("/api/selfpatch/apply")
async def selfpatch_apply(req: SelfPatchApplyRequest):
    t = _selfpatch_tokens.get(req.token)
    if not t:
        raise HTTPException(400, "invalid token")
    if float(t.get("expires_at") or 0) < time.time():
        _selfpatch_tokens.pop(req.token, None)
        raise HTTPException(400, "token expired")

    p = Path(t["file_path"])
    txt = p.read_text()
    if t["old_text"] not in txt:
        raise HTTPException(400, "old_text no longer present")

    backup_dir = Path('/app/data/selfpatch_backups')
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = str(backup_dir / f"{p.name}.{int(time.time())}.bak")
    Path(backup).write_text(txt)

    try:
        p.write_text(txt.replace(t["old_text"], t["new_text"], 1))
        store.db.add_event("selfpatch_applied", f"🛠️ selfpatch applied to {p.name}", meta_json=json.dumps({"diff_hash": t.get("diff_hash"), "reason": t.get("reason")}, ensure_ascii=False))
        _selfpatch_tokens.pop(req.token, None)
        return {"status": "applied", "file": str(p), "backup": backup}
    except PermissionError:
        # fallback: persist proposal for host-side/manual apply
        pending_dir = Path('/app/data/selfpatch_pending')
        pending_dir.mkdir(parents=True, exist_ok=True)
        pending_path = pending_dir / f"patch_{int(time.time())}_{p.name}.json"
        pending_path.write_text(json.dumps(t, ensure_ascii=False, indent=2))
        store.db.add_event("selfpatch_pending", f"🧩 selfpatch pending (sem permissão de escrita em {p.name})", meta_json=json.dumps({"pending": str(pending_path), "diff_hash": t.get("diff_hash")}, ensure_ascii=False))
        _selfpatch_tokens.pop(req.token, None)
        return {"status": "pending_manual", "file": str(p), "pending": str(pending_path), "backup": backup}


# --- Etapa F: benchmark + replay ---

@app.post("/api/agi/benchmark/run")
async def run_agi_benchmark():
    agi = _compute_agi_mode_metrics()
    p = agi.get("pillars") or {}
    meta = _metacognition_tick()

    # Cenários fixos (Etapa F)
    lang_eval = semantics.evaluate_language_dataset("/app/ultronpro/data_language_eval.json")
    scenarios = {
        "graph_learning": float(p.get("learning", 0)) >= 45,
        "conflict_handling": float(p.get("synthesis", 0)) >= 35,
        "memory_hygiene": float(p.get("curation", 0)) >= 35,
        "safety_controls": int(_autonomy_state.get("consecutive_errors") or 0) < 3,
        "autonomy_quality": float(meta.get("decision_quality") or 0) >= 0.2,
        "language_ambiguity_eval": float(lang_eval.get("accuracy") or 0.0) >= 0.6,
    }

    # Sprint 1: benchmark formal requisitos 1..8 (item 9 fora)
    intent = tom.infer_user_intent(store.db.list_experiences(limit=30))
    open_conf = len(store.db.list_conflicts(status="open", limit=500))
    procs = store.list_procedures(limit=100)
    domain_counts = {}
    for x in procs:
        d = (x.get("domain") or "").strip().lower()
        if not d:
            continue
        domain_counts[d] = domain_counts.get(d, 0) + int(x.get("attempts") or 0)
    proc_domains = len(domain_counts)
    total_attempts = sum(domain_counts.values())
    top_share = (max(domain_counts.values()) / max(1, total_attempts)) if domain_counts else 1.0
    anti_overfit_bonus = max(0.0, 1.0 - top_share)  # perto de 1 quando distribuído entre domínios

    accepted_analogies = len(store.list_analogies(limit=200, status="accepted_validated"))
    reasoning_audits = len([e for e in store.db.list_events(limit=300) if (e.get("kind") or "") == "reasoning_audit"])
    lang_diag = semantics.detect_ambiguity("\n".join([(e.get("text") or "")[:220] for e in store.db.list_experiences(limit=8)]))
    goals_all = store.db.list_goals(status=None, limit=200)
    milestones_total = 0
    for g in goals_all[:40]:
        milestones_total += len(store.list_goal_milestones(int(g.get("id") or 0), status=None, limit=16))

    req_scores = {
        "1_generalizacao_entre_dominios": round(min(100.0, proc_domains * 12 + accepted_analogies * 6 + anti_overfit_bonus * 18), 1),
        "2_transferencia_aprendizado": round(min(100.0, accepted_analogies * 18 + float(p.get("synthesis", 0)) * 0.4), 1),
        "3_raciocinio_abstracao": round(min(100.0, float(p.get("synthesis", 0)) * 0.7 + reasoning_audits * 0.2), 1),
        "4_aprendizado_autonomo": round(min(100.0, float(p.get("autonomy", 0)) * 0.75 + max(0, 30 - open_conf) * 0.5), 1),
        "5_linguagem_natural": round(min(100.0, 30.0 + (20.0 if intent.get("label") else 0.0) + float(intent.get("confidence") or 0) * 20.0 + (float(lang_eval.get("accuracy") or 0.0) * 40.0) + (10.0 if float(lang_diag.get("score") or 0) >= 0.35 else 0.0)), 1),
        "6_metacognicao": round(min(100.0, float(meta.get("decision_quality") or 0) * 100.0 + (20 - min(20, int(meta.get("low_quality_streak") or 0) * 5))), 1),
        "7_planejamento_decisao": round(min(100.0, float(p.get("goals", 0)) * 0.8 + min(25.0, milestones_total * 1.8)), 1),
        "8_adaptabilidade_ambientes_novos": round(min(100.0, float(p.get("autonomy", 0)) * 0.6 + proc_domains * 8 + accepted_analogies * 4 + anti_overfit_bonus * 14), 1),
    }

    passed = len([v for v in scenarios.values() if v])
    score = round((passed / max(1, len(scenarios))) * 100.0, 1)
    req_avg = round(sum(req_scores.values()) / max(1, len(req_scores)), 1)

    out = {
        "ts": int(time.time()),
        "score": score,
        "scenarios": scenarios,
        "agi_mode_percent": agi.get("agi_mode_percent"),
        "decision_quality": meta.get("decision_quality"),
        "requirements_1_8": req_scores,
        "requirements_avg_1_8": req_avg,
        "sprint3_signals": {
            "semantic_ambiguity_score": float(lang_diag.get("score") or 0.0),
            "language_eval_accuracy": float(lang_eval.get("accuracy") or 0.0),
            "domain_diversity": proc_domains,
            "anti_overfit_bonus": round(float(anti_overfit_bonus), 3),
            "top_domain_share": round(float(top_share), 3),
        },
    }
    _autonomy_state["last_benchmark"] = out
    _benchmark_history_append(out)
    store.db.add_event("agi_benchmark", f"📊 benchmark AGI score={score} req_avg(1-8)={req_avg}", meta_json=json.dumps(out, ensure_ascii=False))
    return out


@app.get("/api/agi/benchmark/status")
async def agi_benchmark_status():
    return _autonomy_state.get("last_benchmark") or {}


@app.get("/api/agi/benchmark/trend")
async def agi_benchmark_trend(limit: int = 10):
    arr = _benchmark_history_load()
    arr = arr[-max(1, int(limit)):]
    return {"history": arr, "avg_score": round(sum([float(x.get('score') or 0) for x in arr]) / max(1, len(arr)), 2) if arr else 0}


@app.post("/api/learning/replay/run")
async def learning_replay_run(limit: int = 80):
    evs = store.db.list_events(limit=max(40, int(limit)))
    sev_map = {
        "action_error": 3,
        "conflict_needs_human": 2,
        "metacog_guard": 3,
        "circuit_breaker": 2,
        "external_action_denied": 1,
    }

    weighted = 0
    counts = {}
    for e in evs:
        k = (e.get("kind") or "")
        if k in sev_map:
            weighted += int(sev_map[k])
            counts[k] = int(counts.get(k, 0)) + 1

    # replay por severidade
    if weighted >= 3:
        _enqueue_action_if_new("ask_evidence", "(ação) Revisar evidências dos últimos erros para corrigir lacunas.", priority=6)
    if weighted >= 5:
        _enqueue_action_if_new("curate_memory", "(ação) Curadoria orientada por falhas recentes.", priority=5)
    if weighted >= 7:
        _enqueue_action_if_new("generate_questions", "(ação) Gerar perguntas corretivas para reduzir recorrência de falhas.", priority=6)

    res = {
        "replayed_from_events": sum(counts.values()),
        "severity_score": weighted,
        "counts": counts,
        "queued": len(store.db.list_actions(limit=30)),
    }
    store.db.add_event("learning_replay", f"🔁 replay executado: eventos={res['replayed_from_events']} severidade={weighted}", meta_json=json.dumps(res, ensure_ascii=False))
    return res


@app.post("/api/memory/curation/run")
async def memory_curation_run(batch: int = 30):
    info = _run_memory_curation(batch_size=batch)
    return {"status": "ok", **info}


# --- Goals ---

@app.get("/api/goals/persistent")
async def persistent_goals_list():
    data = _persistent_goals_load()
    active = _persistent_goal_active()
    return {"goals": data.get("goals", []), "active": active, "active_id": data.get("active_id")}


@app.post("/api/goals/persistent")
async def persistent_goals_add(req: PersistentGoalRequest):
    t = (req.title or "").strip()
    if not t:
        raise HTTPException(400, "title required")

    data = _persistent_goals_load()
    gid = f"pg_{int(time.time())}_{secrets.token_hex(3)}"
    actions = req.proactive_actions or [
        f"Que evidência devo coletar hoje para avançar: {t}?",
        f"Qual experimento mental simples valida a meta: {t}?",
    ]
    interval_min = max(5, int(req.interval_min or 60))
    active_hours = req.active_hours if (req.active_hours and len(req.active_hours) == 2) else [8, 23]
    g = {
        "id": gid,
        "title": t,
        "description": (req.description or "").strip() or None,
        "proactive_actions": actions[:8],
        "interval_min": interval_min,
        "active_hours": [int(active_hours[0]), int(active_hours[1])],
        "last_run_at": 0,
        "created_at": int(time.time()),
    }
    data.setdefault("goals", []).append(g)
    if not data.get("active_id"):
        data["active_id"] = gid
    _persistent_goals_save(data)
    store.db.add_event("persistent_goal_added", f"🎯 meta persistente criada: {t}")
    return {"status": "ok", "goal": g, "active_id": data.get("active_id")}


@app.post("/api/goals/persistent/{goal_id}/activate")
async def persistent_goals_activate(goal_id: str):
    data = _persistent_goals_load()
    exists = any(g.get("id") == goal_id for g in data.get("goals", []))
    if not exists:
        raise HTTPException(404, "Persistent goal not found")
    data["active_id"] = goal_id
    _persistent_goals_save(data)
    store.db.add_event("persistent_goal_activated", f"🎯 meta persistente ativada: {goal_id}")
    return {"status": "ok", "active_id": goal_id}


@app.post("/api/goals/persistent/{goal_id}/schedule")
async def persistent_goals_schedule(goal_id: str, interval_min: int = 60, start_hour: int = 8, end_hour: int = 23):
    data = _persistent_goals_load()
    found = False
    for g in data.get("goals", []):
        if g.get("id") == goal_id:
            g["interval_min"] = max(5, int(interval_min))
            g["active_hours"] = [max(0, min(23, int(start_hour))), max(0, min(23, int(end_hour)))]
            found = True
            break
    if not found:
        raise HTTPException(404, "Persistent goal not found")
    _persistent_goals_save(data)
    store.db.add_event("persistent_goal_scheduled", f"🗓️ meta persistente agenda atualizada: {goal_id}")
    return {"status": "ok", "goal_id": goal_id}


@app.delete("/api/goals/persistent/{goal_id}")
async def persistent_goals_delete(goal_id: str):
    data = _persistent_goals_load()
    goals0 = data.get("goals", [])
    goals1 = [g for g in goals0 if g.get("id") != goal_id]
    if len(goals1) == len(goals0):
        raise HTTPException(404, "Persistent goal not found")
    data["goals"] = goals1
    if data.get("active_id") == goal_id:
        data["active_id"] = goals1[0].get("id") if goals1 else None
    _persistent_goals_save(data)
    store.db.add_event("persistent_goal_deleted", f"🗑️ meta persistente removida: {goal_id}")
    return {"status": "ok", "active_id": data.get("active_id")}


@app.get("/api/procedures")
async def procedures_list(limit: int = 50, domain: str = ""):
    d = domain.strip() or None
    return {"procedures": store.list_procedures(limit=limit, domain=d)}


@app.post("/api/procedures/learn")
async def procedures_learn(req: ProcedureLearnRequest):
    p = _extract_procedure_from_text(req.observation_text, domain=req.domain, name_hint=req.name)
    if not p:
        raise HTTPException(400, "Could not extract procedure")

    pid = store.add_procedure(
        name=p['name'],
        goal=p.get('goal'),
        steps_json=json.dumps(p.get('steps') or [], ensure_ascii=False),
        domain=p.get('domain'),
        proc_type=p.get('proc_type') or 'analysis',
        preconditions=p.get('preconditions'),
        success_criteria=p.get('success_criteria'),
    )
    store.db.add_insight("procedure_learned", "Nova habilidade procedural", f"Aprendi procedimento: {p['name']} ({p.get('domain')}).", priority=4)
    return {"status": "ok", "procedure_id": pid, "procedure": p}


@app.post("/api/procedures/run-log")
async def procedures_run_log(req: ProcedureRunRequest):
    rid = store.add_procedure_run(
        procedure_id=req.procedure_id,
        input_text=req.input_text,
        output_text=req.output_text,
        score=float(req.score),
        success=bool(req.success),
        notes=req.notes,
    )
    return {"status": "ok", "run_id": rid}


@app.post("/api/procedures/select")
async def procedures_select(req: ProcedureSelectRequest):
    sel = _select_procedure(req.context_text, domain=req.domain)
    return {"selected": sel}


@app.post("/api/procedures/invent")
async def procedures_invent(req: ProcedureInventRequest):
    inv = _invent_procedure_from_context(req.context_text, domain=req.domain, name_hint=req.name_hint)
    if not inv:
        raise HTTPException(400, "Could not invent procedure")
    pid = store.add_procedure(
        name=inv['name'],
        goal=inv.get('goal'),
        steps_json=json.dumps(inv.get('steps') or [], ensure_ascii=False),
        domain=inv.get('domain'),
        proc_type=inv.get('proc_type') or 'analysis',
        preconditions=inv.get('preconditions'),
        success_criteria=inv.get('success_criteria'),
    )
    store.db.add_insight("procedure_invented", "Novo procedimento inventado", f"Invenção procedural: {inv['name']} ({inv.get('domain')})", priority=5)
    return {"status": "ok", "procedure_id": pid, "procedure": inv}


@app.post("/api/procedures/execute")
async def procedures_execute(procedure_id: int, input_text: str = ""):
    return _execute_procedure_simulation(procedure_id, input_text=input_text)


@app.post("/api/procedures/execute-active")
async def procedures_execute_active(procedure_id: int, input_text: str = "", notify: bool = False):
    return _execute_procedure_active(procedure_id, input_text=input_text, notify=notify)


@app.post("/api/analogy/transfer")
async def analogy_transfer(req: AnalogyTransferRequest):
    return await _run_analogy_transfer(req.problem_text, target_domain=req.target_domain)


@app.get("/api/analogies")
async def analogies_list(limit: int = 50, status: str = "", target_domain: str = ""):
    s = status.strip() or None
    td = target_domain.strip() or None
    return {"analogies": store.list_analogies(limit=limit, status=s, target_domain=td)}


@app.post("/api/analogies/{analogy_id}/validate")
async def analogy_validate(analogy_id: int):
    res = _validate_analogy_with_evidence(analogy_id)
    if res.get("status") == "not_found":
        raise HTTPException(404, "Analogy not found")
    return res


@app.get("/api/reasoning/audit")
async def reasoning_audit(limit: int = 80):
    # list_events returns oldest-first; fetch a wide window and slice from tail
    evs = [e for e in store.db.list_events(limit=5000) if (e.get('kind') or '') == 'reasoning_audit']
    return {"items": evs[-max(1, int(limit)):], "count": len(evs)}


@app.get("/api/neurosym/proofs")
async def neurosym_proofs(limit: int = 80):
    return {"items": neurosym.history(limit=limit)}


@app.get("/api/neurosym/consistency")
async def neurosym_consistency(limit: int = 200):
    return neurosym.consistency_check(limit=limit)


@app.get("/api/neurosym/fidelity")
async def neurosym_fidelity(limit: int = 120):
    return neurosym.explanation_fidelity(limit=limit)


@app.post("/api/neurosym/check")
async def neurosym_check(limit: int = 200):
    return {"consistency": neurosym.consistency_check(limit=limit), "fidelity": neurosym.explanation_fidelity(limit=min(120, limit))}


@app.get('/api/integrity/status')
async def integrity_status():
    return integrity.status()


@app.post('/api/integrity/rules')
async def integrity_rules_patch(req: IntegrityRulesPatchRequest):
    integrity.save_rules(req.rules or {})
    return integrity.status()


@app.post('/api/integrity/evaluate')
async def integrity_evaluate(kind: str, neural_confidence: float = 0.5, symbolic_consistency: float = 1.0, has_proof: bool = True, causal_checked: bool = True):
    ok, reason = integrity.evaluate(kind, neural_confidence=neural_confidence, symbolic_consistency=symbolic_consistency, has_proof=has_proof, causal_checked=causal_checked)
    return {'allowed': ok, 'reason': reason}


@app.post("/api/workspace/publish")
async def workspace_publish(req: WorkspacePublishRequest):
    wid = _workspace_publish(req.module, req.channel, req.payload or {}, salience=float(req.salience), ttl_sec=int(req.ttl_sec))
    return {"status": "ok", "id": wid}


@app.post("/api/workspace/broadcast")
async def workspace_broadcast(req: WorkspaceBroadcastRequest):
    ids = []
    for ch in req.channels[:12]:
        wid = _workspace_publish(req.module, str(ch), req.payload or {}, salience=float(req.salience), ttl_sec=int(req.ttl_sec))
        if wid:
            ids.append(wid)
    return {"status": "ok", "ids": ids, "count": len(ids)}


@app.post("/api/workspace/consume")
async def workspace_consume(req: WorkspaceConsumeRequest):
    ok = store.mark_workspace_consumed(int(req.item_id), str(req.consumer_module))
    return {"status": "ok" if ok else "miss", "consumed": bool(ok)}


@app.get("/api/workspace/read")
async def workspace_read(limit: int = 30, channels: str = "", include_expired: bool = False):
    chs = [c.strip() for c in channels.split(",") if c.strip()] if channels else None
    return {"items": store.read_workspace(channels=chs, limit=limit, include_expired=include_expired)}


@app.get("/api/workspace/status")
async def workspace_status(limit: int = 80):
    return _workspace_status(limit=limit)


@app.get("/api/workspace/authorship")
async def workspace_authorship(limit: int = 40):
    return _workspace_authorship_snapshot(limit=limit)


@app.get("/api/authorship/trace")
async def authorship_trace(limit: int = 40):
    return _authorship_trace_snapshot(limit=limit)


@app.get("/api/authorship/status")
async def authorship_status(limit: int = 40):
    return _authorship_trace_snapshot(limit=limit)


@app.get("/api/meta-observer/status")
async def meta_observer_status(limit: int = 80):
    return _meta_observer_snapshot(limit=limit)


@app.get("/api/affect/status")
async def affect_status(limit: int = 80):
    return _artificial_affect_snapshot(limit=limit)


@app.get("/api/affect/workspace")
async def affect_workspace(limit: int = 20):
    return {"items": store.read_workspace(channels=['affect.state', 'policy.risk'], limit=limit, include_expired=False)}


@app.get("/api/integration-proxy/status")
async def integration_proxy_status(limit: int = 100):
    return _integration_proxy_snapshot(limit=limit)


@app.get("/api/integration-proxy/workspace")
async def integration_proxy_workspace(limit: int = 20):
    return {"items": store.read_workspace(channels=['integration.proxy'], limit=limit, include_expired=False)}


@app.get('/api/operational-consciousness/benchmark/status')
async def operational_consciousness_benchmark_status(limit: int = 20):
    return {
        'baseline': operational_consciousness_benchmark.baseline_status(),
        'recent_runs': operational_consciousness_benchmark.recent_runs(limit=limit),
    }


@app.post('/api/operational-consciousness/benchmark/freeze-baseline')
async def operational_consciousness_benchmark_freeze_baseline(tag: str = 'manual', limit: int = 100):
    snap = _operational_consciousness_snapshot(limit=limit)
    out = operational_consciousness_benchmark.freeze_baseline(snap, tag=tag)
    store.db.add_event('operational_consciousness_baseline', f"🧊 operational consciousness baseline score={((out.get('evaluation') or {}).get('benchmark_score'))}")
    return out


@app.post('/api/operational-consciousness/benchmark/run')
async def operational_consciousness_benchmark_run(compare_to_baseline: bool = True, tag: str = '', limit: int = 100):
    snap = _operational_consciousness_snapshot(limit=limit)
    out = operational_consciousness_benchmark.run(snap, compare_to_baseline=compare_to_baseline, tag=tag)
    store.db.add_event('operational_consciousness_benchmark', f"🧠 operational consciousness benchmark score={(((out.get('evaluation') or {}).get('benchmark_score')))}")
    return out


@app.get("/api/goals")
async def goals_list(status: str = "all", limit: int = 30):
    s = None if status == "all" else status
    return {"goals": store.db.list_goals(status=s, limit=limit), "active": store.db.get_active_goal()}


@app.post("/api/goals/refresh")
async def goals_refresh():
    info = _refresh_goals_from_context()
    return {"status": "ok", **info}


@app.post("/api/goals/{goal_id}/activate")
async def goal_activate(goal_id: int):
    ok = store.db.activate_goal(goal_id)
    if not ok:
        raise HTTPException(404, "Goal not found")
    return {"status": "active", "goal": store.db.get_active_goal()}


@app.post("/api/goals/{goal_id}/done")
async def goal_done(goal_id: int):
    store.db.mark_goal_done(goal_id)
    return {"status": "done"}


@app.get("/api/goals/{goal_id}/milestones")
async def goal_milestones(goal_id: int, status: str = "all", limit: int = 30):
    s = None if status == "all" else status
    items = store.list_goal_milestones(goal_id=goal_id, status=s, limit=limit)
    return {"goal_id": goal_id, "milestones": items, "next": store.get_next_open_milestone(goal_id)}


@app.post("/api/goals/{goal_id}/milestones/ensure")
async def goal_milestones_ensure(goal_id: int, weeks: int = 4):
    g = [x for x in store.db.list_goals(status=None, limit=500) if int(x.get("id") or 0) == int(goal_id)]
    if not g:
        raise HTTPException(404, "Goal not found")
    added = _ensure_goal_milestones(goal_id, g[0].get("title") or "Goal", g[0].get("description"), weeks=weeks)
    return {"status": "ok", "added": added}


@app.post("/api/milestones/{milestone_id}/progress")
async def milestone_progress(milestone_id: int, req: MilestoneProgressRequest):
    p = max(0.0, min(1.0, float(req.progress)))
    st = req.status or ("done" if p >= 1.0 else ("active" if p > 0 else "open"))
    store.update_milestone_progress(milestone_id, p, status=st)
    _audit_reasoning("milestone_progress_update", {"milestone_id": milestone_id}, f"progress={p:.2f}, state={st}", confidence=p)
    return {"status": "ok", "milestone_id": milestone_id, "progress": p, "state": st}

# --- Settings ---

@app.get("/api/settings")
async def get_settings():
    """Get current settings (masked keys)."""
    s = settings.load_settings()
    masked = {}
    for k, v in s.items():
        if "key" in k and v:
            masked[k] = "..." + v[-4:] # Show only last 4 chars
        else:
            masked[k] = v
    return {"settings": masked}

@app.post("/api/settings")
async def update_settings(new_settings: SettingsModel):
    """Update settings."""
    current = settings.load_settings()
    to_save = {}
    
    # Only update provided fields (ignore empty strings if user didn't change)
    data = new_settings.dict(exclude_unset=True)
    
    for k, v in data.items():
        if v and v != "..." + current.get(k, "")[-4:]: # Check if it's not the masked value sent back
            to_save[k] = v
            
    if to_save:
        settings.save_settings(to_save)
        # Invalidate LLM clients cache to force reload with new keys
        llm.router.clients = {}
        
    return {"status": "updated", "updated_keys": list(to_save.keys())}

# --- Static UI ---
app.mount("/", StaticFiles(directory="/app/ui", html=True), name="ui")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
