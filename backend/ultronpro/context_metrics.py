from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

LOG_PATH = Path('/app/data/context_metrics.jsonl')


def estimate_tokens(obj: Any) -> int:
    try:
        raw = json.dumps(obj, ensure_ascii=False)
    except Exception:
        raw = str(obj or '')
    return max(1, int(len(raw) / 4))


def persist_row(row: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {'ts': int(time.time()), **dict(row or {})}
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')
