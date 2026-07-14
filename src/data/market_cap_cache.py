"""Persist market-cap lookups so large universe ranking stays fast week-to-week."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

CACHE_PATH = Path("data/cache/market_caps.json")
MAX_AGE_DAYS = 7


def _load() -> Dict[str, Any]:
    if not CACHE_PATH.is_file():
        return {"entries": {}, "updated_at": ""}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"entries": {}, "updated_at": ""}


def _save(data: Dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _entry_fresh(entry: Dict[str, Any]) -> bool:
    checked = entry.get("checked_at")
    if not checked:
        return False
    try:
        dt = datetime.fromisoformat(checked)
        return datetime.now() - dt <= timedelta(days=MAX_AGE_DAYS)
    except Exception:
        return False


def lookup_cached_market_cap(ticker: str) -> Optional[float]:
    data = _load()
    entry = (data.get("entries") or {}).get(str(ticker).upper())
    if not entry or not _entry_fresh(entry):
        return None
    try:
        mc = float(entry.get("market_cap") or 0.0)
    except Exception:
        return None
    return mc if mc > 0 else None


def record_market_cap(ticker: str, market_cap: float) -> None:
    data = _load()
    entries = data.setdefault("entries", {})
    entries[str(ticker).upper()] = {
        "market_cap": float(market_cap),
        "checked_at": datetime.now().isoformat(),
    }
    _save(data)


def bulk_record(market_caps: Dict[str, float]) -> None:
    if not market_caps:
        return
    data = _load()
    entries = data.setdefault("entries", {})
    now = datetime.now().isoformat()
    for t, mc in market_caps.items():
        if float(mc or 0) <= 0:
            continue
        entries[str(t).upper()] = {"market_cap": float(mc), "checked_at": now}
    _save(data)
