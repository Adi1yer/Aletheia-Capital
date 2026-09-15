"""Risk-adjusted scorecard for the wheel hybrid book vs SPY."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.performance.options_ledger import _read_lines

logger = structlog.get_logger()

SCORECARD_PATH = Path("data/performance/wheel_scorecard.json")
WEEKLY_LEDGER = Path("data/performance/weekly_ledger.jsonl")


def _sharpe(returns: List[float], periods_per_year: float = 52.0) -> Optional[float]:
    if len(returns) < 4:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std <= 1e-12:
        return None
    return (mean / std) * math.sqrt(periods_per_year)


def _max_dd(equity_curve: List[float]) -> Optional[float]:
    if len(equity_curve) < 2:
        return None
    peak = equity_curve[0]
    max_dd = 0.0
    for x in equity_curve:
        peak = max(peak, x)
        if peak > 0:
            max_dd = min(max_dd, (x - peak) / peak)
    return max_dd


def _premium_from_ledger(rows: List[Dict[str, Any]]) -> float:
    total = 0.0
    for r in rows:
        if r.get("status") not in ("executed", "assigned", "expired", "closed", None):
            # Count executed opens; resolved rows may carry realized pnl.
            pass
        if r.get("status") == "executed":
            total += float(r.get("premium_usd") or 0)
        pnl = r.get("realized_pnl_usd")
        if pnl is not None:
            try:
                total += float(pnl)
            except (TypeError, ValueError):
                pass
    return total


def build_wheel_scorecard(
    *,
    equity: float,
    cash: float,
    wheel_diagnostics: Optional[Dict[str, Any]] = None,
    spy_returns: Optional[List[float]] = None,
    fund_returns: Optional[List[float]] = None,
    equity_curve: Optional[List[float]] = None,
    path: Path = SCORECARD_PATH,
) -> Dict[str, Any]:
    """Persist a compact weekly scorecard for email / ops."""
    diag = wheel_diagnostics or {}
    opt_rows = _read_lines()
    premium = _premium_from_ledger(opt_rows)

    # Prefer explicit series; else try weekly ledger equity snapshots.
    f_rets = list(fund_returns or [])
    curve = list(equity_curve or [])
    if not f_rets and WEEKLY_LEDGER.is_file():
        eq_hist: List[float] = []
        try:
            for line in WEEKLY_LEDGER.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                e = row.get("equity") or (row.get("portfolio") or {}).get("equity")
                if e is not None:
                    eq_hist.append(float(e))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            eq_hist = []
        if len(eq_hist) >= 2:
            curve = eq_hist
            f_rets = [
                (eq_hist[i] - eq_hist[i - 1]) / eq_hist[i - 1]
                for i in range(1, len(eq_hist))
                if eq_hist[i - 1] > 0
            ]

    fund_sharpe = _sharpe(f_rets)
    spy_sharpe = _sharpe(list(spy_returns or []))
    max_dd = _max_dd(curve) if curve else None

    wheel_deployed = 0.0
    for t in diag.get("cc_lot_tickers") or []:
        # Approximate: unknown price here — leave sleeve weights from diagnostics budgets.
        pass
    card = {
        "mode": "wheel_hybrid",
        "equity": round(float(equity), 2),
        "cash": round(float(cash), 2),
        "cash_pct": round(float(cash) / float(equity), 4) if equity else None,
        "wheel_pct_target": diag.get("wheel_budget"),
        "directional_pct_target": diag.get("directional_budget"),
        "cc_lot_tickers": list(diag.get("cc_lot_tickers") or []),
        "csp_candidates": list(diag.get("csp_candidates") or []),
        "directional_targets": list(diag.get("directional_targets") or []),
        "premium_ledger_usd": round(premium, 2),
        "fund_sharpe": None if fund_sharpe is None else round(fund_sharpe, 3),
        "spy_sharpe": None if spy_sharpe is None else round(spy_sharpe, 3),
        "max_drawdown": None if max_dd is None else round(max_dd, 4),
        "weeks_in_sample": len(f_rets),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    logger.info("Wheel scorecard saved", path=str(path), sharpe=card["fund_sharpe"])
    return card
