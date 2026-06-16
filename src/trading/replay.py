"""Deterministic replay and diff helpers for cached runs."""

from __future__ import annotations

from typing import Any, Dict

from src.scan_cache import ScanCache
from src.trading.pipeline import TradingPipeline


def replay_run(run_id: str, *, scan_cache: ScanCache | None = None) -> Dict[str, Any]:
    cache = scan_cache or ScanCache()
    run = cache.load_run(run_id)
    tickers = list((run.get("meta") or {}).get("tickers") or []) or list(run.get("risk", {}).keys())
    cfg = dict((run.get("meta") or {}).get("config") or {})
    cfg["save_to_cache"] = False
    pipe = TradingPipeline()
    return pipe.run_weekly_trading(tickers=tickers, execute=False, scan_cache=None, run_config=cfg)


def decision_diff(baseline: Dict[str, Any], replayed: Dict[str, Any]) -> Dict[str, Any]:
    b = baseline.get("decisions") or {}
    r = replayed.get("decisions") or {}
    out: Dict[str, Any] = {"changed": [], "missing": [], "new": []}
    for t, bd in b.items():
        rd = r.get(t)
        if rd is None:
            out["missing"].append(t)
            continue
        ba = bd.get("action") if isinstance(bd, dict) else str(bd)
        ra = rd.get("action") if isinstance(rd, dict) else str(rd)
        bc = int((bd or {}).get("confidence") or 0) if isinstance(bd, dict) else 0
        rc = int((rd or {}).get("confidence") or 0) if isinstance(rd, dict) else 0
        if ba != ra or bc != rc:
            out["changed"].append({"ticker": t, "baseline_action": ba, "replay_action": ra, "baseline_conf": bc, "replay_conf": rc})
    for t in r.keys():
        if t not in b:
            out["new"].append(t)
    return out

