"""Hard gates before any paper execution."""

from __future__ import annotations

from typing import List, Tuple

from src.biotech.models import BiotechAnalysisOutput, BiotechSnapshot
import structlog

logger = structlog.get_logger()


def apply_gates(
    snapshot: BiotechSnapshot,
    analysis: BiotechAnalysisOutput,
    min_price: float = 1.0,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    ok = True

    if snapshot.last_price is None or snapshot.last_price < min_price:
        ok = False
        reasons.append(f"Price missing or below min ({min_price})")

    if analysis.no_trade:
        ok = False
        reasons.extend(analysis.no_trade_reasons or ["Model flagged no_trade"])

    if not snapshot.trials and not snapshot.filings:
        ok = False
        reasons.append("No ClinicalTrials hits and no SEC filings — insufficient public context")

    width = analysis.prob_success_high - analysis.prob_success_low
    if width < 0.05:
        reasons.append("Very narrow probability range — treat as low resolution (informational)")

    return ok, reasons
