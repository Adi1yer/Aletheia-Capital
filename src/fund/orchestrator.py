"""Fund-level orchestrator: aggregate workflow snapshots and set allocation targets."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.broker.registry import list_workflows, load_workflow_registry
from src.config.settings import settings
from src.ops.daily_snapshots import load_snapshots_for_days

logger = structlog.get_logger()


def _allocation_path() -> Path:
    return Path(getattr(settings, "fund_allocation_path", "config/fund_allocation.json"))


def _metrics_path() -> Path:
    return Path(getattr(settings, "fund_metrics_path", "data/fund/weekly_metrics.json"))


def collect_workflow_equity() -> Dict[str, Dict[str, Any]]:
    """Latest equity per enabled workflow from daily snapshots."""
    out: Dict[str, Dict[str, Any]] = {}
    for wf in list_workflows(enabled_only=True):
        snaps = load_snapshots_for_days(wf.snapshot_subdir, days=14)
        if not snaps:
            out[wf.workflow_id] = {
                "equity": 0.0,
                "snapshot_subdir": wf.snapshot_subdir,
                "label": wf.label,
                "broker": wf.broker,
            }
            continue
        latest = snaps[0]
        eq = float(latest.get("equity") or 0)
        prior = float(snaps[1].get("equity") or eq) if len(snaps) > 1 else eq
        delta_pct = ((eq - prior) / prior * 100) if prior > 0 else 0.0
        out[wf.workflow_id] = {
            "equity": round(eq, 2),
            "equity_delta_pct_1d": round(delta_pct, 4),
            "date": latest.get("date"),
            "snapshot_subdir": wf.snapshot_subdir,
            "label": wf.label,
            "broker": wf.broker,
            "alerts": latest.get("alerts") or [],
        }
    return out


def compute_weekly_metrics() -> Dict[str, Any]:
    """Build fund metrics artifact from snapshots."""
    workflows = collect_workflow_equity()
    total = sum(w.get("equity", 0) for w in workflows.values())
    weights: Dict[str, float] = {}
    for wid, w in workflows.items():
        eq = float(w.get("equity") or 0)
        weights[wid] = round(eq / total, 4) if total > 0 else 0.0

    return {
        "generated_at": date.today().isoformat(),
        "total_equity": round(total, 2),
        "workflows": workflows,
        "weights": weights,
    }


def load_sleeve_budget_targets() -> Dict[str, float]:
    path = Path("config/sleeve_budgets.json")
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("targets") or {}
        return {str(k): float(v) for k, v in raw.items()}
    except Exception:
        return {}


def default_allocation() -> Dict[str, Any]:
    reg = load_workflow_registry()
    budget_targets = load_sleeve_budget_targets()
    targets: Dict[str, float] = {}
    if budget_targets:
        for wid in reg:
            if wid in budget_targets:
                targets[wid] = float(budget_targets[wid])
        # Any registered workflow missing from config gets a small residual share
        missing = [wid for wid in reg if wid not in targets]
        used = sum(targets.values())
        residual = max(0.0, 1.0 - used)
        if missing:
            each = residual / len(missing) if residual > 0 else 0.02
            for wid in missing:
                targets[wid] = round(each, 4)
        total = sum(targets.values()) or 1.0
        targets = {k: round(v / total, 4) for k, v in targets.items()}
        notes = "Phase 13 sleeve_budgets.json targets (normalized)."
    else:
        n = max(1, len(reg))
        equal = round(1.0 / n, 4)
        targets = {wid: equal for wid in reg}
        notes = "Equal-weight default until promotion gates adjust targets."
    return {
        "generated_at": date.today().isoformat(),
        "targets": targets,
        "kill_switches": {},
        "notes": notes,
    }


def load_allocation() -> Dict[str, Any]:
    path = _allocation_path()
    if not path.is_file():
        return default_allocation()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or default_allocation()
    except Exception:
        return default_allocation()


def save_allocation(data: Dict[str, Any]) -> Path:
    path = _allocation_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["generated_at"] = date.today().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def save_weekly_metrics(data: Optional[Dict[str, Any]] = None) -> Path:
    data = data or compute_weekly_metrics()
    path = _metrics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def run_orchestrator(*, update_allocation: bool = False) -> Dict[str, Any]:
    """Aggregate metrics; optionally nudge allocation toward recent performers."""
    metrics = compute_weekly_metrics()
    save_weekly_metrics(metrics)
    alloc = load_allocation()
    if update_allocation and metrics.get("workflows"):
        targets = dict(alloc.get("targets") or {})
        for wid, w in metrics["workflows"].items():
            delta = float(w.get("equity_delta_pct_1d") or 0)
            if delta > 1.0:
                targets[wid] = min(0.35, float(targets.get(wid, 0.1)) + 0.01)
            elif delta < -2.0:
                targets[wid] = max(0.02, float(targets.get(wid, 0.1)) - 0.01)
        total_t = sum(targets.values()) or 1.0
        alloc["targets"] = {k: round(v / total_t, 4) for k, v in targets.items()}
        save_allocation(alloc)
    logger.info(
        "Fund orchestrator",
        total_equity=metrics.get("total_equity"),
        workflows=len(metrics.get("workflows") or {}),
    )
    return {"metrics": metrics, "allocation": alloc}


def workflow_risk_budget_pct(workflow_id: str) -> float:
    """Optional cap read by each workflow before trading."""
    alloc = load_allocation()
    if alloc.get("kill_switches", {}).get(workflow_id):
        return 0.0
    targets = alloc.get("targets") or {}
    if workflow_id in targets:
        return float(targets[workflow_id])
    # Fall back to Phase 13 sleeve budget config
    budget = load_sleeve_budget_targets()
    if workflow_id in budget:
        return float(budget[workflow_id])
    return 0.1
