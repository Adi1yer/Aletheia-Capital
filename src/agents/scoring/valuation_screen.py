"""Valuation / margin-of-safety screen."""

from __future__ import annotations

from src.agents.inputs import AgentInputs
from src.agents.scoring._helpers import _check, insufficient_data, latest_metric
from src.agents.scoring.models import RuleScore


def score(inputs: AgentInputs, profile: str = "dcf_simple") -> RuleScore:
    m = inputs.latest_metrics
    if not m:
        return insufficient_data(inputs, "valuation")

    checks = []
    pe = latest_metric(inputs, "pe_ratio")
    pb = latest_metric(inputs, "price_to_book_ratio")
    mc = inputs.context.get("market_cap")
    fcf = None
    if inputs.line_items:
        fcf = inputs.line_items[0].get("free_cash_flow")

    bull, bear = 0, 0
    if pe is not None and pe > 0:
        ok = pe < 25 if profile == "dcf_simple" else pe < 20
        checks.append(_check("pe_reasonable", ok, pe, 25))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    if pb is not None and pb > 0:
        ok = pb < 4
        checks.append(_check("pb_reasonable", ok, pb, 4))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    mos_pct = None
    if fcf and mc and mc > 0 and fcf > 0:
        fcf_yield = fcf / mc * 100
        mos_pct = round(fcf_yield, 2)
        ok = fcf_yield >= 4.0
        checks.append(_check("fcf_yield", ok, fcf_yield, 4.0))
        bull += 2 if ok else 0
        bear += 0 if ok else 1

    if bull > bear + 1:
        sig = "bullish"
    elif bear > bull + 1:
        sig = "bearish"
    else:
        sig = "neutral"

    conf = min(85, 42 + bull * 8)
    return RuleScore(
        suggested_signal=sig,
        rule_confidence=conf,
        facts={"fcf_yield_pct": mos_pct, "profile": profile},
        checks=checks,
        lane="valuation",
    )
