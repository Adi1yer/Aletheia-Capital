"""Hybrid agent signal finalization tests."""

from src.agents.hybrid import HybridAgentMixin, HybridExplainOutput
from src.agents.scoring.models import RuleScore


class _Stub(HybridAgentMixin):
    name = "Stub"
    investing_style = "test"


def test_finalize_binds_signal_without_override():
    stub = _Stub()
    rule = RuleScore("bullish", 60, checks=[{"name": "a", "pass": True}], lane="value")
    resp = HybridExplainOutput(
        signal="bearish",
        confidence=70,
        reasoning="Checks: a passed",
        override=False,
        override_reason="",
    )
    sig = stub._finalize_signal(resp, rule)
    assert sig.signal == "bullish"
    assert 45 <= sig.confidence <= 75


def test_finalize_allows_override():
    stub = _Stub()
    rule = RuleScore(
        "neutral",
        50,
        checks=[{"name": "fraud", "pass": True}],
        lane="value",
    )
    resp = HybridExplainOutput(
        signal="bearish",
        confidence=55,
        reasoning="Checks: fraud cited in news",
        override=True,
        override_reason="Major fraud headline",
    )
    sig = stub._finalize_signal(resp, rule)
    assert sig.signal == "bearish"
