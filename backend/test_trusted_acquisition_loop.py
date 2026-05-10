import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _gap(gap_id: str, priority: float, domain: str = "routing"):
    return SimpleNamespace(
        id=gap_id,
        label=f"{domain} coverage gap",
        domain=domain,
        metric="coverage_delta",
        priority=priority,
        evidence={"route": "test"},
        next_experiment=f"Find trusted documentation for {domain} coverage",
    )


def test_decides_highest_priority_need_without_llm(monkeypatch):
    from ultronpro import trusted_acquisition_loop as loop

    monkeypatch.setattr(
        loop.epistemic_curiosity,
        "collect_epistemic_gaps",
        lambda use_cache=False: [_gap("low_gap", 0.2), _gap("router_gap", 0.91)],
    )

    need = loop.decide_need()

    assert need["schema"] == loop.NEED_SCHEMA
    assert need["id"] == "router_gap"
    assert need["priority"] == 0.91
    assert need["application_target"] == "code_patch_proposal"
    assert "routing" in need["search_query"]
    assert need["decision_rule"] == "highest_epistemic_gap_priority_then_stable_id"


def test_filters_trusted_sources_and_extracts_useful_content(monkeypatch):
    from ultronpro import trusted_acquisition_loop as loop

    need = {
        "id": "memory_gap",
        "label": "episodic memory consolidation gap",
        "domain": "memory",
        "metric": "digest_coverage",
        "need_terms": ["episodic", "memory", "consolidation", "digest"],
        "search_query": "episodic memory consolidation digest documentation",
        "application_target": "knowledge",
    }
    monkeypatch.setattr(
        loop.web_browser,
        "search_web",
        lambda query, top_k=5: {
            "ok": True,
            "items": [
                {"title": "Random blog", "url": "https://example.net/nope", "snippet": "some post"},
                {
                    "title": "Python docs",
                    "url": "https://docs.python.org/3/library/sqlite3.html",
                    "snippet": "episodic memory consolidation digest",
                },
            ],
        },
    )
    monkeypatch.setattr(
        loop.source_probe,
        "fetch_clean_text",
        lambda url, max_chars=10000: {
            "ok": True,
            "url": url,
            "title": "Trusted docs",
            "status_code": 200,
            "text": (
                "Episodic memory consolidation should record a durable digest after new evidence. "
                "The digest is useful when memory coverage changes and later retrieval needs source evidence."
            ),
            "text_chars": 170,
        },
    )

    sources = loop.find_trusted_sources(need, allowed_domains=["docs.python.org"])
    extracted = loop.extract_from_sources(need, sources["trusted"])

    assert sources["ok"] is True
    assert len(sources["trusted"]) == 1
    assert sources["trusted"][0]["domain"] == "docs.python.org"
    assert sources["rejected"][0]["domain"] == "example.net"
    assert extracted["ok"] is True
    assert extracted["best"]["useful"] is True
    assert "episodic" in extracted["best"]["need_terms_matched"]


def test_run_once_applies_patch_proposal_without_llm(tmp_path, monkeypatch):
    from ultronpro import trusted_acquisition_loop as loop
    from ultronpro.core.ports import recording_ports

    monkeypatch.setattr(loop, "RUN_LOG_PATH", tmp_path / "trusted_acquisition_runs.jsonl")
    monkeypatch.setattr(loop, "STATE_PATH", tmp_path / "trusted_acquisition_state.json")
    monkeypatch.setattr(loop.epistemic_curiosity, "collect_epistemic_gaps", lambda use_cache=False: [_gap("routing_gap", 0.88)])
    monkeypatch.setattr(
        loop.web_browser,
        "search_web",
        lambda query, top_k=5: {
            "ok": True,
            "items": [
                {
                    "title": "FastAPI docs",
                    "url": "https://fastapi.tiangolo.com/tutorial/path-operation-configuration/",
                    "snippet": "routing coverage documentation",
                }
            ],
        },
    )
    monkeypatch.setattr(
        loop.source_probe,
        "fetch_clean_text",
        lambda url, max_chars=10000: {
            "ok": True,
            "url": url,
            "title": "FastAPI docs",
            "status_code": 200,
            "text": (
                "Routing coverage should use explicit route metadata and validation evidence. "
                "Trusted documentation examples are useful when a patch changes routing behavior."
            ),
            "text_chars": 160,
        },
    )

    created_payloads = []
    monkeypatch.setattr(
        loop.cognitive_patches,
        "create_patch",
        lambda payload: created_payloads.append(payload) or {"id": "cp_test", "status": "proposed", "kind": payload["kind"]},
    )
    ports, events, workspace, _ = recording_ports()

    result = loop.run_once(allowed_domains=["fastapi.tiangolo.com"], apply=True, ports=ports)

    assert result["ok"] is True
    assert result["non_llm"] is True
    assert result["phases"] == ["decide_need", "trusted_sources", "extraction", "application"]
    assert result["application"]["mode"] == "code_patch_proposal"
    assert result["application"]["patch_id"] == "cp_test"
    assert created_payloads[0]["source"] == "trusted_acquisition_loop"
    assert created_payloads[0]["status"] == "proposed"
    assert "no LLM used" in created_payloads[0]["notes"]
    assert events.rows[0]["kind"] == "trusted_acquisition.patch_proposed"
    assert workspace.rows[0]["channel"] == "trusted_acquisition.patch_proposed"


def test_run_once_applies_knowledge_when_gap_is_not_code(tmp_path, monkeypatch):
    from ultronpro import trusted_acquisition_loop as loop
    from ultronpro.core.ports import recording_ports

    memory_gap = _gap("digest_gap", 0.84, domain="memory")
    monkeypatch.setattr(loop, "RUN_LOG_PATH", tmp_path / "trusted_acquisition_runs.jsonl")
    monkeypatch.setattr(loop, "STATE_PATH", tmp_path / "trusted_acquisition_state.json")
    monkeypatch.setattr(loop.epistemic_curiosity, "collect_epistemic_gaps", lambda use_cache=False: [memory_gap])
    monkeypatch.setattr(
        loop.web_browser,
        "search_web",
        lambda query, top_k=5: {
            "ok": True,
            "items": [
                {
                    "title": "Python docs",
                    "url": "https://docs.python.org/3/library/json.html",
                    "snippet": "memory digest coverage trusted source",
                }
            ],
        },
    )
    monkeypatch.setattr(
        loop.source_probe,
        "fetch_clean_text",
        lambda url, max_chars=10000: {
            "ok": True,
            "url": url,
            "title": "Python docs",
            "status_code": 200,
            "text": (
                "Memory coverage should preserve a digest after trusted source evidence is collected. "
                "The digest coverage metric can be improved when useful source evidence is stored."
            ),
            "text_chars": 165,
        },
    )
    ports, events, workspace, memory = recording_ports()

    result = loop.run_once(allowed_domains=["docs.python.org"], apply=True, ports=ports)

    assert result["ok"] is True
    assert result["decision"]["need"]["application_target"] == "knowledge"
    assert result["application"]["mode"] == "knowledge"
    assert result["application"]["experience_id"] == 1
    assert result["application"]["insight_id"] == 1
    assert memory.experiences[0]["modality"] == "trusted_web"
    assert events.rows[0]["kind"] == "trusted_acquisition.applied_knowledge"
    assert workspace.rows[0]["channel"] == "trusted_acquisition.applied_knowledge"
