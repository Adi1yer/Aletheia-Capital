"""Tiered biotech candidate discovery: strict → relaxed → watchlist."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.biotech.candidate_discovery import discover_catalyst_candidates
from src.biotech.watchlist import load_biotech_tickers
from src.config.settings import settings

logger = structlog.get_logger()

DISCOVERY_KNOBS = frozenset(
    {
        "discovery_min_phase",
        "readout_max_forward_days",
        "min_days_to_readout",
    }
)


def run_discovery_ladder(
    *,
    forward_days: int,
    past_grace_days: int,
    fallback_forward_days: int,
    fallback_past_grace_days: int,
    max_universe: int,
    max_candidates: int,
    broker: Optional[Any],
    policy: Dict[str, Any],
    discovery_kw: Optional[Dict[str, Any]] = None,
    biotech_first: bool = True,
    profile_seed_size: int = 900,
) -> Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
    """
    Run strict → relaxed → watchlist discovery.

    Returns (tickers, primary_discovery_info, ladder_meta).
    ladder_meta includes discovery_stage and per-stage diagnostics.
    """
    discovery_kw = dict(discovery_kw or {})
    ladder_meta: Dict[str, Any] = {"stages": []}

    strict_min_phase = int(
        discovery_kw.get("min_phase")
        if discovery_kw.get("min_phase") is not None
        else policy.get("discovery_min_phase", settings.biotech_discovery_min_phase)
    )
    strict_rd = discovery_kw.get("readout_max_forward_days")
    if strict_rd is None:
        rd_raw = policy.get(
            "readout_max_forward_days", settings.biotech_discovery_readout_max_forward_days
        )
        strict_rd = int(rd_raw) if rd_raw is not None and int(rd_raw) > 0 else None
    else:
        strict_rd = int(strict_rd) if int(strict_rd) > 0 else None

    common = {
        "max_universe": max_universe,
        "max_candidates": max_candidates,
        "broker": broker,
        "policy": policy,
        "biotech_first": biotech_first,
        "profile_seed_size": profile_seed_size,
        **{k: v for k, v in discovery_kw.items() if k not in ("min_phase", "readout_max_forward_days")},
    }

    # Stage 1: strict
    tickers, strict_diag = discover_catalyst_candidates(
        forward_days=forward_days,
        past_grace_days=past_grace_days,
        min_phase=strict_min_phase,
        readout_max_forward_days=strict_rd,
        **common,
    )
    strict_diag["discovery_stage"] = "strict"
    ladder_meta["stages"].append(
        {"stage": "strict", "selected_count": len(tickers), "diagnostics": strict_diag}
    )
    if tickers:
        ladder_meta["discovery_stage"] = "strict"
        ladder_meta["near_miss_summaries"] = strict_diag.get("near_miss_summaries") or []
        return tickers, strict_diag, ladder_meta

    # Stage 2: relaxed gates + wider window
    relaxed_min_phase = 1
    relaxed_rd = 180
    tickers, relaxed_diag = discover_catalyst_candidates(
        forward_days=int(fallback_forward_days),
        past_grace_days=int(fallback_past_grace_days),
        min_phase=relaxed_min_phase,
        readout_max_forward_days=relaxed_rd,
        **common,
    )
    relaxed_diag["discovery_stage"] = "relaxed"
    ladder_meta["stages"].append(
        {"stage": "relaxed", "selected_count": len(tickers), "diagnostics": relaxed_diag}
    )
    if tickers:
        ladder_meta["discovery_stage"] = "relaxed"
        ladder_meta["strict_diagnostics"] = strict_diag
        ladder_meta["near_miss_summaries"] = strict_diag.get("near_miss_summaries") or []
        return tickers, relaxed_diag, ladder_meta

    # Stage 3: watchlist (no cap filter; still readout + optionability)
    watchlist = load_biotech_tickers()
    watchlist_diag: Dict[str, Any] = {
        "discovery_stage": "watchlist",
        "watchlist_count": len(watchlist),
        "selected_count": 0,
        "selected_tickers": [],
        "candidate_summaries": [],
        "near_miss_summaries": [],
    }
    if watchlist:
        tickers, wl_diag = discover_catalyst_candidates(
            forward_days=int(fallback_forward_days),
            past_grace_days=int(fallback_past_grace_days),
            min_phase=relaxed_min_phase,
            readout_max_forward_days=relaxed_rd,
            seed_tickers=watchlist,
            skip_cap_filter=True,
            broker=broker,
            policy=policy,
            max_candidates=max_candidates,
        )
        watchlist_diag = {**wl_diag, "discovery_stage": "watchlist", "watchlist_count": len(watchlist)}
        ladder_meta["stages"].append(
            {"stage": "watchlist", "selected_count": len(tickers), "diagnostics": watchlist_diag}
        )
        if tickers:
            ladder_meta["discovery_stage"] = "watchlist"
            ladder_meta["strict_diagnostics"] = strict_diag
            ladder_meta["near_miss_summaries"] = (
                strict_diag.get("near_miss_summaries")
                or relaxed_diag.get("near_miss_summaries")
                or []
            )
            return tickers, watchlist_diag, ladder_meta

    ladder_meta["discovery_stage"] = "none"
    ladder_meta["strict_diagnostics"] = strict_diag
    ladder_meta["relaxed_diagnostics"] = relaxed_diag
    ladder_meta["watchlist_diagnostics"] = watchlist_diag
    ladder_meta["near_miss_summaries"] = strict_diag.get("near_miss_summaries") or []
    logger.warning(
        "Discovery ladder exhausted",
        stage="none",
        strict_excluded_readout=strict_diag.get("excluded_no_readout_window"),
    )
    return [], strict_diag, ladder_meta
