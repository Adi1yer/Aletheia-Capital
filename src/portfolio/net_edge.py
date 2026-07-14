"""Net-edge scoring: prefer historically winning lanes / agents after costs."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _lane_ic_from_scorecard(scorecard: Optional[Dict[str, Any]], agent_key: str) -> float:
    if not scorecard:
        return 0.0
    agents = scorecard.get("agents") or scorecard.get("by_agent") or {}
    row = agents.get(agent_key) or {}
    # Prefer confidence-weighted return scaled into [-1, 1]-ish
    try:
        cw = float(row.get("confidence_weighted_return") or row.get("cw_return") or 0.0)
        n = int(row.get("n") or row.get("observations") or 0)
    except Exception:
        return 0.0
    if n < 15:
        return 0.0
    # Soft squash
    return max(-1.0, min(1.0, cw / 500.0))


def net_edge_score(
    *,
    confidence: int,
    agent_details: Optional[list] = None,
    scorecard: Optional[Dict[str, Any]] = None,
    cost_penalty: float = 0.02,
    cash_opportunity_penalty: float = 0.01,
) -> float:
    """
    Approximate expected net edge in [~-1, ~2].
    Positive lane IC boosts; negative IC damps confidence contribution.
    """
    conf = max(0.0, min(100.0, float(confidence))) / 100.0
    details = agent_details or []
    ics = []
    for d in details:
        if not isinstance(d, dict):
            continue
        agent = str(d.get("agent") or "")
        if agent.startswith("lane:"):
            # lane aggregates — use mean of member agents if present later; for now skip
            continue
        ics.append(_lane_ic_from_scorecard(scorecard, agent))
    ic = sum(ics) / len(ics) if ics else 0.0
    raw = conf * (1.0 + ic) - float(cost_penalty) - float(cash_opportunity_penalty)
    return round(raw, 6)


def load_scorecard_safe() -> Dict[str, Any]:
    try:
        from src.backtesting.agent_evaluator import load_scorecard

        return load_scorecard() or {}
    except Exception:
        return {}
