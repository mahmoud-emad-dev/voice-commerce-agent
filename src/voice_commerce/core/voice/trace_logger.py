from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from voice_commerce.config.settings import settings

_RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
_LOCK = threading.Lock()


def get_trace_run_id() -> str:
    return _RUN_ID


def trace_event(session_id: str, source: str, event: str, **payload: Any) -> Path | None:
    if not settings.voice_trace_enabled:
        return None

    session_key = _sanitize_path_part(session_id)
    root = Path(settings.voice_trace_root).expanduser().resolve() / _RUN_ID
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{session_key}.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": _RUN_ID,
        "session_id": session_id,
        "source": source,
        "event": event,
        **payload,
    }

    with _LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")
    return path


def _sanitize_path_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return safe[:120] or "unknown_session"
