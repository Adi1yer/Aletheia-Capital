"""Value / quality checklist scorer."""

from __future__ import annotations

from src.agents.inputs import AgentInputs
from src.agents.scoring._helpers import (
    _check,
    _confidence_from_checks,
    _signal_from_score,
    insufficient_data,
    latest_metric,
)
from src.agents.scoring.models import RuleScore

PROFILE_THRESHOLDS = {
    "buffett": {"max_pb": 8.0, "max_de": 1.5, "min_roe": 0.10},
    "graham": {"max_pb": 1.5, "max_de": 0.8, "min_roe": 0.08},
    "munger": {"max_pb": 6.0, "max_de": 1.2, "min_roe": 0.12},
    "deep_value": {"max_pb": 1.2, "max_de": 0.6, "min_roe": 0.05},
    "activist": {"max_pb": 5.0, "max_de": 2.0, "min_roe": 0.08},
    "neutral_fundamentals": {"max_pb": 10.0, "max_de": 2.5, "min_roe": 0.05},
}


def score(inputs: AgentInputs, profile: str = "buffett") -> RuleScore:
    m = inputs.latest_metrics
    if not m:
        return insufficient_data(inputs, "value")

    th = PROFILE_THRESHOLDS.get(profile, PROFILE_THRESHOLDS["buffett"])
    checks = []
    bull, bear = 0, 0

    pb = latest_metric(inputs, "price_to_book_ratio")
    if pb is not None:
        ok = pb <= th["max_pb"]
        checks.append(_check("price_to_book", ok, pb, th["max_pb"]))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    de = latest_metric(inputs, "debt_to_equity")
    if de is not None:
        de_norm = de / 100.0 if de > 10 else de
        ok = de_norm <= th["max_de"]
        checks.append(_check("debt_to_equity", ok, de_norm, th["max_de"]))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    roe = latest_metric(inputs, "return_on_equity") or latest_metric(inputs, "roe")
    if roe is not None:
        ok = roe >= th["min_roe"]
        checks.append(_check("roe", ok, roe, th["min_roe"]))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    rev_yoy = inputs.trends.get("revenue_yoy_pct")
    if rev_yoy is not None:
        ok = rev_yoy > 0
        checks.append(_check("revenue_growth", ok, rev_yoy, ">0"))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    insider = (inputs.insider_summary or "").lower()
    if "buy" in insider or "purchase" in insider:
        checks.append(_check("insider_activity", True, "net_buying", None))
        bull += 1

    sig = _signal_from_score(bull, bear)
    conf = _confidence_from_checks(checks, base=48 if profile == "graham" else 45)
    return RuleScore(
        suggested_signal=sig,
        rule_confidence=conf,
        facts={"profile": profile, "bull_points": bull, "bear_points": bear},
        checks=checks,
        lane="value",
    )
