"""Lane-level ensemble utilities to reduce correlated persona voting."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict

from src.agents.registry import get_registry


def build_lane_signals(
    ticker: str,
    agent_signals: Dict[str, Dict[str, Any]],
    agent_weights: Dict[str, float],
) -> Dict[str, Dict[str, Any]]:
    """Collapse raw agent signals into one weighted signal per lane."""
    registry = get_registry()
    lanes: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"bullish": 0.0, "bearish": 0.0, "weight": 0.0}
    )
    reasoning: Dict[str, str] = {}
    for agent_key, ticker_signals in (agent_signals or {}).items():
        signal = (ticker_signals or {}).get(ticker)
        if not signal:
            continue
        lane = getattr(registry.get(agent_key), "hybrid_lane", "") or ""
        if not lane:
            low = agent_key.lower()
            if "growth" in low:
                lane = "growth"
            elif "value" in low or "valuation" in low:
                lane = "value"
            else:
                lane = "other"
        sig_val = signal.signal if hasattr(signal, "signal") else signal.get("signal", "neutral")
        sig_conf = int(
            signal.confidence if hasattr(signal, "confidence") else signal.get("confidence", 0)
        )
        weight = float(agent_weights.get(agent_key, 1.0))
        if sig_val not in ("bullish", "bearish"):
            continue
        lanes[lane][sig_val] += sig_conf * weight
        lanes[lane]["weight"] += weight
        if lane not in reasoning:
            rs = signal.reasoning if hasattr(signal, "reasoning") else signal.get("reasoning", "")
            reasoning[lane] = str(rs or "")[:100]

    out: Dict[str, Dict[str, Any]] = {}
    for lane, row in lanes.items():
        total = float(row.get("weight") or 0.0)
        if total <= 0:
            continue
        bull = float(row.get("bullish") or 0.0) / total
        bear = float(row.get("bearish") or 0.0) / total
        if bull > bear:
            sig = "bullish"
            conf = int(min(100, bull))
        elif bear > bull:
            sig = "bearish"
            conf = int(min(100, bear))
        else:
            sig = "neutral"
            conf = 0
        out[f"lane:{lane}"] = {
            "signal": sig,
            "confidence": conf,
            "weight": total,
            "reasoning": reasoning.get(lane, ""),
        }
    return out

