"""Discover biotech catalyst candidates from broad equity universe."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import structlog
import yfinance as yf

from src.biotech.ingest import build_snapshot
from src.biotech.readout_window import best_readout_date, snapshot_has_readout_catalyst
from src.data.universe import StockUniverse

logger = structlog.get_logger()

_BIOTECH_INDUSTRY_HINTS = (
    "biotech",
    "biotechnology",
    "drug",
    "pharmaceutical",
    "life sciences",
)


def _profile_ticker(ticker: str) -> Dict[str, Any]:
    """Fetch lightweight metadata for universe filtering."""
    out: Dict[str, Any] = {
        "ticker": ticker,
        "is_biotech": False,
        "last_price": 0.0,
        "avg_dollar_volume_30d": 0.0,
        "has_yf_options": False,
        "error": "",
    }
    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
        sector = str(info.get("sector") or "").lower()
        industry = str(info.get("industry") or "").lower()
        out["is_biotech"] = (
            "healthcare" in sector and any(h in industry for h in _BIOTECH_INDUSTRY_HINTS)
        ) or any(h in industry for h in _BIOTECH_INDUSTRY_HINTS)
        hist = tk.history(period="1mo")
        if hist is not None and not hist.empty:
            out["last_price"] = float(hist["Close"].iloc[-1])
            out["avg_dollar_volume_30d"] = float((hist["Close"] * hist["Volume"]).mean())
        try:
            out["has_yf_options"] = bool(getattr(tk, "options", []) or [])
        except Exception:
            out["has_yf_options"] = False
    except Exception as e:
        out["error"] = str(e)
    return out


def discover_catalyst_candidates(
    *,
    forward_days: int,
    past_grace_days: int,
    max_universe: int = 320,
    max_candidates: int = 20,
    min_avg_dollar_volume: float = 20_000_000.0,
    broker: Optional[Any] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """
    Discovery-first biotech universe construction.

    Steps:
    1) pull broad tradable universe
    2) sector/industry biotech filter + liquidity
    3) optional optionability gate
    4) snapshot and readout-window gate
    5) rank by nearest readout date and return top candidates
    """
    universe = StockUniverse()
    seeds = universe.get_trading_universe(
        full_market=True,
        max_stocks=int(max_universe),
        apply_filters=True,
        rank_by_market_cap=True,
    )
    diagnostics: Dict[str, Any] = {
        "seed_count": len(seeds),
        "profiled_count": 0,
        "excluded_non_biotech": 0,
        "excluded_illiquid": 0,
        "excluded_non_optionable": 0,
        "excluded_no_readout_window": 0,
        "candidate_count": 0,
        "selected_count": 0,
        "selected_tickers": [],
    }
    if not seeds:
        return [], diagnostics

    profiled: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(24, len(seeds))) as ex:
        futures = [ex.submit(_profile_ticker, t) for t in seeds]
        for fut in as_completed(futures):
            profiled.append(fut.result())
    diagnostics["profiled_count"] = len(profiled)

    screened: List[Dict[str, Any]] = []
    for p in profiled:
        if not p.get("is_biotech"):
            diagnostics["excluded_non_biotech"] += 1
            continue
        if float(p.get("avg_dollar_volume_30d") or 0.0) < float(min_avg_dollar_volume):
            diagnostics["excluded_illiquid"] += 1
            continue
        screened.append(p)

    survivors: List[Tuple[str, str]] = []
    for p in screened:
        t = str(p["ticker"])
        if broker is not None:
            px = float(p.get("last_price") or 0.0)
            if px <= 0:
                diagnostics["excluded_non_optionable"] += 1
                continue
            contracts = broker.get_option_contracts(
                underlying=t,
                option_type="call",
                strike_gte=max(1.0, px * 0.8),
                strike_lte=px * 1.2,
                limit=8,
            )
            if not contracts:
                diagnostics["excluded_non_optionable"] += 1
                continue
        elif not p.get("has_yf_options"):
            diagnostics["excluded_non_optionable"] += 1
            continue

        snap = build_snapshot(t)
        if not snapshot_has_readout_catalyst(
            snap, forward_days=forward_days, past_grace_days=past_grace_days
        ):
            diagnostics["excluded_no_readout_window"] += 1
            continue
        rd = ""
        for tr in snap.trials:
            d = best_readout_date(tr)
            if d is not None:
                rd = d.isoformat()
                break
        survivors.append((t, rd))

    diagnostics["candidate_count"] = len(survivors)
    survivors.sort(key=lambda x: x[1] or "9999-99-99")
    selected = [t for t, _ in survivors[: max(0, int(max_candidates))]]
    diagnostics["selected_count"] = len(selected)
    diagnostics["selected_tickers"] = selected

    logger.info("Biotech candidate discovery", **diagnostics)
    return selected, diagnostics
