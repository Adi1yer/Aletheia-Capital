"""Cross-sectional residual μ̂: 12-1 momentum, quality, value, vol haircut."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.alpha.factors import score_ticker_from_dossier


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _zscore(values: List[Optional[float]]) -> List[float]:
    xs = [v for v in values if v is not None and math.isfinite(v)]
    if len(xs) < 2:
        return [0.0 if v is None else 0.0 for v in values]
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / max(1, len(xs) - 1)
    std = math.sqrt(var)
    if std < 1e-9:
        return [0.0 for _ in values]
    out: List[float] = []
    for v in values:
        if v is None or not math.isfinite(v):
            out.append(0.0)
        else:
            z = (v - mean) / std
            out.append(max(-3.0, min(3.0, z)))
    return out


def realized_vol(closes: Sequence[float], window: int = 60) -> Optional[float]:
    if len(closes) < 5:
        return None
    use = list(closes)[-max(6, min(int(window) + 1, len(closes))) :]
    rets = []
    for i in range(1, len(use)):
        if use[i - 1] > 0:
            rets.append(math.log(use[i] / use[i - 1]))
    if len(rets) < 4:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(max(var, 0.0) * 252.0)


def momentum_12_1(closes: Sequence[float]) -> Optional[float]:
    """Skip the most recent ~21 sessions; return over the prior year."""
    n = len(closes)
    if n < 40:
        if n >= 5 and closes[0] > 0:
            return (closes[-1] / closes[0]) - 1.0
        return None
    skip = min(21, n // 5)
    end_idx = n - 1 - skip
    lookback = min(252, end_idx)
    start_idx = max(0, end_idx - lookback)
    if start_idx >= end_idx or closes[start_idx] <= 0:
        return None
    return (closes[end_idx] / closes[start_idx]) - 1.0


def _closes_from_dossier(dossier: Optional[Dict[str, Any]]) -> List[float]:
    if not dossier:
        return []
    raw = (dossier.get("prices") or {}).get("closes") or []
    out: List[float] = []
    for x in raw:
        f = _safe_float(x)
        if f is not None and f > 0:
            out.append(f)
    return out


def rank_residual_mu(
    tickers: List[str],
    dossiers: Dict[str, Dict[str, Any]],
    *,
    extra_closes: Optional[Dict[str, Sequence[float]]] = None,
    sectors: Optional[Dict[str, str]] = None,
    liquidity_penalty: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, Any]]:
    """Return (mu_by_ticker, vol_by_ticker, diagnostics)."""
    extra_closes = extra_closes or {}
    sectors = sectors or {}
    mom: List[Optional[float]] = []
    qual: List[Optional[float]] = []
    val: List[Optional[float]] = []
    vol_raw: List[Optional[float]] = []
    vols: Dict[str, float] = {}

    for t in tickers:
        d = dossiers.get(t) or {}
        closes = list(extra_closes.get(t) or []) or _closes_from_dossier(d)
        fac = score_ticker_from_dossier(d)
        m12 = momentum_12_1(closes) if closes else None
        if m12 is None:
            m12 = _safe_float((d.get("prices") or {}).get("return_pct_period"))
            if m12 is not None:
                m12 = m12 / 100.0
        mom.append(m12)
        qual.append(fac.get("quality"))
        val.append(fac.get("value"))
        rv = realized_vol(closes) if closes else None
        vol_raw.append(rv)
        vols[t] = float(rv) if rv is not None and rv > 0 else 0.20

    z_m = _zscore(mom)
    z_q = _zscore(qual)
    z_v = _zscore(val)
    z_vol = _zscore(vol_raw)

    mu: Dict[str, float] = {}
    for i, t in enumerate(tickers):
        raw = 0.40 * z_m[i] + 0.35 * z_q[i] + 0.25 * z_v[i] - 0.15 * z_vol[i]
        if liquidity_penalty and t in liquidity_penalty:
            raw -= float(liquidity_penalty[t])
        mu[t] = round(raw, 6)

    if sectors:
        by_sec: Dict[str, List[str]] = {}
        for t in tickers:
            sec = sectors.get(t) or "Unknown"
            by_sec.setdefault(sec, []).append(t)
        for sec, names in by_sec.items():
            if sec == "Unknown" or len(names) < 3:
                continue
            mean = sum(mu[t] for t in names) / len(names)
            for t in names:
                mu[t] = round(mu[t] - mean, 6)

    diag = {
        "tickers_scored": len(tickers),
        "mom_non_null": sum(1 for x in mom if x is not None),
        "vol_non_null": sum(1 for x in vol_raw if x is not None),
        "sector_residual": bool(sectors),
    }
    return mu, vols, diag
