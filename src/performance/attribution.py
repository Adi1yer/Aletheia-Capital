"""Portfolio return attribution vs SPY (beta / residual / selection proxy)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional


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


def build_attribution_report(
    *,
    equity_now: float,
    equity_prev: Optional[float],
    data_provider=None,
    assumed_beta: float = 1.0,
) -> Dict[str, Any]:
    """Simple weekly attribution: total Δ ≈ beta * SPY + residual."""
    equity_delta_pct = None
    if equity_prev and float(equity_prev) > 0:
        equity_delta_pct = round((float(equity_now) / float(equity_prev) - 1.0) * 100.0, 4)

    spy = _spy_return_pct(data_provider) if data_provider is not None else None
    beta_contrib = None
    residual_pct = None
    if spy is not None:
        beta_contrib = round(float(assumed_beta) * float(spy), 4)
        if equity_delta_pct is not None:
            residual_pct = round(float(equity_delta_pct) - float(beta_contrib), 4)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "equity_now": equity_now,
        "equity_prev": equity_prev,
        "equity_delta_pct": equity_delta_pct,
        "spy_return_pct": spy,
        "assumed_beta": assumed_beta,
        "beta_contribution_pct": beta_contrib,
        "residual_return_pct": residual_pct,
        "active_vs_spy_pct": (
            round(float(equity_delta_pct) - float(spy), 4)
            if equity_delta_pct is not None and spy is not None
            else None
        ),
    }
