"""Turn scorecard metrics into short prompt blocks per agent."""

from __future__ import annotations

import json
import os
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


def refresh_feedback_from_cache(scan_cache: Any, max_run_pairs: int = 20) -> None:
    """Regenerate scorecard, per-ticker calibration, and agent_feedback.json for prompt injection."""
    sc = evaluate_scan_cache(scan_cache, max_run_pairs=max_run_pairs)
    try:
        rebuild_ticker_agent_calibration(scan_cache, max_run_pairs=max_run_pairs)
    except Exception as e:
        logger.warning("Ticker-agent calibration rebuild failed", error=str(e))
    if not sc:
        return
    payload = build_feedback_payload(sc)
    os.makedirs(os.path.dirname(DEFAULT_FEEDBACK_PATH) or ".", exist_ok=True)
    with open(DEFAULT_FEEDBACK_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    logger.info("Wrote agent feedback for prompts", path=DEFAULT_FEEDBACK_PATH)


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
