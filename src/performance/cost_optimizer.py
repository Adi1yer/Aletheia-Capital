"""Lane-level marginal utility tracking and budget tuning."""

from __future__ import annotations

from typing import Any, Dict


def compute_lane_utility(results: Dict[str, Any]) -> Dict[str, float]:
    details = []
    for p in (results.get("decision_provenance") or {}).values():
        details.extend((p.get("raw") or []))
    lanes: Dict[str, Dict[str, float]] = {}
    for d in details:
        agent = str(d.get("agent") or "")
        if not agent.startswith("lane:"):
            continue
        lane = agent.split(":", 1)[1]
        lanes.setdefault(lane, {"count": 0.0, "conf": 0.0})
        lanes[lane]["count"] += 1.0
        lanes[lane]["conf"] += float(d.get("confidence") or 0.0)
    out: Dict[str, float] = {}
    for lane, row in lanes.items():
        out[lane] = round((row["conf"] / max(1.0, row["count"])) / 100.0, 4)
    return out


def tune_lane_budget(current: Dict[str, int], utility: Dict[str, float]) -> Dict[str, int]:
    out = dict(current or {})
    for lane, score in utility.items():
        cur = int(out.get(lane, 1))
        if score > 0.7:
            out[lane] = min(cur + 1, 20)
        elif score < 0.4:
            out[lane] = max(cur - 1, 1)
    return out

