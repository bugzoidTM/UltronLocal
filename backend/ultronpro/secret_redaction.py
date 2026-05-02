from __future__ import annotations

import logging
import re
from typing import Iterable


_REDACTION = "***REDACTED***"


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)([?&](?:key|api_key|apikey|token|access_token|auth)=)([^&\s]+)"),
        rf"\1{_REDACTION}",
    ),
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9._~+/=-]+)"),
        rf"\1{_REDACTION}",
    ),
    (
        re.compile(r"(?i)((?:api[_-]?key|token|secret|gemini_api_key|openai_api_key|anthropic_api_key|groq_api_key|deepseek_api_key|openrouter_api_key|huggingface_api_key)\s*[:=]\s*[\"']?)([^\"'\s,&}}]+)"),
        rf"\1{_REDACTION}",
    ),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "AIza***REDACTED***"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "sk-***REDACTED***"),
    (re.compile(r"ghp_[A-Za-z0-9_]{20,}"), "ghp_***REDACTED***"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github_pat_***REDACTED***"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "hf_***REDACTED***"),
)


def redact_text(value: object) -> str:
    text = str(value or "")
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
            redacted = redact_text(rendered)
            if redacted != rendered:
                record.msg = redacted
                record.args = ()
        except Exception:
            pass
        return True


_FILTER = RedactingFilter()
_INSTALLED = False


def _has_filter(filters: Iterable[logging.Filter]) -> bool:
    return any(isinstance(item, RedactingFilter) for item in filters)


def add_redaction_filter(target: logging.Logger | logging.Handler) -> None:
    if not _has_filter(getattr(target, "filters", ())):
        target.addFilter(_FILTER)


def install_logging_redaction() -> dict[str, object]:
    global _INSTALLED
    names = [
        "",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "httpx",
        "httpcore",
        "ultronpro",
    ]
    for name in names:
        logger = logging.getLogger(name)
        add_redaction_filter(logger)
        for handler in logger.handlers:
            add_redaction_filter(handler)
    _INSTALLED = True
    return {"enabled": True, "logger_names": names}


def installed() -> bool:
    return bool(_INSTALLED)
