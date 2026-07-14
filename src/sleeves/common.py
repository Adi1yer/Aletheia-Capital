"""Shared helpers for isolated workflow sleeves."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.broker.registry import get_workflow, try_get_broker, workflow_credentials_configured
from src.fund.orchestrator import workflow_risk_budget_pct
from src.risk.fund_risk import should_halt_workflow

logger = structlog.get_logger()


def init_workflow_broker(workflow_id: str, *, require_broker: bool = False):
    if should_halt_workflow(workflow_id):
        msg = f"Workflow halted by fund kill switch: {workflow_id}"
        if require_broker:
            raise RuntimeError(msg)
        logger.warning(msg)
        return None
    budget = workflow_risk_budget_pct(workflow_id)
    if budget <= 0:
        msg = f"Workflow risk budget zero: {workflow_id}"
        if require_broker:
            raise RuntimeError(msg)
        logger.warning(msg)
        return None
    wf = get_workflow(workflow_id)
    if wf is None or not wf.enabled:
        msg = f"Workflow disabled or unknown: {workflow_id}"
        if require_broker:
            raise RuntimeError(msg)
        return None
    if not workflow_credentials_configured(wf):
        msg = f"Workflow credentials missing: {workflow_id}"
        if require_broker:
            raise RuntimeError(msg)
        logger.warning(msg)
        return None
    broker = try_get_broker(workflow_id)
    if broker is None and require_broker:
        raise RuntimeError(f"Broker init failed for {workflow_id}")
    return broker


def append_skip(workflow_id: str, reason: str, **extra: Any) -> None:
    """Always write a ledger row on skip so digests never show no_ledger_file."""
    row: Dict[str, Any] = {
        "run_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "action": "skip",
        "reason": reason,
    }
    row.update(extra)
    append_ledger(workflow_id, row)


def append_ledger(workflow_id: str, row: Dict[str, Any]) -> None:
    wf = get_workflow(workflow_id)
    if wf is None:
        return
    path = Path(wf.data_dir) / "trades_ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {**row, "saved_at": datetime.utcnow().isoformat() + "Z", "workflow_id": workflow_id}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def read_ledger(workflow_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    wf = get_workflow(workflow_id)
    if wf is None:
        return []
    path = Path(wf.data_dir) / "trades_ledger.jsonl"
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows[-limit:]
