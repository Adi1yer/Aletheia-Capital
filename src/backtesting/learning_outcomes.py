"""
Per-(agent, ticker) outcomes from consecutive weekly scan_cache runs.

Builds a compact history of: signal, confidence, forward return, directional hit.
Used to inject calibration hints into agent prompts on the next run.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, DefaultDict, Dict, List, Tuple

import structlog

logger = structlog.get_logger()

DEFAULT_TICKER_CALIBRATION_PATH = "data/performance/ticker_agent_calibration.json"
PAIR_SEP = "|"
MAX_EVENTS_PER_PAIR = 24


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


def rebuild_ticker_agent_calibration(
    scan_cache: Any,
    max_run_pairs: int = 40,
    output_path: str = DEFAULT_TICKER_CALIBRATION_PATH,
) -> Dict[str, Any]:
    """
    Walk consecutive cached runs and record per-(agent, ticker) forward returns vs prior signal.

    Requires the same structure as agent_evaluator (prices in risk at T and T+1).
    """
    runs = scan_cache.list_runs(limit=500)
    if len(runs) < 2:
        logger.info("Ticker calibration skipped: fewer than 2 cached runs")
        return {}

    runs = sorted(runs, key=lambda r: r.get("run_date") or "")
    pairs: List[Tuple[Dict, Dict]] = []
    for i in range(len(runs) - 1):
        pairs.append((runs[i], runs[i + 1]))
    pairs = pairs[-max_run_pairs:]

    # pair_key -> list of events (most recent last after extend)
    events: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)

    for left_meta, right_meta in pairs:
        try:
            left = scan_cache.load_run(left_meta["run_id"])
            right = scan_cache.load_run(right_meta["run_id"])
        except Exception as e:
            logger.debug("Calibration pair load failed", error=str(e))
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
                conf = int(sig.get("confidence", 0) or 0)
                sector = _sector_for_ticker(snap if isinstance(snap, dict) else {}, ticker)

                hit: bool | None = None
                if sig_val == "bullish":
                    hit = ret_pct > 0
                elif sig_val == "bearish":
                    hit = ret_pct < 0
                elif sig_val == "neutral":
                    hit = None

                run_date = left_meta.get("run_date") or ""
                key = f"{agent_key}{PAIR_SEP}{ticker.upper()}"
                events[key].append(
                    {
                        "signal_as_of": run_date,
                        "signal": sig_val,
                        "confidence": conf,
                        "forward_return_pct": round(ret_pct, 4),
                        "directionally_correct": hit,
                        "sector": sector,
                    }
                )

    # Trim long tails per pair
    pairs_out: Dict[str, List[Dict[str, Any]]] = {}
    for k, ev in events.items():
        pairs_out[k] = ev[-MAX_EVENTS_PER_PAIR:]

    summary = _rollup_summary(pairs_out)

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "run_pairs_used": len(pairs),
        "pairs": pairs_out,
        "summary": summary,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    try:
        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info(
            "Wrote ticker-agent calibration",
            path=output_path,
            pair_count=len(pairs_out),
        )
    except Exception as e:
        logger.warning("Could not write ticker calibration file", error=str(e))

    return payload


def _rollup_summary(pairs: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Aggregate hit rates per agent (across tickers) for quick inspection."""
    by_agent: DefaultDict[str, Dict[str, float]] = defaultdict(lambda: {"hits": 0.0, "n": 0.0})
    for key, evs in pairs.items():
        agent_key = key.split(PAIR_SEP, 1)[0]
        for ev in evs:
            hit = ev.get("directionally_correct")
            if hit is None:
                continue
            by_agent[agent_key]["n"] += 1
            if hit:
                by_agent[agent_key]["hits"] += 1
    out: Dict[str, Any] = {}
    for ak, row in by_agent.items():
        n = row["n"]
        out[ak] = {
            "directional_observations": int(n),
            "directional_accuracy": round(row["hits"] / n, 4) if n else 0.0,
        }
    return out


def load_ticker_calibration(path: str = DEFAULT_TICKER_CALIBRATION_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def ticker_calibration_block(
    agent_key: str, ticker: str, path: str = DEFAULT_TICKER_CALIBRATION_PATH
) -> str:
    """
    Short paragraph for system prompt: this agent's recent outcomes on this ticker.
    """
    data = load_ticker_calibration(path)
    pairs = data.get("pairs") or {}
    key = f"{agent_key}{PAIR_SEP}{ticker.strip().upper()}"
    evs = pairs.get(key) or []
    if not evs:
        return ""

    recent = evs[-5:]
    lines = []
    for ev in recent:
        sig = ev.get("signal", "?")
        conf = ev.get("confidence", 0)
        ret = ev.get("forward_return_pct")
        ret_f = float(ret) if ret is not None else 0.0
        hit = ev.get("directionally_correct")
        as_of = ev.get("signal_as_of", "")
        hit_s = "n/a" if hit is None else ("hit" if hit else "miss")
        lines.append(
            f"- {as_of}: {sig} @ {conf}% conf → next-period return {ret_f:+.2f}% ({hit_s})"
        )

    hits = [
        ev.get("directionally_correct") for ev in evs if ev.get("directionally_correct") is not None
    ]
    rate = (sum(1 for x in hits if x) / len(hits)) if hits else None
    rate_s = (
        f"{rate:.0%} directional hit rate over {len(hits)} scored calls"
        if hits
        else "insufficient directional samples"
    )

    return (
        "\n## Your past weekly signals on this ticker (weak prior — calibrate confidence)\n"
        + "\n".join(lines)
        + f"\nAggregate on this name: {rate_s}. "
        "If recent misses cluster at high confidence, temper conviction; if hits are strong, stay disciplined.\n"
    )
