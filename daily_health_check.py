#!/usr/bin/env python3
"""Daily snapshot for every configured workflow paper account."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.broker.registry import (
    WorkflowAccount,
    list_physical_accounts,
    list_workflows,
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


def _collect_payload(
    broker: Any,
    workflow: WorkflowAccount,
    max_position_pct: float,
) -> Tuple[Dict[str, Any], List[str], int]:
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


def _run_biotech_hooks(broker: Any) -> None:
    try:
        from src.biotech.outcome_resolver import resolve_open_thesis_entries
        from src.biotech.counterfactual_ledger import resolve_counterfactuals

        n = resolve_open_thesis_entries(broker)
        if n:
            logger.info("Biotech thesis entries updated", count=n)
        resolve_counterfactuals()
    except Exception as e:
        logger.warning("Biotech thesis resolve skipped", error=str(e))
    try:
        from src.biotech.exit_policy import evaluate_open_straddles_for_exit

        exits = evaluate_open_straddles_for_exit(broker)
        if exits:
            logger.info("Biotech exit policy", actions=len(exits))
    except Exception as e:
        logger.warning("Biotech exit policy skipped", error=str(e))


def _resolve_accounts_arg(arg: str) -> List[WorkflowAccount]:
    if arg in ("both", "legacy-both"):
        return [w for w in list_workflows(enabled_only=True) if w.snapshot_subdir in ("stock", "biotech")]
    if arg == "all":
        return list_physical_accounts(enabled_only=True)
    if arg in ("stock", "biotech"):
        mapping = {"stock": "weekly-scan", "biotech": "biotech-catalyst"}
        wf = next((w for w in list_workflows() if w.workflow_id == mapping[arg]), None)
        return [wf] if wf else []
    wf = next((w for w in list_workflows() if w.workflow_id == arg or w.snapshot_subdir == arg), None)
    return [wf] if wf else []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Daily snapshot per workflow paper account")
    p.add_argument(
        "--account",
        default="all",
        help="all | stock | biotech | both | workflow_id (e.g. weekly-scan)",
    )
    p.add_argument("--max-position-pct", type=float, default=25.0)
    p.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: never fail on concentration alerts (exit 1 only if no snapshots saved)",
    )
    p.add_argument(
        "--fail-on-alerts",
        action="store_true",
        help="Exit 2 when any account exceeds --max-position-pct (default off in --ci)",
    )
    args = p.parse_args(argv)
    fail_on_alerts = bool(args.fail_on_alerts) and not args.ci

    workflows = _resolve_accounts_arg(args.account)
    if not workflows:
        logger.error("No matching workflows", account=args.account)
        print(
            "DAILY HEALTH CHECK FAILED: no workflow accounts with credentials configured. "
            "Set ALPACA_*, BIOTECH_ALPACA_*, and MULTI_SLEEVE_ALPACA_* secrets.",
            file=sys.stderr,
        )
        return 1

    worst = 0
    skipped = 0
    saved = 0
    errors: List[str] = []
    alert_msgs: List[str] = []
    for wf in workflows:
        if not workflow_credentials_configured(wf):
            logger.warning("Skipping workflow — credentials not set", workflow=wf.workflow_id)
            skipped += 1
            continue
        broker = try_get_broker(wf.workflow_id)
        if broker is None:
            msg = f"{wf.workflow_id}: broker init failed"
            logger.warning(msg)
            errors.append(msg)
            skipped += 1
            continue
        try:
            payload, alerts, xc = _collect_payload(broker, wf, args.max_position_pct)
            enrich_payload_with_prior_day_lifecycle(wf.snapshot_subdir, payload)
            path = save_snapshot(wf.snapshot_subdir, payload)
            logger.info(
                "Saved daily snapshot",
                workflow=wf.workflow_id,
                path=str(path),
                alerts=len(alerts),
            )
            saved += 1
            worst = max(worst, xc)
            for a in alerts:
                alert_msgs.append(f"{wf.workflow_id}: {a}")
            if wf.workflow_id == "biotech-catalyst":
                try:
                    _run_biotech_hooks(broker)
                except Exception as hook_err:
                    logger.warning(
                        "Biotech post-snapshot hooks failed",
                        workflow=wf.workflow_id,
                        error=str(hook_err),
                    )
        except Exception as e:
            msg = f"{wf.workflow_id}: {e}"
            logger.error("Daily snapshot failed", workflow=wf.workflow_id, error=str(e))
            errors.append(msg)
            skipped += 1
        finally:
            if hasattr(broker, "disconnect"):
                broker.disconnect()

    if alert_msgs:
        logger.warning("Concentration alerts", alerts=alert_msgs)
        for line in alert_msgs:
            print(f"ALERT: {line}", file=sys.stderr)

    if errors:
        logger.warning("Daily health check account errors", count=len(errors), errors=errors)
        for line in errors:
            print(f"ERROR: {line}", file=sys.stderr)

    print(
        f"Daily health check: saved={saved}/{len(workflows)} "
        f"skipped={skipped} concentration_alerts={len(alert_msgs)}"
    )

    if saved == 0:
        logger.error(
            "No snapshots saved",
            workflows=len(workflows),
            skipped=skipped,
            errors=errors,
        )
        print("DAILY HEALTH CHECK FAILED: no snapshots saved.", file=sys.stderr)
        return 1
    if errors:
        logger.warning("Partial daily health check", saved=saved, failed=len(errors))
    if fail_on_alerts and worst == 2:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
