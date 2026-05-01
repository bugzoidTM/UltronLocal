import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_sir_schema_and_payload_are_structured():
    from ultronpro import sir_amplifier

    sir = sir_amplifier.build_sir_from_raw_context(
        "qual o status do sistema?",
        "Sistema UltronPro operacional.\nLoops ativos: autonomy e reflexion.",
        source="test",
    )

    for field in sir_amplifier.REQUIRED_SIR_FIELDS:
        assert field in sir
    assert sir["facts"][0]["id"] == "FACT_1"
    assert sir["constraints"][0]["id"] == "CONSTRAINT_A"
    payload = json.loads(sir_amplifier.build_llm_payload(sir))
    assert "context" in payload
    assert payload["response_schema"]["required"][0] == "answer"
    assert sir_amplifier.SIR_SYSTEM_PROMPT.startswith("Gere resposta em PT-BR")


def test_post_llm_verifier_catches_critical_omission_and_contradiction():
    from ultronpro import sir_amplifier

    sir = sir_amplifier.build_sir_from_raw_context(
        "qual o status?",
        "Sistema UltronPro operacional.\nProvider primario ativo: Groq.",
        source="test",
    )

    omission = sir_amplifier.verify_answer_against_sir("O sistema UltronPro esta operacional.", sir)
    assert omission["ok"] is False
    assert "FACT_2" in omission["omitted_fact_ids"]

    contradiction = sir_amplifier.verify_answer_against_sir(
        "O sistema UltronPro nao esta operacional. Provider primario ativo: Groq.",
        sir,
    )
    assert contradiction["ok"] is False
    assert contradiction["contradictions"]


def test_synthesis_regenerates_then_accepts_schema_valid_answer():
    from ultronpro import sir_amplifier

    sir = sir_amplifier.build_sir_from_raw_context(
        "qual o status?",
        "Sistema UltronPro operacional.\nProvider primario ativo: Groq.",
        source="test",
    )
    calls = {"n": 0}

    def fake_complete(prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps(
                {
                    "answer": "O sistema UltronPro esta operacional.",
                    "used_fact_ids": ["FACT_1"],
                    "used_rule_ids": ["RULE_1"],
                    "satisfied_constraints": ["CONSTRAINT_A"],
                    "verification_notes": "faltou provider",
                }
            )
        return json.dumps(
            {
                "answer": "O sistema UltronPro esta operacional. Provider primario ativo: Groq.",
                "used_fact_ids": ["FACT_1", "FACT_2"],
                "used_rule_ids": ["RULE_1"],
                "satisfied_constraints": ["CONSTRAINT_A", "CONSTRAINT_B", "CONSTRAINT_C"],
                "verification_notes": "cobre fatos criticos",
            }
        )

    result = sir_amplifier.synthesize_answer_with_sir(
        query="qual o status?",
        sir=sir,
        complete_fn=fake_complete,
        fallback_text="fallback",
    )

    assert result["strategy"] == "sir_constrained_synthesis"
    assert calls["n"] == 2
    assert result["verification"]["ok"] is True

