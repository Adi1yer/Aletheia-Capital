#!/usr/bin/env python3
"""Daily snapshot for every configured workflow paper account."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

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
from src.ops.account_snapshot import collect_account_payload
from src.ops.daily_snapshots import enrich_payload_with_prior_day_lifecycle, save_snapshot

logger = structlog.get_logger()


def _run_biotech_hooks(broker) -> None:
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
            payload, alerts, xc = collect_account_payload(broker, wf, args.max_position_pct)
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
