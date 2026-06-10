"""Free macro series snippets for agents and macro sleeves."""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
import structlog

logger = structlog.get_logger()

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def fred_latest(series_id: str, api_key: Optional[str] = None) -> Optional[float]:
    key = api_key or ""
    if not key:
        return None
    try:
        r = requests.get(
            _FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            },
            timeout=15,
        )
        r.raise_for_status()
        obs = (r.json() or {}).get("observations") or []
        if not obs:
            return None
        val = obs[0].get("value")
        return float(val) if val not in (None, ".") else None
    except Exception as e:
        logger.debug("FRED fetch failed", series=series_id, error=str(e))
        return None


def macro_context_snippet() -> str:
    """Compact macro block for Druckenmiller-style agents (yfinance fallback)."""
    import os

    import yfinance as yf

    lines = ["MACRO CONTEXT (informational):"]
    fred_key = (os.environ.get("FRED_API_KEY") or "").strip()
    if fred_key:
        fed = fred_latest("FEDFUNDS", fred_key)
        t10 = fred_latest("DGS10", fred_key)
        if fed is not None:
            lines.append(f"- Fed funds rate (latest): {fed:.2f}%")
        if t10 is not None:
            lines.append(f"- 10Y Treasury yield: {t10:.2f}%")
    try:
        spy = yf.Ticker("SPY").history(period="6mo")
        tlt = yf.Ticker("TLT").history(period="6mo")
        if spy is not None and len(spy) >= 2:
            ret = (spy["Close"].iloc[-1] - spy["Close"].iloc[0]) / spy["Close"].iloc[0] * 100
            lines.append(f"- SPY 6m return: {ret:.1f}%")
        if tlt is not None and len(tlt) >= 2:
            ret = (tlt["Close"].iloc[-1] - tlt["Close"].iloc[0]) / tlt["Close"].iloc[0] * 100
            lines.append(f"- TLT 6m return: {ret:.1f}%")
    except Exception:
        pass
    return "\n".join(lines)


def spy_regime_harvest() -> bool:
    """True when SPY below 200d SMA (risk-off)."""
    import yfinance as yf

    try:
        hist = yf.Ticker("SPY").history(period="1y")
        if hist is None or len(hist) < 200:
            return False
        last = float(hist["Close"].iloc[-1])
        sma = float(hist["Close"].tail(200).mean())
        return last < sma * 0.99
    except Exception:
        return False
