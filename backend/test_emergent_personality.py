import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


@contextmanager
def isolated_personality_substrate(tmp_path):
    from ultronpro import biographic_digest, cognitive_response, emergent_personality, self_model, store

    old_values = (
        store.DB_PATH,
        store.db,
        self_model.PATH,
        biographic_digest.DIGEST_PATH,
        biographic_digest.BIOGRAPHY_PATH,
        biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH,
        emergent_personality.PROFILE_PATH,
        emergent_personality.PROFILE_LOG_PATH,
        cognitive_response.TRACE_PATH,
        cognitive_response.EXTERNAL_FACT_TRACE_PATH,
        cognitive_response._ENGINE,
    )

    store.DB_PATH = str(tmp_path / "ultron.db")
    store.db = store.Store(store.DB_PATH)
    self_model.PATH = tmp_path / "self_model.json"
    biographic_digest.DIGEST_PATH = tmp_path / "biographic_digest.json"
    biographic_digest.BIOGRAPHY_PATH = tmp_path / "biography.jsonl"
    biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH = tmp_path / "active_investigations.jsonl"
    emergent_personality.PROFILE_PATH = tmp_path / "emergent_personality_profile.json"
    emergent_personality.PROFILE_LOG_PATH = tmp_path / "emergent_personality_profiles.jsonl"
    cognitive_response.TRACE_PATH = tmp_path / "cognitive_response_traces.jsonl"
    cognitive_response.EXTERNAL_FACT_TRACE_PATH = tmp_path / "external_fact_traces.jsonl"
    cognitive_response._ENGINE = None

    now = int(time.time())
    self_model.PATH.write_text(
        json.dumps(
            {
                "created_at": now - 86400,
                "updated_at": now,
                "identity": {
                    "name": "UltronPro",
                    "role": "agente cognitivo autonomo de teste",
                    "mission": "aprender com evidencia real",
                    "origin": "laboratorio de memoria autobiografica",
                    "foundational_context": "teste de personalidade emergente baseada em digest e memoria",
                },
                "operational": {
                    "strengths": [
                        "Calibra incerteza antes de responder com confianca.",
                        "Executa investigacao sandboxada quando encontra lacuna causal.",
                    ],
                    "weaknesses": ["Pode estagnar se o digest de sono nao consolidar memoria episodica."],
                    "failure_patterns": ["Erros e falhas viram patches e revisoes explicitas."],
                },
                "causal": {
                    "recent_events": [
                        {
                            "strategy": "active_investigation",
                            "task_type": "causal_gap",
                            "ok": True,
                            "notes": "lacuna virou experimento e aresta causal injetada",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    biographic_digest.DIGEST_PATH.write_text(
        json.dumps(
            {
                "id": "bio_test_personality",
                "day": "2099-01-01",
                "generated_at": now,
                "identity_thesis": "Identidade como processo acumulado por evidencia, correcoes e gates causais.",
                "narrative": "O sistema consolidou memoria no sleep cycle, respondeu UNKNOWN calibrado e executou investigacao ativa sandboxada.",
                "became": [
                    "mais prudente diante de risco e rollback",
                    "mais investigativo diante de lacunas causais",
                    "mais autobiografico pela memoria episodica enriquecida",
                ],
                "significant_episodes": [
                    {"title": "UNKNOWN calibrado com proposta de aprendizado", "evidence": "gap signal explicito"},
                    {"title": "sleep digest criou memoria episodica recuperavel", "evidence": "nightly digest"},
                ],
                "corrections": [
                    {"summary": "patch corrigiu comportamento confiante sem cobertura"},
                ],
                "decisions": [
                    {"summary": "usar sandbox antes de aumentar confianca em prior causal"},
                ],
                "causal_gap_investigations": [
                    {"investigation_id": "inv_test", "status": "injected", "summary": "lacuna causal virou experimento"},
                ],
                "open_tensions": [
                    {"summary": "prudencia operacional versus iniciativa autonoma"},
                ],
                "evidence_counts": {"events": 5, "memories": 4, "causal_gap_injections": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store.add_autobiographical_memory(
        "UNKNOWN calibrado: lacuna causal registrada antes da resposta.",
        memory_type="episodic",
        importance=0.82,
    )
    store.add_autobiographical_memory(
        "Investigacao ativa executou experimento sandboxado e injetou evidencia causal.",
        memory_type="episodic",
        importance=0.84,
    )
    store.add_autobiographical_memory(
        "Digest noturno consolidou memoria episodica para evitar estagnacao.",
        memory_type="semantic",
        importance=0.86,
    )
    store.db.add_event("causal_gap_investigation", "lacuna causal virou experimento sandboxado com evidence")
    store.db.add_event("sleep_cycle", "sleep digest episodic memory enrichment recorded")
    store.db.add_event("policy_veto", "risco operacional bloqueado ate rollback estar pronto")
    store.db.add_event("code_patch", "erro corrigido por patch e teste")

    try:
        yield
    finally:
        (
            store.DB_PATH,
            store.db,
            self_model.PATH,
            biographic_digest.DIGEST_PATH,
            biographic_digest.BIOGRAPHY_PATH,
            biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH,
            emergent_personality.PROFILE_PATH,
            emergent_personality.PROFILE_LOG_PATH,
            cognitive_response.TRACE_PATH,
            cognitive_response.EXTERNAL_FACT_TRACE_PATH,
            cognitive_response._ENGINE,
        ) = old_values


def test_emergent_personality_extracts_traits_from_real_substrate(tmp_path):
    from ultronpro import emergent_personality, self_model, store

    with isolated_personality_substrate(tmp_path):
        profile = emergent_personality.analyze_emergent_personality(persist=True)

        assert profile["schema"] == emergent_personality.SCHEMA
        assert profile["substrate_status"]["status"] == "sufficient"
        trait_ids = {trait["id"] for trait in profile["dominant_traits"]}
        assert "evidence_grounded" in trait_ids
        assert "investigative_curiosity" in trait_ids
        assert profile["shadow_tensions"]
        assert "perfil comportamental observado" in profile["narrative"]

        saved = json.loads(emergent_personality.PROFILE_PATH.read_text(encoding="utf-8"))
        assert saved["id"] == profile["id"]
        assert self_model.load()["emergent_personality"]["profile_id"] == profile["id"]
        memories = store.list_autobiographical_memories(memory_type="semantic", limit=20)
        assert any("Perfil de personalidade emergente" in row["text"] for row in memories)


def test_personality_question_routes_to_non_llm_profile(tmp_path):
    from ultronpro import cognitive_response
    from ultronpro.core.intent import classify_autobiographical_intent

    with isolated_personality_substrate(tmp_path):
        decision = classify_autobiographical_intent("quais sao seus tracos de personalidade emergente?")
        result = cognitive_response.answer("quais sao seus tracos de personalidade emergente?")

    assert decision.label == "autobiographical"
    assert decision.category == "personality"
    assert result["resolved"] is True
    assert result["strategy"] == "non_llm_emergent_personality"
    assert result["module"] == "personality_profile"
    assert "Tracos dominantes" in result["answer"]
    assert "Substrato:" in result["answer"]
