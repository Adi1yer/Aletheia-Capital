"""Portfolio risk metrics from daily snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


def _load_snapshots(snapshots_dir: Path, account: str = "stock", days: int = 28) -> List[Dict[str, Any]]:
    base = snapshots_dir / account
    if not base.is_dir():
        return []
    files = sorted(base.glob("*.json"), reverse=True)[:days]
    rows = []
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                rows.append(json.load(f))
        except Exception:
            continue
    return list(reversed(rows))


def compute_snapshot_metrics(
    snapshots_dir: str = "data/daily_snapshots",
    days: int = 28,
) -> Dict[str, Any]:
    rows = _load_snapshots(Path(snapshots_dir), days=days)
    if len(rows) < 2:
        return {"max_drawdown_4w_pct": None, "herfindahl": None, "snapshot_days": len(rows)}

    equities = [float(r.get("equity") or 0) for r in rows if r.get("equity")]
    max_dd = 0.0
    peak = equities[0] if equities else 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)

    last = rows[-1]
    positions = last.get("positions") or {}
    weights = []
    total = float(last.get("equity") or 0) or 1.0
    for pos in positions.values():
        mv = float(pos.get("market_value") or pos.get("value") or 0)
        if mv > 0:
            weights.append(mv / total)
    hhi = sum(w * w for w in weights) if weights else None

    return {
        "max_drawdown_4w_pct": round(max_dd * 100, 2) if equities else None,
        "herfindahl": round(hhi, 4) if hhi is not None else None,
        "snapshot_days": len(rows),
    }
