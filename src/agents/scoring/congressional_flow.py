"""Congressional trade flow scorer."""

from __future__ import annotations

from src.agents.inputs import AgentInputs
from src.agents.scoring._helpers import _check
from src.agents.scoring.models import RuleScore


def score(inputs: AgentInputs, profile: str = "default") -> RuleScore:
    trades = inputs.extras.get("congressional_trades") or []
    buys = sum(1 for t in trades if t.get("transaction_type") == "buy")
    sells = sum(1 for t in trades if t.get("transaction_type") == "sell")
    total = buys + sells

    if total == 0:
        return RuleScore(
            suggested_signal="neutral",
            rule_confidence=0,
            facts={"buys": 0, "sells": 0},
            checks=[],
            lane="congressional",
        )

    checks = [
        _check("net_flow", buys != sells, {"buys": buys, "sells": sells}, None),
    ]
    net = buys - sells

    if total >= 3 and net >= 2:
        sig, conf, skip = "bullish", min(75, 50 + net * 5), True
    elif total >= 3 and net <= -2:
        sig, conf, skip = "bearish", min(75, 50 + abs(net) * 5), True
    elif net > 0:
        sig, conf, skip = "bullish", 45, False
    elif net < 0:
        sig, conf, skip = "bearish", 45, False
    else:
        sig, conf, skip = "neutral", 40, False

    return RuleScore(
        suggested_signal=sig,
        rule_confidence=conf,
        facts={"buys": buys, "sells": sells, "total": total},
        checks=checks,
        lane="congressional",
        skip_llm=skip,
    )
