import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ultronpro.secret_redaction import RedactingFilter, redact_text


def test_redact_text_masks_query_keys_and_provider_tokens():
    raw = (
        "POST https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent"
        "?key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWxyZ token=sk-abcdefghijklmnopqrstuvwxyz123456"
    )

    out = redact_text(raw)

    assert "ABCDEFGHIJKLMNOP" not in out
    assert "abcdefghijklmnopqrstuvwxyz" not in out
    assert "key=***REDACTED***" in out
    assert "token=***REDACTED***" in out


def test_redacting_filter_mutates_log_record_message():
    record = logging.LogRecord(
        name="uvicorn",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="authorization: Bearer %s",
        args=("secret-token-1234567890",),
        exc_info=None,
    )

    assert RedactingFilter().filter(record) is True
    assert "secret-token" not in record.getMessage()
    assert "***REDACTED***" in record.getMessage()
