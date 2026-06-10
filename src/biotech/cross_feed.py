"""Biotech catalyst signals for stock pipeline cross-feed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.biotech.thesis_ledger import recent_entries

CROSS_FEED_PATH = Path("data/biotech/stock_cross_feed.json")


def build_cross_feed(weeks: int = 4) -> Dict[str, Any]:
    rows = recent_entries(weeks=weeks)
    tickers: List[str] = []
    for r in rows:
        t = str(r.get("ticker") or "").upper()
        if t and t not in tickers:
            tickers.append(t)
    return {
        "source": "biotech_catalyst",
        "weeks": weeks,
        "tickers": tickers,
        "count": len(tickers),
    }


def save_cross_feed(weeks: int = 4) -> Path:
    payload = build_cross_feed(weeks=weeks)
    CROSS_FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CROSS_FEED_PATH.write_text(json.dumps(payload, indent=2))
    return CROSS_FEED_PATH


def load_cross_feed() -> Dict[str, Any]:
    if not CROSS_FEED_PATH.is_file():
        return {}
    try:
        return json.loads(CROSS_FEED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def cross_feed_prompt_snippet() -> str:
    data = load_cross_feed()
    tickers = data.get("tickers") or []
    if not tickers:
        return ""
    return (
        "BIOTECH CATALYST WATCH (from biotech arm, informational): "
        + ", ".join(tickers[:15])
    )
