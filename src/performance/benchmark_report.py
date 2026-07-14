"""Weekly active-return vs SPY and do-nothing prior portfolio."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

OUTPUT_PATH = Path("data/performance/benchmark_latest.json")


def _spy_return_pct(data_provider, *, days: int = 7) -> Optional[float]:
    try:
        end = datetime.utcnow().date()
        start = end - timedelta(days=max(days + 5, 12))
        prices = data_provider.get_prices("SPY", start.isoformat(), end.isoformat())
        closes = []
        if isinstance(prices, list):
            for p in prices:
                c = getattr(p, "close", None)
                if c is not None:
                    closes.append(float(c))
        if len(closes) < 2:
            return None
        return round((closes[-1] / closes[0] - 1.0) * 100.0, 4)
    except Exception:
        return None


def build_benchmark_report(
    *,
    equity_now: float,
    equity_prev: Optional[float],
    data_provider=None,
    prior_portfolio_return_pct: Optional[float] = None,
) -> Dict[str, Any]:
    equity_delta_pct = None
    if equity_prev and float(equity_prev) > 0 and equity_now is not None:
        equity_delta_pct = round((float(equity_now) / float(equity_prev) - 1.0) * 100.0, 4)

    spy = None
    if data_provider is not None:
        spy = _spy_return_pct(data_provider)

    do_nothing = prior_portfolio_return_pct
    active_vs_spy = None
    if equity_delta_pct is not None and spy is not None:
        active_vs_spy = round(float(equity_delta_pct) - float(spy), 4)
    active_vs_do_nothing = None
    if equity_delta_pct is not None and do_nothing is not None:
        active_vs_do_nothing = round(float(equity_delta_pct) - float(do_nothing), 4)

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "equity_now": equity_now,
        "equity_prev": equity_prev,
        "equity_delta_pct": equity_delta_pct,
        "spy_return_pct": spy,
        "do_nothing_return_pct": do_nothing,
        "active_vs_spy_pct": active_vs_spy,
        "active_vs_do_nothing_pct": active_vs_do_nothing,
    }
    try:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass
    return report


def enrich_results_benchmark(
    results: Dict[str, Any],
    *,
    data_provider=None,
    scan_cache=None,
    current_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Attach benchmark + refresh auto-throttle from results portfolio."""
    from src.performance.prior_run import load_previous_run_context
    from src.performance.auto_throttle import record_active_return

    port = results.get("portfolio") or {}
    equity_now = float(port.get("equity") or 0.0)
    learning = results.get("learning_context") or {}
    prior = load_previous_run_context(
        scan_cache,
        current_run_id=results.get("run_id"),
        current_prices=current_prices,
    )
    if learning.get("prev_equity") is not None and prior.get("prev_equity") is None:
        prior["prev_equity"] = learning.get("prev_equity")
    if learning.get("do_nothing_return_pct") is not None and prior.get("do_nothing_return_pct") is None:
        prior["do_nothing_return_pct"] = learning.get("do_nothing_return_pct")

    bench = build_benchmark_report(
        equity_now=equity_now,
        equity_prev=prior.get("prev_equity"),
        data_provider=data_provider,
        prior_portfolio_return_pct=prior.get("do_nothing_return_pct"),
    )
    results["benchmark"] = bench
    results.setdefault("learning_context", {})
    results["learning_context"]["prev_equity"] = prior.get("prev_equity")
    results["learning_context"]["prev_run_id"] = prior.get("prev_run_id")
    results["learning_context"]["do_nothing_return_pct"] = prior.get("do_nothing_return_pct")
    if bench.get("active_vs_spy_pct") is not None:
        results["auto_throttle"] = record_active_return(float(bench["active_vs_spy_pct"]))
    return results
