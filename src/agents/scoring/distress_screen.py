"""Distress / contrarian screen (Burry-style)."""

from __future__ import annotations

from src.agents.inputs import AgentInputs
from src.agents.scoring._helpers import _check, insufficient_data, latest_metric
from src.agents.scoring.models import RuleScore


def score(inputs: AgentInputs, profile: str = "default") -> RuleScore:
    if not inputs.latest_metrics:
        return insufficient_data(inputs, "distress")

    checks = []
    bear, bull = 0, 0

    de = latest_metric(inputs, "debt_to_equity")
    if de is not None:
        de_n = de / 100.0 if de > 10 else de
        ok = de_n > 1.5
        checks.append(_check("high_leverage", ok, de_n, 1.5))
        bear += 2 if ok else 0

    rev_yoy = inputs.trends.get("revenue_yoy_pct")
    if rev_yoy is not None and rev_yoy < -5:
        checks.append(_check("revenue_decline", True, rev_yoy, -5))
        bear += 1

    fcf_yoy = inputs.trends.get("fcf_yoy_pct")
    if fcf_yoy is not None and fcf_yoy < 0:
        checks.append(_check("fcf_negative_trend", True, fcf_yoy, 0))
        bear += 1

    pe = latest_metric(inputs, "pe_ratio")
    if pe is not None and pe < 0:
        checks.append(_check("negative_earnings", True, pe, 0))
        bear += 1

    if bear >= 3:
        sig = "bearish"
    elif bear >= 2:
        sig = "neutral"
    else:
        sig = "neutral"

    conf = min(80, 40 + bear * 10)
    return RuleScore(
        suggested_signal=sig,
        rule_confidence=conf,
        facts={"distress_flags": bear},
        checks=checks,
        lane="distress",
    )
