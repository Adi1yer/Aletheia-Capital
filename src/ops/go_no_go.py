"""Go/no-go gate report for weekly deployment."""

from __future__ import annotations

from typing import Any, Dict, List

from src.ops.slo import HARD_SLO_CHECKS, execution_counts


def build_go_no_go_report(results: Dict[str, Any]) -> Dict[str, Any]:
    blockers: List[str] = []
    warnings: List[str] = []

    slo = results.get("slo") or {}
    checks = slo.get("checks") or {}
    hard_names = set(slo.get("hard_checks") or HARD_SLO_CHECKS)
    hard_fail = any(not checks.get(k, True) for k in hard_names)
    if hard_fail:
        blockers.append("slo_hard_breach")
    elif not slo.get("ok", True):
        warnings.append("slo_soft_breach")
    if checks.get("cash_floor_ok") is False:
        warnings.append("cash_floor_breach")
    if checks.get("concentration_ok") is False:
        warnings.append("concentration_breach")

    pretrade = results.get("pretrade_simulation") or {}
    if bool(pretrade.get("hard_block")):
        blockers.append(f"pretrade_block:{pretrade.get('block_reason')}")
    if int((results.get("data_quality") or {}).get("score", 100)) < 80:
        warnings.append("data_quality_degraded")

    submitted, _, pending = execution_counts(results.get("execution_status") or {})
    if pending > 0:
        warnings.append("pending_orders_after_run")

    # Check for zero submissions when execute was intended and window was open
    exec_status = results.get("execution_status") or {}
    run_in_rth = bool(exec_status.get("run_in_rth"))
    meta = results.get("meta") or {}
    cfg = meta.get("config") or {}
    execute_mode = bool(cfg.get("execute")) if isinstance(cfg, dict) else False
    
    # Soft-fail if execute mode + RTH window but zero equity/options submits
    if execute_mode and run_in_rth and submitted == 0:
        # Check if there were decisions that should have led to orders
        decisions = results.get("decisions") or {}
        non_hold = [d for d in decisions.values() if isinstance(d, dict) and d.get("action") != "hold"]
        if len(non_hold) > 0:
            warnings.append(f"zero_submits_in_execute_window:{len(non_hold)}_decisions")

    promo = (results.get("learning_context") or {}).get("promotion") or {}
    if promo and not promo.get("promote", True):
        warnings.append(f"promotion_blocked:{promo.get('reason')}")

    return {
        "go": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "override_reason": results.get("go_no_go_override_reason") or "",
    }
