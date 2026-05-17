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


def _fake_causal_gap_response():
    return {
        "ok": True,
        "resolved": True,
        "answer": (
            "Encontrei cobertura direta insuficiente, mas nao vou parar em UNKNOWN: "
            "transferi um prior causal de hard_eval para unknown:general.\n"
            "Lacunas restantes: aresta_causal_relevante, fato_estruturado_recuperavel."
        ),
        "strategy": "non_llm_causal_transfer_prior",
        "module": "causal_transfer_engine",
        "confidence": 0.62,
        "evidence_summary": {
            "reason": "no_structured_coverage",
            "investigation_id": "inv_test_stream",
            "status": "transfer_prior_validated",
            "coverage": {"score": 1.0},
            "missing_slots": ["aresta_causal_relevante", "fato_estruturado_recuperavel"],
            "next_experiment": {"kind": "causal_transfer_prior_validation"},
            "candidate_modules": ["active_investigation"],
            "transfer_prior": {
                "type": "autoisomorphic_transfer_prior",
                "source_domain": "hard_eval",
                "target_domain": "unknown:general",
                "confidence": 0.58,
                "transferred_policy": "Topologia causal comum",
            },
            "prior_validation": {"status": "validated", "confidence_after": 0.68},
        },
        "gap_signal": {
            "schema": "ultron.cognitive_gap_signal.v1",
            "missing_slots": ["aresta_causal_relevante", "fato_estruturado_recuperavel"],
        },
        "inference_trace": {
            "schema": "ultron.unified_inference.v1",
            "formalism": "weighted_support_graph_v1",
            "premises": [
                {
                    "id": "p1",
                    "source": "active_investigation",
                    "modality": "gap_report",
                    "statement": "investigation status=transfer_prior_validated",
                    "confidence": 0.62,
                    "role": "evidence",
                }
            ],
            "inference_steps": [],
            "gaps": [],
            "conclusion": {"resolved": True, "confidence": 0.62},
        },
    }


def test_backend_causal_synthesis_separates_stream_answer_from_trace(monkeypatch):
    from fastapi.testclient import TestClient
    from ultronpro import local_reasoning_engine, main, skill_memory, symbolic_reasoner

    monkeypatch.setattr(main, "_intent_pre_classifier", lambda q: "unknown")
    monkeypatch.setattr(main, "is_autobiographical_intent", lambda q: False)
    monkeypatch.setattr(main, "_suggest_skill_name_for_chat", lambda q: None)
    monkeypatch.setattr(main, "_external_factual_decision", lambda q: {"label": "internal"})
    monkeypatch.setattr(main, "_record_conversation_route", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_record_chat_turn_episode", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_cognitive_response_answer", lambda q: _fake_causal_gap_response())
    monkeypatch.setattr(symbolic_reasoner, "_solve_deterministic", lambda q: None)
    monkeypatch.setattr(local_reasoning_engine, "resolve", lambda q: {})
    monkeypatch.setattr(skill_memory, "learn_from_chat_turn", lambda *args, **kwargs: None)

    client = TestClient(main.app)
    response = client.post("/api/chat/stream", json={"message": "explique o dominio azorq-91"})
    events = [
        json.loads(chunk[6:])
        for chunk in response.text.split("\n\n")
        if chunk.startswith("data: ")
    ]
    done = next(event for event in events if event.get("type") == "done")

    assert done["synthesized_text"] == done["answer"]
    assert done["trace_causal"]["schema"] == "ultron.chat.causal_trace.v1"
    assert done["trace_causal"]["evidence_summary"]["investigation_id"] == "inv_test_stream"
    assert done["source_strategy"] == "non_llm_causal_transfer_prior"
    assert "Encontrei cobertura direta insuficiente" not in done["answer"]
    assert "Lacunas restantes" not in done["answer"]
    assert "aresta_causal_relevante" not in done["answer"]


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
