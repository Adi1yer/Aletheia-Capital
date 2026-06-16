"""Simple SLO checks for weekly pipeline health."""

from __future__ import annotations

from typing import Any, Dict


def evaluate_slos(results: Dict[str, Any]) -> Dict[str, Any]:
    decisions = results.get("decisions") or {}
    errs = results.get("agent_errors") or {}
    data_q = results.get("data_quality") or {}
    coverage = len([d for d in decisions.values() if isinstance(d, dict) and d.get("action") != "hold"])
    checks = {
        "agent_error_budget_ok": len(errs) <= 2,
        "data_quality_ok": int(data_q.get("score", 100)) >= 80,
        "decision_coverage_ok": coverage >= 1,
    }
    return {
        "checks": checks,
        "ok": all(checks.values()),
        "coverage": coverage,
        "agent_error_count": len(errs),
        "data_quality_score": int(data_q.get("score", 100)),
    }

