from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ultronpro import cognitive_patches, epistemic_curiosity, source_probe, web_browser
from ultronpro.core.ports import RuntimePorts, default_ports


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RUN_LOG_PATH = DATA_DIR / "trusted_acquisition_runs.jsonl"
STATE_PATH = DATA_DIR / "trusted_acquisition_state.json"
RUN_SCHEMA = "ultron.trusted_acquisition_run.v1"
NEED_SCHEMA = "ultron.acquisition_need.v1"
EXTRACTION_SCHEMA = "ultron.trusted_extraction.v1"

DEFAULT_TRUSTED_DOMAINS = {
    "docs.python.org",
    "developer.mozilla.org",
    "fastapi.tiangolo.com",
    "docs.pydantic.dev",
    "pydantic.dev",
    "docs.pytest.org",
    "pytest.org",
    "docs.github.com",
    "github.com",
    "causal-learn.readthedocs.io",
    "arxiv.org",
    "www.ietf.org",
    "datatracker.ietf.org",
    "nvlpubs.nist.gov",
    "nist.gov",
    "openai.com",
    "platform.openai.com",
    "learn.microsoft.com",
    "microsoft.github.io",
    "networkx.org",
    "numpy.org",
    "pandas.pydata.org",
    "pywhy.org",
    "scikit-learn.org",
    "www.pywhy.org",
    "www.statsmodels.org",
}

TRUSTED_SOURCE_SEEDS = [
    {
        "title": "DoWhy causal modeling documentation",
        "url": "https://www.pywhy.org/dowhy/main/user_guide/modeling_causal_relationships/index.html",
        "terms": ["causal", "causal_graph", "graph", "interventional", "edges", "effect", "model"],
    },
    {
        "title": "causal-learn documentation",
        "url": "https://causal-learn.readthedocs.io/en/latest/",
        "terms": ["causal", "graph", "discovery", "interventional", "edges"],
    },
    {
        "title": "NetworkX directed graph reference",
        "url": "https://networkx.org/documentation/stable/reference/classes/digraph.html",
        "terms": ["graph", "directed", "edges", "nodes", "causal_graph"],
    },
    {
        "title": "FastAPI path operation documentation",
        "url": "https://fastapi.tiangolo.com/tutorial/path-operation-configuration/",
        "terms": ["routing", "api", "endpoint", "validation", "coverage"],
    },
    {
        "title": "pytest documentation",
        "url": "https://docs.pytest.org/en/stable/",
        "terms": ["test", "benchmark", "coverage", "validation", "regression"],
    },
    {
        "title": "Python sqlite3 documentation",
        "url": "https://docs.python.org/3/library/sqlite3.html",
        "terms": ["memory", "digest", "store", "sqlite", "persistence"],
    },
]

CODE_TARGET_TERMS = {
    "adapter",
    "adapters",
    "api",
    "benchmark",
    "code",
    "confidence",
    "endpoint",
    "eval",
    "guard",
    "planner",
    "routing",
    "runtime",
    "sandbox",
    "test",
}

