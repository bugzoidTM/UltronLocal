from ultronpro.ultron_ui.activation import ActivationGate, transcript_has_keyword, verify_keyword_candidate, wake_phrase_variants


def test_activation_keyword_is_verified_without_plaintext_storage():
    assert verify_keyword_candidate("playboyzinho") is True
    assert transcript_has_keyword("olá playboyzinho iniciar") is True
    assert transcript_has_keyword("olá plei boi zinho iniciar") is True
    assert transcript_has_keyword("olá play boy sinho iniciar") is True
    assert transcript_has_keyword("senha errada") is False
    assert wake_phrase_variants()


def test_activation_gate_denies_then_locks_after_more_than_three_errors():
    gate = ActivationGate(max_denied_attempts=3)

    assert gate.handle_transcript("banana").state == "denied"
    assert gate.handle_transcript("abacaxi").state == "denied"
    assert gate.handle_transcript("laranja").state == "denied"
    locked = gate.handle_transcript("uva")

    assert locked.state == "lockout"
    assert locked.message == "Você não é a mamãe!"
