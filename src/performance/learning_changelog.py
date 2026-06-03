"""Append-only learning changelog for weights, policy, and scorecard metadata."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

CHANGELOG_PATH = Path("data/performance/learning_changelog.jsonl")


def append_changelog_entry(
    *,
    run_id: Optional[str],
    run_date: str,
    weight_changes: Optional[List[Dict[str, Any]]] = None,
    weight_skips: Optional[List[Dict[str, Any]]] = None,
    policy_adjustments: Optional[List[Dict[str, Any]]] = None,
    scorecard_source: str = "",
    regime_mode: str = "",
    regime_bucket_counts: Optional[Dict[str, int]] = None,
    promoted: Optional[bool] = None,
    promotion_reason: str = "",
    path: Path = CHANGELOG_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "run_id": run_id,
        "run_date": run_date,
        "weight_changes": weight_changes or [],
        "weight_skips": weight_skips or [],
        "policy_adjustments": policy_adjustments or [],
        "scorecard_source": scorecard_source,
        "regime_mode": regime_mode,
        "regime_bucket_counts": regime_bucket_counts or {},
        "promoted": promoted,
        "promotion_reason": promotion_reason or "",
        "saved_at": datetime.utcnow().isoformat() + "Z",
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    logger.info(
        "Appended learning changelog",
        run_id=run_id,
        weight_changes=len(row["weight_changes"]),
        policy_adjustments=len(row["policy_adjustments"]),
    )


def latest_entry(path: Path = CHANGELOG_PATH) -> Optional[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows[-1] if rows else None