STOPWORDS = {
    "about",
    "across",
    "after",
    "antes",
    "como",
    "com",
    "das",
    "del",
    "dos",
    "entre",
    "from",
    "into",
    "para",
    "pela",
    "pelo",
    "por",
    "que",
    "sem",
    "the",
    "uma",
    "with",
}


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _read_jsonl(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        for line in lines[-max(1, int(limit)) :]:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    except Exception:
        return []


def _clip_text(value: Any, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(1, int(limit))]


def _tokens(text: str, *, min_len: int = 3) -> list[str]:
    out: list[str] = []
    for token in re.findall(r"[a-zA-Z0-9_][a-zA-Z0-9_\-]{2,}", (text or "").lower()):
        t = token.strip("-_")
        if len(t) < min_len or t in STOPWORDS:
            continue
        out.append(t)
    return out


def _unique_tokens(text: str, *, limit: int = 18) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in _tokens(text):
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _hash_dict(value: dict[str, Any], prefix: str) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8', errors='ignore')).hexdigest()[:12]}"


def _domain(url: str) -> str:
    try:
        return (urlparse(str(url or "").strip()).netloc or "").lower().split("@")[-1].split(":")[0]
    except Exception:
        return ""


def _normalize_gap(gap: Any) -> dict[str, Any]:
    if gap is None:
        return {}
    if isinstance(gap, dict):
        return dict(gap)
    if is_dataclass(gap):
        try:
            return asdict(gap)
        except Exception:
            pass
    out: dict[str, Any] = {}
    for key in ("id", "label", "domain", "metric", "priority", "evidence", "next_experiment"):
        try:
            value = getattr(gap, key)
        except Exception:
            continue
        out[key] = value
    return out


def trusted_domains() -> list[str]:
    configured = str(os.getenv("ULTRON_TRUSTED_SOURCE_DOMAINS", "") or "")
    values = set(DEFAULT_TRUSTED_DOMAINS)
    for chunk in re.split(r"[,;\s]+", configured):
        item = chunk.strip().lower()
        if item:
            values.add(item)
    return sorted(values)


def source_is_trusted(url: str, allowed_domains: list[str] | set[str] | None = None) -> bool:
    dom = _domain(url)
    if not dom:
        return False
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https":
        return False
    allowed = set(allowed_domains or trusted_domains())
    return any(dom == item or dom.endswith("." + item) for item in allowed)


def source_score(url: str, allowed_domains: list[str] | set[str] | None = None) -> float:
    dom = _domain(url)
    if not dom:
        return 0.0
    allowed = set(allowed_domains or trusted_domains())
    matched = [item for item in allowed if dom == item or dom.endswith("." + item)]
    if not matched:
        return 0.0
    score = 0.90 if dom in allowed else 0.78
    if str(url or "").startswith("https://"):
        score += 0.08
    if dom.endswith(".gov") or dom.endswith(".edu") or dom in {"arxiv.org", "www.ietf.org", "datatracker.ietf.org"}:
        score += 0.02
    return round(min(1.0, score), 4)


def _application_target(gap: dict[str, Any]) -> str:
    text = " ".join(
        str(gap.get(key) or "")
        for key in ("id", "label", "domain", "metric", "next_experiment")
    ).lower()
    tokens = set(_tokens(text, min_len=3))
    if tokens.intersection(CODE_TARGET_TERMS):
        return "code_patch_proposal"
    evidence = gap.get("evidence") if isinstance(gap.get("evidence"), dict) else {}
    if any(str(k).lower() in CODE_TARGET_TERMS for k in evidence.keys()):
        return "code_patch_proposal"
    return "knowledge"


def _fallback_need() -> dict[str, Any]:
    raw = {
        "id": "need_epistemic_gap_scan",
        "label": "Nenhuma lacuna priorizada foi encontrada; verificar cobertura epistemica recente",
        "domain": "metacognition",
        "metric": "gap_scan_empty",
        "priority": 0.3,
        "evidence": {"reason": "collect_epistemic_gaps_empty"},
        "next_experiment": "Buscar documentacao confiavel sobre avaliacao de lacunas epistemicas e aplicar como criterio de memoria.",
    }
    return _need_from_gap(raw, rank=1, total_candidates=0)


def _need_from_gap(gap: dict[str, Any], *, rank: int, total_candidates: int) -> dict[str, Any]:
    gap_id = _clip_text(gap.get("id") or f"gap_{rank}", 120)
    label = _clip_text(gap.get("label") or gap_id, 260)
    domain = _clip_text(gap.get("domain") or "general", 120)
    metric = _clip_text(gap.get("metric") or "unknown_metric", 120)
    next_experiment = _clip_text(gap.get("next_experiment") or "", 500)
    evidence = gap.get("evidence") if isinstance(gap.get("evidence"), dict) else {}
    basis = " ".join([gap_id, label, domain, metric, next_experiment])
    terms = _unique_tokens(basis, limit=16)
    target = _application_target(gap)
    need = {
        "schema": NEED_SCHEMA,
        "id": gap_id,
        "label": label,
        "domain": domain,
        "metric": metric,
        "priority": round(float(gap.get("priority") or 0.0), 4),
        "rank": int(rank),
        "total_candidates": int(total_candidates),
        "evidence": evidence,
        "next_experiment": next_experiment,
        "need_terms": terms,
        "search_query": build_search_query({
            "id": gap_id,
            "label": label,
            "domain": domain,
            "metric": metric,
            "next_experiment": next_experiment,
            "need_terms": terms,
        }),
        "application_target": target,
        "decision_rule": "highest_epistemic_gap_priority_then_stable_id",
    }
    need["need_id"] = _hash_dict(need, "need")
    return need


def build_search_query(need: dict[str, Any]) -> str:
    terms = list(need.get("need_terms") or [])
    if not terms:
        terms = _unique_tokens(
            " ".join(str(need.get(k) or "") for k in ("label", "domain", "metric", "next_experiment")),
            limit=12,
        )
    selected = terms[:8]
    domain = str(need.get("domain") or "").strip()
    suffix = "documentation reliable source"
    if domain:
        selected.insert(0, domain)
    query = " ".join(x for x in selected if x)
    return _clip_text(f"{query} {suffix}", 240)


def decide_need(target_gap_id: str | None = None, *, use_cache: bool = False) -> dict[str, Any]:
    try:
        raw_gaps = epistemic_curiosity.collect_epistemic_gaps(use_cache=use_cache)
    except Exception as exc:
        raw_gaps = []
        error = str(exc)[:240]
    else:
        error = ""

    gaps = [_normalize_gap(item) for item in raw_gaps]
    gaps = [gap for gap in gaps if gap.get("id") or gap.get("label")]
    if target_gap_id:
        wanted = str(target_gap_id).strip()
        gaps = [gap for gap in gaps if str(gap.get("id") or "") == wanted]

    if not gaps:
        need = _fallback_need()
        if error:
            need["decision_error"] = error
        return need

    gaps.sort(key=lambda item: (-float(item.get("priority") or 0.0), str(item.get("id") or ""), str(item.get("label") or "")))
    return _need_from_gap(gaps[0], rank=1, total_candidates=len(gaps))


def find_trusted_sources(need: dict[str, Any], *, top_k: int = 5, allowed_domains: list[str] | None = None) -> dict[str, Any]:
    query = str(need.get("search_query") or build_search_query(need)).strip()
    allowed = allowed_domains or trusted_domains()
    try:
        search = web_browser.search_web(query, top_k=max(1, min(10, int(top_k or 5))))
    except Exception as exc:
        search = {"ok": False, "error": str(exc)[:240], "items": []}

    trusted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for index, item in enumerate(search.get("items") if isinstance(search.get("items"), list) else []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        dom = _domain(url)
        if source_is_trusted(url, allowed):
            seen_urls.add(url)
            score = source_score(url, allowed)
            trusted.append({
                "rank": index + 1,
                "title": _clip_text(item.get("title"), 240),
                "url": url,
                "domain": dom,
                "snippet": _clip_text(item.get("snippet"), 500),
                "source_score": score,
                "trusted_reason": "domain_whitelist_https",
            })
        else:
            rejected.append({
                "rank": index + 1,
                "title": _clip_text(item.get("title"), 160),
                "url": url,
                "domain": dom,
                "reason": "domain_not_in_trusted_whitelist_or_non_https",
            })

    trusted.extend(_seed_source_candidates(need, allowed, seen_urls=seen_urls))
    trusted.sort(key=lambda item: (-float(item.get("source_score") or 0.0), int(item.get("rank") or 999)))
    return {
        "ok": bool(search.get("ok")) and bool(trusted),
        "query": query,
        "trusted_domains": allowed,
        "trusted": trusted,
        "rejected": rejected[:10],
        "search_ok": bool(search.get("ok")),
        "search_error": search.get("error"),
    }


def _seed_source_candidates(need: dict[str, Any], allowed: list[str], *, seen_urls: set[str]) -> list[dict[str, Any]]:
    need_terms = set(str(x).lower() for x in (need.get("need_terms") or []) if str(x).strip())
    if not need_terms:
        need_terms = set(_tokens(" ".join(str(need.get(k) or "") for k in ("id", "label", "domain", "metric", "next_experiment"))))
    out: list[dict[str, Any]] = []
    for index, seed in enumerate(TRUSTED_SOURCE_SEEDS):
        url = str(seed.get("url") or "")
        if not url or url in seen_urls or not source_is_trusted(url, allowed):
            continue
        seed_terms = set(str(x).lower() for x in (seed.get("terms") or []) if str(x).strip())
        seed_terms.update(_tokens(str(seed.get("title") or "")))
        overlap = sorted(need_terms.intersection(seed_terms))
        if not overlap:
            continue
        base_score = source_score(url, allowed)
        overlap_score = min(0.10, len(overlap) / max(1, len(need_terms)) * 0.20)
        out.append({
            "rank": 1000 + index,
            "title": _clip_text(seed.get("title"), 240),
            "url": url,
            "domain": _domain(url),
            "snippet": f"seeded trusted source; matched terms: {', '.join(overlap[:8])}",
            "source_score": round(min(1.0, base_score + overlap_score), 4),
            "trusted_reason": "trusted_seed_catalog_term_overlap",
            "matched_terms": overlap[:12],
        })
        seen_urls.add(url)
    return out


def _sentence_score(sentence: str, need_terms: set[str]) -> float:
    sentence_tokens = set(_tokens(sentence))
    if not sentence_tokens or not need_terms:
        return 0.0
    overlap = sentence_tokens.intersection(need_terms)
    density = len(overlap) / max(1, len(need_terms))
    length_bonus = 0.08 if 80 <= len(sentence) <= 360 else 0.0
    source_hint_bonus = 0.05 if any(x in sentence.lower() for x in ("should", "must", "recommended", "guide", "example", "use")) else 0.0
    return round(min(1.0, density + length_bonus + source_hint_bonus), 4)


def extract_useful_content(need: dict[str, Any], source: dict[str, Any], *, max_chars: int = 10000, max_points: int = 5) -> dict[str, Any]:
    url = str(source.get("url") or "")
    fetched = source_probe.fetch_clean_text(url, max_chars=max_chars)
    if not bool(fetched.get("ok")):
        return {
            "schema": EXTRACTION_SCHEMA,
            "ok": False,
            "url": url,
            "source": source,
            "error": fetched.get("error") or "fetch_failed",
            "useful": False,
            "key_points": [],
            "confidence": 0.0,
        }

    text = str(fetched.get("text") or "")
    title = _clip_text(fetched.get("title") or source.get("title") or "", 240)
    need_terms = set(str(x).lower() for x in (need.get("need_terms") or []) if str(x).strip())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) >= 35]
    scored: list[tuple[float, str]] = []
    for sentence in sentences[:300]:
        score = _sentence_score(sentence, need_terms)
        if score > 0:
            scored.append((score, _clip_text(sentence, 420)))
    scored.sort(key=lambda item: (-item[0], item[1]))

    key_points: list[dict[str, Any]] = []
    seen: set[str] = set()
    for score, sentence in scored:
        fp = hashlib.sha1(sentence.lower().encode("utf-8", errors="ignore")).hexdigest()[:10]
        if fp in seen:
            continue
        seen.add(fp)
        key_points.append({"score": score, "text": sentence})
        if len(key_points) >= max(1, int(max_points)):
            break

    best_score = max([float(item["score"]) for item in key_points], default=0.0)
    coverage = len(key_points) / max(1, int(max_points))
    confidence = round(min(0.95, (0.62 * best_score) + (0.23 * coverage) + (0.15 * float(source.get("source_score") or 0.0))), 4)
    useful = bool(key_points) and confidence >= 0.22
    summary = " ".join(str(item.get("text") or "") for item in key_points[:2])
    if not summary and text:
        summary = _clip_text(text, 700)

    return {
        "schema": EXTRACTION_SCHEMA,
        "ok": True,
        "useful": useful,
        "url": str(fetched.get("url") or url),
        "title": title,
        "domain": _domain(str(fetched.get("url") or url)),
        "source": source,
        "status_code": int(fetched.get("status_code") or 0),
        "text_chars": int(fetched.get("text_chars") or len(text)),
        "need_terms_matched": sorted(set().union(*(set(_tokens(item["text"])).intersection(need_terms) for item in key_points)))[:20],
        "key_points": key_points,
        "summary": _clip_text(summary, 1000),
        "confidence": confidence,
        "extraction_rule": "sentence_overlap_with_need_terms_plus_trusted_source_score",
    }


