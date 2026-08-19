"""Biweekly full-rebalance cadence for Beat SPY (weekly runs still do stops)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Set, Tuple

STATE_PATH = Path("data/performance/beat_spy_rebalance.json")


def _load(path: Path = STATE_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(payload: Dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def holdings_need_rebuild(
    *,
    held_tickers: Sequence[str],
    eligible: Optional[Set[str]] = None,
    dossiers: Optional[Dict[str, Any]] = None,
    prices: Optional[Dict[str, float]] = None,
    max_names: int = 12,
    min_mcap_usd: float = 10_000_000_000.0,
    min_adv_usd: float = 20_000_000.0,
    min_price_usd: float = 10.0,
) -> Tuple[bool, Dict[str, Any]]:
    """True if the live book is not a valid concentrated S&P-like 10–12."""
    from src.alpha.liquidity_gate import passes_buy_liquidity

    held = [str(t) for t in held_tickers if t]
    diag: Dict[str, Any] = {"held": len(held), "outside_universe": [], "illiquid": []}
    if len(held) > int(max_names):
        diag["reason"] = "too_many_names"
        return True, diag
    eligible = eligible or set()
    dossiers = dossiers or {}
    prices = prices or {}
    for t in held:
        if eligible and t not in eligible:
            diag["outside_universe"].append(t)
            continue
        px = float(prices.get(t) or 0.0)
        ok, reason = passes_buy_liquidity(
            dossiers.get(t),
            px,
            min_mcap=min_mcap_usd,
            min_adv=min_adv_usd,
            min_price=min_price_usd,
        )
        if not ok:
            diag["illiquid"].append({"ticker": t, "reason": reason})
    if diag["outside_universe"] or diag["illiquid"]:
        diag["reason"] = "book_violates_mandate"
        return True, diag
    diag["reason"] = "book_ok"
    return False, diag


def should_skip_new_buys(
    *,
    interval_weeks: int = 2,
    now: datetime | None = None,
    path: Path = STATE_PATH,
    force: bool = False,
    mandate_rebuild: bool = False,
) -> Tuple[bool, Dict[str, Any]]:
    """True → risk-only week (stops, no rebuild/adds). First run is always full."""
    now = now or datetime.utcnow()
    interval_weeks = max(1, int(interval_weeks or 1))
    if force:
        return False, {"reason": "forced_full_rebalance", "last_full_rebalance_at": None}
    if mandate_rebuild:
        return False, {"reason": "book_violates_mandate", "last_full_rebalance_at": None}
    state = _load(path)
    last_raw = state.get("last_full_rebalance_at")
    if not last_raw:
        return False, {"reason": "no_prior_full_rebalance", "last_full_rebalance_at": None}
    try:
        last = datetime.fromisoformat(str(last_raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return False, {"reason": "bad_timestamp", "last_full_rebalance_at": last_raw}
    elapsed_days = (now - last).days
    skip = elapsed_days < int(interval_weeks) * 7
    return skip, {
        "reason": "inside_interval" if skip else "interval_elapsed",
        "last_full_rebalance_at": last_raw,
        "elapsed_days": elapsed_days,
        "interval_weeks": interval_weeks,
    }


def mark_full_rebalance(path: Path = STATE_PATH) -> None:
    _save({"last_full_rebalance_at": datetime.utcnow().isoformat() + "Z"})
