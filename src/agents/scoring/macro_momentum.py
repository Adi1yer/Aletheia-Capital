"""Macro momentum scorer."""

from __future__ import annotations

from src.agents.inputs import AgentInputs
from src.agents.scoring._helpers import _check, insufficient_data
from src.agents.scoring.models import RuleScore


def score(inputs: AgentInputs, profile: str = "macro") -> RuleScore:
    p = inputs.prices
    b = inputs.benchmarks
    if not p:
        return insufficient_data(inputs, "macro")

    checks = []
    bull, bear = 0, 0

    ret = p.get("return_pct_period")
    if ret is not None:
        ok = ret > 3
        checks.append(_check("stock_momentum", ok, ret, 3))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    vs_spy = p.get("return_vs_spy_pct") or inputs.technicals.get("return_vs_spy_pct")
    if vs_spy is not None:
        ok = vs_spy > 0
        checks.append(_check("vs_spy", ok, vs_spy, 0))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    spy_ret = b.get("spy_return_pct")
    if spy_ret is not None and spy_ret < -5:
        checks.append(_check("weak_market", False, spy_ret, -5))
        bear += 1

    if bull > bear:
        sig = "bullish"
    elif bear > bull:
        sig = "bearish"
    else:
        sig = "neutral"

    conf = min(82, 42 + (bull - bear) * 12)
    return RuleScore(
        suggested_signal=sig,
        rule_confidence=max(35, conf),
        facts={"spy_return": spy_ret, "vs_spy": vs_spy},
        checks=checks,
        lane="macro",
    )
