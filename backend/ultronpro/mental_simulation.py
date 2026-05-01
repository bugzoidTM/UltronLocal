"""
Mental Simulation Engine — Motor de Simulação Mental
=====================================================

Fase 13 — Capacidade de "pensar antes de agir" de forma estruturada.

O UltronPro precisa:
  1. IMAGINAR consequências de ações antes de executá-las
  2. COMPARAR hipóteses rivais e escolher a mais robusta
  3. TESTAR MENTALMENTE caminhos alternativos (cenários)
  4. APRENDER COM ERROS (pós-mortem causal → competência)
  5. CONSOLIDAR competências reutilizáveis

Módulos integrados:
  - world_model: estado do ambiente para simulação
  - causal / causal_preflight: predição causal
  - contrafactual: deliberação de alternativas
  - rl_policy: política de reforço
  - continuous_learning: padrões aprendidos
  - explicit_abstractions: biblioteca de competências
  - episodic_memory: memória de episódios passados
  - self_model: auto-avaliação

Persistência: data/mental_simulation.json
"""

from __future__ import annotations

import json
import logging
import time
import uuid
import hashlib
from collections import deque
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("uvicorn")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SIM_PATH = DATA_DIR / "mental_simulation.json"
COMPETENCY_PATH = DATA_DIR / "competency_library.json"


# ─── Data Structures ─────────────────────────────────────────────

@dataclass
class Hypothesis:
    """Uma hipótese rival sobre qual caminho é melhor."""
    id: str
    description: str
    predicted_outcome: str
    confidence: float  # 0.0–1.0
    risk: float  # 0.0–1.0
    cost: float  # 0.0–1.0
    benefit: float  # 0.0–1.0
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)
    causal_chain: list[dict] = field(default_factory=list)


@dataclass
class Scenario:
    """Cenário mental: uma sequência simulada de passos + resultado previsto."""
    id: str
    name: str
    hypotheses: list[Hypothesis]
    chosen_hypothesis_id: Optional[str] = None
    simulated_outcome: Optional[dict] = None
    actual_outcome: Optional[dict] = None
    surprise_score: float = 0.0
    lessons: list[str] = field(default_factory=list)
    competencies_extracted: list[str] = field(default_factory=list)
    ts_created: int = 0
    ts_resolved: int = 0
    status: str = "open"  # open, simulated, resolved, learned


@dataclass
class Competency:
    """Competência reutilizável extraída de experiência."""
    id: str
    name: str
    description: str
    trigger_conditions: list[str]
    procedure: str  # Procedimento textual (receita)
    success_count: int = 0
    failure_count: int = 0
    confidence: float = 0.5
    source_scenarios: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    created_at: int = 0
    last_used: int = 0
    version: int = 1


# ─── Engine ──────────────────────────────────────────────────────

