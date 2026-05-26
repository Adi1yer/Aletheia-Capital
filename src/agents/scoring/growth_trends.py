"""Growth trend scorer."""

from __future__ import annotations

from src.agents.inputs import AgentInputs
from src.agents.scoring._helpers import _check, insufficient_data, latest_metric
from src.agents.scoring.models import RuleScore


def score(inputs: AgentInputs, profile: str = "growth") -> RuleScore:
    if not inputs.latest_metrics and not inputs.trends:
        return insufficient_data(inputs, "growth")

    checks = []
    bull, bear = 0, 0
    rev_g = inputs.trends.get("revenue_yoy_pct") or latest_metric(inputs, "revenue_growth")
    if rev_g is not None:
        try:
            rev_f = float(rev_g)
            if rev_f > 1:
                rev_f *= 100
        except (TypeError, ValueError):
            rev_f = 0
        threshold = 15 if profile == "disruptive" else 8
        ok = rev_f >= threshold
        checks.append(_check("revenue_growth", ok, rev_f, threshold))
        bull += 2 if ok else 0
        bear += 0 if ok else 1

    earn_g = latest_metric(inputs, "earnings_growth")
    if earn_g is not None:
        eg = float(earn_g) * 100 if abs(earn_g) <= 1 else float(earn_g)
        ok = eg > 5
        checks.append(_check("earnings_growth", ok, eg, 5))
        bull += 1 if ok else 0

    fcf_yoy = inputs.trends.get("fcf_yoy_pct")
    if fcf_yoy is not None and fcf_yoy < 0:
        checks.append(_check("fcf_declining", False, fcf_yoy, 0))
        bear += 1

    if bull > bear + 1:
        sig = "bullish"
    elif bear > bull:
        sig = "bearish"
    else:
        sig = "neutral"

    conf = min(85, 45 + bull * 7)
    return RuleScore(
        suggested_signal=sig,
        rule_confidence=conf,
        facts={"profile": profile, "revenue_growth": rev_g},
        checks=checks,
        lane="growth",
    )
