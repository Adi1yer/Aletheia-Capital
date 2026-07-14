"""Load previous weekly-run equity / portfolio for benchmarking."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def _equity_from_portfolio(
    portfolio: Optional[Dict[str, Any]],
    risk: Optional[Dict[str, Any]] = None,
    *,
    price_overrides: Optional[Dict[str, float]] = None,
) -> Optional[float]:
    if not portfolio:
        return None
    equity_val = float(portfolio.get("cash", 0.0) or 0.0)
    positions = portfolio.get("positions") or {}
    risk_data = risk or {}
    overrides = price_overrides or {}
    for sym, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        price = overrides.get(sym)
        if price is None:
            price = (risk_data.get(sym) or {}).get("current_price")
        if price is None:
            price = pos.get("long_cost_basis") or pos.get("short_cost_basis") or 0.0
        price = float(price or 0.0)
        equity_val += float(pos.get("long", 0) or 0) * price
        equity_val -= float(pos.get("short", 0) or 0) * price
    return round(equity_val, 2)


def load_previous_run_context(
    scan_cache,
    *,
    current_run_id: Optional[str] = None,
    current_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Return prior-run equity and a do-nothing return estimate.

    Do-nothing = prior portfolio held at *current* prices vs prior equity
    (isolates selection/trading vs sitting on last week's book).
    """
    out: Dict[str, Any] = {
        "prev_run_id": None,
        "prev_equity": None,
        "do_nothing_equity": None,
        "do_nothing_return_pct": None,
        "prev_portfolio": None,
    }
    if scan_cache is None:
        return out
    try:
        runs = scan_cache.list_runs(limit=12, since_date=None)
    except Exception:
        return out
    if not runs:
        return out

    prev_meta = None
    if current_run_id:
        for idx, meta in enumerate(runs):
            if meta.get("run_id") == current_run_id and idx + 1 < len(runs):
                prev_meta = runs[idx + 1]
                break
    if prev_meta is None:
        # Before current run is saved: newest cached run is previous
        prev_meta = runs[0] if not current_run_id else (runs[1] if len(runs) > 1 else None)
        if current_run_id and runs and runs[0].get("run_id") == current_run_id:
            prev_meta = runs[1] if len(runs) > 1 else None
        elif not current_run_id:
            prev_meta = runs[0]

    if not prev_meta:
        return out

    try:
        prev = scan_cache.load_run(prev_meta["run_id"])
    except Exception:
        return out

    prev_port = prev.get("portfolio_after") or prev.get("portfolio_before") or {}
    prev_eq = _equity_from_portfolio(prev_port, prev.get("risk"))
    # Prefer stored equity if present
    if isinstance(prev_port, dict) and prev_port.get("equity") is not None and prev_eq is None:
        try:
            prev_eq = float(prev_port.get("equity"))
        except Exception:
            pass

    do_nothing_eq = None
    do_nothing_pct = None
    if prev_port and current_prices:
        do_nothing_eq = _equity_from_portfolio(prev_port, price_overrides=current_prices)
        if prev_eq and prev_eq > 0 and do_nothing_eq is not None:
            do_nothing_pct = round((do_nothing_eq / prev_eq - 1.0) * 100.0, 4)

    out.update(
        {
            "prev_run_id": prev_meta.get("run_id"),
            "prev_equity": prev_eq,
            "do_nothing_equity": do_nothing_eq,
            "do_nothing_return_pct": do_nothing_pct,
            "prev_portfolio": prev_port,
        }
    )
    return out
