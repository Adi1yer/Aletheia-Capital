"""Warmup: cash/concentration SLO warn-only for 2 weeks, then hard."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

STATE_PATH = Path("data/performance/phase13_slo_warmup.json")
WARMUP_DAYS = 14


def _load() -> Dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def ensure_warmup_started() -> Dict[str, Any]:
    state = _load()
    if not state.get("started_at"):
        state = {
            "started_at": datetime.utcnow().isoformat() + "Z",
            "warmup_days": WARMUP_DAYS,
        }
        _save(state)
    return state


def cash_conc_hard_enabled() -> bool:
    state = ensure_warmup_started()
    try:
        started = datetime.fromisoformat(str(state["started_at"]).replace("Z", ""))
    except Exception:
        return False
    return datetime.utcnow() >= started + timedelta(days=int(state.get("warmup_days") or WARMUP_DAYS))
