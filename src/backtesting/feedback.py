"""Turn scorecard metrics into short prompt blocks per agent."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.backtesting.agent_evaluator import evaluate_scan_cache, load_scorecard
from src.backtesting.learning_outcomes import (
    rebuild_ticker_agent_calibration,
    rebuild_ticker_agent_calibration_from_ledger,
)

logger = structlog.get_logger()

DEFAULT_FEEDBACK_PATH = "data/performance/agent_feedback.json"
SCORECARD_PATH = "data/performance/agent_scorecard.json"


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
        source = scorecard.get("source") or "scan_cache"
        text = (
            f"Recent multi-week calibration ({source}): directional accuracy ~{row.get('directional_accuracy', 0):.0%} "
            f"over {row.get('directional_observations', 0)} signal-weeks; "
            f"confidence-weighted return score {row.get('confidence_weighted_return_pct', 0):.2f}. "
            f"Composite rank hint: {comp:.2f}."
        )
        out["agents"][key] = {"text": text, "composite": round(comp, 4)}
    return out


def _write_scorecard_and_feedback(sc: Dict[str, Any], meta: Dict[str, Any]) -> None:
    if not sc or not sc.get("agents"):
        return
    os.makedirs(os.path.dirname(SCORECARD_PATH) or ".", exist_ok=True)
    with open(SCORECARD_PATH, "w") as f:
        json.dump(sc, f, indent=2)
    meta["wrote_scorecard_file"] = True
    meta["scorecard_agent_count"] = len(sc.get("agents") or {})
    meta["scorecard_pairs_used"] = int(sc.get("run_pairs_used") or 0)
    payload = build_feedback_payload(sc)
    with open(DEFAULT_FEEDBACK_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    meta["wrote_agent_feedback"] = True
    meta["scorecard_source"] = sc.get("source") or "scan_cache"
    try:
        from src.performance.confidence_calibration import rebuild_calibration_files

        rebuild_calibration_files()
    except Exception as e:
        logger.warning("Confidence calibration rebuild failed", error=str(e))
    logger.info("Wrote agent feedback for prompts", path=DEFAULT_FEEDBACK_PATH)


def refresh_feedback_from_cache(scan_cache: Any, max_run_pairs: int = 20) -> Dict[str, Any]:
    """Regenerate scorecard, per-ticker calibration, and agent_feedback.json for prompt injection.

    Falls back to compact weekly_ledger when full scan_cache has fewer than 2 runs.
    """
    meta: Dict[str, Any] = {
        "scan_cache_run_count": 0,
        "ledger_run_count": 0,
        "scorecard_pairs_used": 0,
        "scorecard_agent_count": 0,
        "wrote_agent_feedback": False,
        "wrote_scorecard_file": False,
        "scorecard_skip_reason": "",
        "scorecard_source": "",
    }
    runs = scan_cache.list_runs(limit=500) if scan_cache is not None else []
    meta["scan_cache_run_count"] = len(runs)

    from src.performance.weekly_ledger import evaluate_ledger_scorecard, ledger_run_count

    meta["ledger_run_count"] = ledger_run_count()

    sc: Dict[str, Any] = {}
    if len(runs) >= 2:
        sc = evaluate_scan_cache(scan_cache, max_run_pairs=max_run_pairs) or {}
        if sc:
            sc["source"] = "scan_cache"
        try:
            rebuild_ticker_agent_calibration(scan_cache, max_run_pairs=max_run_pairs)
        except Exception as e:
            logger.warning("Ticker-agent calibration rebuild failed", error=str(e))
    elif meta["ledger_run_count"] >= 2:
        sc = evaluate_ledger_scorecard(max_pairs=max_run_pairs)
        meta["scorecard_source"] = "weekly_ledger"
        try:
            rebuild_ticker_agent_calibration_from_ledger(max_run_pairs=max_run_pairs)
        except Exception as e:
            logger.warning("Ledger ticker calibration rebuild failed", error=str(e))
    else:
        meta["scorecard_skip_reason"] = "need_at_least_2_cached_runs"
        return meta

    if not sc or not sc.get("agents"):
        if not meta.get("scorecard_skip_reason"):
            meta["scorecard_skip_reason"] = "no_agent_metrics_from_run_pairs"
        return meta

    _write_scorecard_and_feedback(sc, meta)
    return meta


def existing_feedback_loaded() -> bool:
    return Path(DEFAULT_FEEDBACK_PATH).is_file() or Path(SCORECARD_PATH).is_file()


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
