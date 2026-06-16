"""Alpha lifecycle tracking: staleness detection and lane retirement."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

LIFECYCLE_PATH = Path("data/performance/alpha_lifecycle.json")


def _load(path: Path = LIFECYCLE_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {"lanes": {}}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"lanes": {}}


def _save(payload: Dict[str, Any], path: Path = LIFECYCLE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def update_lane_metrics(
    lane: str,
    *,
    hit_rate: float,
    sample_n: int,
    path: Path = LIFECYCLE_PATH,
) -> Dict[str, Any]:
    data = _load(path)
    lanes = data.setdefault("lanes", {})
    row = lanes.setdefault(lane, {"history": []})
    row["history"].append(
        {
            "hit_rate": round(hit_rate, 4),
            "sample_n": int(sample_n),
            "observed_at": datetime.utcnow().isoformat() + "Z",
        }
    )
    row["history"] = row["history"][-12:]
    _save(data, path)
    return row


def evaluate_lane_retirement(
    lane: str,
    *,
    min_samples: int = 6,
    stale_weeks: int = 4,
    min_hit_rate: float = 0.45,
    path: Path = LIFECYCLE_PATH,
) -> Dict[str, Any]:
    row = (_load(path).get("lanes") or {}).get(lane) or {}
    hist: List[Dict[str, Any]] = row.get("history") or []
    if len(hist) < min_samples:
        return {"retire": False, "reason": "insufficient_samples", "lane": lane}
    recent = hist[-stale_weeks:]
    avg_hit = sum(float(h.get("hit_rate") or 0.0) for h in recent) / max(1, len(recent))
    if avg_hit < min_hit_rate:
        return {
            "retire": True,
            "reason": "stale_underperforming_lane",
            "lane": lane,
            "avg_hit_rate": round(avg_hit, 4),
        }
    return {"retire": False, "reason": "healthy", "lane": lane, "avg_hit_rate": round(avg_hit, 4)}
