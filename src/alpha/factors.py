"""Deterministic factor scores from ticker dossiers (no LLM)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def score_ticker_from_dossier(dossier: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Return raw factor scores in ~[-1, 1] for mom / quality / value."""
    out = {"momentum": 0.0, "quality": 0.0, "value": 0.0}
    if not dossier:
        return out
    trends = dossier.get("trends") or {}
    tech = dossier.get("technicals") or {}
    metrics = (dossier.get("metrics") or [{}])[0] if dossier.get("metrics") else {}

    ret_1m = _safe_float(trends.get("return_1m_pct") or tech.get("return_1m_pct"))
    ret_3m = _safe_float(trends.get("return_3m_pct") or tech.get("return_3m_pct"))
    if ret_1m is not None and ret_3m is not None:
        out["momentum"] = max(-1.0, min(1.0, (ret_1m * 0.4 + ret_3m * 0.6) / 15.0))
    elif ret_3m is not None:
        out["momentum"] = max(-1.0, min(1.0, ret_3m / 20.0))

    roe = _safe_float(metrics.get("return_on_equity") or metrics.get("roe"))
    margin = _safe_float(metrics.get("operating_margin") or metrics.get("net_margin"))
    if roe is not None:
        out["quality"] += max(-0.5, min(0.5, roe / 40.0))
    if margin is not None:
        out["quality"] += max(-0.5, min(0.5, margin / 30.0))
    out["quality"] = max(-1.0, min(1.0, out["quality"]))

    pe = _safe_float(metrics.get("price_to_earnings") or metrics.get("pe_ratio"))
    pb = _safe_float(metrics.get("price_to_book") or metrics.get("pb_ratio"))
    if pe is not None and pe > 0:
        out["value"] += max(-0.5, min(0.5, (25.0 - pe) / 50.0))
    if pb is not None and pb > 0:
        out["value"] += max(-0.5, min(0.5, (3.0 - pb) / 6.0))
    out["value"] = max(-1.0, min(1.0, out["value"]))
    return out


def composite_mu(factors: Dict[str, float], *, weights: Optional[Dict[str, float]] = None) -> float:
    w = weights or {"momentum": 0.4, "quality": 0.35, "value": 0.25}
    total = 0.0
    denom = 0.0
    for k, wt in w.items():
        total += float(factors.get(k, 0.0)) * float(wt)
        denom += float(wt)
    return round(total / max(denom, 1e-9), 6)


def rank_universe(
    tickers: List[str],
    dossiers: Dict[str, Dict[str, Any]],
    *,
    liquidity_penalty: Optional[Dict[str, float]] = None,
) -> List[Tuple[str, float, Dict[str, float]]]:
    """Rank tickers by composite μ̂ descending."""
    rows: List[Tuple[str, float, Dict[str, float]]] = []
    for t in tickers:
        fac = score_ticker_from_dossier(dossiers.get(t))
        mu = composite_mu(fac)
        if liquidity_penalty and t in liquidity_penalty:
            mu -= float(liquidity_penalty[t])
        rows.append((t, mu, fac))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows


def percentile_rank(ticker: str, ranked: List[Tuple[str, float, Dict[str, float]]]) -> float:
    if not ranked:
        return 0.0
    order = [t for t, _, _ in ranked]
    if ticker not in order:
        return 0.0
    idx = order.index(ticker)
    return 1.0 - (idx / max(1, len(order) - 1))
