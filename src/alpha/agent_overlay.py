"""Apply agent judgment as veto / boost on factor residual μ̂."""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple


def apply_agent_overlay(
    ranked: List[Tuple[str, float, Dict[str, float]]],
    aggregated_by_ticker: Dict[str, Dict[str, Any]],
    *,
    min_factor_pct_for_new_buy: float = 0.5,
    boost_confidence_threshold: int = 70,
    boost_amount: float = 0.08,
    veto_bearish_threshold: int = 65,
) -> Tuple[Dict[str, float], Set[str], Dict[str, Any]]:
    """
    Returns (adjusted_mu, vetoed_tickers, diagnostics).
    Conflict rule: tickers below min_factor_pct cannot receive boost into top book.
    """
    order = [t for t, _, _ in ranked]
    n = len(order)
    pct_by_ticker = {}
    if n > 1:
        for i, t in enumerate(order):
            pct_by_ticker[t] = 1.0 - (i / (n - 1))
    elif n == 1:
        pct_by_ticker[order[0]] = 1.0

    adjusted: Dict[str, float] = {t: mu for t, mu, _ in ranked}
    vetoed: Set[str] = set()
    boosts = 0
    vetoes = 0

    for t, mu, _ in ranked:
        agg = aggregated_by_ticker.get(t) or {}
        sig = str(agg.get("signal") or "neutral")
        conf = int(agg.get("confidence") or 0)
        fac_pct = float(pct_by_ticker.get(t, 0.0))

        if sig == "bearish" and conf >= veto_bearish_threshold:
            vetoed.add(t)
            vetoes += 1
            continue

        if (
            sig == "bullish"
            and conf >= boost_confidence_threshold
            and fac_pct >= min_factor_pct_for_new_buy
        ):
            adjusted[t] = round(mu + boost_amount, 6)
            boosts += 1
        elif sig == "bullish" and conf >= boost_confidence_threshold and fac_pct < min_factor_pct_for_new_buy:
            # Agents cannot promote bottom-half factor names
            pass

    diag = {
        "boosts_applied": boosts,
        "vetoes_applied": vetoes,
        "min_factor_pct_for_new_buy": min_factor_pct_for_new_buy,
    }
    return adjusted, vetoed, diag
