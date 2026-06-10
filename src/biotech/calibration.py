"""Hard gates before any paper execution."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.biotech.models import BiotechAnalysisOutput, BiotechSnapshot
import structlog

logger = structlog.get_logger()


def apply_gates(
    snapshot: BiotechSnapshot,
    analysis: BiotechAnalysisOutput,
    min_price: float = 1.0,
    policy: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    ok = True
    policy = policy or {}

    if snapshot.last_price is None or snapshot.last_price < min_price:
        ok = False
        reasons.append(f"Price missing or below min ({min_price})")

    if analysis.no_trade:
        ok = False
        reasons.extend(analysis.no_trade_reasons or ["Model flagged no_trade"])

    if not snapshot.trials and not snapshot.filings:
        ok = False
        reasons.append("No ClinicalTrials hits and no SEC filings — insufficient public context")

    prob_lo = float(analysis.prob_success_low or 0)
    prob_hi = float(analysis.prob_success_high or 1)
    width = prob_hi - prob_lo
    mid = (prob_lo + prob_hi) / 2.0

    min_mid = float(policy.get("min_llm_prob_mid", 0.45))
    min_width = float(policy.get("min_prob_range_width", 0.10))

    if not analysis.no_trade and mid < min_mid:
        ok = False
        reasons.append(
            f"Learned policy: prob mid {mid:.2f} below min_llm_prob_mid {min_mid:.2f}"
        )

    if not analysis.no_trade and width < min_width:
        ok = False
        reasons.append(
            f"Learned policy: prob range width {width:.2f} below min {min_width:.2f}"
        )

    if width < 0.05:
        reasons.append("Very narrow probability range — treat as low resolution (informational)")

    return ok, reasons
