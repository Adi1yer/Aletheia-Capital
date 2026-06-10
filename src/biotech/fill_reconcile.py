"""Reconcile biotech straddle leg orders against Alpaca closed orders."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.broker.alpaca import AlpacaBroker

logger = structlog.get_logger()

_FILLED_STATUSES = frozenset({"filled", "partially_filled", "closed"})


def reconcile_straddle_orders(
    broker: AlpacaBroker,
    leg_orders: List[Dict[str, Any]],
    *,
    poll_limit: int = 40,
    retry_delay_sec: float = 2.5,
) -> Dict[str, Any]:
    """
    Match submitted legs to recent closed orders by contract symbol.
    Returns normalized status: filled | partial | submitted | failed.
    """
    contracts = []
    for lo in leg_orders or []:
        if not isinstance(lo, dict):
            continue
        sym = str(lo.get("contract") or "").strip()
        if sym:
            contracts.append(sym)

    if not contracts:
        return {
            "status": "failed",
            "legs": [],
            "total_premium_filled": 0.0,
            "total_premium_est": 0.0,
        }

    def _match_orders() -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], int, float]:
        recent = broker.get_recent_orders(limit=poll_limit)
        by_symbol: Dict[str, Dict[str, Any]] = {}
        for o in recent:
            sym = str(o.get("symbol") or "").strip()
            if sym and sym not in by_symbol:
                by_symbol[sym] = o
        legs_out: List[Dict[str, Any]] = []
        filled_count = 0
        total_filled = 0.0
        for sym in contracts:
            o = by_symbol.get(sym) or {}
            oid = str(o.get("id") or "")
            status = str(o.get("status") or "unknown").lower()
            fqty = int(o.get("filled_qty") or 0)
            fpx = float(o.get("filled_avg_price") or 0)
            leg_prem = fpx * 100.0 * max(1, fqty) if fpx > 0 and fqty > 0 else 0.0
            if status in _FILLED_STATUSES and fqty > 0 and fpx > 0:
                filled_count += 1
                total_filled += leg_prem
            legs_out.append(
                {
                    "contract": sym,
                    "order_id": oid,
                    "status": status,
                    "filled_qty": fqty,
                    "filled_avg_price": fpx,
                    "premium_filled_usd": round(leg_prem, 2),
                }
            )
        return by_symbol, legs_out, filled_count, total_filled

    _, legs_out, filled_count, total_filled = _match_orders()
    n = len(contracts)
    if filled_count < n and retry_delay_sec > 0:
        time.sleep(retry_delay_sec)
        _, legs_out, filled_count, total_filled = _match_orders()

    if filled_count >= n and n > 0:
        norm = "filled"
    elif filled_count > 0:
        norm = "partial"
    elif any(str(l.get("status")) in _FILLED_STATUSES for l in legs_out):
        norm = "partial"
    else:
        norm = "submitted"

    return {
        "status": norm,
        "legs": legs_out,
        "total_premium_filled": round(total_filled, 2),
        "filled_leg_count": filled_count,
        "expected_leg_count": n,
    }
