"""Persist and load daily Alpaca snapshots for main vs biotech paper accounts."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal

from src.config.settings import settings

Account = Literal["stock", "biotech"]


def _root() -> Path:
    return Path(getattr(settings, "daily_snapshots_dir", "data/daily_snapshots"))


def snapshot_path(account: Account, day: date | None = None) -> Path:
    day = day or date.today()
    sub = "stock" if account == "stock" else "biotech"
    return _root() / sub / f"{day.isoformat()}.json"


def save_snapshot(account: Account, payload: Dict[str, Any]) -> Path:
    """Write one JSON file per day (overwrites same day)."""
    path = snapshot_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def load_snapshots_for_days(
    account: Account, days: int = 7, end: date | None = None
) -> List[Dict[str, Any]]:
    """Load up to `days` daily files ending at `end`, newest first."""
    end = end or date.today()
    out: List[Dict[str, Any]] = []
    for i in range(days):
        d = end - timedelta(days=i)
        p = snapshot_path(account, d)
        if not p.is_file():
            continue
        try:
            with open(p) as f:
                out.append(json.load(f))
        except Exception:
            continue
    return out


def format_snapshots_markdown(account: Account, days: int = 7) -> str:
    """Human-readable block for prompts and email from the last N snapshots."""
    rows = load_snapshots_for_days(account, days=days)
    if not rows:
        return ""
    label = "Main paper account" if account == "stock" else "Biotech paper account"
    lines = [f"### {label} — last {len(rows)} daily snapshot(s) (newest first)", ""]
    for r in rows:
        day = r.get("date", "?")
        eq = r.get("equity")
        cash = r.get("cash")
        npos = r.get("position_count", 0)
        if isinstance(eq, (int, float)) and isinstance(cash, (int, float)):
            lines.append(f"- **{day}**: equity ${eq:,.2f}, cash ${cash:,.2f}, positions {npos}")
        else:
            lines.append(f"- **{day}**: {r}")
        alerts = r.get("alerts") or []
        if alerts:
            lines.append(f"  - alerts: {', '.join(alerts)}")
        top = r.get("top_positions") or []
        if top:
            bits = [f"{x.get('symbol')} {x.get('pct_equity', 0):.1f}% eq" for x in top[:5]]
            lines.append(f"  - top: {', '.join(bits)}")
        lines.append("")
    return "\n".join(lines).strip()
