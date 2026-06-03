"""Tests for regime-specific agent weights."""

from __future__ import annotations

from src.agents.registry import AgentRegistry
from src.agents.base import BaseAgent, AgentSignal


class _StubAgent(BaseAgent):
    def analyze(self, ticker, start_date, end_date):
        return AgentSignal(signal="neutral", confidence=50, reasoning="")


def test_regime_weight_blend():
    reg = AgentRegistry()
    agent = _StubAgent(
        name="Growth Analyst",
        description="test",
        investing_style="growth",
        weight=1.0,
    )
    reg.register(agent)
    reg._weights["growth_analyst"] = 1.0
    reg.update_weight("growth_analyst", 2.0, regime_mode="accumulate")
    blended = reg.get_weights(regime_mode="accumulate")
    assert blended["growth_analyst"] > 1.0
    assert blended["growth_analyst"] < 2.0
