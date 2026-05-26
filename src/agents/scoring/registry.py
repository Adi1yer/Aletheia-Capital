"""Map agent lanes to scoring functions."""

from __future__ import annotations

from typing import Callable

from src.agents.inputs import AgentInputs
from src.agents.scoring import (
    congressional_flow,
    distress_screen,
    growth_trends,
    macro_momentum,
    sentiment_news,
    technicals_signals,
    valuation_screen,
    value_checklist,
)
from src.agents.scoring.models import RuleScore

ScorerFn = Callable[[AgentInputs, str], RuleScore]

LANE_SCORERS: dict[str, ScorerFn] = {
    "value": value_checklist.score,
    "valuation": valuation_screen.score,
    "growth": growth_trends.score,
    "technicals": technicals_signals.score,
    "distress": distress_screen.score,
    "macro": macro_momentum.score,
    "sentiment": sentiment_news.score,
    "congressional": congressional_flow.score,
}


def run_scorer(lane: str, inputs: AgentInputs, profile: str) -> RuleScore:
    fn = LANE_SCORERS.get(lane)
    if not fn:
        return RuleScore(
            suggested_signal="neutral",
            rule_confidence=0,
            facts={"error": f"unknown_lane:{lane}"},
            checks=[],
            lane=lane,
        )
    return fn(inputs, profile)
