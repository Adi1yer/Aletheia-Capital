"""Persist yfinance liquidity screening results to reduce universe build time."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

CACHE_PATH = Path("data/cache/liquidity.json")
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


def lookup_cached_pass(ticker: str) -> Optional[bool]:
    """Return True/False if fresh cache entry exists, else None."""
    data = _load()
    entry = (data.get("entries") or {}).get(ticker.upper())
    if not entry or not _entry_fresh(entry):
        return None
    return bool(entry.get("pass"))


def record_liquidity_result(ticker: str, passed: bool, meta: Optional[dict] = None) -> None:
    data = _load()
    entries = data.setdefault("entries", {})
    entries[ticker.upper()] = {
        "pass": passed,
        "checked_at": datetime.now().isoformat(),
        **(meta or {}),
    }
    _save(data)


def cache_stats(tickers: List[str]) -> Tuple[int, int]:
    """Return (hits, misses) for a ticker list against fresh cache."""
    hits = misses = 0
    for t in tickers:
        if lookup_cached_pass(t) is None:
            misses += 1
        else:
            hits += 1
    return hits, misses
