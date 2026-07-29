from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


def append_event(event: dict[str, Any]) -> None:
    """Appends one JSON line to the audit log — the durable, append-only
    counterpart to the in-memory gate_log/replan_log carried in state."""
    settings = get_settings()
    path = Path(settings.audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")
