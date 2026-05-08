from __future__ import annotations

import hashlib
import json
import math
import time
import unicodedata
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROCEDURAL_CONTRACTS_PATH = DATA_DIR / "procedural_contracts.json"
CONTRACT_SCHEMA = "ultron.procedural_contract.v1"

MIN_POSITIVE_RUNS = 2
MIN_SUPPORT = 0.66
MIN_PRECISION = 0.67
MIN_DELTA = 0.20
MAX_CONDITIONS = 12

STOP_TOKENS = {
    "the", "and", "for", "with", "from", "into", "this", "that", "then",
    "uma", "um", "para", "com", "sem", "que", "por", "quando", "onde",
    "true", "false", "none", "null", "step", "analysis", "strategy",
}

VOLATILE_KEYS = {
    "id", "idx", "index", "sample", "run_id", "created_at", "updated_at",
    "ts", "timestamp", "time", "date",
}


def _now() -> int:
    return int(time.time())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if number != number:
            return default
        return number
    except Exception:
        return default


def _norm(value: Any, limit: int = 160) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = " ".join(text.lower().split())
    return text[:limit]


def _tokenize(value: Any) -> set[str]:
    text = _norm(value, limit=4000)
    chars = []
    for ch in text:
        chars.append(ch if ch.isalnum() else " ")
    tokens = set()
    for tok in "".join(chars).split():
        if len(tok) < 3 or tok in STOP_TOKENS:
            continue
        if tok.isdigit():
            continue
        tokens.add(tok[:48])
    return tokens


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _predicate_id(pred: dict[str, Any]) -> str:
    key = {
        "field": pred.get("field"),
        "kind": pred.get("kind"),
        "op": pred.get("op"),
        "path": pred.get("path"),
        "key": pred.get("key"),
        "value": pred.get("value"),
        "threshold": pred.get("threshold"),
    }
    return "pc_" + _hash_payload(key)


