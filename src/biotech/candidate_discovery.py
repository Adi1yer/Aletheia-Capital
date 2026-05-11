"""Discover biotech catalyst candidates from broad equity universe."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.biotech.ingest import build_snapshot
from src.biotech.readout_window import best_readout_date, snapshot_has_readout_catalyst
from src.config.settings import settings

logger = structlog.get_logger()

_BIOTECH_INDUSTRY_HINTS = (
    "biotech",
    "biotechnology",
    "drug",
    "pharmaceutical",
    "life sciences",
)


def _load_discovery_blocklist(path: str, env_csv: str) -> Set[str]:
    """Tickers to hard-exclude from discovery (file + BIOTECH_DISCOVERY_BLOCKLIST)."""
    out: Set[str] = set()
    p = Path(path)
    if p.is_file():
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        for line in raw.splitlines():
            s = line.split("#")[0].strip().upper()
            if s:
                out.add(s)
    for part in (env_csv or "").split(","):
        s = part.strip().upper()
        if s:
            out.add(s)
    return out


def _profile_ticker(ticker: str) -> Dict[str, Any]:
    """Fetch lightweight metadata for universe filtering."""
    import yfinance as yf

    out: Dict[str, Any] = {
        "ticker": ticker,
        "is_biotech": False,
        "last_price": 0.0,
        "avg_dollar_volume_30d": 0.0,
        "has_yf_options": False,
        "market_cap": None,
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
        mc = info.get("marketCap")
        if mc is not None:
            try:
                out["market_cap"] = float(mc)
            except (TypeError, ValueError):
                out["market_cap"] = None
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
    min_market_cap_usd: Optional[float] = None,
    max_market_cap_usd: Optional[float] = None,
    exclude_missing_market_cap: Optional[bool] = None,
    blocklist: Optional[Set[str]] = None,
    min_phase: Optional[int] = None,
    readout_max_forward_days: Optional[int] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """
    Discovery-first biotech universe construction.

    Steps:
    1) pull broad tradable universe (not ranked by mega-cap by default)
    2) sector/industry biotech filter + liquidity + market cap + blocklist
    3) optional optionability gate
    4) snapshot and readout-window gate (optional phase + tighter forward cap)
    5) rank by nearest readout date and return top candidates
    """
    excl_missing = (
        bool(settings.biotech_discovery_exclude_missing_market_cap)
        if exclude_missing_market_cap is None
        else bool(exclude_missing_market_cap)
    )
    min_cap = (
        float(settings.biotech_discovery_min_market_cap_usd)
        if min_market_cap_usd is None
        else float(min_market_cap_usd)
    )
    max_cap_raw = (
        float(settings.biotech_discovery_max_market_cap_usd)
        if max_market_cap_usd is None
        else float(max_market_cap_usd)
    )
    max_cap: Optional[float] = None if max_cap_raw <= 0 else max_cap_raw
    min_cap_eff: Optional[float] = None if min_cap <= 0 else min_cap

    min_ph = int(settings.biotech_discovery_min_phase) if min_phase is None else int(min_phase)
    rd_cap = (
        settings.biotech_discovery_readout_max_forward_days
        if readout_max_forward_days is None
        else readout_max_forward_days
    )
    rd_cap_i: Optional[int] = int(rd_cap) if rd_cap is not None and int(rd_cap) > 0 else None

    bl = (
        blocklist
        if blocklist is not None
        else _load_discovery_blocklist(
            settings.biotech_discovery_blocklist_path,
            os.environ.get("BIOTECH_DISCOVERY_BLOCKLIST", ""),
        )
    )

    from src.data.universe import StockUniverse

    universe = StockUniverse()
    seeds = universe.get_trading_universe(
        full_market=True,
        max_stocks=int(max_universe),
        apply_filters=True,
        rank_by_market_cap=False,
    )
    diagnostics: Dict[str, Any] = {
        "seed_count": len(seeds),
        "profiled_count": 0,
        "excluded_non_biotech": 0,
        "excluded_illiquid": 0,
        "excluded_market_cap_too_small": 0,
        "excluded_market_cap_too_large": 0,
        "excluded_missing_market_cap": 0,
        "excluded_blocklist": 0,
        "excluded_non_optionable": 0,
        "excluded_no_readout_window": 0,
        "candidate_count": 0,
        "selected_count": 0,
        "selected_tickers": [],
        "discovery_min_phase": min_ph,
        "discovery_readout_max_forward_days": rd_cap_i,
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
        t_sym = str(p["ticker"]).strip().upper()
        if t_sym in bl:
            diagnostics["excluded_blocklist"] += 1
            continue
        mc = p.get("market_cap")
        if mc is None or (isinstance(mc, float) and mc <= 0):
            if excl_missing:
                diagnostics["excluded_missing_market_cap"] += 1
                continue
        else:
            mcv = float(mc)
            if min_cap_eff is not None and mcv < min_cap_eff:
                diagnostics["excluded_market_cap_too_small"] += 1
                continue
            if max_cap is not None and mcv > max_cap:
                diagnostics["excluded_market_cap_too_large"] += 1
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
            snap,
            forward_days=forward_days,
            past_grace_days=past_grace_days,
            min_phase=min_ph,
            readout_max_forward_days=rd_cap_i,
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
