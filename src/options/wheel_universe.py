"""Rules-first universe screener for the wheel sleeve (cheap, liquid, options-friendly)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import structlog

logger = structlog.get_logger()


@dataclass
class WheelCandidate:
    ticker: str
    price: float
    adv_usd: float
    open_interest: int
    score: float
    reason: str = ""


def _f(d: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return default


def extract_price_adv(
    ticker: str,
    *,
    prices: Optional[Dict[str, float]] = None,
    dossiers: Optional[Dict[str, Any]] = None,
) -> tuple[float, float]:
    """Return (last_price, dollar_ADV) from prices map and/or ticker dossiers."""
    px = float((prices or {}).get(ticker) or 0.0)
    adv = 0.0
    d = (dossiers or {}).get(ticker) or {}
    if not isinstance(d, dict):
        d = {}
    prices_block = d.get("prices") if isinstance(d.get("prices"), dict) else {}
    if px <= 0:
        px = _f(prices_block, "last_close", "close", "price")
    # Prefer explicit dollar ADV, then volume × price (volume usually lives under prices).
    adv = _f(d, "adv_usd", "dollar_volume", "avg_dollar_volume")
    if adv <= 0:
        mkt = d.get("market") if isinstance(d.get("market"), dict) else {}
        adv = _f(mkt, "adv_usd", "avg_dollar_volume", "avg_dollar_volume_30d")
    if adv <= 0:
        vol = _f(prices_block, "avg_volume", "average_volume", "volume")
        if vol <= 0:
            vol = _f(d, "avg_volume", "average_volume", "volume")
        if vol <= 0:
            mkt = d.get("market") if isinstance(d.get("market"), dict) else {}
            vol = _f(mkt, "avg_volume", "average_volume")
        if vol > 0 and px > 0:
            adv = vol * px
    return px, adv


def screen_wheel_candidates(
    tickers: Sequence[str],
    *,
    prices: Optional[Dict[str, float]] = None,
    dossiers: Optional[Dict[str, Any]] = None,
    option_oi_by_ticker: Optional[Dict[str, int]] = None,
    max_price: float = 35.0,
    min_price: float = 3.0,
    min_adv_usd: float = 5_000_000.0,
    min_option_oi: int = 0,
    top_n: int = 20,
    allow_missing_adv: bool = True,
) -> List[WheelCandidate]:
    """
    Rank tickers for CSP/CC wheel use.

    Score favors mid-cheap names with high ADV (proxy for option liquidity when OI missing).
    When ADV is missing from dossiers, ``allow_missing_adv`` still admits price-eligible
    names at a low liquidity score so the wheel sleeve is not starved empty.
    """
    oi_map = option_oi_by_ticker or {}
    out: List[WheelCandidate] = []
    rejected_adv = 0
    missing_adv = 0
    for t in tickers:
        ticker = str(t).upper().strip()
        if not ticker:
            continue
        px, adv = extract_price_adv(ticker, prices=prices, dossiers=dossiers)
        if px < min_price or px > float(max_price):
            continue
        if adv < float(min_adv_usd):
            if adv <= 0 and allow_missing_adv:
                missing_adv += 1
                adv = float(min_adv_usd)  # neutral floor for scoring only
            else:
                rejected_adv += 1
                continue
        oi = int(oi_map.get(ticker) or 0)
        if min_option_oi > 0 and oi > 0 and oi < int(min_option_oi):
            continue
        # Prefer names where 100 shares are affordable but not penny stocks.
        lot_cost = px * 100.0
        afford = max(0.0, 1.0 - (lot_cost / (float(max_price) * 100.0)))
        liq = min(adv / max(float(min_adv_usd), 1.0), 5.0) / 5.0
        oi_boost = min(oi / 500.0, 1.0) if oi > 0 else 0.35
        score = 0.45 * liq + 0.35 * afford + 0.20 * oi_boost
        out.append(
            WheelCandidate(
                ticker=ticker,
                price=px,
                adv_usd=adv,
                open_interest=oi,
                score=round(score, 4),
                reason=f"px={px:.2f} adv={adv:.0f} oi={oi}",
            )
        )
    out.sort(key=lambda c: c.score, reverse=True)
    ranked = out[: max(1, int(top_n))] if out else []
    logger.info(
        "Wheel universe screened",
        input_n=len(tickers),
        passed=len(out),
        top_n=len(ranked),
        rejected_adv=rejected_adv,
        missing_adv_admitted=missing_adv,
        top=[c.ticker for c in ranked[:8]],
    )
    return ranked


def candidate_tickers(candidates: Iterable[WheelCandidate]) -> List[str]:
    return [c.ticker for c in candidates]
