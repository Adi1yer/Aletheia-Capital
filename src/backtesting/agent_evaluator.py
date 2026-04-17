"""Build agent scorecards from cached weekly scan runs (no extra market API calls)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple

import json
import os

import structlog

logger = structlog.get_logger()


def _sector_for_ticker(data_snapshot: Dict[str, Any], ticker: str) -> str:
    snap = (data_snapshot or {}).get(ticker) or {}
    if not isinstance(snap, dict):
        return "unknown"
    m = snap.get("metrics") or {}
    if isinstance(m, dict):
        sec = m.get("sector") or m.get("industry")
        if sec:
            return str(sec)[:40]
    return "unknown"


def evaluate_scan_cache(
    scan_cache: Any,
    max_run_pairs: int = 20,
    output_path: str = "data/performance/agent_scorecard.json",
) -> Dict[str, Any]:
    """
    Compare consecutive cached runs: signal at T vs return T→T+1.

    Returns a dict suitable for JSON export and for PerformanceTracker / feedback.
    """
    runs = scan_cache.list_runs(limit=500)
    if len(runs) < 2:
        logger.info("Scorecard skipped: fewer than 2 cached runs")
        return {}

    runs = sorted(runs, key=lambda r: r.get("run_date") or "")
    pairs: List[Tuple[Dict, Dict]] = []
    for i in range(len(runs) - 1):
        pairs.append((runs[i], runs[i + 1]))
    pairs = pairs[-max_run_pairs:]

    correct = defaultdict(int)
    total_dir = defaultdict(int)
    cw_ret_sum = defaultdict(float)
    hyp_pnl_sum = defaultdict(float)
    hyp_count = defaultdict(int)
    sec_correct = defaultdict(lambda: defaultdict(int))
    sec_total = defaultdict(lambda: defaultdict(int))

    for left_meta, right_meta in pairs:
        try:
            left = scan_cache.load_run(left_meta["run_id"])
            right = scan_cache.load_run(right_meta["run_id"])
        except Exception as e:
            logger.debug("Scorecard pair load failed", error=str(e))
            continue

        signals = left.get("signals") or {}
        risk_l = left.get("risk") or {}
        risk_r = right.get("risk") or {}
        snap = left.get("data_snapshot") or {}

        prices_l = {
            t: float(r.get("current_price", 0) or 0)
            for t, r in risk_l.items()
            if isinstance(r, dict)
        }
        prices_r = {
            t: float(r.get("current_price", 0) or 0)
            for t, r in risk_r.items()
            if isinstance(r, dict)
        }
        common = set(prices_l) & set(prices_r)
        if not common:
            continue

        for agent_key, ticker_signals in signals.items():
            if not isinstance(ticker_signals, dict):
                continue
            for ticker, sig in ticker_signals.items():
                if ticker not in common:
                    continue
                if not isinstance(sig, dict):
                    continue
                p0, p1 = prices_l.get(ticker) or 0, prices_r.get(ticker) or 0
                if p0 <= 0:
                    continue
                ret_pct = (p1 - p0) / p0 * 100.0
                sig_val = sig.get("signal")
                conf = int(sig.get("confidence", 0) or 0) / 100.0

                sector = _sector_for_ticker(snap if isinstance(snap, dict) else {}, ticker)

                if sig_val == "bullish":
                    cw_ret_sum[agent_key] += ret_pct * conf
                    hyp_pnl_sum[agent_key] += ret_pct
                    hyp_count[agent_key] += 1
                    total_dir[agent_key] += 1
                    if ret_pct > 0:
                        correct[agent_key] += 1
                    sec_total[agent_key][sector] += 1
                    if ret_pct > 0:
                        sec_correct[agent_key][sector] += 1
                elif sig_val == "bearish":
                    cw_ret_sum[agent_key] += (-ret_pct) * conf
                    hyp_pnl_sum[agent_key] += (-ret_pct)
                    hyp_count[agent_key] += 1
                    total_dir[agent_key] += 1
                    if ret_pct < 0:
                        correct[agent_key] += 1
                    sec_total[agent_key][sector] += 1
                    if ret_pct < 0:
                        sec_correct[agent_key][sector] += 1

    agents_out: Dict[str, Any] = {}
    for agent_key in set(correct.keys()) | set(total_dir.keys()):
        td = total_dir[agent_key]
        acc = (correct[agent_key] / td) if td else 0.0
        hyp = (hyp_pnl_sum[agent_key] / hyp_count[agent_key]) if hyp_count[agent_key] else 0.0
        sec_hits: Dict[str, float] = {}
        for sec, tot in sec_total[agent_key].items():
            if tot <= 0:
                continue
            sec_hits[sec] = round(sec_correct[agent_key][sec] / tot, 4)
        agents_out[agent_key] = {
            "directional_accuracy": round(acc, 4),
            "directional_observations": td,
            "confidence_weighted_return_pct": round(cw_ret_sum[agent_key], 4),
            "hypothetical_avg_return_pct": round(hyp, 4),
            "sector_directional_accuracy": sec_hits,
        }

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "run_pairs_used": len(pairs),
        "agents": agents_out,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    try:
        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info("Wrote agent scorecard", path=output_path, agents=len(agents_out))
    except Exception as e:
        logger.warning("Could not write scorecard file", error=str(e))

    return payload


def load_scorecard(path: str = "data/performance/agent_scorecard.json") -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}
