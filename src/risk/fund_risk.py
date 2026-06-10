"""Fund-level risk across isolated workflow paper accounts."""

from __future__ import annotations

from typing import Any, Dict, List

import structlog

from src.fund.orchestrator import collect_workflow_equity, load_allocation
from src.broker.registry import list_workflows

logger = structlog.get_logger()


def per_workflow_limits() -> Dict[str, Dict[str, float]]:
    """Default risk knobs per workflow (overridable via fund_allocation.json)."""
    return {
        "weekly-scan": {"max_gross_pct": 1.0, "max_single_position_pct": 0.25},
        "biotech-catalyst": {"max_gross_pct": 0.5, "max_single_position_pct": 0.15},
        "hedge-weekly": {"max_gross_pct": 0.3, "max_single_position_pct": 0.2},
        "options-income": {"max_gross_pct": 0.6, "max_single_position_pct": 0.1},
        "congressional": {"max_gross_pct": 0.25, "max_single_position_pct": 0.05},
        "macro-etf": {"max_gross_pct": 0.5, "max_single_position_pct": 0.2},
        "crypto-weekly": {"max_gross_pct": 0.3, "max_single_position_pct": 0.15},
        "forex-weekly": {"max_gross_pct": 2.0, "max_single_position_pct": 0.15},
        "futures-trend": {"max_gross_pct": 1.5, "max_single_position_pct": 0.25},
        "commodities": {"max_gross_pct": 1.0, "max_single_position_pct": 0.2},
    }


def evaluate_fund_risk() -> Dict[str, Any]:
    """Summarize concentration and kill-switch state across workflows."""
    equity_map = collect_workflow_equity()
    alloc = load_allocation()
    limits = per_workflow_limits()
    alerts: List[str] = []
    by_workflow: Dict[str, Any] = {}

    for wf in list_workflows(enabled_only=True):
        snap = equity_map.get(wf.workflow_id) or {}
        lim = limits.get(wf.workflow_id, {})
        wf_alerts = list(snap.get("alerts") or [])
        if alloc.get("kill_switches", {}).get(wf.workflow_id):
            wf_alerts.append("KILL_SWITCH_ACTIVE")
        by_workflow[wf.workflow_id] = {
            "equity": snap.get("equity"),
            "limits": lim,
            "alerts": wf_alerts,
        }
        alerts.extend(f"{wf.workflow_id}: {a}" for a in wf_alerts)

    total = sum(float(v.get("equity") or 0) for v in equity_map.values())
    return {
        "total_equity": round(total, 2),
        "workflows": by_workflow,
        "alerts": alerts,
        "halt": bool(any("KILL_SWITCH" in a for a in alerts)),
    }


def should_halt_workflow(workflow_id: str) -> bool:
    alloc = load_allocation()
    return bool(alloc.get("kill_switches", {}).get(workflow_id))
