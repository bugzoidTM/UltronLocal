"""
Modelos de Mundo Locais por Família de Ambiente
================================================

Em vez de um modelo global gigante, este módulo gerencia World Models locais transferíveis
('sandbox_financeiro', 'fs_com_rollback', 'interacoes_codigo', 'busca_autonoma').
Cada modelo é treinado nos episódios da sua respectiva família e pode consultar
um grafo explícito de pontes para compor previsões entre famílias.

O sinal de treinamento é o erro de previsão (surpresa). O estado em T deve 
prever o estado em T+1 dada uma ação. Quando o modelo erra sistematicamente,
o LLM atua como "professor auxiliar" induzindo novas hipóteses/abstrações.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
import uuid
from typing import Any
from pathlib import Path
from collections import deque

from ultronpro import llm, store

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
LOCAL_WORLD_MODELS_PATH = DATA_DIR / 'local_world_models.json'
LOCAL_CONFIDENCE_MIN = 0.55
TRANSFER_CONFIDENCE_MIN = 0.18
COMPOSITION_SCORE_MIN = 0.72
TRANSFER_DEGRADATION = 0.78


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if number != number:
            return default
        return max(0.0, min(1.0, number))
    except Exception:
        return default


def _tokens(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", str(value or "").lower()))


def _bridge_id(source_family: str, target_family: str, relation_type: str, payload: dict[str, Any] | None = None) -> str:
    raw = json.dumps({
        "source": str(source_family or ""),
        "target": str(target_family or ""),
        "relation": str(relation_type or ""),
        "feature_map": (payload or {}).get("feature_map") or {},
        "action_map": (payload or {}).get("action_map") or {},
    }, sort_keys=True, ensure_ascii=False, default=str)
    return "wmb_" + hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _compact(value: Any, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(k)[:80]: _compact(v, limit=limit // 2) for k, v in list(value.items())[:24]}
    if isinstance(value, list):
        return [_compact(v, limit=limit // 2) for v in value[:12]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)[:limit] if isinstance(value, str) else value
    return str(value)[:limit]


def _invert_mapping(mapping: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (mapping or {}).items():
        skey = str(key or "").strip()
        svalue = str(value or "").strip()
        if skey and svalue:
            out[svalue] = skey
    return out


def _flatten_for_mapping(state: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultronpro.structural_abstractor import _flatten_dict

        return _flatten_dict(state or {})
    except Exception:
        return dict(state or {}) if isinstance(state, dict) else {}


def _set_nested(out: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = [p for p in str(dotted_key or "").split(".") if p]
    if not parts:
        return
    cursor = out
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def _remap_state_to_source(target_state: dict[str, Any], feature_map: dict[str, str]) -> dict[str, Any]:
    """
    feature_map maps target_feature -> source_feature.
    If no map exists, keep the target state as a weak structural prior.
    """
    if not feature_map:
        return dict(target_state or {})
    flat = _flatten_for_mapping(target_state)
    out: dict[str, Any] = {}
    for target_key, source_key in feature_map.items():
        tkey = str(target_key or "").strip()
        skey = str(source_key or "").strip()
        if not tkey or not skey or tkey not in flat:
            continue
        _set_nested(out, skey, flat[tkey])
    return out or dict(target_state or {})


def _entry_outcome(entry: dict[str, Any]) -> tuple[str, float]:
    outcomes = entry.get("outcomes") if isinstance(entry.get("outcomes"), dict) else {}
    if not outcomes:
        return "unknown", 0.0
    outcome, count = max(outcomes.items(), key=lambda item: float(item[1] or 0.0))
    observations = max(1.0, float(entry.get("observations") or 1.0))
    return str(outcome), _safe_float(float(count or 0.0) / observations)

class LocalWorldModel:
    MAX_HISTORY = 100
    SURPRISE_THRESHOLD = 0.65  # Ponto em que pedimos pro LLM induzir hipótese

    def __init__(self, family_name: str):
        self.family_name = family_name
        self.transitions: deque[dict[str, Any]] = deque(maxlen=self.MAX_HISTORY)
        self.hypotheses: list[dict[str, Any]] = []
        self.structural_features: list[str] = []
        self.empirical_matrix: dict[str, dict[str, Any]] = {}
        # empirical_matrix: action -> {outcome -> weight, "expected_value": 0.0, "risk": 0.0}

    def train_step(self, state_t: dict[str, Any], action: str, state_t_plus_1: dict[str, Any], actual_outcome: str, metrics: dict[str, float] | None = None):
        """Treina o modelo baseado na transição empírica T -> T+1."""
        now = int(time.time())
        metrics = metrics or {}
        
        # O que o modelo previa antes dessa observação?
        prediction = self.predict_next_state(state_t, action)
        pred_outcome = prediction.get('predicted_outcome')
        
        # Calcular Erro de Previsão (Surprise)
        match = (pred_outcome == actual_outcome)
        surprise = metrics.get('surprise_delta', 0.0)
        if not match:
            # Erro de previsão empilha surpresa
            surprise += 0.5 

        # Registro de transição real
        transition = {
            'ts': now,
            'action': action,
            'state_hash': str(hash(json.dumps(state_t, sort_keys=True)))[:8],
            'state_t': state_t,
            'actual_outcome': actual_outcome,
            'predicted_outcome': pred_outcome,
            'surprise': min(1.0, surprise),
            'metrics': metrics
        }
        self.transitions.append(transition)


        # ── Surprise-Weighted Training ──
        # Estados raros (alta surpresa) recebem peso multiplicado no update
        # para forçar o modelo a aprender nos casos difíceis.
        from ultronpro.causal_maturity import compute_surprise_weight
        training_weight = compute_surprise_weight(surprise)

        # Mineração periódica de invariants estruturais
        if len(self.transitions) > 5 and len(self.transitions) % 10 == 0:
            try:
                from ultronpro.structural_abstractor import extract_structural_features
                new_features = extract_structural_features(list(self.transitions))
                if new_features and new_features != self.structural_features:
                    self.structural_features = new_features
                    # Retroactive struct mapping para episódios que não tinham a abstração na época
                    from ultronpro.structural_abstractor import compute_structural_hash
                    for t_past in self.transitions:
                        if 'state_t' in t_past:
                            shash = compute_structural_hash(t_past['state_t'], t_past['action'], self.structural_features)
                            if shash:
                                # Update usando as lógicas base, assumimos peso base para reconstrução rápida
                                self._update_empirical_entry(shash, t_past['actual_outcome'], t_past.get('surprise', 0.1), 1.0)
            except Exception as e:
                pass

        try:
            from ultronpro.structural_abstractor import compute_structural_hash
            struct_hash = compute_structural_hash(state_t, action, self.structural_features)
        except Exception:
            struct_hash = None


        # Atualizar gradiente empírico para a ação bruta
        self._update_empirical_entry(action, actual_outcome, surprise, training_weight)

        # Se abstração ocorreu, atualizar também o grafo estrutural invisível
        if struct_hash:
            self._update_empirical_entry(struct_hash, actual_outcome, surprise, training_weight)

        # Se erramos previsões recorrentemente (alta surpresa sistêmica), chame o professor (LLM)
        recent_surprises = [t['surprise'] for t in list(self.transitions)[-5:] if t['action'] == action]
        if len(recent_surprises) >= 3 and (sum(recent_surprises) / len(recent_surprises)) >= self.SURPRISE_THRESHOLD:
            self._induce_hypothesis(action, list(self.transitions)[-10:])

    def _update_empirical_entry(self, key: str, actual_outcome: str, surprise: float, training_weight: float):
        if key not in self.empirical_matrix:
            self.empirical_matrix[key] = {'outcomes': {}, 'expected_value': 0.0, 'risk': 0.0, 'observations': 0.0}
        
        entry = self.empirical_matrix[key]
        entry['observations'] += training_weight
        entry['outcomes'][actual_outcome] = entry['outcomes'].get(actual_outcome, 0) + training_weight
        
        total_obs = max(1.0, entry['observations'])
        win_count = entry['outcomes'].get('increase', entry['outcomes'].get('ok', entry['outcomes'].get('success', 0)))
        win_rate = win_count / total_obs
        entry['expected_value'] = round(win_rate, 4)
        entry['risk'] = round(min(1.0, (1.0 - win_rate) + (surprise * 0.2 * training_weight)), 4)

    def predict_next_state(self, state_t: dict[str, Any], action: str) -> dict[str, Any]:
        """Prevê T+1 e o outcome baseado na matriz treinada."""
        try:
            from ultronpro.structural_abstractor import compute_structural_hash
            struct_hash = compute_structural_hash(state_t, action, self.structural_features)
        except Exception:
            struct_hash = None

        # 1. Mapeamento Estrutural tem PREFERÊNCIA sobre aliases verbais (action_name)
        if struct_hash and struct_hash in self.empirical_matrix:
            lookup_key = struct_hash
        else:
            lookup_key = action

        if lookup_key not in self.empirical_matrix:
             return {
                 'predicted_outcome': 'unknown',
                 'confidence': 0.0,
                 'expected_value': 0.5,
                 'risk': 0.5,
                 'warning': f"Zero histórico na Matriz Causal. (Key: {lookup_key})"
             }
        
        entry = self.empirical_matrix[lookup_key]
        outcomes = entry['outcomes']
        if not outcomes:
            return {'predicted_outcome': 'unknown', 'confidence': 0.0, 'expected_value': 0.5, 'risk': 0.5}

        most_likely = max(outcomes.items(), key=lambda x: x[1])
        confidence = most_likely[1] / entry['observations']

        return {
            'predicted_outcome': most_likely[0],
            'confidence': round(confidence, 4),
            'expected_value': entry['expected_value'],
            'risk': entry['risk']
        }

    def _induce_hypothesis(self, action: str, history: list[dict]):
        """Usa o LLM para abstrair regras quando o modelo falha demasiadamente na previsão (Gradiente corretivo)."""
        import os
        if os.environ.get('BENCHMARK_MODE') == '1':
            return
            
        prompt = f"O modelo empírico falhou repetidamente ao prever a ação '{action}' no domínio '{self.family_name}'.\n"
        prompt += f"Aqui estão as transições recentes (surpresa indica erro de precisão causal):\n{json.dumps(history, ensure_ascii=False)}\n"
        prompt += "Gere uma HIPÓTESE ESTRUTURAL explicando o que esse modelo local ignorou no state_t. Formato JSON com chaves: 'hypothesis', 'hidden_variable_suspected'."
        
        try:
            res = llm.complete(prompt, strategy='cheap', json_mode=True)
            if res:
                cleaned = res.strip()
                f_idx = cleaned.find('{')
                l_idx = cleaned.rfind('}')
                if f_idx != -1 and l_idx != -1:
                    data = json.loads(cleaned[f_idx:l_idx+1])
                    hyp = {
                        'id': f"hyp_{int(time.time())}_{uuid.uuid4().hex[:4]}",
                        'action': action,
                        'hypothesis': data.get('hypothesis', ''),
                        'hidden_variable': data.get('hidden_variable_suspected', ''),
                        'created_at': int(time.time()),
                        'status': 'under_test'
                    }
                    self.hypotheses.append(hyp)
                    store.publish_workspace(
                        module='local_world_models',

                        channel='model.hypothesis_induced',
                        payload_json=json.dumps({'family': self.family_name, **hyp}),
                        salience=0.8,
                        ttl_sec=3600
                    )
        except Exception:
            pass


class LocalWorldModelManager:
    def __init__(self):
        self.models: dict[str, LocalWorldModel] = {}
        self.transfer_graph: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
        if LOCAL_WORLD_MODELS_PATH.exists():
            try:
                data = json.loads(LOCAL_WORLD_MODELS_PATH.read_text(encoding='utf-8'))
                self.transfer_graph = data.get('transfer_graph', {}) if isinstance(data.get('transfer_graph'), dict) else {}
                for fam, payload in data.get('models', {}).items():
                    m = LocalWorldModel(family_name=fam)
                    m.empirical_matrix = payload.get('empirical_matrix', {})
                    m.hypotheses = payload.get('hypotheses', [])
                    m.structural_features = payload.get('structural_features', [])
                    m.transitions = deque(payload.get('transitions', []), maxlen=LocalWorldModel.MAX_HISTORY)
                    self.models[fam] = m
            except Exception:
                pass

    def _save(self):
        LOCAL_WORLD_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {'models': {}, 'transfer_graph': self.transfer_graph}
        for fam, m in self.models.items():
            data['models'][fam] = {
                'empirical_matrix': m.empirical_matrix,
                'hypotheses': m.hypotheses,
                'structural_features': m.structural_features,
                'transitions': list(m.transitions)
            }
        LOCAL_WORLD_MODELS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def get_model(self, family_name: str) -> LocalWorldModel:
        if family_name not in self.models:
            self.models[family_name] = LocalWorldModel(family_name)
        return self.models[family_name]

    def train_transition(self, family_name: str, state_t: dict, action: str, state_t_plus_1: dict, actual_outcome: str, metrics: dict | None = None):
        """Acopla a transição empírica e chama o treino no Domain Local Model."""
        model = self.get_model(family_name)
        model.train_step(state_t, action, state_t_plus_1, actual_outcome, metrics)
        if len(self.models) > 1:
            self.compose_family_graph(changed_family=family_name)
        self._save()

    def predict(self, family_name: str, state_t: dict, action: str) -> dict | None:
        """Invoca o modelo local treinado para inferir o próximo estado e risco."""
        model = self.get_model(family_name)
        local_prediction = model.predict_next_state(state_t, action)
        composed = self._compose_prediction(family_name, state_t, action, local_prediction=local_prediction)

        local_known = (local_prediction or {}).get('predicted_outcome') != 'unknown'
        local_conf = _safe_float((local_prediction or {}).get('confidence'))
        if local_known and local_conf >= LOCAL_CONFIDENCE_MIN:
            if composed:
                local_prediction['composition'] = composed
            return local_prediction

        if composed:
            result = dict(composed)
            result['local_prediction'] = local_prediction
            self._publish_transfer_prediction(result)
            return result
        return local_prediction

    def register_transfer_bridge(
        self,
        source_family: str,
        target_family: str,
        *,
        feature_map: dict[str, str] | None = None,
        action_map: dict[str, str] | None = None,
        confidence: float = 0.5,
        relation_type: str = "manual_transfer_bridge",
        evidence: dict[str, Any] | None = None,
        bidirectional: bool = False,
        save: bool = True,
    ) -> dict[str, Any]:
        """
        Registra uma ponte de transferencia entre familias.

        feature_map usa a direcao target_feature -> source_feature.
        action_map usa a direcao target_action -> source_action.
        """
        feature_map = {str(k): str(v) for k, v in (feature_map or {}).items() if str(k or "").strip() and str(v or "").strip()}
        action_map = {str(k): str(v) for k, v in (action_map or {}).items() if str(k or "").strip() and str(v or "").strip()}
        payload = {"feature_map": feature_map, "action_map": action_map}
        bridge = {
            "id": _bridge_id(source_family, target_family, relation_type, payload),
            "source_family": str(source_family),
            "target_family": str(target_family),
            "feature_map": feature_map,
            "action_map": action_map,
            "confidence": round(_safe_float(confidence, 0.5), 4),
            "relation_type": str(relation_type or "manual_transfer_bridge"),
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "observations": 1,
            "status": "active",
            "evidence": _compact(evidence or {}),
        }

        existing = self.transfer_graph.get(bridge["id"])
        if existing:
            old_conf = _safe_float(existing.get("confidence"), 0.5)
            bridge["created_at"] = existing.get("created_at") or bridge["created_at"]
            bridge["observations"] = int(existing.get("observations") or 0) + 1
            bridge["confidence"] = round(max(old_conf, bridge["confidence"]), 4)
            bridge["evidence"] = _compact({**(existing.get("evidence") or {}), **(evidence or {})})

        self.transfer_graph[bridge["id"]] = bridge
        self._publish_transfer_bridge(bridge, created=existing is None)

        if bidirectional:
            self.register_transfer_bridge(
                target_family,
                source_family,
                feature_map=_invert_mapping(feature_map),
                action_map=_invert_mapping(action_map),
                confidence=bridge["confidence"],
                relation_type=relation_type,
                evidence={"reverse_of": bridge["id"], **(evidence or {})},
                bidirectional=False,
                save=False,
            )

        if save:
            self._save()
        return bridge

    def compose_family_graph(self, changed_family: str | None = None) -> dict[str, Any]:
        """
        Descobre pontes sistematicas entre familias por semelhanca de politica empirica.

        Isso nao exige isomorfismo perfeito: basta que familias diferentes tenham
        acoes comparaveis com EV/risco/outcome semelhantes e evidencia minima.
        """
        families = sorted(self.models)
        created: list[dict[str, Any]] = []
        checked = 0
        for source_name in families:
            source = self.models[source_name]
            source_policy = self._raw_policy_entries(source)
            if not source_policy:
                continue
            for target_name in families:
                if source_name == target_name:
                    continue
                if changed_family and changed_family not in (source_name, target_name):
                    continue
                target = self.models[target_name]
                target_policy = self._raw_policy_entries(target)
                common_actions = sorted(set(source_policy) & set(target_policy))
                if not common_actions:
                    continue
                checked += 1
                scores = [
                    self._policy_composition_score(source_policy[action], target_policy[action])
                    for action in common_actions
                ]
                score = round(sum(scores) / max(1, len(scores)), 4)
                if score < COMPOSITION_SCORE_MIN:
                    continue
                evidence = {
                    "score": score,
                    "common_actions": common_actions[:16],
                    "checked_actions": len(common_actions),
                    "source_observations": round(sum(float(source_policy[a].get("observations") or 0.0) for a in common_actions), 4),
                    "target_observations": round(sum(float(target_policy[a].get("observations") or 0.0) for a in common_actions), 4),
                }
                bridge = self.register_transfer_bridge(
                    source_name,
                    target_name,
                    feature_map=self._shared_feature_map(source, target),
                    action_map={action: action for action in common_actions},
                    confidence=score,
                    relation_type="empirical_policy_composition",
                    evidence=evidence,
                    save=False,
                )
                created.append(bridge)
        if created:
            self._save()
        return {"ok": True, "checked": checked, "bridges": created, "bridge_count": len(self.transfer_graph)}

    def transfer_status(self) -> dict[str, Any]:
        active = [b for b in self.transfer_graph.values() if b.get("status") == "active"]
        return {
            "ok": True,
            "model_families": sorted(self.models),
            "bridge_count": len(active),
            "bridges": sorted(active, key=lambda b: (b.get("source_family", ""), b.get("target_family", ""), b.get("relation_type", ""))),
        }

    def _raw_policy_entries(self, model: LocalWorldModel) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key, entry in (model.empirical_matrix or {}).items():
            skey = str(key or "")
            if skey.startswith("struct:"):
                continue
            if isinstance(entry, dict) and entry.get("observations"):
                out[skey] = entry
        return out

    def _shared_feature_map(self, source: LocalWorldModel, target: LocalWorldModel) -> dict[str, str]:
        source_features = {str(f) for f in (source.structural_features or [])}
        target_features = {str(f) for f in (target.structural_features or [])}
        return {feat: feat for feat in sorted(source_features & target_features)}

    def _policy_composition_score(self, source_entry: dict[str, Any], target_entry: dict[str, Any]) -> float:
        source_ev = _safe_float(source_entry.get("expected_value"), 0.5)
        target_ev = _safe_float(target_entry.get("expected_value"), 0.5)
        source_risk = _safe_float(source_entry.get("risk"), 0.5)
        target_risk = _safe_float(target_entry.get("risk"), 0.5)
        source_outcome, source_conf = _entry_outcome(source_entry)
        target_outcome, target_conf = _entry_outcome(target_entry)
        ev_similarity = max(0.0, 1.0 - abs(source_ev - target_ev))
        risk_similarity = max(0.0, 1.0 - abs(source_risk - target_risk))
        outcome_similarity = 1.0 if source_outcome == target_outcome and source_outcome != "unknown" else 0.0
        obs_strength = min(
            1.0,
            min(float(source_entry.get("observations") or 0.0), float(target_entry.get("observations") or 0.0)) / 3.0,
        )
        certainty = (source_conf + target_conf) / 2.0
        return max(0.0, min(1.0, (
            0.34 * ev_similarity
            + 0.24 * risk_similarity
            + 0.22 * outcome_similarity
            + 0.12 * obs_strength
            + 0.08 * certainty
        )))

    def _candidate_source_action(self, source_model: LocalWorldModel, bridge: dict[str, Any], target_action: str) -> str | None:
        action_map = bridge.get("action_map") if isinstance(bridge.get("action_map"), dict) else {}
        mapped = action_map.get(str(target_action))
        if mapped:
            return str(mapped)
        source_policy = self._raw_policy_entries(source_model)
        if str(target_action) in source_policy:
            return str(target_action)
        target_tokens = _tokens(target_action)
        best_action = None
        best_score = 0.0
        for action_key in source_policy:
            overlap = target_tokens & _tokens(action_key)
            union = target_tokens | _tokens(action_key)
            score = len(overlap) / max(1, len(union))
            if score > best_score:
                best_action = action_key
                best_score = score
        return best_action if best_score >= 0.34 else None

    def _transfer_predictions(self, target_family: str, state_t: dict[str, Any], action: str) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for bridge in self.transfer_graph.values():
            if bridge.get("status") != "active" or bridge.get("target_family") != target_family:
                continue
            source_family = str(bridge.get("source_family") or "")
            source_model = self.models.get(source_family)
            if not source_model:
                continue
            source_action = self._candidate_source_action(source_model, bridge, action)
            if not source_action:
                continue
            feature_map = bridge.get("feature_map") if isinstance(bridge.get("feature_map"), dict) else {}
            source_state = _remap_state_to_source(state_t, feature_map)
            prediction = source_model.predict_next_state(source_state, source_action)
            if not prediction or prediction.get("predicted_outcome") == "unknown":
                continue
            bridge_conf = _safe_float(bridge.get("confidence"), 0.0)
            source_conf = _safe_float(prediction.get("confidence"), 0.0)
            confidence = round(source_conf * bridge_conf * TRANSFER_DEGRADATION, 4)
            if confidence < TRANSFER_CONFIDENCE_MIN:
                continue
            candidates.append({
                "bridge_id": bridge.get("id"),
                "relation_type": bridge.get("relation_type"),
                "source_family": source_family,
                "target_family": target_family,
                "source_action": source_action,
                "target_action": str(action),
                "feature_map": dict(feature_map),
                "confidence": confidence,
                "source_confidence": prediction.get("confidence"),
                "bridge_confidence": bridge.get("confidence"),
                "predicted_outcome": prediction.get("predicted_outcome"),
                "expected_value": prediction.get("expected_value", 0.5),
                "risk": prediction.get("risk", 0.5),
            })
        return sorted(candidates, key=lambda c: c.get("confidence", 0.0), reverse=True)

    def _compose_prediction(
        self,
        target_family: str,
        state_t: dict[str, Any],
        action: str,
        *,
        local_prediction: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        transfers = self._transfer_predictions(target_family, state_t, action)
        if not transfers:
            return None

        totals: dict[str, float] = {}
        for transfer in transfers:
            outcome = str(transfer.get("predicted_outcome") or "unknown")
            totals[outcome] = totals.get(outcome, 0.0) + _safe_float(transfer.get("confidence"))
        predicted_outcome, support = max(totals.items(), key=lambda item: item[1])
        selected = [t for t in transfers if t.get("predicted_outcome") == predicted_outcome]
        total_weight = sum(_safe_float(t.get("confidence")) for t in selected) or 1.0
        expected_value = sum(_safe_float(t.get("expected_value"), 0.5) * _safe_float(t.get("confidence")) for t in selected) / total_weight
        risk = sum(_safe_float(t.get("risk"), 0.5) * _safe_float(t.get("confidence")) for t in selected) / total_weight
        all_weight = sum(_safe_float(t.get("confidence")) for t in transfers) or 1.0
        confidence = min(1.0, support / all_weight * min(1.0, support))

        return {
            "predicted_outcome": predicted_outcome,
            "confidence": round(confidence, 4),
            "expected_value": round(expected_value, 4),
            "risk": round(risk, 4),
            "composed": True,
            "composition_mode": "cross_family_transfer",
            "target_family": target_family,
            "target_action": str(action),
            "transfer_count": len(transfers),
            "transfers": transfers[:8],
            "local_gap": {
                "predicted_outcome": (local_prediction or {}).get("predicted_outcome"),
                "confidence": (local_prediction or {}).get("confidence"),
                "reason": (local_prediction or {}).get("warning") or "local_model_low_confidence",
            },
        }

    def _publish_transfer_bridge(self, bridge: dict[str, Any], *, created: bool) -> None:
        payload = {"created": bool(created), "bridge": _compact(bridge)}
        try:
            store.publish_workspace(
                module="local_world_models",
                channel="world_model.transfer_bridge",
                payload_json=json.dumps(payload, ensure_ascii=False),
                salience=0.62 if created else 0.42,
                ttl_sec=3600,
            )
        except Exception:
            pass
        try:
            store.db.add_event(
                "world_model.transfer_bridge",
                f"world model bridge {bridge.get('source_family')} -> {bridge.get('target_family')} type={bridge.get('relation_type')} conf={bridge.get('confidence')}",
                meta_json=json.dumps(payload, ensure_ascii=False),
            )
        except Exception:
            pass

    def _publish_transfer_prediction(self, prediction: dict[str, Any]) -> None:
        payload = _compact(prediction)
        try:
            store.publish_workspace(
                module="local_world_models",
                channel="world_model.transfer_prediction",
                payload_json=json.dumps(payload, ensure_ascii=False),
                salience=0.58,
                ttl_sec=1800,
            )
        except Exception:
            pass
        try:
            store.db.add_event(
                "world_model.transfer_prediction",
                f"world model transfer target={prediction.get('target_family')} action={prediction.get('target_action')} outcome={prediction.get('predicted_outcome')} conf={prediction.get('confidence')}",
                meta_json=json.dumps(payload, ensure_ascii=False),
            )
        except Exception:
            pass


_manager: LocalWorldModelManager | None = None

def get_manager() -> LocalWorldModelManager:
    global _manager
    if _manager is None:
        _manager = LocalWorldModelManager()
    return _manager

def train_local_model(family_name: str, state_t: dict, action: str, state_t_plus_1: dict, actual_outcome: str, metrics: dict | None = None):
    get_manager().train_transition(family_name, state_t, action, state_t_plus_1, actual_outcome, metrics)

def predict_local_model(family_name: str, state_t: dict, action: str) -> dict | None:
    return get_manager().predict(family_name, state_t, action)

def register_transfer_bridge(
    source_family: str,
    target_family: str,
    *,
    feature_map: dict[str, str] | None = None,
    action_map: dict[str, str] | None = None,
    confidence: float = 0.5,
    relation_type: str = "manual_transfer_bridge",
    evidence: dict[str, Any] | None = None,
    bidirectional: bool = False,
) -> dict[str, Any]:
    return get_manager().register_transfer_bridge(
        source_family,
        target_family,
        feature_map=feature_map,
        action_map=action_map,
        confidence=confidence,
        relation_type=relation_type,
        evidence=evidence,
        bidirectional=bidirectional,
    )

def compose_world_models(changed_family: str | None = None) -> dict[str, Any]:
    return get_manager().compose_family_graph(changed_family=changed_family)

def transfer_status() -> dict[str, Any]:
    return get_manager().transfer_status()
