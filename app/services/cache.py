from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


def load_cache(path: Path, max_age_seconds: int) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > max_age_seconds:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cache(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