def extract_from_sources(need: dict[str, Any], sources: list[dict[str, Any]], *, max_sources: int = 3) -> dict[str, Any]:
    extractions: list[dict[str, Any]] = []
    for source in sources[: max(1, int(max_sources or 3))]:
        extractions.append(extract_useful_content(need, source))
    useful = [item for item in extractions if bool(item.get("useful"))]
    useful.sort(key=lambda item: (-float(item.get("confidence") or 0.0), str(item.get("url") or "")))
    return {
        "ok": bool(useful),
        "extractions": extractions,
        "useful": useful,
        "best": useful[0] if useful else {},
    }


def _patch_kind_for_need(need: dict[str, Any]) -> str:
    text = " ".join(str(need.get(k) or "") for k in ("id", "label", "domain", "metric", "next_experiment")).lower()
    if "routing" in text or "route" in text or "adapter" in text:
        return "routing_patch"
    if "confidence" in text or "calibr" in text or "uncertain" in text or "unknown" in text:
        return "confidence_patch"
    if "planner" in text or "plan" in text:
        return "planner_patch"
    return "heuristic_patch"


def _apply_knowledge(need: dict[str, Any], extraction: dict[str, Any], *, ports: RuntimePorts | None = None) -> dict[str, Any]:
    ports = ports or default_ports()
    source_url = str(extraction.get("url") or "")
    source_id = f"trusted:{_domain(source_url) or 'unknown'}:{hashlib.sha1(source_url.encode('utf-8', errors='ignore')).hexdigest()[:10]}"
    title = _clip_text(f"Trusted acquisition: {need.get('label')}", 180)
    text = _clip_text(
        "\n".join([
            f"Need: {need.get('label')}",
            f"Domain: {need.get('domain')}",
            f"Metric: {need.get('metric')}",
            f"Source: {source_url}",
            f"Summary: {extraction.get('summary')}",
        ]),
        2400,
    )
    meta = {
        "schema": RUN_SCHEMA,
        "need_id": need.get("need_id"),
        "gap_id": need.get("id"),
        "source_url": source_url,
        "source_score": (extraction.get("source") or {}).get("source_score"),
        "confidence": extraction.get("confidence"),
        "key_points": extraction.get("key_points"),
    }
    exp_id = None
    insight_id = None
    event_id = None
    try:
        exp_id = ports.memory.add_experience(text=text, source_id=source_id, modality="trusted_web")
    except Exception as exc:
        meta["experience_error"] = str(exc)[:200]
    try:
        insight_id = ports.memory.add_insight(
            kind="trusted_acquisition",
            title=title,
            text=text,
            priority=2 if float(need.get("priority") or 0.0) >= 0.7 else 3,
            source_id=source_id,
            meta=meta,
        )
    except Exception as exc:
        meta["insight_error"] = str(exc)[:200]
    try:
        event_id = ports.events.add_event(
            "trusted_acquisition.applied_knowledge",
            f"trusted acquisition applied knowledge for gap {need.get('id')}",
            meta=meta,
        )
    except Exception:
        event_id = None
    try:
        ports.workspace.publish(
            "trusted_acquisition",
            "trusted_acquisition.applied_knowledge",
            {
                "need": need,
                "source_url": source_url,
                "confidence": extraction.get("confidence"),
                "insight_id": insight_id,
                "experience_id": exp_id,
            },
            salience=0.74,
            ttl_sec=3600,
        )
    except Exception:
        pass
    return {
        "ok": bool(exp_id or insight_id or event_id),
        "mode": "knowledge",
        "source_id": source_id,
        "experience_id": exp_id,
        "insight_id": insight_id,
        "event_id": event_id,
    }


