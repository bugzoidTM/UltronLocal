import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"F:\sistemas\UltronPro\backend")


def test_external_factual_classifier_routes_public_role():
    from ultronpro.core.intent import EXTERNAL_FACTUAL_LABEL, classify_external_factual_intent

    decision = classify_external_factual_intent("Quem era o Presidente do Brasil?")

    assert decision.label == EXTERNAL_FACTUAL_LABEL
    assert decision.category in {"external_entity_lookup", "current_world_fact"}
    assert "relation:external_entity" in decision.signals


def test_external_factual_classifier_keeps_self_and_causal_questions_out():
    from ultronpro.core.intent import is_external_factual_intent

    assert not is_external_factual_intent("Quem e voce?")
    assert not is_external_factual_intent("Qual o risco de executar esse comando?")
    assert not is_external_factual_intent("Qual e a versao do UltronPro?")
    assert not is_external_factual_intent("Qual sua opiniao sobre o presidente do Brasil?")


def test_skill_suggestion_uses_web_search_for_external_fact():
    from ultronpro import skill_loader

    skill = skill_loader.suggest_skill("Quem e o presidente do Brasil?")

    assert skill is not None
    assert skill.name == "web_search"


def test_cognitive_response_executes_web_search_for_external_fact():
    from ultronpro import cognitive_response, web_browser

    calls = {"search": 0}
    old_search = web_browser.search_web
    old_fetch = web_browser.fetch_url
    old_trace = cognitive_response.EXTERNAL_FACT_TRACE_PATH

    def fake_search_web(query: str, top_k: int = 5, timeout_sec: float = 10.0):
        calls["search"] += 1
        return {
            "ok": True,
            "query": query,
            "count": 1,
            "items": [
                {
                    "title": "Presidente do Brasil",
                    "url": "https://example.test/presidente",
                    "snippet": "O presidente do Brasil e Luiz Inacio Lula da Silva.",
                }
            ],
        }

    def fake_fetch_url(url: str, max_chars: int = 12000):
        return {
            "ok": True,
            "url": url,
            "title": "Presidente do Brasil",
            "text": "O presidente do Brasil e Luiz Inacio Lula da Silva.",
        }

    try:
        with tempfile.TemporaryDirectory() as td:
            cognitive_response.EXTERNAL_FACT_TRACE_PATH = Path(td) / "external_factual_web_searches.jsonl"
            web_browser.search_web = fake_search_web
            web_browser.fetch_url = fake_fetch_url
            result = cognitive_response.answer("Quem e o presidente do Brasil?")
    finally:
        web_browser.search_web = old_search
        web_browser.fetch_url = old_fetch
        cognitive_response.EXTERNAL_FACT_TRACE_PATH = old_trace

    assert calls["search"] == 1
    assert result["resolved"] is True
    assert result["strategy"] == "web_search_external_factual"
    assert result["evidence_summary"]["web_search_executed"] is True
    assert result["intent_decision"]["label"] == "external_factual"


def test_local_reasoning_does_not_answer_external_fact_from_system_facts():
    from ultronpro import local_reasoning_engine

    result = local_reasoning_engine.resolve("Qual e o nome do presidente do Brasil?")

    assert result["resolved"] is False
    assert result["reason"] == "external_factual_requires_web_search"