class MentalSimulationEngine:
    MAX_SCENARIOS = 500
    MAX_COMPETENCIES = 200

    def __init__(self, sim_path: Path | None = None, competency_path: Path | None = None):
        self.sim_path = sim_path or SIM_PATH
        self.competency_path = competency_path or COMPETENCY_PATH
        self.scenarios: deque[Scenario] = deque(maxlen=self.MAX_SCENARIOS)
        self.competencies: dict[str, Competency] = {}
        self._sim_count = 0
        self._load()

    # ── Persistence ──────────────────────────────────────

    def _load(self):
        for path, target in [(self.sim_path, "scenarios"), (self.competency_path, "competencies")]:
            if not path.exists():
                continue
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                if target == "scenarios":
                    raw = d.get("scenarios", [])
                    self.scenarios = deque(
                        [self._scenario_from_dict(s) for s in raw[-self.MAX_SCENARIOS:]],
                        maxlen=self.MAX_SCENARIOS,
                    )
                    self._sim_count = d.get("sim_count", 0)
                else:
                    raw = d.get("competencies", {})
                    self.competencies = {k: Competency(**v) for k, v in raw.items()}
            except Exception as e:
                logger.warning(f"MentalSim: load error ({path.name}): {e}")

    @staticmethod
    def _scenario_from_dict(raw: dict[str, Any]) -> Scenario:
        payload = dict(raw or {})
        hyp_fields = {f.name for f in fields(Hypothesis)}
        hypotheses = []
        for idx, item in enumerate(payload.get("hypotheses") or []):
            if isinstance(item, Hypothesis):
                hypotheses.append(item)
                continue
            if not isinstance(item, dict):
                continue
            hyp = {k: v for k, v in item.items() if k in hyp_fields}
            hyp.setdefault("id", f"loaded_hyp_{idx}")
            hyp.setdefault("description", "hipotese registrada")
            hyp.setdefault("predicted_outcome", "desconhecido")
            hyp.setdefault("confidence", 0.5)
            hyp.setdefault("risk", 0.5)
            hyp.setdefault("cost", 0.3)
            hyp.setdefault("benefit", 0.5)
            hyp.setdefault("evidence_for", [])
            hyp.setdefault("evidence_against", [])
            hyp.setdefault("causal_chain", [])
            hypotheses.append(Hypothesis(**hyp))
        payload["hypotheses"] = hypotheses
        payload.setdefault("id", f"loaded_{int(time.time())}")
        payload.setdefault("name", "cenario carregado")
        scenario_fields = {f.name for f in fields(Scenario)}
        return Scenario(**{k: v for k, v in payload.items() if k in scenario_fields})

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # scenarios
        sim_data = {
            "scenarios": [asdict(s) for s in list(self.scenarios)],
            "sim_count": self._sim_count,
            "updated_at": int(time.time()),
        }
        self.sim_path.write_text(json.dumps(sim_data, ensure_ascii=False, indent=2), encoding="utf-8")
        # competencies
        comp_data = {
            "competencies": {k: asdict(v) for k, v in self.competencies.items()},
            "updated_at": int(time.time()),
        }
        self.competency_path.write_text(json.dumps(comp_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 1. Imaginar Consequências ────────────────────────

    @staticmethod
    def _absent_cause_context(context: dict[str, Any], cause: dict[str, Any]) -> dict[str, Any]:
        ctx = json.loads(json.dumps(context or {}, ensure_ascii=False, default=str))
        key = str(cause.get("variable") or "").strip()
        aliases = {key, key.lower(), "primary_cause", "causal_factor", "causal_feature"}

        def _prune(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _prune(v) for k, v in obj.items() if str(k) not in aliases and str(k).lower() not in aliases}
            if isinstance(obj, list):
                return [_prune(v) for v in obj]
            return obj

        pruned = _prune(ctx)
        if isinstance(pruned, dict):
            pruned["counterfactual_absent_cause"] = key or "unknown"
            pruned["primary_cause_present"] = False
        return pruned if isinstance(pruned, dict) else {}

    @staticmethod
    def _derive_primary_cause(action_kind: str, action_text: str, context: dict[str, Any], preflight: dict[str, Any], wm_sim: dict[str, Any]) -> dict[str, Any]:
        ctx = context or {}
        for key in ("primary_cause", "causal_factor", "causal_feature", "cause"):
            val = ctx.get(key)
            if val not in (None, ""):
                if isinstance(val, dict):
                    return {
                        "variable": str(val.get("variable") or val.get("name") or key),
                        "value": val.get("value"),
                        "source": f"context.{key}",
                    }
                return {"variable": str(val), "value": True, "source": f"context.{key}"}

        visual_features = ctx.get("visual_features") if isinstance(ctx.get("visual_features"), list) else []
        if visual_features:
            return {"variable": str(visual_features[0]), "value": True, "source": "context.visual_features"}

        predicted = preflight.get("predicted_outcomes") if isinstance(preflight.get("predicted_outcomes"), list) else []
        if predicted:
            return {"variable": str(predicted[0])[:120], "value": True, "source": "preflight.predicted_outcomes"}

        wm_pred = str(wm_sim.get("predicted_outcome") or "").strip()
        if wm_pred and wm_pred != "unknown":
            return {"variable": wm_pred[:120], "value": True, "source": "world_model.predicted_outcome"}

        return {"variable": str(action_kind or action_text or "unknown")[:120], "value": True, "source": "action_kind"}

    def _absent_cause_counterfactual(
        self,
        *,
        action_kind: str,
        action_text: str,
        context: dict[str, Any],
        preflight: dict[str, Any],
        wm_sim: dict[str, Any],
        base_composite: float,
    ) -> dict[str, Any]:
        cause = self._derive_primary_cause(action_kind, action_text, context, preflight, wm_sim)
        cf_context = self._absent_cause_context(context, cause)
        try:
            from ultronpro import world_model
            cf_prediction = world_model.simulate_action(action_kind, cf_context)
        except Exception as e:
            cf_prediction = {"predicted_outcome": "unknown", "confidence": 0.0, "error": str(e)[:120]}

        base_outcome = str(wm_sim.get("predicted_outcome") or "unknown")
        cf_outcome = str(cf_prediction.get("predicted_outcome") or "unknown")
        base_conf = float(wm_sim.get("confidence") or 0.0)
        cf_conf = float(cf_prediction.get("confidence") or 0.0)
        same_outcome = bool(base_outcome == cf_outcome and base_outcome != "unknown")
        confidence_retained = cf_conf >= max(0.35, base_conf * 0.8)
        absent_same = same_outcome and confidence_retained

        visual_terms = ("visual", "vision", "image", "arc", "grid", "pixel", "object", "cor", "color")
        visual_mode = any(t in str(action_kind).lower() for t in visual_terms) or bool(context.get("visual_features"))
        mirage_risk = bool(absent_same and visual_mode)
        penalty = 0.0
        if absent_same:
            penalty = 0.35 if mirage_risk else 0.2

        return {
            "question": "If my main cause were absent, would the result be the same?",
            "primary_cause": cause,
            "base_prediction": {"outcome": base_outcome, "confidence": round(base_conf, 4)},
            "absent_cause_prediction": {
                "outcome": cf_outcome,
                "confidence": round(cf_conf, 4),
                "error": cf_prediction.get("error"),
            },
            "same_result_without_cause": absent_same,
            "mirage_risk": mirage_risk,
            "causal_verdict": "spurious_or_unproven_cause" if absent_same else "cause_has_counterfactual_weight",
            "composite_penalty": round(penalty, 4),
            "counterfactual_composite": round(max(0.0, base_composite - penalty), 4),
        }

    def imagine_consequences(
        self,
        action_kind: str,
        action_text: str,
        context: dict | None = None,
    ) -> dict[str, Any]:
        """
        Simula mentalmente as consequências de uma ação ANTES de executá-la.
        Usa o world_model + causal_preflight + contrafactual.
        Retorna dicionário com:
          - predicted_outcomes: lista de efeitos esperados
          - risk_benefit: score composto
          - recommended_posture: proceed / caution / abort
          - mental_trace: cadeia de raciocínio
        """
        trace = []

        # Step 1: Causal Preflight
        try:
            from ultronpro import causal_preflight
            preflight = causal_preflight.run_preflight(
                action_kind=action_kind,
                action_text=action_text,
                governance_meta=context,
                tool_outputs=[],
            )
            trace.append({"step": "causal_preflight", "risk": preflight.get("risk_score"), "recommended": preflight.get("recommended_action")})
        except Exception as e:
            preflight = {"risk_score": 0.5, "reversibility_score": 0.5, "predicted_outcomes": [], "recommended_action": "proceed"}
            trace.append({"step": "causal_preflight", "error": str(e)[:100]})

        # Step 2: World Model simulation
        try:
            from ultronpro import world_model
            wm_sim = world_model.simulate_action(action_kind, context or {})
            trace.append({"step": "world_model_sim", "predicted": wm_sim.get("predicted_outcome"), "confidence": wm_sim.get("confidence")})
        except Exception as e:
            wm_sim = {"predicted_outcome": "unknown", "confidence": 0.0, "state_delta": {}}
            trace.append({"step": "world_model_sim", "error": str(e)[:100]})

        # Step 3: Contrafactual deliberation (what are the alternatives?)
        try:
            from ultronpro import contrafactual
            deliberation = contrafactual.deliberate(action_kind, action_text, context)
            trace.append({"step": "contrafactual", "approved": deliberation.get("approved"), "chosen_score": (deliberation.get("chosen") or {}).get("score")})
        except Exception as e:
            deliberation = {"approved": True, "chosen": None, "alternatives": []}
            trace.append({"step": "contrafactual", "error": str(e)[:100]})

        # Step 4: Check competency library for past experience
        matching_comp = self._find_matching_competencies(action_kind, action_text)
        if matching_comp:
            avg_conf = sum(c.confidence for c in matching_comp) / len(matching_comp)
            trace.append({"step": "competency_match", "matched": len(matching_comp), "avg_confidence": round(avg_conf, 3)})
        else:
            trace.append({"step": "competency_match", "matched": 0})

        # Step 5: Episodic recall for similar past situations
        similar_scenarios = self._find_similar_scenarios(action_kind, action_text, limit=3)
        past_surprises = [s.surprise_score for s in similar_scenarios if s.status == "learned"]
        avg_past_surprise = sum(past_surprises) / len(past_surprises) if past_surprises else 0.5
        trace.append({"step": "episodic_recall", "similar_count": len(similar_scenarios), "avg_past_surprise": round(avg_past_surprise, 3)})

        # ── Composição final ───────────────────────────
        risk = float(preflight.get("risk_score", 0.5))
        reversibility = float(preflight.get("reversibility_score", 0.5))
        wm_conf = float(wm_sim.get("confidence", 0.5))
        comp_boost = min(0.15, len(matching_comp) * 0.05)  # competencies reduce uncertainty

        # Composite score: benefit weighted - risk weighted
        composite = (wm_conf * 0.3 + reversibility * 0.25 + (1.0 - risk) * 0.3 + comp_boost + (1.0 - avg_past_surprise) * 0.15)
        absent_cause_cf = self._absent_cause_counterfactual(
            action_kind=action_kind,
            action_text=action_text,
            context=context or {},
            preflight=preflight,
            wm_sim=wm_sim,
            base_composite=composite,
        )
        if absent_cause_cf.get("same_result_without_cause"):
            composite = float(absent_cause_cf.get("counterfactual_composite") or composite)
            risk = min(1.0, risk + (0.25 if absent_cause_cf.get("mirage_risk") else 0.12))
        trace.append({
            "step": "absent_cause_counterfactual",
            "cause": absent_cause_cf.get("primary_cause"),
            "same_result_without_cause": absent_cause_cf.get("same_result_without_cause"),
            "mirage_risk": absent_cause_cf.get("mirage_risk"),
            "verdict": absent_cause_cf.get("causal_verdict"),
        })

        if composite >= 0.7:
            posture = "proceed"
        elif composite >= 0.45:
            posture = "caution"
        else:
            posture = "abort"
        if absent_cause_cf.get("mirage_risk") and posture == "proceed":
            posture = "caution"

        result = {
            "action_kind": action_kind,
            "action_text": action_text[:200],
            "predicted_outcomes": preflight.get("predicted_outcomes", []),
            "world_model_prediction": wm_sim.get("predicted_outcome"),
            "risk_score": round(risk, 4),
            "reversibility": round(reversibility, 4),
            "composite_score": round(composite, 4),
            "recommended_posture": posture,
            "matching_competencies": [c.name for c in matching_comp],
            "similar_past_scenarios": len(similar_scenarios),
            "mental_trace": trace,
            "contrafactual_approved": deliberation.get("approved"),
            "absent_cause_counterfactual": absent_cause_cf,
            "alternatives_considered": len(deliberation.get("alternatives", [])),
        }

        self._sim_count += 1
        return result

    # ── 2. Comparar Hipóteses ────────────────────────────

    def compare_hypotheses(
        self,
        scenario_name: str,
        hypotheses_raw: list[dict[str, Any]],
    ) -> Scenario:
        """
        Recebe N hipóteses rivais, avalia cada uma mentalmente e cria um Scenario
        com ranking e escolha.

        Cada hipótese em hypotheses_raw tem:
          description, predicted_outcome, confidence (opcional), risk (opcional),
          cost (opcional), benefit (opcional)
        """
        now = int(time.time())
        hyps: list[Hypothesis] = []

        for i, raw in enumerate(hypotheses_raw[:10]):  # Max 10 hipóteses
            h = Hypothesis(
                id=f"hyp_{now}_{i}",
                description=str(raw.get("description", f"Hipótese {i + 1}")),
                predicted_outcome=str(raw.get("predicted_outcome", "desconhecido")),
                confidence=float(raw.get("confidence", 0.5)),
                risk=float(raw.get("risk", 0.5)),
                cost=float(raw.get("cost", 0.3)),
                benefit=float(raw.get("benefit", 0.5)),
                evidence_for=list(raw.get("evidence_for", [])),
                evidence_against=list(raw.get("evidence_against", [])),
                causal_chain=list(raw.get("causal_chain", [])),
            )
            hyps.append(h)

        # Score each hypothesis: benefit × confidence - risk × cost
        def _score_hyp(h: Hypothesis) -> float:
            evidence_bonus = len(h.evidence_for) * 0.05 - len(h.evidence_against) * 0.08
            return (
                h.benefit * 0.35
                + h.confidence * 0.30
                - h.risk * 0.20
                - h.cost * 0.15
                + evidence_bonus
            )

        hyps.sort(key=_score_hyp, reverse=True)
        chosen_id = hyps[0].id if hyps else None

        scenario = Scenario(
            id=f"scn_{now}_{uuid.uuid4().hex[:6]}",
            name=scenario_name,
            hypotheses=hyps,
            chosen_hypothesis_id=chosen_id,
            ts_created=now,
            status="simulated",
        )

        # Simulate outcome for best hypothesis
        if hyps:
            best = hyps[0]
            scenario.simulated_outcome = {
                "hypothesis_id": best.id,
                "hypothesis_description": best.description,
                "expected_result": best.predicted_outcome,
                "composite_score": round(_score_hyp(best), 4),
                "risk_accepted": round(best.risk, 4),
                "alternatives_rejected": len(hyps) - 1,
                "rejection_reasons": [
                    {"id": h.id, "description": h.description[:80], "score": round(_score_hyp(h), 4), "gap": round(_score_hyp(best) - _score_hyp(h), 4)}
                    for h in hyps[1:]
                ],
            }

        self.scenarios.append(scenario)
        self._save()

        logger.info(f"MentalSim: Scenario '{scenario_name}' created with {len(hyps)} hypotheses → chosen: {chosen_id}")
        return scenario

    # ── 3. Testar Mentalmente Caminhos ───────────────────

    def test_paths(
        self,
        objective: str,
        paths: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Dado um objetivo e N caminhos possíveis, simula mentalmente cada um
        usando imagine_consequences + competency lookup e retorna ranking.

        Cada path tem: name, steps (list[str]), estimated_cost (float)
        """
        results = []
        for path in paths[:8]:  # Max 8 caminhos
            name = str(path.get("name", "caminho"))
            steps = list(path.get("steps", []))
            est_cost = float(path.get("estimated_cost", 0.5))

            # Simulate each step
            step_results = []
            cumulative_risk = 0.0
            cumulative_benefit = 0.0

            for step in steps[:10]:  # Max 10 passos por caminho
                sim = self.imagine_consequences(
                    action_kind=f"path_step:{name}",
                    action_text=str(step),
                    context={"objective": objective, "path_name": name},
                )
                step_risk = float(sim.get("risk_score", 0.5))
                step_benefit = float(sim.get("composite_score", 0.5))

                cumulative_risk = 1.0 - (1.0 - cumulative_risk) * (1.0 - step_risk * 0.3)
                cumulative_benefit += step_benefit * 0.2

                step_results.append({
                    "step": str(step)[:120],
                    "risk": round(step_risk, 3),
                    "composite": round(step_benefit, 3),
                    "posture": sim.get("recommended_posture"),
                })

            # Path viability
            viability = max(0.0, min(1.0,
                cumulative_benefit - cumulative_risk * 0.5 - est_cost * 0.3
            ))

            results.append({
                "name": name,
                "steps_count": len(steps),
                "cumulative_risk": round(cumulative_risk, 4),
                "cumulative_benefit": round(cumulative_benefit, 4),
                "estimated_cost": round(est_cost, 4),
                "viability_score": round(viability, 4),
                "step_details": step_results,
                "verdict": "viable" if viability >= 0.5 else "risky" if viability >= 0.25 else "avoid",
            })

        results.sort(key=lambda r: r["viability_score"], reverse=True)

        return {
            "objective": objective[:200],
            "paths_evaluated": len(results),
            "results": results,
            "recommended_path": results[0]["name"] if results else None,
            "recommended_viability": results[0]["viability_score"] if results else 0.0,
        }

    # ── 4. Aprender com Erros (Post-Mortem Causal) ──────

    def learn_from_outcome(
        self,
        scenario_id: str,
        actual_outcome: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Após o resultado real chegar, compara com o previsto e extrai lições.
        Registra surpresa e atualiza competências.
        """
        scenario = self._find_scenario(scenario_id)
        if not scenario:
            return {"ok": False, "error": "scenario_not_found"}

        scenario.actual_outcome = actual_outcome
        scenario.ts_resolved = int(time.time())

        # Calculate surprise
        predicted = scenario.simulated_outcome or {}
        expected_result = str(predicted.get("expected_result", "")).lower()
        actual_result = str(actual_outcome.get("result", "")).lower()
        actual_success = bool(actual_outcome.get("success", False))

        # Surprise: how different was reality from prediction?
        if expected_result and actual_result:
            if expected_result == actual_result:
                surprise = 0.1
            elif actual_success and "sucesso" in expected_result:
                surprise = 0.2
            elif not actual_success and "falha" in expected_result:
                surprise = 0.2
            else:
                surprise = 0.8  # Unexpected result
        else:
            surprise = 0.5  # Ambiguous

        scenario.surprise_score = surprise

        # Extract lessons
        lessons = []
        if surprise >= 0.6:
            lessons.append(f"Alta surpresa ({surprise:.2f}): o modelo de mundo/previsão falhou para esse tipo de ação.")
            if not actual_success:
                lessons.append(f"Falha inesperada: revisar premissas causais de '{predicted.get('hypothesis_description', 'ação')}'.")
            else:
                lessons.append(f"Sucesso inesperado: o modelo subestimou capacidade ou superestimou risco.")
        elif surprise <= 0.25:
            lessons.append(f"Previsão precisa ({surprise:.2f}): modelo de mundo está bem calibrado para este domínio.")

        # Check rejected hypotheses
        if scenario.hypotheses and actual_success:
            chosen = next((h for h in scenario.hypotheses if h.id == scenario.chosen_hypothesis_id), None)
            if chosen and chosen.predicted_outcome.lower() != actual_result:
                # We chose right but for wrong reasons, or wrong entirely
                lessons.append("A hipótese escolhida não previu corretamente o resultado, mesmo com sucesso.")

        scenario.lessons = lessons
        scenario.status = "learned"

        # Try to extract competency from successful patterns
        competencies_extracted = []
        if actual_success and surprise <= 0.4:
            comp_id = self._extract_competency(scenario)
            if comp_id:
                competencies_extracted.append(comp_id)
                scenario.competencies_extracted.append(comp_id)

        # Update RL policy if possible
        try:
            from ultronpro import rl_policy
            chosen_hyp = next((h for h in scenario.hypotheses if h.id == scenario.chosen_hypothesis_id), None)
            if chosen_hyp and not bool(actual_outcome.get("skip_rl_update")):
                reward = 0.8 if actual_success else 0.2
                rl_policy.observe(chosen_hyp.description[:40], "mental_simulation", reward)
        except Exception:
            pass

        self._save()

        logger.info(f"MentalSim: Learned from scenario '{scenario.name}': surprise={surprise:.2f}, lessons={len(lessons)}, competencies={len(competencies_extracted)}")

        return {
            "ok": True,
            "scenario_id": scenario_id,
            "surprise_score": round(surprise, 4),
            "lessons": lessons,
            "competencies_extracted": competencies_extracted,
            "status": scenario.status,
        }

    # ── 5. Consolidar Competências ───────────────────────

    def _extract_competency(self, scenario: Scenario) -> Optional[str]:
        """
        Extrai uma competência reutilizável de um cenário bem-sucedido.
        Só consolida se o padrão apareceu em ≥2 cenários similares.
        """
        if not scenario.hypotheses:
            return None

        chosen = next((h for h in scenario.hypotheses if h.id == scenario.chosen_hypothesis_id), None)
        if not chosen:
            return None

        # Check if a similar competency already exists
        comp_key = self._competency_key(chosen.description)
        if comp_key in self.competencies:
            existing = self.competencies[comp_key]
            existing.success_count += 1
            existing.last_used = int(time.time())
            existing.confidence = existing.success_count / max(1, existing.success_count + existing.failure_count)
            existing.source_scenarios.append(scenario.id)
            existing.source_scenarios = existing.source_scenarios[-20:]  # Keep last 20
            existing.version += 1
            return existing.id

        # Check if pattern appeared in past scenarios
        similar = self._find_similar_scenarios(
            scenario.hypotheses[0].description[:40] if scenario.hypotheses else "",
            scenario.name,
            limit=5,
        )
        similar_successful = [s for s in similar if s.status == "learned" and s.surprise_score <= 0.4]

        if len(similar_successful) < 1:  # Need at least 1 prior success to consolidate
            return None

        try:
            from ultronpro import epistemic_ledger
            ledger_gate = epistemic_ledger.record_competency_evidence(
                artifact_id=comp_key,
                claim=chosen.description,
                actual_success=bool((scenario.actual_outcome or {}).get("success")),
                alternatives_count=max(0, len(scenario.hypotheses or []) - 1),
                longitudinal_support=len(similar_successful),
                payload={
                    "scenario_id": scenario.id,
                    "scenario_name": scenario.name,
                    "surprise_score": scenario.surprise_score,
                    "predicted_outcome": chosen.predicted_outcome,
                },
            )
            if not bool(ledger_gate.get("promotion_ready")):
                logger.info(f"MentalSim: competency blocked by epistemic ledger: {ledger_gate.get('blockers')}")
                return None
        except Exception as e:
            logger.warning(f"MentalSim: competency ledger gate unavailable: {e}")
            return None

        # Create new competency
        now = int(time.time())
        comp = Competency(
            id=f"comp_{now}_{uuid.uuid4().hex[:6]}",
            name=f"Competência: {chosen.description[:60]}",
            description=f"Padrão de sucesso extraído de {len(similar_successful) + 1} cenários similares. "
                        f"Hipótese vencedora: {chosen.description}. "
                        f"Resultado esperado: {chosen.predicted_outcome}.",
            trigger_conditions=[
                f"Tipo de ação similar a: {scenario.name[:80]}",
                f"Risco ≤ {chosen.risk:.2f}",
                f"Confiança ≥ {chosen.confidence:.2f}",
            ],
            procedure=f"1. Avaliar riscos (risk≤{chosen.risk:.2f})\n"
                      f"2. Aplicar abordagem: {chosen.description}\n"
                      f"3. Monitorar resultado previsto: {chosen.predicted_outcome}\n"
                      f"4. Se surpresa > 0.5, revisar cadeia causal.",
            success_count=len(similar_successful) + 1,
            failure_count=0,
            confidence=0.6 + min(0.3, len(similar_successful) * 0.1),
            source_scenarios=[scenario.id] + [s.id for s in similar_successful],
            domains=[scenario.name.split(":")[0] if ":" in scenario.name else "general"],
            created_at=now,
            last_used=now,
        )

        if len(self.competencies) >= self.MAX_COMPETENCIES:
            # Evict least confident / oldest
            worst = min(self.competencies.values(), key=lambda c: c.confidence * 0.6 + (c.last_used / (now + 1)) * 0.4)
            del self.competencies[self._competency_key(worst.description)]

        self.competencies[comp_key] = comp
        logger.info(f"MentalSim: New competency '{comp.name}' (conf={comp.confidence:.2f})")
        return comp.id

    def record_competency_failure(self, competency_id: str) -> dict:
        """Registra falha ao usar uma competência, diminuindo sua confiança."""
        comp = next((c for c in self.competencies.values() if c.id == competency_id), None)
        if not comp:
            return {"ok": False, "error": "competency_not_found"}

        comp.failure_count += 1
        comp.last_used = int(time.time())
        comp.confidence = comp.success_count / max(1, comp.success_count + comp.failure_count)

        self._save()
        return {"ok": True, "competency_id": competency_id, "new_confidence": round(comp.confidence, 4)}

    # ── Lookup Helpers ───────────────────────────────────

    def _find_scenario(self, scenario_id: str) -> Optional[Scenario]:
        for s in self.scenarios:
            if s.id == scenario_id:
                return s
        return None

    def _find_matching_competencies(self, action_kind: str, action_text: str) -> list[Competency]:
        """Encontra competências relevantes para a ação."""
        key = f"{action_kind} {action_text}".lower()
        matches = []
        for comp in self.competencies.values():
            # Simple keyword matching (could be improved with embeddings)
            name_lower = comp.name.lower()
            desc_lower = comp.description.lower()
            triggers_lower = " ".join(comp.trigger_conditions).lower()
            combined = name_lower + " " + desc_lower + " " + triggers_lower

            # Check overlap
            words = set(key.split())
            matched = sum(1 for w in words if w in combined and len(w) > 3)
            if matched >= 2 or any(d in key for d in comp.domains):
                matches.append(comp)

        matches.sort(key=lambda c: c.confidence, reverse=True)
        return matches[:5]

    def _find_similar_scenarios(self, action_kind: str, action_text: str, limit: int = 5) -> list[Scenario]:
        """Encontra cenários passados similares."""
        key = f"{action_kind} {action_text}".lower()
        scored = []
        for s in self.scenarios:
            name_lower = (s.name or "").lower()
            hyps_text = " ".join(h.description for h in (s.hypotheses or [])).lower()
            combined = name_lower + " " + hyps_text

            words = set(key.split())
            matched = sum(1 for w in words if w in combined and len(w) > 3)
            if matched >= 1:
                scored.append((matched, s))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    @staticmethod
    def _competency_key(description: str) -> str:
        """Gera chave normalizada para deduplicar competências."""
        norm = " ".join(sorted(set(description.lower().split())))[:100]
        return hashlib.md5(norm.encode()).hexdigest()[:16]

    # ── Status & Observability ───────────────────────────

    def run_longitudinal_probe(self, cycles: int = 12, update_rl: bool = True) -> dict[str, Any]:
        """Run a deterministic convergence probe for roadmap item 13.7."""
        n = max(4, min(60, int(cycles or 12)))
        comp_before = len(self.competencies)
        surprises: list[float] = []
        extracted: list[str] = []

        for idx in range(n):
            scenario = self.compare_hypotheses(
                "longitudinal_probe: external_verification_loop",
                [
                    {
                        "description": "validate externally before promotion",
                        "predicted_outcome": "success",
                        "confidence": 0.82,
                        "risk": 0.12,
                        "cost": 0.1,
                        "benefit": 0.9,
                        "evidence_for": ["external benchmark anchor", "sandbox verification"],
                    },
                    {
                        "description": "promote from internal style score only",
                        "predicted_outcome": "failure",
                        "confidence": 0.35,
                        "risk": 0.8,
                        "cost": 0.2,
                        "benefit": 0.2,
                        "evidence_against": ["circular validation risk"],
                    },
                ],
            )
            learned = self.learn_from_outcome(
                scenario.id,
                {
                    "success": True,
                    "result": "success",
                    "probe_cycle": idx + 1,
                    "skip_rl_update": not bool(update_rl),
                },
            )
            surprises.append(float(learned.get("surprise_score") or 0.0))
            extracted.extend([str(x) for x in (learned.get("competencies_extracted") or []) if str(x)])

        half = max(1, len(surprises) // 2)
        first_avg = sum(surprises[:half]) / max(1, half)
        second_avg = sum(surprises[half:]) / max(1, len(surprises) - half)
        comp_after = len(self.competencies)
        reusable = [
            asdict(c)
            for c in self.competencies.values()
            if "validate externally before promotion" in c.description.lower()
            and (c.success_count + c.failure_count) > 1
        ]
        return {
            "ok": True,
            "cycles": n,
            "first_half_avg_surprise": round(first_avg, 4),
            "second_half_avg_surprise": round(second_avg, 4),
            "surprise_delta": round(second_avg - first_avg, 4),
            "competencies_before": comp_before,
            "competencies_after": comp_after,
            "competencies_created": max(0, comp_after - comp_before),
            "reusable_competencies": len(reusable),
            "extracted_competency_ids": sorted(set(extracted)),
            "rl_updated": bool(update_rl),
            "passed": bool(second_avg <= first_avg and len(reusable) >= 1),
        }

    def status(self, limit: int = 20) -> dict[str, Any]:
        recent = list(self.scenarios)[-limit:]
        learned = [s for s in self.scenarios if s.status == "learned"]
        avg_surprise = sum(s.surprise_score for s in learned) / max(1, len(learned))

        return {
            "total_simulations": self._sim_count,
            "total_scenarios": len(self.scenarios),
            "scenarios_learned": len(learned),
            "competencies_count": len(self.competencies),
            "avg_surprise_score": round(avg_surprise, 4),
            "top_competencies": [
                {"id": c.id, "name": c.name, "confidence": round(c.confidence, 3), "uses": c.success_count + c.failure_count}
                for c in sorted(self.competencies.values(), key=lambda c: c.confidence, reverse=True)[:10]
            ],
            "recent_scenarios": [
                {
                    "id": s.id,
                    "name": s.name,
                    "status": s.status,
                    "hypotheses_count": len(s.hypotheses),
                    "surprise": round(s.surprise_score, 3),
                    "lessons_count": len(s.lessons),
                    "ts": s.ts_created,
                }
                for s in recent
            ],
        }

    def get_competency_library(self) -> list[dict[str, Any]]:
        return [asdict(c) for c in sorted(self.competencies.values(), key=lambda c: c.confidence, reverse=True)]


# ─── Singleton ────────────────────────────────────────────────────

_engine: Optional[MentalSimulationEngine] = None


def get_engine() -> MentalSimulationEngine:
    global _engine
    if _engine is None:
        _engine = MentalSimulationEngine()
    return _engine


# ─── Public API ───────────────────────────────────────────────────

def imagine(action_kind: str, action_text: str, context: dict | None = None) -> dict:
    return get_engine().imagine_consequences(action_kind, action_text, context)


def compare(scenario_name: str, hypotheses: list[dict]) -> dict:
    s = get_engine().compare_hypotheses(scenario_name, hypotheses)
    return asdict(s)


def test_paths(objective: str, paths: list[dict]) -> dict:
    return get_engine().test_paths(objective, paths)


def learn(scenario_id: str, actual_outcome: dict) -> dict:
    return get_engine().learn_from_outcome(scenario_id, actual_outcome)


def status(limit: int = 20) -> dict:
    return get_engine().status(limit)


def competencies() -> list[dict]:
    return get_engine().get_competency_library()


def record_failure(competency_id: str) -> dict:
    return get_engine().record_competency_failure(competency_id)


def longitudinal_probe(cycles: int = 12, persist: bool = False) -> dict:
    if persist:
        return get_engine().run_longitudinal_probe(cycles, update_rl=True)

    import tempfile

    with tempfile.TemporaryDirectory(prefix="mental-sim-probe-") as td:
        base = Path(td)
        engine = MentalSimulationEngine(
            sim_path=base / "mental_simulation.json",
            competency_path=base / "competency_library.json",
        )
        out = engine.run_longitudinal_probe(cycles, update_rl=False)
        out["isolated"] = True
        return out