def _apply_patch_proposal(need: dict[str, Any], extraction: dict[str, Any], *, ports: RuntimePorts | None = None) -> dict[str, Any]:
    ports = ports or default_ports()
    source_url = str(extraction.get("url") or "")
    evidence_ref = f"trusted_acquisition:{need.get('id')}:{hashlib.sha1(source_url.encode('utf-8', errors='ignore')).hexdigest()[:10]}"
    patch = cognitive_patches.create_patch({
        "kind": _patch_kind_for_need(need),
        "source": "trusted_acquisition_loop",
        "problem_pattern": _clip_text(need.get("label"), 300),
        "hypothesis": _clip_text(
            f"Trusted source evidence can reduce gap {need.get('id')} by updating {need.get('application_target')}. "
            f"Evidence summary: {extraction.get('summary')}",
            1200,
        ),
        "proposed_change": {
            "change_type": "evidence_grounded_cognitive_patch",
            "gap_id": need.get("id"),
            "domain": need.get("domain"),
            "metric": need.get("metric"),
            "source_url": source_url,
            "source_domain": extraction.get("domain"),
            "key_points": extraction.get("key_points"),
            "acceptance": "shadow_eval must improve target metric without domain regression before promotion",
        },
        "expected_gain": _clip_text(f"Reduce epistemic gap on {need.get('metric')} using trusted evidence.", 800),
        "risk_level": "medium",
        "status": "proposed",
        "evidence_refs": [evidence_ref],
        "tags": ["trusted_acquisition", str(need.get("domain") or "general")[:60]],
        "notes": "Generated deterministically from trusted source extraction; no LLM used.",
    })
    try:
        ports.events.add_event(
            "trusted_acquisition.patch_proposed",
            f"trusted acquisition proposed cognitive patch {patch.get('id')}",
            meta={"need": need, "patch_id": patch.get("id"), "source_url": source_url},
        )
    except Exception:
        pass
    try:
        ports.workspace.publish(
            "trusted_acquisition",
            "trusted_acquisition.patch_proposed",
            {"need": need, "patch": patch, "source_url": source_url},
            salience=0.80,
            ttl_sec=3600,
        )
    except Exception:
        pass
    return {
        "ok": bool(patch.get("id")),
        "mode": "code_patch_proposal",
        "patch_id": patch.get("id"),
        "patch_status": patch.get("status"),
        "patch_kind": patch.get("kind"),
    }


