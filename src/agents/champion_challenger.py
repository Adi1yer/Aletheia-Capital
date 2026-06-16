"""Lane-level champion/challenger registry and evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

REGISTRY_PATH = Path("data/performance/champion_challenger.json")


def _load(path: Path = REGISTRY_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {"lanes": {}}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"lanes": {}}


def _save(payload: Dict[str, Any], path: Path = REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def register_challenger(lane: str, challenger_id: str, *, path: Path = REGISTRY_PATH) -> None:
    data = _load(path)
    lanes = data.setdefault("lanes", {})
    row = lanes.setdefault(lane, {"champion": lane, "challengers": []})
    if challenger_id not in row["challengers"]:
        row["challengers"].append(challenger_id)
    _save(data, path)


def evaluate_challenger(
  lane: str,
  *,
  champion_score: float,
  challenger_score: float,
  min_lift_pp: float = 1.0,
) -> Dict[str, Any]:
    lift = challenger_score - champion_score
    if lift >= min_lift_pp:
        return {
            "promote_challenger": True,
            "lane": lane,
            "lift_pp": round(lift, 4),
            "reason": "challenger_outperformed",
        }
    return {
        "promote_challenger": False,
        "lane": lane,
        "lift_pp": round(lift, 4),
        "reason": "challenger_regressed_or_flat",
    }


def lane_summary(path: Path = REGISTRY_PATH) -> Dict[str, Any]:
    data = _load(path)
    out: Dict[str, Any] = {}
    for lane, row in (data.get("lanes") or {}).items():
        out[lane] = {
            "champion": row.get("champion"),
            "challenger_count": len(row.get("challengers") or []),
        }
    return out
