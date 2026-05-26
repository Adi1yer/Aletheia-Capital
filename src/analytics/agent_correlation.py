"""Pairwise agent agreement from a single run's signals."""

from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, List


def top_redundant_pairs(
    agent_signals: Dict[str, Dict[str, Any]],
    min_observations: int = 20,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """
    agent_signals: agent_key -> ticker -> {signal, ...}
    Returns pairs with highest agreement rate on non-neutral signals.
    """
    agents = list(agent_signals.keys())
    if len(agents) < 2:
        return []

    pairs_out: List[Dict[str, Any]] = []
    for a, b in combinations(agents, 2):
        agree = total = 0
        for ticker in set(agent_signals.get(a, {})) & set(agent_signals.get(b, {})):
            sa = agent_signals[a][ticker]
            sb = agent_signals[b][ticker]
            sig_a = sa.get("signal") if isinstance(sa, dict) else getattr(sa, "signal", "neutral")
            sig_b = sb.get("signal") if isinstance(sb, dict) else getattr(sb, "signal", "neutral")
            if sig_a == "neutral" or sig_b == "neutral":
                continue
            total += 1
            if sig_a == sig_b:
                agree += 1
        if total < min_observations:
            continue
        pairs_out.append(
            {
                "agent_a": a,
                "agent_b": b,
                "agreement_pct": round(100.0 * agree / total, 1),
                "observations": total,
            }
        )

    pairs_out.sort(key=lambda x: (-x["agreement_pct"], -x["observations"]))
    return pairs_out[:top_n]
