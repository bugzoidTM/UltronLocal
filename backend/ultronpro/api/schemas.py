"""
ultronpro.api.schemas
=====================
Todos os Pydantic request/response models do UltronPro, extraídos do main.py.

Regra: este módulo NÃO importa nenhum módulo de `ultronpro.*` (exceto tipos).
       Só depende de pydantic e typing-stdlib.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Knowledge / Ingest
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    text: str
    source_id: Optional[str] = None
    modality: str = "text"


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10


# ---------------------------------------------------------------------------
# Questions / Conflicts
# ---------------------------------------------------------------------------

class AnswerRequest(BaseModel):
    question_id: int
    answer: str


class DismissRequest(BaseModel):
    question_id: int


class ResolveConflictRequest(BaseModel):
    chosen_object: str
    decided_by: Optional[str] = None
    resolution: Optional[str] = None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsModel(BaseModel):
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    github_api_key: Optional[str] = None
    ollama_api_key: Optional[str] = None
    lightrag_api_key: Optional[str] = None
    lightrag_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Actions / Procedures
# ---------------------------------------------------------------------------

class ActionPrepareRequest(BaseModel):
    kind: str
    target: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    reason: str


class ActionExecRequest(BaseModel):
    kind: str
    target: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    dry_run: bool = True
    reason: Optional[str] = None
    confirm_token: Optional[str] = None


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


# ---------------------------------------------------------------------------
# Analogy / Transfer
# ---------------------------------------------------------------------------

class AnalogyTransferRequest(BaseModel):
    problem_text: str
    target_domain: Optional[str] = None


# ---------------------------------------------------------------------------
# Global Workspace
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Goals / Milestones
# ---------------------------------------------------------------------------

class MilestoneProgressRequest(BaseModel):
    progress: float
    status: Optional[str] = None


class PersistentGoalRequest(BaseModel):
    title: str
    description: Optional[str] = None
    proactive_actions: Optional[List[str]] = None
    interval_min: int = 60
    active_hours: Optional[List[int]] = None  # [start_hour, end_hour]


# ---------------------------------------------------------------------------
# Neuroplastic / Mutation
# ---------------------------------------------------------------------------

class MutationProposalRequest(BaseModel):
    title: str
    rationale: str
    patch: Dict[str, Any]
    author: Optional[str] = "manual"


class MutationDecisionRequest(BaseModel):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Cognitive Patches
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Shadow Eval
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# UltronBody (embodied RL)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Explicit Abstractions / Structural Mapping
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# External Benchmarks
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Intrinsic / ITC
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Plasticity / FineTune
# ---------------------------------------------------------------------------

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


class GapFineTuneProposalRequest(BaseModel):
    gap_label: str
    examples: list[dict[str, str]] = []
    task_type: str = 'reasoning'
    base_model: Optional[str] = None


# ---------------------------------------------------------------------------
# Roadmap / AGI Path / Learning Agenda
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Chat / Voice
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str


class MetacogAskRequest(BaseModel):
    message: str
    authorship_origin: Optional[str] = 'externally_triggered'


class VoiceChatRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Horizon / Subgoals / Projects
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool routing / Sandbox / SQL / Source
# ---------------------------------------------------------------------------

class ToolRouteRequest(BaseModel):
    intent: str
    context: Optional[Dict[str, Any]] = None
    prefer_low_cost: bool = True


class SandboxWriteRequest(BaseModel):
    path: str
    content: str


class SandboxRunRequest(BaseModel):
    code: Optional[str] = None
    file_path: Optional[str] = None
    timeout_sec: int = 15


class SqlQueryBody(BaseModel):
    query: str
    limit: int = 200


class SourceVerifyBody(BaseModel):
    url: str
    max_chars: int = 8000
    ingest: bool = True


# ---------------------------------------------------------------------------
# Integrity / Self-Patch
# ---------------------------------------------------------------------------

class IntegrityRulesPatchRequest(BaseModel):
    rules: Dict[str, Any]


class SelfPatchPrepareRequest(BaseModel):
    file_path: str
    old_text: str
    new_text: str
    reason: str


class SelfPatchApplyRequest(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

class PersonaExampleRequest(BaseModel):
    user_input: str
    assistant_output: str
    tone: str = 'direct'
    tags: Optional[List[str]] = None
    score: float = 1.0


class PersonaConfigRequest(BaseModel):
    config: Dict[str, Any]


# ---------------------------------------------------------------------------
# Mission Control / Squad
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Governance / Identity / Homeostasis / Descendants
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Causal Graph / Cognitive State
# ---------------------------------------------------------------------------

class CausalTripleIngestRequest(BaseModel):
    cause: str
    effect: str
    condition: Optional[str] = ''
    confidence: Optional[float] = 0.65


class CognitiveStatePatchRequest(BaseModel):
    beliefs: Optional[Dict[str, Any]] = None
    goals: Optional[List[str]] = None
    uncertainties: Optional[List[str]] = None
    constraints: Optional[List[str]] = None
    self_model: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Squad
# ---------------------------------------------------------------------------

class SquadSwitchRequest(BaseModel):
    profile_id: str


# ---------------------------------------------------------------------------
# Epistemic Dialogue / Long-Horizon Agency
# ---------------------------------------------------------------------------

class EpistemicDisputeRequest(BaseModel):
    domain: str
    spurious_variable: str
    human_rationale: str


class EpistemicProjectRequest(BaseModel):
    title: str
    description: str
    target_domain: str
    ttl_days: int = 180


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class SkillExecuteRequest(BaseModel):
    task: str
    skill_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Web Explorer
# ---------------------------------------------------------------------------

class WebExploreRequest(BaseModel):
    topic: str


# ---------------------------------------------------------------------------
# Code Self-Healer
# ---------------------------------------------------------------------------

class HealErrorRequest(BaseModel):
    module: str
    function: str
    exception_type: str
    message: str
    traceback_text: Optional[str] = None


class HealApplyRequest(BaseModel):
    attempt_id: str


class HealAnalyzeRequest(BaseModel):
    error_id: str


# ---------------------------------------------------------------------------
# Mental Simulation
# ---------------------------------------------------------------------------

class MentalImagineRequest(BaseModel):
    action_kind: str
    action_text: str
    context: Optional[dict] = None


class MentalCompareRequest(BaseModel):
    scenario_name: str
    hypotheses: list


class MentalTestPathsRequest(BaseModel):
    objective: str
    paths: list


class MentalLearnRequest(BaseModel):
    scenario_id: str
    actual_outcome: dict


class CompetencyFailureRequest(BaseModel):
    competency_id: str
