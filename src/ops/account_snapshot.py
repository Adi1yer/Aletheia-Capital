"""Capture broker account snapshots for daily health and fund digest."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.broker.registry import (
    WorkflowAccount,
    list_physical_accounts,
    try_get_broker,
    workflow_credentials_configured,
)
from src.ops.daily_snapshots import enrich_payload_with_prior_day_lifecycle, save_snapshot

logger = structlog.get_logger()

_OCC_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def _parse_occ_symbol(symbol: str) -> Dict[str, Any]:
    m = _OCC_RE.match(symbol or "")
    if not m:
        return {}
    under, yymmdd, cp, strike_raw = m.groups()
    yy = int(yymmdd[:2]) + 2000
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])
    return {
        "underlying": under.strip(),
        "expiry": f"{yy:04d}-{mm:02d}-{dd:02d}",
        "type": "call" if cp == "C" else "put",
        "strike": int(strike_raw) / 1000.0,
    }


def collect_account_payload(
    broker: Any,
    workflow: WorkflowAccount,
    max_position_pct: float = 25.0,
) -> Tuple[Dict[str, Any], List[str], int]:
    """Build snapshot payload from live broker state."""
    acct = broker.get_account()
    positions = broker.get_positions()
    equity = float(acct.get("equity") or acct.get("portfolio_value") or 0)
    cash = float(acct.get("cash", 0))

    alerts: List[str] = []
    all_rows: List[Dict[str, Any]] = []
    option_rows: List[Dict[str, Any]] = []

    for sym, pos in sorted(positions.items(), key=lambda x: -abs(x[1].get("market_value", 0))):
        mv = float(pos.get("market_value", 0))
        qty = int(pos.get("qty", 0))
        avg = float(pos.get("avg_entry_price", 0))
        side = pos.get("side", "long")
        pct_eq = (100.0 * mv / equity) if equity > 0 and side == "long" and mv > 0 else 0.0
        if equity > 0 and side == "long" and mv > 0 and pct_eq > max_position_pct:
            alerts.append(f"{sym}: {pct_eq:.1f}% of equity (>{max_position_pct}%)")
        pnl_pct = 0.0
        if qty and avg:
            last = mv / qty if qty else 0
            pnl_pct = ((last - avg) / avg * 100) if avg > 0 else 0.0
        row = {
            "symbol": sym,
            "side": side,
            "qty": qty,
            "market_value": round(mv, 2),
            "pct_equity": round(pct_eq, 2),
            "unrealized_pnl_pct": round(pnl_pct, 2),
        }
        all_rows.append(row)
        occ = _parse_occ_symbol(sym)
        if occ:
            option_rows.append(
                {
                    "symbol": sym,
                    "qty": qty,
                    "side": side,
                    "avg_entry_price": round(avg, 4),
                    "market_value": round(mv, 2),
                    **occ,
                }
            )

    payload: Dict[str, Any] = {
        "date": date.today().isoformat(),
        "workflow_id": workflow.workflow_id,
        "account": workflow.snapshot_subdir,
        "label": workflow.label,
        "broker": workflow.broker,
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "buying_power": round(float(acct.get("buying_power", 0) or 0), 2),
        "position_count": len(positions),
        "dry_run": bool(acct.get("dry_run")),
        "alerts": alerts,
        "top_positions": all_rows[:15],
        "all_positions": all_rows,
        "option_positions": option_rows,
    }
    exit_code = 2 if alerts else 0
    return payload, alerts, exit_code


def _workflow_for_account_group(account_group: str) -> Optional[WorkflowAccount]:
    for wf in list_physical_accounts(enabled_only=True):
        if wf.physical_account_key == account_group or wf.account_group == account_group:
            return wf
    return None


def snapshot_physical_account(
    account_group: str,
    *,
    max_position_pct: float = 25.0,
) -> Optional[Path]:
    """Snapshot one physical account by account_group (e.g. multi_sleeve). Returns path or None."""
    wf = _workflow_for_account_group(account_group)
    if wf is None:
        logger.warning("No workflow for account group", account_group=account_group)
        return None
    if not workflow_credentials_configured(wf):
        logger.warning("Credentials missing for snapshot", account_group=account_group)
        return None
    broker = try_get_broker(wf.workflow_id)
    if broker is None:
        logger.warning("Broker init failed for snapshot", workflow=wf.workflow_id)
        return None
    try:
        payload, alerts, _ = collect_account_payload(broker, wf, max_position_pct)
        enrich_payload_with_prior_day_lifecycle(wf.snapshot_subdir, payload)
        path = save_snapshot(wf.snapshot_subdir, payload)
        logger.info(
            "Saved account snapshot",
            account_group=account_group,
            workflow=wf.workflow_id,
            equity=payload.get("equity"),
            path=str(path),
            alerts=len(alerts),
        )
        return path
    except Exception as e:
        logger.error("Account snapshot failed", account_group=account_group, error=str(e))
        return None
    finally:
        if hasattr(broker, "disconnect"):
            broker.disconnect()
