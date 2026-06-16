"""Constrained portfolio optimizer for rebalance allocations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def optimize_allocations(
    candidates: List[Dict[str, Any]],
    *,
    equity: float,
    cash_buffer_pct: float = 0.05,
    max_position_pct: float = 0.20,
    max_sector_pct: float = 0.35,
    turnover_penalty: float = 0.15,
    current_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Greedy constrained allocator with turnover penalty."""
    current_weights = current_weights or {}
    if equity <= 0 or not candidates:
        return {"allocations": {}, "metrics": {"turnover": 0.0, "concentration": 0.0}}

    deployable = equity * max(0.0, 1.0 - cash_buffer_pct)
    ranked = sorted(
        candidates,
        key=lambda c: float(c.get("score") or 0.0) - turnover_penalty * abs(
            float(current_weights.get(str(c.get("ticker")), 0.0))
        ),
        reverse=True,
    )

    sector_notional: Dict[str, float] = {}
    allocations: Dict[str, Dict[str, Any]] = {}
    used = 0.0

    for c in ranked:
        ticker = str(c.get("ticker") or "")
        if not ticker:
            continue
        sector = str(c.get("sector") or "unknown")
        target = min(deployable * max_position_pct, deployable - used)
        if target <= 0:
            break
        sector_cap = deployable * max_sector_pct
        sector_used = sector_notional.get(sector, 0.0)
        room = max(0.0, sector_cap - sector_used)
        notional = min(target, room)
        if notional < 250.0:
            continue
        qty = int(notional / max(1.0, float(c.get("price") or 1.0)))
        if qty <= 0:
            continue
        allocations[ticker] = {
            "quantity": qty,
            "notional": round(qty * float(c.get("price") or 0.0), 2),
            "score": float(c.get("score") or 0.0),
            "sector": sector,
        }
        used += allocations[ticker]["notional"]
        sector_notional[sector] = sector_used + allocations[ticker]["notional"]

    weights = [v["notional"] / max(1.0, equity) for v in allocations.values()]
    concentration = max(weights) if weights else 0.0
    turnover = sum(
        abs((v["notional"] / max(1.0, equity)) - float(current_weights.get(t, 0.0)))
        for t, v in allocations.items()
    )
    return {
        "allocations": allocations,
        "metrics": {"turnover": round(turnover, 4), "concentration": round(concentration, 4)},
    }
