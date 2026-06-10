"""Build consolidated weekly digest for satellite workflow sleeves."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from src.broker.registry import list_workflows, workflow_credentials_configured
from src.fund.orchestrator import collect_workflow_equity

SATELLITE_WORKFLOWS = frozenset(
    {
        "hedge-weekly",
        "options-income",
        "congressional",
        "macro-etf",
        "crypto-weekly",
    }
)


def _read_ledger_tail(data_dir: str, limit: int = 3) -> List[Dict[str, Any]]:
    path = Path(data_dir) / "trades_ledger.jsonl"
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


def build_sleeve_digest(*, run_date: str | None = None) -> Dict[str, Any]:
    """Aggregate latest ledger rows and equity snapshots per satellite workflow."""
    run_date = run_date or date.today().isoformat()
    equity = collect_workflow_equity()
    sections: List[Dict[str, Any]] = []

    for wf in list_workflows(enabled_only=True):
        if wf.workflow_id not in SATELLITE_WORKFLOWS:
            continue
        creds_ok = workflow_credentials_configured(wf)
        eq_info = equity.get(wf.workflow_id) or {}
        ledger_rows = _read_ledger_tail(wf.data_dir)
        latest = ledger_rows[-1] if ledger_rows else {}
        action = latest.get("action") or ("executed" if latest.get("executed") else "skip")
        reason = (
            latest.get("reason")
            or latest.get("note")
            or latest.get("regime")
            or ("credentials_missing" if not creds_ok else "no_ledger")
        )
        sections.append(
            {
                "workflow_id": wf.workflow_id,
                "label": wf.label,
                "credentials_ok": creds_ok,
                "equity": eq_info.get("equity"),
                "equity_delta_pct_1d": eq_info.get("equity_delta_pct_1d"),
                "action": action,
                "reason": reason,
                "latest_ledger": latest,
            }
        )

    return {
        "run_date": run_date,
        "sections": sections,
        "total_satellite_equity": round(
            sum(float(s.get("equity") or 0) for s in sections if s.get("equity") is not None),
            2,
        ),
    }


def format_digest_markdown(digest: Dict[str, Any]) -> str:
    lines = [
        "SATELLITE SLEEVE WEEKLY DIGEST",
        "=" * 60,
        f"Date: {digest.get('run_date')}",
        f"Total satellite equity (snapshots): ${digest.get('total_satellite_equity', 0):,.2f}",
        "",
    ]
    for s in digest.get("sections") or []:
        lines.append(f"{s.get('label')} ({s.get('workflow_id')})")
        cred = "ok" if s.get("credentials_ok") else "MISSING"
        lines.append(f"  Credentials: {cred}")
        eq = s.get("equity")
        lines.append(f"  Equity: ${eq:,.2f}" if eq is not None else "  Equity: n/a")
        d1 = s.get("equity_delta_pct_1d")
        if d1 is not None:
            lines.append(f"  1d delta: {d1:+.2f}%")
        lines.append(f"  Last action: {s.get('action')} — {s.get('reason')}")
        latest = s.get("latest_ledger") or {}
        if latest:
            summary_keys = ("pick", "symbol", "candidates", "picks", "qty", "executed")
            bits = [f"{k}={latest[k]}" for k in summary_keys if k in latest]
            if bits:
                lines.append(f"  Ledger: {', '.join(bits)}")
        lines.append("")
    return "\n".join(lines).strip()