def apply_extraction(need: dict[str, Any], extraction: dict[str, Any], *, mode: str = "auto", ports: RuntimePorts | None = None) -> dict[str, Any]:
    if not extraction or not bool(extraction.get("useful")):
        return {"ok": False, "mode": "none", "reason": "no_useful_extraction"}
    selected = str(mode or "auto").strip().lower()
    if selected == "auto":
        selected = str(need.get("application_target") or "knowledge")
    if selected in {"patch", "code", "code_patch", "code_patch_proposal"}:
        return _apply_patch_proposal(need, extraction, ports=ports)
    return _apply_knowledge(need, extraction, ports=ports)


def run_once(
    *,
    target_gap_id: str | None = None,
    top_k: int = 5,
    max_sources: int = 3,
    apply: bool = True,
    application_mode: str = "auto",
    allowed_domains: list[str] | None = None,
    ports: RuntimePorts | None = None,
) -> dict[str, Any]:
    started = _now()
    need = decide_need(target_gap_id=target_gap_id, use_cache=False)
    source_report = find_trusted_sources(need, top_k=top_k, allowed_domains=allowed_domains)
    extraction_report = extract_from_sources(need, source_report.get("trusted") or [], max_sources=max_sources)
    application = {"ok": False, "mode": "none", "reason": "apply_disabled" if not apply else "no_useful_extraction"}
    if apply and extraction_report.get("best"):
        application = apply_extraction(need, extraction_report["best"], mode=application_mode, ports=ports)

    result = {
        "schema": RUN_SCHEMA,
        "ok": bool(source_report.get("trusted")) and bool(extraction_report.get("ok")) and (not apply or bool(application.get("ok"))),
        "ts": started,
        "duration_ms": int((time.time() - started) * 1000),
        "run_id": "",
        "phases": ["decide_need", "trusted_sources", "extraction", "application"],
        "non_llm": True,
        "decision": {"need": need},
        "sources": source_report,
        "extraction": extraction_report,
        "application": application,
        "gaps_remaining": [] if application.get("ok") else ["trusted_source_missing_or_no_useful_content"],
    }
    result["run_id"] = _hash_dict({
        "ts": started,
        "need_id": need.get("need_id"),
        "source_urls": [item.get("url") for item in source_report.get("trusted", [])],
        "application": application,
    }, "ta")

    _append_jsonl(RUN_LOG_PATH, result)
    _write_json(STATE_PATH, {
        "schema": RUN_SCHEMA,
        "last_run_id": result["run_id"],
        "last_ts": started,
        "last_ok": result["ok"],
        "last_need": need,
        "last_application": application,
        "last_gaps_remaining": result["gaps_remaining"],
    })
    return result


