"""Technical signals from precomputed dossier fields."""

from __future__ import annotations

from src.agents.inputs import AgentInputs
from src.agents.scoring._helpers import _check, insufficient_data
from src.agents.scoring.models import RuleScore


def score(inputs: AgentInputs, profile: str = "default") -> RuleScore:
    t = inputs.technicals
    p = inputs.prices
    if not t and not p:
        return insufficient_data(inputs, "technicals")

    checks = []
    bull, bear = 0, 0

    if t.get("golden_cross") is True:
        checks.append(_check("golden_cross", True, True, None))
        bull += 2
    elif t.get("golden_cross") is False:
        checks.append(_check("golden_cross", False, False, None))
        bear += 1

    rsi = t.get("rsi_14")
    if rsi is not None:
        if rsi < 35:
            checks.append(_check("rsi_oversold", True, rsi, 35))
            bull += 1
        elif rsi > 70:
            checks.append(_check("rsi_overbought", False, rsi, 70))
            bear += 1
        else:
            checks.append(_check("rsi_neutral", True, rsi, "35-70"))

    ret = p.get("return_pct_period")
    if ret is not None:
        ok = ret > 5
        checks.append(_check("momentum_positive", ok, ret, 5))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    vs_spy = t.get("return_vs_spy_pct")
    if vs_spy is not None:
        ok = vs_spy > 2
        checks.append(_check("outperform_spy", ok, vs_spy, 2))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    if bull > bear:
        sig = "bullish"
    elif bear > bull:
        sig = "bearish"
    else:
        sig = "neutral"

    conf = min(82, 40 + (bull - bear) * 10)
    return RuleScore(
        suggested_signal=sig,
        rule_confidence=max(35, conf),
        facts={"rsi": rsi, "golden_cross": t.get("golden_cross")},
        checks=checks,
        lane="technicals",
    )
