"""Backward-compatible wrapper over thesis ledger."""

from __future__ import annotations

from typing import Any, Dict

from src.biotech.thesis_ledger import recent_entries


def append_entry(entry: Dict[str, Any]) -> None:
    from src.biotech.thesis_ledger import append_thesis_entry

    append_thesis_entry(
        {
            "ticker": entry.get("ticker"),
            "arm": entry.get("arm", "legacy"),
            "status": entry.get("status"),
            "premium_filled_usd": entry.get("premium"),
            "run_date": entry.get("run_date", ""),
            "execution": entry.get("execution"),
        }
    )


def weekly_summary(limit: int = 20) -> Dict[str, Any]:
    rows = recent_entries(weeks=52)
    recent = rows[-limit:]
    return {
        "count": len(rows),
        "entries": [
            {
                "ticker": r.get("ticker"),
                "status": r.get("status"),
                "premium": r.get("premium_filled_usd"),
                "arm": r.get("arm"),
                "recorded_at": r.get("recorded_at"),
            }
            for r in recent
        ],
    }