def _make_predicate(
    *,
    field: str,
    kind: str,
    op: str,
    label: str,
    path: str | None = None,
    key: str | None = None,
    value: Any = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    pred = {
        "field": field,
        "kind": kind,
        "op": op,
        "label": label[:180],
    }
    if path:
        pred["path"] = path[:120]
    if key:
        pred["key"] = key[:80]
    if value is not None:
        pred["value"] = _norm(value, limit=120)
    if threshold is not None:
        pred["threshold"] = round(float(threshold), 4)
    pred["id"] = _predicate_id(pred)
    return pred


def _load_json_text(text: str | None) -> Any | None:
    raw = str(text or "").strip()
    if not raw or raw[0] not in "{[":
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _walk_json(obj: Any, *, field: str, path: str = "") -> list[dict[str, Any]]:
    preds: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in sorted(obj.items(), key=lambda item: str(item[0])):
            skey = _norm(key, limit=80).replace(" ", "_")
            if not skey:
                continue
            if skey in VOLATILE_KEYS:
                continue
            child = f"{path}.{skey}" if path else skey
            preds.append(_make_predicate(
                field=field,
                kind="json_key",
                op="exists",
                path=child,
                label=f"{field}.{child} exists",
            ))
            preds.extend(_walk_json(value, field=field, path=child))
    elif isinstance(obj, list):
        if obj:
            preds.append(_make_predicate(
                field=field,
                kind="json_array_nonempty",
                op="exists",
                path=path,
                label=f"{field}.{path} is non-empty",
            ))
        for item in obj[:6]:
            preds.extend(_walk_json(item, field=field, path=path))
    else:
        if path and isinstance(obj, (str, int, float, bool)) and str(obj).strip() != "":
            preds.append(_make_predicate(
                field=field,
                kind="json_value",
                op="eq",
                path=path,
                value=obj,
                label=f"{field}.{path} == {_norm(obj, 80)}",
            ))
    return preds


def _line_key_predicates(text: str | None, *, field: str) -> list[dict[str, Any]]:
    preds: list[dict[str, Any]] = []
    for line in str(text or "").splitlines()[:80]:
        clean = line.strip()
        if not clean:
            continue
        sep = "=" if "=" in clean else (":" if ":" in clean else "")
        if not sep:
            continue
        raw_key, raw_value = clean.split(sep, 1)
        key = _norm(raw_key, 80).replace(" ", "_").strip("-_")
        value = raw_value.strip()
        if not key or len(key) > 80:
            continue
        preds.append(_make_predicate(
            field=field,
            kind="kv_key",
            op="exists",
            key=key,
            label=f"{field} has key {key}",
        ))
        low_value = _norm(value, 80)
        if low_value in {"ok", "success", "validated", "true", "ready", "done"}:
            preds.append(_make_predicate(
                field=field,
                kind="kv_value",
                op="eq",
                key=key,
                value=low_value,
                label=f"{field}.{key} == {low_value}",
            ))
        if "artifact" in key or key.endswith("_path"):
            path = Path(value.strip().strip("'\""))
            if path.exists():
                preds.append(_make_predicate(
                    field=field,
                    kind="artifact_exists",
                    op="exists",
                    key=key,
                    label=f"{field}.{key} artifact exists",
                ))
    return preds


def _field_predicates(text: str | None, *, field: str) -> dict[str, dict[str, Any]]:
    preds: dict[str, dict[str, Any]] = {}
    parsed = _load_json_text(text)
    if parsed is not None:
        for pred in _walk_json(parsed, field=field):
            preds[pred["id"]] = pred
        return preds
    for token in sorted(_tokenize(text))[:80]:
        if token in VOLATILE_KEYS:
            continue
        pred = _make_predicate(
            field=field,
            kind="token",
            op="contains",
            value=token,
            label=f"{field} contains token '{token}'",
        )
        preds[pred["id"]] = pred
    for pred in _line_key_predicates(text, field=field):
        preds[pred["id"]] = pred
    return preds


def _score_predicate(score: float) -> dict[str, Any]:
    threshold = max(0.0, min(1.0, math.floor(float(score) * 20.0) / 20.0))
    return _make_predicate(
        field="score",
        kind="score",
        op="gte",
        threshold=threshold,
        label=f"score >= {threshold:.2f}",
    )


def _success(row: dict[str, Any]) -> bool:
    return bool(row.get("success"))


def _candidate_counts(
    rows: list[dict[str, Any]],
    *,
    field: str,
    include_score: bool = False,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    counts: dict[str, int] = {}
    metas: dict[str, dict[str, Any]] = {}
    for row in rows:
        if field == "input":
            preds = _field_predicates(row.get("input_text"), field="input")
        elif field == "output":
            preds = _field_predicates(row.get("output_text"), field="output")
        else:
            preds = {}
        if include_score:
            pred = _score_predicate(_safe_float(row.get("score")))
            preds[pred["id"]] = pred
        for pid, pred in preds.items():
            counts[pid] = counts.get(pid, 0) + 1
            metas.setdefault(pid, pred)
    return counts, metas


def _select_conditions(
    *,
    positive_counts: dict[str, int],
    negative_counts: dict[str, int],
    metas: dict[str, dict[str, Any]],
    positive_n: int,
    negative_n: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for pid, pos_count in positive_counts.items():
        neg_count = int(negative_counts.get(pid) or 0)
        support = float(pos_count) / max(1, positive_n)
        negative_support = float(neg_count) / max(1, negative_n) if negative_n else 0.0
        precision = float(pos_count) / max(1, pos_count + neg_count)
        delta = support - negative_support
        if support < MIN_SUPPORT:
            continue
        if negative_n and precision < MIN_PRECISION:
            continue
        if negative_n and delta < MIN_DELTA:
            continue
        pred = dict(metas[pid])
        pred.update({
            "support": round(support, 4),
            "negative_support": round(negative_support, 4),
            "precision": round(precision, 4),
            "positive_count": pos_count,
            "negative_count": neg_count,
        })
        selected.append(pred)

    kind_rank = {
        "json_value": 0,
        "json_key": 1,
        "kv_value": 2,
        "kv_key": 3,
        "artifact_exists": 4,
        "score": 5,
        "token": 6,
    }
    selected.sort(
        key=lambda p: (
            float(p.get("precision") or 0.0),
            float(p.get("support") or 0.0),
            -kind_rank.get(str(p.get("kind")), 9),
        ),
        reverse=True,
    )
    return selected[:MAX_CONDITIONS]


def _predicate_holds(
    predicate: dict[str, Any],
    *,
    input_text: str | None = None,
    output_text: str | None = None,
    score: float | None = None,
) -> bool:
    kind = predicate.get("kind")
    if kind == "score":
        return _safe_float(score, -1.0) >= _safe_float(predicate.get("threshold"), 1.0)
    field = str(predicate.get("field") or "")
    text = input_text if field == "input" else output_text
    preds = _field_predicates(text, field=field)
    return str(predicate.get("id") or "") in preds


def verify_contract(
    contract: dict[str, Any],
    *,
    input_text: str | None = None,
    output_text: str | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    preconditions = contract.get("preconditions") if isinstance(contract.get("preconditions"), list) else []
    postconditions = contract.get("postconditions") if isinstance(contract.get("postconditions"), list) else []

    pre = [
        {**p, "holds": _predicate_holds(p, input_text=input_text, output_text=output_text, score=score)}
        for p in preconditions
    ]
    post = [
        {**p, "holds": _predicate_holds(p, input_text=input_text, output_text=output_text, score=score)}
        for p in postconditions
    ]
    pre_ok = all(item["holds"] for item in pre) if pre else False
    post_ok = all(item["holds"] for item in post) if post else False
    return {
        "ok": True,
        "schema": CONTRACT_SCHEMA,
        "pre_ok": pre_ok,
        "post_ok": post_ok,
        "applicable": pre_ok,
        "precondition_results": pre,
        "postcondition_results": post,
        "violations": [p for p in pre + post if not p.get("holds")],
    }


def _quality(contract: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    covered = 0
    covered_success = 0
    covered_failure = 0
    post_violations_on_success = 0
    for row in rows:
        check = verify_contract(
            contract,
            input_text=row.get("input_text"),
            output_text=row.get("output_text"),
            score=_safe_float(row.get("score")),
        )
        if not check.get("pre_ok"):
            continue
        covered += 1
        if _success(row):
            covered_success += 1
            if not check.get("post_ok"):
                post_violations_on_success += 1
        else:
            covered_failure += 1
    return {
        "covered_runs": covered,
        "covered_successes": covered_success,
        "covered_failures": covered_failure,
        "applicability_precision": round(covered_success / max(1, covered), 4) if covered else 0.0,
        "post_violations_on_success": post_violations_on_success,
    }


def induce_contract(procedure: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [r for r in runs if _success(r)]
    negatives = [r for r in runs if not _success(r)]
    procedure_id = int(procedure.get("id") or 0)
    contract = {
        "ok": True,
        "schema": CONTRACT_SCHEMA,
        "contract_id": f"proc_contract_{procedure_id}",
        "procedure_id": procedure_id,
        "procedure_name": procedure.get("name"),
        "domain": procedure.get("domain"),
        "proc_type": procedure.get("proc_type"),
        "created_at": _now(),
        "updated_at": _now(),
        "status": "insufficient_data",
        "positive_runs": len(positives),
        "negative_runs": len(negatives),
        "preconditions": [],
        "postconditions": [],
        "verification": {
            "covered_runs": 0,
            "applicability_precision": 0.0,
        },
        "learning_gap": None,
    }

    if len(positives) < MIN_POSITIVE_RUNS:
        contract["learning_gap"] = {
            "missing": "positive_runs",
            "required": MIN_POSITIVE_RUNS,
            "observed": len(positives),
        }
        return contract

    pre_pos, pre_meta = _candidate_counts(positives, field="input")
    pre_neg, _ = _candidate_counts(negatives, field="input")
    post_pos, post_meta = _candidate_counts(positives, field="output", include_score=True)
    post_neg, _ = _candidate_counts(negatives, field="output", include_score=True)

    contract["preconditions"] = _select_conditions(
        positive_counts=pre_pos,
        negative_counts=pre_neg,
        metas=pre_meta,
        positive_n=len(positives),
        negative_n=len(negatives),
    )
    contract["postconditions"] = _select_conditions(
        positive_counts=post_pos,
        negative_counts=post_neg,
        metas=post_meta,
        positive_n=len(positives),
        negative_n=len(negatives),
    )

    if not contract["preconditions"]:
        contract["learning_gap"] = {
            "missing": "discriminative_preconditions",
            "required": "input predicates with support and precision",
            "observed": "no predicate separates successful runs from failures",
        }
    elif not contract["postconditions"]:
        contract["learning_gap"] = {
            "missing": "verifiable_postconditions",
            "required": "output or score predicates confirmed by successful runs",
            "observed": "no stable postcondition found",
        }
    else:
        contract["status"] = "induced"

    contract["verification"] = _quality(contract, runs)
    if (
        contract["status"] == "induced"
        and len(positives) >= 3
        and float(contract["verification"].get("applicability_precision") or 0.0) >= 0.75
        and int(contract["verification"].get("post_violations_on_success") or 0) == 0
    ):
        contract["status"] = "verified"
    return contract


def _load_contracts() -> dict[str, Any]:
    if PROCEDURAL_CONTRACTS_PATH.exists():
        try:
            data = json.loads(PROCEDURAL_CONTRACTS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("version", 1)
                data.setdefault("contracts", {})
                return data
        except Exception:
            pass
    return {"version": 1, "contracts": {}}


def _save_contracts(data: dict[str, Any]) -> None:
    PROCEDURAL_CONTRACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROCEDURAL_CONTRACTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_contract(procedure_id: int) -> dict[str, Any] | None:
    data = _load_contracts()
    contract = data.get("contracts", {}).get(str(int(procedure_id)))
    return contract if isinstance(contract, dict) else None


def _persist(contract: dict[str, Any]) -> dict[str, Any]:
    data = _load_contracts()
    data.setdefault("contracts", {})[str(int(contract.get("procedure_id") or 0))] = contract
    _save_contracts(data)
    return contract


def _publish(contract: dict[str, Any]) -> None:
    try:
        from ultronpro import store

        payload = json.dumps(contract, ensure_ascii=False, default=str)
        channel = "procedure.contract_gap" if contract.get("status") == "insufficient_data" else "procedure.contract_induced"
        store.publish_workspace(
            module="procedural_induction",
            channel=channel,
            payload_json=payload,
            salience=0.76 if contract.get("status") in {"induced", "verified"} else 0.52,
            ttl_sec=3600,
        )
        event_kind = "procedure.contract_gap" if contract.get("status") == "insufficient_data" else "procedure.contract_induced"
        store.db.add_event(
            event_kind,
            f"procedure contract pid={contract.get('procedure_id')} status={contract.get('status')} pre={len(contract.get('preconditions') or [])} post={len(contract.get('postconditions') or [])}",
            meta_json=payload,
        )
    except Exception:
        pass


def induce_and_persist(procedure_id: int, *, limit: int = 80, publish: bool = True) -> dict[str, Any]:
    from ultronpro import store

    procedure = store.get_procedure(int(procedure_id))
    if not procedure:
        return {"ok": False, "error": "procedure_not_found", "procedure_id": int(procedure_id)}
    runs = store.list_procedure_runs(int(procedure_id), limit=limit)
    contract = induce_contract(procedure, runs)
    existing = load_contract(int(procedure_id))
    if existing:
        contract["created_at"] = existing.get("created_at") or contract["created_at"]
    contract = _persist(contract)
    if publish:
        _publish(contract)
    return contract


def verify_procedure(procedure_id: int, *, input_text: str | None = None, output_text: str | None = None, score: float | None = None) -> dict[str, Any]:
    contract = load_contract(int(procedure_id))
    if not contract:
        return {"ok": False, "error": "contract_not_found", "procedure_id": int(procedure_id)}
    return verify_contract(contract, input_text=input_text, output_text=output_text, score=score)


def score_applicability(procedure_id: int, input_text: str | None) -> dict[str, Any]:
    contract = load_contract(int(procedure_id))
    if not contract:
        return {"ok": True, "available": False, "score": 0.0, "applicable": False}
    checks = verify_contract(contract, input_text=input_text, output_text="", score=0.0)
    pre = checks.get("precondition_results") or []
    held = sum(1 for item in pre if item.get("holds"))
    score = held / max(1, len(pre)) if pre else 0.0
    return {
        "ok": True,
        "available": True,
        "score": round(score, 4),
        "applicable": bool(pre) and held == len(pre),
        "status": contract.get("status"),
    }
