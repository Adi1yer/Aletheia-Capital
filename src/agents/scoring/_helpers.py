"""Shared scoring helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agents.inputs import AgentInputs
from src.agents.scoring.models import RuleScore


def _check(name: str, passed: bool, value: Any = None, threshold: Any = None) -> Dict[str, Any]:
    return {"name": name, "pass": passed, "value": value, "threshold": threshold}


def _signal_from_score(bull: int, bear: int, neutral_band: int = 1) -> str:
    if bull - bear >= neutral_band:
        return "bullish"
    if bear - bull >= neutral_band:
        return "bearish"
    return "neutral"


def _confidence_from_checks(checks: List[Dict[str, Any]], base: int = 45) -> int:
    if not checks:
        return 40
    passed = sum(1 for c in checks if c.get("pass"))
    ratio = passed / max(len(checks), 1)
    conf = int(base + ratio * 40)
    return min(85, max(35, conf))


def insufficient_data(inputs: AgentInputs, lane: str) -> RuleScore:
    return RuleScore(
        suggested_signal="neutral",
        rule_confidence=0,
        facts={"reason": "insufficient_data"},
        checks=[],
        lane=lane,
    )


def latest_metric(inputs: AgentInputs, key: str) -> Optional[float]:
    v = inputs.latest_metrics.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
