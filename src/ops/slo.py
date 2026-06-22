"""Simple SLO checks for weekly pipeline health."""

from __future__ import annotations

from typing import Any, Dict, Tuple

HARD_SLO_CHECKS = frozenset(
    {
        "agent_error_budget_ok",
        "data_quality_ok",
        "decision_coverage_ok",
    }
)


def execution_counts(exec_status: Dict[str, Any]) -> Tuple[int, int, int]:
    """Return (submitted, filled, pending_including_partial)."""
    if not exec_status:
        return 0, 0, 0
    pending = int(exec_status.get("pending_count") or exec_status.get("pending") or 0)
    partial = int(exec_status.get("partial") or exec_status.get("partial_count") or 0)
    filled = int(exec_status.get("filled_count") or exec_status.get("filled") or 0)
    submitted = int(exec_status.get("submitted") or 0)
    if submitted <= 0:
        submitted = pending + partial + filled + int(exec_status.get("failed") or 0)
    return submitted, filled, pending + partial


def evaluate_slos(results: Dict[str, Any]) -> Dict[str, Any]:
    decisions = results.get("decisions") or {}
    errs = results.get("agent_errors") or {}
    data_q = results.get("data_quality") or {}
    coverage = len([d for d in decisions.values() if isinstance(d, dict) and d.get("action") != "hold"])
    exec_status = results.get("execution_status") or {}
    submitted, filled, pending = execution_counts(exec_status)

    if submitted == 0:
        execution_fill_rate_ok = True
    elif pending > 0:
        # Large rebalance bursts often leave working orders during RTH.
        execution_fill_rate_ok = True
    else:
        execution_fill_rate_ok = (filled / max(1, submitted)) >= 0.5

    checks = {
        "agent_error_budget_ok": len(errs) <= 2,
        "data_quality_ok": int(data_q.get("score", 100)) >= 80,
        "decision_coverage_ok": coverage >= 1,
        "execution_fill_rate_ok": execution_fill_rate_ok,
        "provider_trust_ok": all(v >= 0.5 for v in (data_q.get("provider_trust") or {}).values())
        if data_q.get("provider_trust")
        else True,
    }
    drift = results.get("provider_drift_alarms") or []
    checks["provider_drift_ok"] = len(drift) <= 3 if drift else True
    return {
        "checks": checks,
        "ok": all(checks.values()),
        "hard_ok": all(checks.get(k, True) for k in HARD_SLO_CHECKS),
        "coverage": coverage,
        "agent_error_count": len(errs),
        "data_quality_score": int(data_q.get("score", 100)),
        "provider_drift_count": len(drift),
        "execution_submitted": submitted,
        "execution_filled": filled,
        "execution_pending": pending,
    }
