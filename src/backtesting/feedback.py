"""Turn scorecard metrics into short prompt blocks per agent."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.backtesting.agent_evaluator import evaluate_scan_cache, load_scorecard
from src.backtesting.learning_outcomes import rebuild_ticker_agent_calibration

logger = structlog.get_logger()

DEFAULT_FEEDBACK_PATH = "data/performance/agent_feedback.json"


def _composite_from_row(row: Dict[str, Any]) -> float:
    acc = float(row.get("directional_accuracy") or 0)
    cw = float(row.get("confidence_weighted_return_pct") or 0)
    cw_norm = max(-1.0, min(1.0, cw / 5.0))
    return 0.55 * acc + 0.45 * ((cw_norm + 1) / 2)


def build_feedback_payload(scorecard: Dict[str, Any]) -> Dict[str, Any]:
    agents = scorecard.get("agents") or {}
    out: Dict[str, Any] = {"agents": {}, "generated_at": scorecard.get("generated_at")}
    for key, row in agents.items():
        if not isinstance(row, dict):
            continue
        comp = _composite_from_row(row)
        text = (
            f"Recent multi-week calibration: directional accuracy ~{row.get('directional_accuracy', 0):.0%} "
            f"over {row.get('directional_observations', 0)} signal-weeks; "
            f"confidence-weighted return score {row.get('confidence_weighted_return_pct', 0):.2f}. "
            f"Composite rank hint: {comp:.2f}."
        )
        out["agents"][key] = {"text": text, "composite": round(comp, 4)}
    return out


def refresh_feedback_from_cache(scan_cache: Any, max_run_pairs: int = 20) -> Dict[str, Any]:
    """Regenerate scorecard, per-ticker calibration, and agent_feedback.json for prompt injection.

    Returns metadata for UI/email (scan cache size, whether scorecard was produced, skip reasons).
    """
    meta: Dict[str, Any] = {
        "scan_cache_run_count": 0,
        "scorecard_pairs_used": 0,
        "scorecard_agent_count": 0,
        "wrote_agent_feedback": False,
        "wrote_scorecard_file": False,
        "scorecard_skip_reason": "",
    }
    runs = scan_cache.list_runs(limit=500)
    meta["scan_cache_run_count"] = len(runs)
    if len(runs) < 2:
        meta["scorecard_skip_reason"] = "need_at_least_2_cached_runs"
        return meta

    sc = evaluate_scan_cache(scan_cache, max_run_pairs=max_run_pairs)
    meta["scorecard_pairs_used"] = int((sc or {}).get("run_pairs_used") or 0)
    meta["scorecard_agent_count"] = len((sc or {}).get("agents") or {})
    meta["wrote_scorecard_file"] = Path("data/performance/agent_scorecard.json").is_file()

    try:
        rebuild_ticker_agent_calibration(scan_cache, max_run_pairs=max_run_pairs)
    except Exception as e:
        logger.warning("Ticker-agent calibration rebuild failed", error=str(e))
    if not sc:
        if not meta.get("scorecard_skip_reason"):
            meta["scorecard_skip_reason"] = "evaluate_scan_cache_returned_empty"
        return meta
    if meta["scorecard_agent_count"] <= 0 and not meta.get("scorecard_skip_reason"):
        meta["scorecard_skip_reason"] = "no_agent_metrics_from_run_pairs"
    payload = build_feedback_payload(sc)
    os.makedirs(os.path.dirname(DEFAULT_FEEDBACK_PATH) or ".", exist_ok=True)
    with open(DEFAULT_FEEDBACK_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    meta["wrote_agent_feedback"] = True
    logger.info("Wrote agent feedback for prompts", path=DEFAULT_FEEDBACK_PATH)
    return meta


def block_for_agent(agent_key: str, path: str = DEFAULT_FEEDBACK_PATH) -> str:
    """Short paragraph appended to system prompts (empty if missing)."""
    if not os.path.exists(path):
        return ""
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return ""
    agents = data.get("agents") or {}
    entry = agents.get(agent_key) or {}
    return str(entry.get("text") or "")


def composite_for_agent(agent_key: str, path: str = DEFAULT_FEEDBACK_PATH) -> Optional[float]:
    sc = load_scorecard()
    row = (sc.get("agents") or {}).get(agent_key)
    if isinstance(row, dict):
        return round(_composite_from_row(row), 4)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        entry = (data.get("agents") or {}).get(agent_key)
        if isinstance(entry, dict) and entry.get("composite") is not None:
            return float(entry["composite"])
    except Exception:
        pass
    return None
