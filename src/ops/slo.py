"""Simple SLO checks for weekly pipeline health."""

from __future__ import annotations

from typing import Any, Dict


def evaluate_slos(results: Dict[str, Any]) -> Dict[str, Any]:
    decisions = results.get("decisions") or {}
    errs = results.get("agent_errors") or {}
    data_q = results.get("data_quality") or {}
    coverage = len([d for d in decisions.values() if isinstance(d, dict) and d.get("action") != "hold"])
    exec_status = results.get("execution_status") or {}
    pending = int(exec_status.get("pending_count") or 0)
    filled = int(exec_status.get("filled_count") or 0)
    submitted = max(1, pending + filled)
    checks = {
        "agent_error_budget_ok": len(errs) <= 2,
        "data_quality_ok": int(data_q.get("score", 100)) >= 80,
        "decision_coverage_ok": coverage >= 1,
        "execution_fill_rate_ok": (filled / submitted) >= 0.5 if submitted else True,
        "provider_trust_ok": all(v >= 0.5 for v in (data_q.get("provider_trust") or {}).values()) if data_q.get("provider_trust") else True,
    }
    drift = results.get("provider_drift_alarms") or []
    if drift:
        checks["provider_drift_ok"] = len(drift) <= 3
    else:
        checks["provider_drift_ok"] = True
    return {
        "checks": checks,
        "ok": all(checks.values()),
        "coverage": coverage,
        "agent_error_count": len(errs),
        "data_quality_score": int(data_q.get("score", 100)),
        "provider_drift_count": len(drift),
    }

