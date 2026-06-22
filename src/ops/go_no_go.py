"""Go/no-go gate report for weekly deployment."""

from __future__ import annotations

from typing import Any, Dict, List

from src.ops.slo import HARD_SLO_CHECKS, execution_counts


def build_go_no_go_report(results: Dict[str, Any]) -> Dict[str, Any]:
    blockers: List[str] = []
    warnings: List[str] = []

    slo = results.get("slo") or {}
    checks = slo.get("checks") or {}
    hard_fail = any(not checks.get(k, True) for k in HARD_SLO_CHECKS)
    if hard_fail:
        blockers.append("slo_hard_breach")
    elif not slo.get("ok", True):
        warnings.append("slo_soft_breach")

    pretrade = results.get("pretrade_simulation") or {}
    if bool(pretrade.get("hard_block")):
        blockers.append(f"pretrade_block:{pretrade.get('block_reason')}")
    if int((results.get("data_quality") or {}).get("score", 100)) < 80:
        warnings.append("data_quality_degraded")

    _, _, pending = execution_counts(results.get("execution_status") or {})
    if pending > 0:
        warnings.append("pending_orders_after_run")

    promo = (results.get("learning_context") or {}).get("promotion") or {}
    if promo and not promo.get("promote", True):
        warnings.append(f"promotion_blocked:{promo.get('reason')}")

    return {
        "go": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "override_reason": results.get("go_no_go_override_reason") or "",
    }
