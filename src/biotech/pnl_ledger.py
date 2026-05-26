"""Append-only straddle P&L ledger for biotech paper book."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

LEDGER_PATH = Path("data/biotech/straddle_ledger.json")


def append_entry(entry: Dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    if LEDGER_PATH.is_file():
        try:
            with open(LEDGER_PATH, encoding="utf-8") as f:
                rows = json.load(f) or []
        except Exception:
            rows = []
    entry.setdefault("recorded_at", datetime.utcnow().isoformat())
    rows.append(entry)
    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def weekly_summary(limit: int = 20) -> Dict[str, Any]:
    if not LEDGER_PATH.is_file():
        return {"count": 0, "entries": []}
    with open(LEDGER_PATH, encoding="utf-8") as f:
        rows = json.load(f) or []
    recent = rows[-limit:]
    return {"count": len(rows), "entries": recent}