def status(limit: int = 20) -> dict[str, Any]:
    runs = _read_jsonl(RUN_LOG_PATH, limit=limit)
    state = _read_json(STATE_PATH, {})
    return {
        "ok": True,
        "schema": RUN_SCHEMA,
        "state": state if isinstance(state, dict) else {},
        "trusted_domains": trusted_domains(),
        "recent_runs": runs,
        "count": len(runs),
    }


def run_selftest() -> dict[str, Any]:
    need = {
        "schema": NEED_SCHEMA,
        "id": "selftest_gap",
        "label": "Selftest trusted acquisition extraction",
        "domain": "routing",
        "metric": "coverage",
        "priority": 0.9,
        "need_terms": ["routing", "coverage", "trusted", "source"],
        "search_query": "routing coverage trusted source documentation",
        "application_target": "code_patch_proposal",
    }
    source = {
        "rank": 1,
        "title": "Docs",
        "url": "https://docs.python.org/3/library/urllib.parse.html",
        "domain": "docs.python.org",
        "snippet": "trusted source routing coverage",
        "source_score": 1.0,
    }
    trusted_ok = source_is_trusted(source["url"])
    extraction = {
        "schema": EXTRACTION_SCHEMA,
        "ok": True,
        "useful": True,
        "url": source["url"],
        "domain": source["domain"],
        "source": source,
        "key_points": [{"score": 0.8, "text": "Routing coverage should be validated against trusted source evidence."}],
        "summary": "Routing coverage should be validated against trusted source evidence.",
        "confidence": 0.8,
    }
    return {
        "ok": trusted_ok and bool(need.get("search_query")) and bool(extraction.get("useful")),
        "non_llm": True,
        "trusted_source_filter": trusted_ok,
        "need": need,
        "extraction": extraction,
    }
