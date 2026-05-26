"""Congressional flow tests."""

from src.agents.inputs import AgentInputs
from src.agents.scoring.congressional_flow import score


def test_rule_only_clear_buys():
    inp = AgentInputs(
        "X",
        "2026-01-01",
        "2026-05-26",
        {"version": 2},
        extras={
            "congressional_trades": [
                {"transaction_type": "buy"},
                {"transaction_type": "buy"},
                {"transaction_type": "buy"},
                {"transaction_type": "sell"},
            ]
        },
    )
    r = score(inp)
    assert r.suggested_signal == "bullish"
    assert r.skip_llm is True
