"""Empirical confidence calibration tables per agent."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

CALIBRATION_PATH = Path("data/performance/confidence_calibration.json")

BINS = [(50, 60), (60, 70), (70, 80), (80, 91)]


def _bin_label(lo: int, hi: int) -> str:
    return f"{lo}-{hi}"


def build_from_scorecard(
    scorecard: Dict[str, Any],
    ticker_calibration: Optional[Dict[str, Any]] = None,
    decision_rows: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build per-agent confidence bin hit rates."""
    agents_out: Dict[str, Any] = {}
    agents = scorecard.get("agents") or {}
    rows_by_agent: Dict[str, list[Dict[str, Any]]] = {}
    for r in decision_rows or []:
        for agent_key in (r.get("agents_for") or []):
            rows_by_agent.setdefault(agent_key, []).append(r)

    for ak, row in agents.items():
        if not isinstance(row, dict):
            continue
        acc = float(row.get("directional_accuracy") or 0.5)
        bins: Dict[str, Dict[str, Any]] = {}
        for lo, hi in BINS:
            agent_rows = [
                rr
                for rr in rows_by_agent.get(ak, [])
                if rr.get("directionally_correct") is not None
                and lo <= int(rr.get("confidence") or 0) < hi
            ]
            if agent_rows:
                hit_rate = sum(1 for rr in agent_rows if rr.get("directionally_correct")) / len(agent_rows)
                obs = len(agent_rows)
            else:
                mid = (lo + hi) / 2.0
                hit_rate = min(1.0, max(0.0, acc / max(0.01, mid / 100.0) * (mid / 100.0)))
                obs = int(row.get("directional_observations", 0) or 0) // len(BINS)
            bins[_bin_label(lo, hi)] = {
                "empirical_hit_rate": round(hit_rate, 4),
                "observations": int(obs),
            }
        agents_out[ak] = {"bins": bins, "global_accuracy": acc}

    if ticker_calibration:
        pairs = ticker_calibration.get("pairs") or {}
        for key, evs in pairs.items():
            if "|" not in key:
                continue
            ak = key.split("|", 1)[0]
            hits = [e for e in evs if e.get("directionally_correct") is not None]
            if len(hits) < 3:
                continue
            rate = sum(1 for h in hits if h.get("directionally_correct")) / len(hits)
            entry = agents_out.setdefault(ak, {"bins": {}, "global_accuracy": rate})
            entry["ticker_adjustment"] = round(rate, 4)

    return {
        "agents": agents_out,
        "bin_edges": [list(b) for b in BINS],
    }


def save_calibration(payload: Dict[str, Any], path: Path = CALIBRATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_calibration(path: Path = CALIBRATION_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def calibrate_confidence(agent_key: str, raw_conf: int, path: Path = CALIBRATION_PATH) -> int:
    """Map raw agent confidence to empirically calibrated confidence."""
    raw_conf = int(max(0, min(100, raw_conf)))
    if raw_conf <= 0:
        return raw_conf
    data = load_calibration(path)
    agent = (data.get("agents") or {}).get(agent_key) or {}
    bins = agent.get("bins") or {}
    for lo, hi in BINS:
        if lo <= raw_conf < hi:
            b = bins.get(_bin_label(lo, hi)) or {}
            hit = b.get("empirical_hit_rate")
            if hit is not None and b.get("observations", 0) >= 3:
                return int(max(30, min(95, round(float(hit) * 100))))
            break
    global_acc = agent.get("global_accuracy")
    if global_acc is not None:
        return int(max(30, min(95, round(float(global_acc) * 100 * (raw_conf / 100.0) + raw_conf * 0.5) / 1.5)))
    return raw_conf


def rebuild_calibration_files() -> Dict[str, Any]:
    from src.backtesting.agent_evaluator import load_scorecard
    from src.backtesting.learning_outcomes import load_ticker_calibration
    from src.performance.decision_ledger import recent_entries

    sc = load_scorecard() or {}
    tc = load_ticker_calibration()
    payload = build_from_scorecard(sc, tc, recent_entries(weeks=26))
    save_calibration(payload)
    logger.info("Rebuilt confidence calibration", agent_count=len(payload.get("agents") or {}))
    return payload


def reliability_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    agents = payload.get("agents") or {}
    ece_sum = 0.0
    ece_n = 0
    for row in agents.values():
        bins = (row or {}).get("bins") or {}
        for label, b in bins.items():
            try:
                lo, hi = [int(x) for x in str(label).split("-")]
            except Exception:
                continue
            mid = ((lo + hi) / 2.0) / 100.0
            hit = float(b.get("empirical_hit_rate") or 0.0)
            obs = int(b.get("observations") or 0)
            if obs <= 0:
                continue
            ece_sum += abs(hit - mid) * obs
            ece_n += obs
    return {"ece": round(ece_sum / max(1, ece_n), 6), "observations": ece_n}
