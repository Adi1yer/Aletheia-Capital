"""Paper wash-sale cooldown tracking."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Set

COOLDOWN_PATH = Path("data/performance/ticker_cooldown.json")


def _load() -> Dict[str, str]:
    if not COOLDOWN_PATH.is_file():
        return {}
    try:
        with open(COOLDOWN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: Dict[str, str]) -> None:
    COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(COOLDOWN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def record_sell(ticker: str, sold_at: Optional[str] = None) -> None:
    data = _load()
    data[ticker.upper()] = sold_at or datetime.utcnow().strftime("%Y-%m-%d")
    _save(data)


def blocked_tickers(wash_sale_days: int) -> Set[str]:
    if wash_sale_days <= 0:
        return set()
    data = _load()
    cutoff = datetime.utcnow().date() - timedelta(days=wash_sale_days)
    blocked = set()
    for sym, sold in data.items():
        try:
            d = datetime.strptime(str(sold)[:10], "%Y-%m-%d").date()
            if d >= cutoff:
                blocked.add(sym.upper())
        except Exception:
            continue
    return blocked
