"""Ticker sector lookup for concentration caps.

Resolution order:
1. Explicit hint (dossier / caller)
2. config/ticker_sectors.json overrides
3. Cached runtime map (data/cache/sector_map.json)
4. S&P 500 GICS constituents (fetched once, cached)
5. Yahoo Finance (cached on success)
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

SECTORS_PATH = Path("config/ticker_sectors.json")
CACHE_PATH = Path("data/cache/sector_map.json")
SP500_CACHE_PATH = Path("data/cache/sp500_sectors.json")
SP500_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "master/data/constituents.csv"
)

# Canonical GICS-style labels used by max_sector_pct.
_CANONICAL = {
    "information technology": "Information Technology",
    "technology": "Information Technology",
    "health care": "Health Care",
    "healthcare": "Health Care",
    "financials": "Financials",
    "financial services": "Financials",
    "financial": "Financials",
    "consumer discretionary": "Consumer Discretionary",
    "consumer cyclical": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "consumer defensive": "Consumer Staples",
    "communication services": "Communication Services",
    "communication": "Communication Services",
    "communications": "Communication Services",
    "industrials": "Industrials",
    "industrial": "Industrials",
    "energy": "Energy",
    "utilities": "Utilities",
    "real estate": "Real Estate",
    "materials": "Materials",
    "basic materials": "Materials",
}


def normalize_sector(raw: Optional[str]) -> str:
    if not raw:
        return "Unknown"
    s = str(raw).strip()
    if not s or s.lower() in {"unknown", "n/a", "none", "null"}:
        return "Unknown"
    return _CANONICAL.get(s.lower(), s)


@lru_cache(maxsize=1)
def _load_static() -> Dict[str, str]:
    if not SECTORS_PATH.is_file():
        return {}
    try:
        raw = json.loads(SECTORS_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return {str(k).upper(): normalize_sector(v) for k, v in raw.items() if v}


def _load_json_map(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return {str(k).upper(): normalize_sector(v) for k, v in raw.items() if v}


def _save_json_map(path: Path, data: Dict[str, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(sorted(data.items())), indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        logger.debug("Sector map save failed", path=str(path), error=str(e))


def _fetch_sp500_sectors(*, force: bool = False) -> Dict[str, str]:
    if not force and SP500_CACHE_PATH.is_file():
        cached = _load_json_map(SP500_CACHE_PATH)
        if cached:
            return cached
    try:
        with urllib.request.urlopen(SP500_URL, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(raw))
        out: Dict[str, str] = {}
        for row in reader:
            sym = (row.get("Symbol") or "").strip().upper().replace(".", "-")
            sec = normalize_sector(row.get("GICS Sector") or row.get("Sector"))
            if sym and sec != "Unknown":
                out[sym] = sec
        if out:
            _save_json_map(SP500_CACHE_PATH, out)
            runtime = _load_json_map(CACHE_PATH)
            runtime.update(out)
            _save_json_map(CACHE_PATH, runtime)
        return out
    except Exception as e:
        logger.warning("S&P sector fetch failed", error=str(e))
        return _load_json_map(SP500_CACHE_PATH)


def _yahoo_sector(ticker: str) -> Optional[str]:
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info or {}
        sec = normalize_sector(info.get("sector"))
        return sec if sec != "Unknown" else None
    except Exception as e:
        logger.debug("Yahoo sector lookup failed", ticker=ticker, error=str(e))
        return None


def remember_sector(ticker: str, sector: str) -> str:
    """Persist a resolved sector for future runs."""
    sec = normalize_sector(sector)
    if sec == "Unknown":
        return sec
    t = ticker.upper().strip()
    runtime = _load_json_map(CACHE_PATH)
    if runtime.get(t) != sec:
        runtime[t] = sec
        _save_json_map(CACHE_PATH, runtime)
    return sec


def get_sector(ticker: str, hint: Optional[str] = None) -> str:
    """Resolve sector for a ticker (never raises)."""
    t = (ticker or "").upper().strip()
    if not t:
        return "Unknown"

    hinted = normalize_sector(hint)
    if hinted != "Unknown":
        return remember_sector(t, hinted)

    static = _load_static().get(t)
    if static and static != "Unknown":
        return static

    runtime = _load_json_map(CACHE_PATH).get(t)
    if runtime and runtime != "Unknown":
        return runtime

    sp500 = _fetch_sp500_sectors().get(t)
    if sp500 and sp500 != "Unknown":
        return remember_sector(t, sp500)

    alt = t.replace("-", ".") if "-" in t else t.replace(".", "-")
    if alt != t:
        for source in (_load_static(), _load_json_map(CACHE_PATH), _fetch_sp500_sectors()):
            sec = source.get(alt)
            if sec and sec != "Unknown":
                return remember_sector(t, sec)

    yahoo = _yahoo_sector(t)
    if yahoo:
        return remember_sector(t, yahoo)

    return "Unknown"


def resolve_sector(
    ticker: str,
    *,
    dossier: Optional[Dict[str, Any]] = None,
    risk: Optional[Dict[str, Any]] = None,
) -> str:
    hint = None
    if isinstance(risk, dict):
        hint = risk.get("sector")
    if not hint and isinstance(dossier, dict):
        ctx = dossier.get("context") or {}
        hint = ctx.get("sector")
        if not hint:
            metrics = dossier.get("metrics") or []
            if metrics and isinstance(metrics[0], dict):
                hint = metrics[0].get("sector")
    return get_sector(ticker, hint=hint if isinstance(hint, str) else None)


def prefetch_sectors(
    tickers: list[str],
    *,
    dossiers: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Resolve sectors for a universe (uses cache; Yahoo only on misses)."""
    dossiers = dossiers or {}
    _fetch_sp500_sectors()
    out: Dict[str, str] = {}
    for t in tickers:
        out[t] = resolve_sector(t, dossier=dossiers.get(t))
    return out
