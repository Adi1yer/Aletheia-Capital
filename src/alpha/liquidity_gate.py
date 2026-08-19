"""Hard liquidity gate for Beat SPY target membership (S&P 500-like)."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from src.portfolio.beat_spy_policy import MIN_ADV_USD, MIN_MCAP_USD, MIN_PRICE_USD


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def dossier_liquidity(dossier: Optional[Dict[str, Any]], price: float) -> Dict[str, Optional[float]]:
    dossier = dossier or {}
    ctx = dossier.get("context") or {}
    prices = dossier.get("prices") or {}
    mcap = _safe_float(ctx.get("market_cap"))
    px = _safe_float(prices.get("last_close")) or (float(price) if price else None)
    avg_vol = _safe_float(prices.get("avg_volume"))
    adv = None
    if avg_vol is not None and px is not None and px > 0:
        adv = avg_vol * px
    return {"market_cap": mcap, "price": px, "avg_volume": avg_vol, "adv_usd": adv}


def passes_buy_liquidity(
    dossier: Optional[Dict[str, Any]],
    price: float,
    *,
    min_mcap: float = MIN_MCAP_USD,
    min_adv: float = MIN_ADV_USD,
    min_price: float = MIN_PRICE_USD,
) -> Tuple[bool, str]:
    """New buys must clear mcap / ADV / price. Missing data fails closed."""
    liq = dossier_liquidity(dossier, price)
    px = liq.get("price") or (float(price) if price else 0.0)
    if px < float(min_price):
        return False, "price"
    mcap = liq.get("market_cap")
    if mcap is None or mcap < float(min_mcap):
        return False, "mcap"
    adv = liq.get("adv_usd")
    if adv is None or adv < float(min_adv):
        return False, "adv"
    return True, "ok"
