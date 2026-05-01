import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_birth_question_routes_to_operational_origin_not_generic_identity(tmp_path):
    from ultronpro import biographic_digest, cognitive_response, self_model, store
    from ultronpro.core.intent import classify_autobiographical_intent

    created_at = 1_700_000_000
    expected_day = time.strftime("%Y-%m-%d", time.localtime(created_at))

    old_self_path = self_model.PATH
    old_store_db = store.db
    old_store_db_path = store.DB_PATH
    old_digest_path = biographic_digest.DIGEST_PATH
    old_biography_path = biographic_digest.BIOGRAPHY_PATH
    old_investigation_log = biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH
    old_trace = cognitive_response.TRACE_PATH
    old_engine = cognitive_response._ENGINE

    self_model.PATH = tmp_path / "self_model.json"
    store.DB_PATH = str(tmp_path / "ultron.db")
    store.db = store.Store(store.DB_PATH)
    biographic_digest.DIGEST_PATH = tmp_path / "biographic_digest.json"
    biographic_digest.BIOGRAPHY_PATH = tmp_path / "biography.jsonl"
    biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH = tmp_path / "active_investigations.jsonl"
    cognitive_response.TRACE_PATH = tmp_path / "cognitive_response_traces.jsonl"
    cognitive_response._ENGINE = None

    try:
        self_model.PATH.write_text(
            json.dumps(
                {
                    "created_at": created_at,
                    "updated_at": created_at,
                    "identity": {
                        "name": "UltronPro",
                        "role": "agente cognitivo autonomo de teste",
                        "mission": "aprender com evidencia",
                        "origin": "laboratorio de teste UltronPro",
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

        decision = classify_autobiographical_intent("quando vc nasceu?")
        assert decision.label == "autobiographical"
        assert decision.category == "creation"

        result = cognitive_response.answer("quando vc nasceu?")
        answer = result["answer"]

        assert result["resolved"] is True
        assert result["strategy"] == "non_llm_autobiographical_creation"
        assert expected_day in answer
        assert "laboratorio de teste UltronPro" in answer
        assert "Minha resposta vem da memoria biografica" not in answer
        assert "Hoje eu sou" not in answer
    finally:
        self_model.PATH = old_self_path
        store.db = old_store_db
        store.DB_PATH = old_store_db_path
        biographic_digest.DIGEST_PATH = old_digest_path
        biographic_digest.BIOGRAPHY_PATH = old_biography_path
        biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH = old_investigation_log
        cognitive_response.TRACE_PATH = old_trace
        cognitive_response._ENGINE = old_engine
