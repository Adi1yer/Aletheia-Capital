"""Sentiment / news heuristic scorer."""

from __future__ import annotations

from src.agents.inputs import AgentInputs
from src.agents.scoring._helpers import _check, insufficient_data
from src.agents.scoring.models import RuleScore

_POS = ("beat", "surge", "growth", "upgrade", "record", "strong", "profit", "bull")
_NEG = ("miss", "cut", "downgrade", "lawsuit", "fraud", "weak", "loss", "bear", "decline")


def _news_score(titles) -> int:
    score = 0
    for t in titles or []:
        low = t.lower()
        score += sum(1 for w in _POS if w in low)
        score -= sum(1 for w in _NEG if w in low)
    return score


def score(inputs: AgentInputs, profile: str = "price_sentiment") -> RuleScore:
    checks = []
    bull, bear = 0, 0

    titles = inputs.news_titles
    if profile == "news_heavy" and titles:
        ns = _news_score(titles)
        ok = ns > 0
        checks.append(_check("news_tone", ok, ns, 0))
        bull += 1 if ok else 0
        bear += 0 if ok else 1

    p = inputs.prices
    if p.get("volume_ratio") and float(p.get("volume_ratio", 1)) > 1.3:
        checks.append(_check("volume_spike", True, p["volume_ratio"], 1.3))
        bull += 1

    ret = p.get("return_pct_period")
    if ret is not None:
        if ret > 5:
            checks.append(_check("price_momentum_up", True, ret, 5))
            bull += 1
        elif ret < -5:
            checks.append(_check("price_momentum_down", True, ret, -5))
            bear += 1

    analyst = inputs.extras.get("analyst_summary", "")
    if "StrongBuy" in analyst or "Buy=" in analyst:
        checks.append(_check("analyst_positive", True, "buy_skew", None))
        bull += 1

    if not checks:
        return insufficient_data(inputs, "sentiment")

    if bull > bear:
        sig = "bullish"
    elif bear > bull:
        sig = "bearish"
    else:
        sig = "neutral"

    conf = min(78, 42 + abs(bull - bear) * 10)
    return RuleScore(
        suggested_signal=sig,
        rule_confidence=conf,
        facts={"news_score": _news_score(titles), "profile": profile},
        checks=checks,
        lane="sentiment",
    )
