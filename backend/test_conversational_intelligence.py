import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


@contextmanager
def isolated_identity(tmp_path):
    from ultronpro import biographic_digest, cognitive_response, self_model, store

    old_self_path = self_model.PATH
    old_store_db = store.db
    old_store_db_path = store.DB_PATH
    old_digest_path = biographic_digest.DIGEST_PATH
    old_biography_path = biographic_digest.BIOGRAPHY_PATH
    old_investigation_log = biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH
    old_trace = cognitive_response.TRACE_PATH
    old_external_trace = cognitive_response.EXTERNAL_FACT_TRACE_PATH
    old_engine = cognitive_response._ENGINE

    created_at = 1_700_000_000
    self_model.PATH = tmp_path / "self_model.json"
    store.DB_PATH = str(tmp_path / "ultron.db")
    store.db = store.Store(store.DB_PATH)
    biographic_digest.DIGEST_PATH = tmp_path / "biographic_digest.json"
    biographic_digest.BIOGRAPHY_PATH = tmp_path / "biography.jsonl"
    biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH = tmp_path / "active_investigations.jsonl"
    cognitive_response.TRACE_PATH = tmp_path / "cognitive_response_traces.jsonl"
    cognitive_response.EXTERNAL_FACT_TRACE_PATH = tmp_path / "external_fact_traces.jsonl"
    cognitive_response._ENGINE = None

    self_model.PATH.write_text(
        json.dumps(
            {
                "created_at": created_at,
                "updated_at": created_at,
                "identity": {
                    "name": "UltronPro",
                    "role": "agente cognitivo autonomo de teste",
                    "mission": "aprender com evidencia",
                    "origin": "laboratorio UltronPro",
                    "creator": "usuario e equipe de pesquisa",
                    "creator_name": "",
                    "foundational_context": "self-model temporario com origem verificavel",
                },
                "capabilities": [],
                "limits": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store.db.add_event("boot", "primeiro evento operacional do teste")

    try:
        yield created_at
    finally:
        self_model.PATH = old_self_path
        store.db = old_store_db
        store.DB_PATH = old_store_db_path
        biographic_digest.DIGEST_PATH = old_digest_path
        biographic_digest.BIOGRAPHY_PATH = old_biography_path
        biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH = old_investigation_log
        cognitive_response.TRACE_PATH = old_trace
        cognitive_response.EXTERNAL_FACT_TRACE_PATH = old_external_trace
        cognitive_response._ENGINE = old_engine


def test_fuzzy_greeting_typo_routes_to_smalltalk():
    from ultronpro.main import _classify_query_type, _quick_smalltalk_intent

    assert _quick_smalltalk_intent("olár") == "greeting"
    assert _classify_query_type("olár") == "greeting"


def test_stream_greeting_typo_does_not_emit_internal_progress():
    from fastapi.testclient import TestClient
    from ultronpro.main import app

    client = TestClient(app)
    response = client.post("/api/chat/stream", json={"message": "olár"})
    events = []
    for chunk in response.text.split("\n\n"):
        if not chunk.startswith("data: "):
            continue
        events.append(json.loads(chunk[6:]))

    progress = [event for event in events if event.get("type") == "progress"]
    done = next(event for event in events if event.get("type") == "done")
    assert progress == []
    assert done["strategy"] == "intent_greeting"


def test_identity_question_is_concise_not_diagnostic(tmp_path):
    from ultronpro import cognitive_response

    with isolated_identity(tmp_path):
        result = cognitive_response.answer("Quem e voce?")

    answer = result["answer"]
    assert result["resolved"] is True
    assert result["strategy"] == "non_llm_autobiographical_identity"
    assert "Sou o UltronPro" in answer
    assert "Incerteza registrada" not in answer
    assert "Evidencia acumulada" not in answer
    assert "Narrativa biografica" not in answer
    assert "benchmarks" not in answer.lower()


def test_birth_date_variant_stays_autobiographical_not_web(tmp_path):
    from ultronpro import cognitive_response
    from ultronpro.core.intent import classify_autobiographical_intent, classify_external_factual_intent

    with isolated_identity(tmp_path) as created_at:
        decision = classify_autobiographical_intent("qual sua data de nascimento?")
        external = classify_external_factual_intent("qual sua data de nascimento?")
        result = cognitive_response.answer("qual sua data de nascimento?")

    expected_day = time.strftime("%Y-%m-%d", time.localtime(created_at))
    assert decision.label == "autobiographical"
    assert decision.category == "creation"
    assert external.label != "external_factual"
    assert result["strategy"] == "non_llm_autobiographical_creation"
    assert expected_day in result["answer"]
    assert "web_search" not in result["strategy"]


def test_creator_name_question_uses_self_model_without_fabricating_name(tmp_path):
    from ultronpro import cognitive_response
    from ultronpro.core.intent import classify_autobiographical_intent

    with isolated_identity(tmp_path):
        decision = classify_autobiographical_intent("Nao sabe o nome do seu criador?")
        result = cognitive_response.answer("Nao sabe o nome do seu criador?")

    answer = result["answer"]
    assert decision.label == "autobiographical"
    assert decision.category == "creation"
    assert result["strategy"] == "non_llm_autobiographical_creation"
    assert "usuario e equipe de pesquisa" in answer
    assert "nome proprio individual" in answer


def test_llm_model_question_uses_runtime_config_not_skill(tmp_path):
    from ultronpro import cognitive_response
    from ultronpro.core.intent import classify_autobiographical_intent

    with isolated_identity(tmp_path):
        decision = classify_autobiographical_intent("Qual LLM vc usa?")
        result = cognitive_response.answer("Qual LLM vc usa?")

    assert decision.label == "autobiographical"
    assert decision.category == "capability"
    assert result["resolved"] is True
    assert result["strategy"] == "non_llm_runtime_model"
    assert "unico LLM" in result["answer"]
    assert "estrategia configurada" in result["answer"]


def test_agi_identity_question_stays_self_route_not_rag(tmp_path):
    from ultronpro import cognitive_response
    from ultronpro.core.intent import classify_autobiographical_intent, classify_external_factual_intent

    with isolated_identity(tmp_path):
        decision = classify_autobiographical_intent("voce e AGI?")
        external = classify_external_factual_intent("voce e AGI?")
        result = cognitive_response.answer("voce e AGI?")

    assert decision.label == "autobiographical"
    assert decision.category == "identity"
    assert external.label != "external_factual"
    assert result["resolved"] is True
    assert result["strategy"] == "non_llm_agi_identity"
    assert "LLMs como ferramentas" in result["answer"]
    assert "Agrilus" not in result["answer"]
