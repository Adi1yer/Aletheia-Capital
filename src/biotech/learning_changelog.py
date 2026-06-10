"""Append-only biotech learning changelog."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

CHANGELOG_PATH = Path("data/biotech/learning_changelog.jsonl")


def append_biotech_changelog(
    *,
    run_id: str,
    run_date: str,
    policy_adjustments: Optional[List[Dict[str, Any]]] = None,
    scorecard: Optional[Dict[str, Any]] = None,
    promoted: Optional[bool] = None,
    promotion_reason: str = "",
    path: Path = CHANGELOG_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "run_id": run_id,
        "run_date": run_date,
        "policy_adjustments": policy_adjustments or [],
        "scorecard": scorecard or {},
        "promoted": promoted,
        "promotion_reason": promotion_reason or "",
        "saved_at": datetime.utcnow().isoformat() + "Z",
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    logger.info(
        "Appended biotech learning changelog",
        run_id=run_id,
        adjustments=len(row["policy_adjustments"]),
        promoted=promoted,
    )


def format_learning_markdown(
    *,
    policy_result: Dict[str, Any],
    promotion: Dict[str, Any],
) -> str:
    lines = ["LEARNING THIS WEEK", "-" * 70]
    adj = policy_result.get("adjustments") or []
    if adj:
        lines.append("Policy adjustments proposed:")
        for a in adj[:8]:
            lines.append(
                f"  - {a.get('knob')}: {a.get('reason')} (n={a.get('sample_n')})"
            )
    else:
        lines.append("  No policy knob changes this run.")
    lines.append(
        f"Promotion: {'APPLIED' if promotion.get('promote') else 'REJECTED'} — {promotion.get('reason', '')}"
    )
    lines.append(f"Closed trades in learning window: {policy_result.get('closed_count', 0)}")
    return "\n".join(lines)


def latest_entry(path: Path = CHANGELOG_PATH) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows[-1] if rows else None
