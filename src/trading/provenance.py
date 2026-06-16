"""Decision provenance graph builder."""

from __future__ import annotations

from typing import Any, Dict


def build_provenance(
    *,
    ticker: str,
    aggregated_signal: Dict[str, Any],
    decision: Dict[str, Any],
    risk: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "raw": aggregated_signal.get("details") or [],
        "lane_aggregation": {
            "signal": aggregated_signal.get("signal"),
            "confidence": aggregated_signal.get("confidence"),
            "bullish_score": aggregated_signal.get("bullish_score"),
            "bearish_score": aggregated_signal.get("bearish_score"),
        },
        "risk_snapshot": {
            "remaining_position_limit": (risk or {}).get("remaining_position_limit"),
            "current_price": (risk or {}).get("current_price"),
        },
        "decision": decision,
    }

