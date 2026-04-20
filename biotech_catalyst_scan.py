#!/usr/bin/env python3
"""
Biotech catalyst scanner — standalone from weekly pipeline.

Ingests public data (ClinicalTrials.gov, EDGAR, Yahoo), runs LLM analysis,
defined-risk paper trades on an isolated Alpaca paper account (BIOTECH_ALPACA_* env)
enabled by default; use --no-paper-execute for analysis only.

By default, only tickers with at least one trial whose primary/completion date falls
in the readout window (see settings / env) are analyzed — intended for near-term
trial readout catalysts.

Usage:
  poetry run python biotech_catalyst_scan.py --tickers MRNA,VRTX
  poetry run python biotech_catalyst_scan.py --from-watchlist
  poetry run python biotech_catalyst_scan.py --from-watchlist --no-paper-execute
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.biotech.analyzer import analyze_snapshot
from src.biotech.calibration import apply_gates
from src.biotech.dataset import append_run
from src.biotech.execution import execute_straddle_paper
from src.biotech.ingest import build_snapshot
from src.biotech.models import BiotechRunRecord
from src.biotech.readout_window import best_readout_date, snapshot_has_readout_catalyst
from src.biotech.risk_biotech import BiotechRiskBudget
from src.biotech.watchlist import load_biotech_tickers
from src.config.settings import settings
from src.ops.daily_snapshots import (
    format_snapshots_markdown,
    format_week_position_lifecycle_markdown,
)
from src.utils.email import get_email_notifier

logger = structlog.get_logger()


def _resolve_tickers(args: argparse.Namespace) -> list[str]:
    if args.from_watchlist:
        tickers = load_biotech_tickers()
        if not tickers:
            logger.error(
                "No tickers: set BIOTECH_TICKERS or add symbols to config/biotech_watchlist.txt",
            )
            sys.exit(1)
        return tickers
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        logger.error("No tickers")
        sys.exit(1)
    return tickers


def _build_biotech_email(
    results: List[Dict[str, Any]],
    fwd: int,
    grace: int,
    position_lifecycle_by_ticker: Dict[str, str] | None = None,
    week_lifecycle_markdown: str = "",
) -> tuple[str, str, str]:
    analyzed = [r for r in results if not r.get("skipped")]
    executed = [
        r
        for r in analyzed
        if isinstance(r.get("execution"), dict) and r["execution"].get("status") == "submitted"
    ]
    skipped = [r for r in results if r.get("skipped")]

    subject = (
        f"Biotech Weekly Catalyst Scan - {len(analyzed)} analyzed, "
        f"{len(executed)} executed, {len(skipped)} skipped"
    )

    lines: List[str] = []
    lines.append("BIOTECH WEEKLY CATALYST RESULTS")
    lines.append("=" * 70)
    lines.append(f"Readout window: today-{grace}d to today+{fwd}d")
    lines.append(
        f"Summary: analyzed={len(analyzed)}, executed={len(executed)}, skipped_no_window={len(skipped)}"
    )
    lines.append("")
    lc_map = position_lifecycle_by_ticker or {}
    if week_lifecycle_markdown.strip():
        lines.append("POSITION LIFECYCLE (7d option book — from daily snapshots)")
        lines.append("-" * 70)
        lines.append(week_lifecycle_markdown.strip())
        lines.append("")

    for row in results:
        t = row.get("ticker", "?")
        if row.get("skipped"):
            lines.append(f"{t}: SKIPPED (no trial in readout window)")
            continue

        analysis = row.get("analysis") or {}
        gate_reasons = row.get("gate_reasons") or []
        execution = row.get("execution") or {}
        lines.append(f"{t}:")
        lines.append(f"  - Gates passed: {bool(row.get('gates_ok'))}")
        lu = str(t).strip().upper()
        if lu in lc_map:
            lines.append(f"  - {lc_map[lu]}")
        else:
            lines.append(
                "  - Position lifecycle: no option legs for this underlying in the 7d snapshot window "
                "(isolated biotech paper book shows no carried straddle on this symbol, or snapshot gap)."
            )

        if execution and execution.get("status") == "submitted":
            orders = execution.get("orders") or []
            legs = [o.get("contract", "?") for o in orders if isinstance(o, dict)]
            strat = execution.get("strategy") or {}
            lines.append("  - Action: Executed defined-risk long straddle (1 call + 1 put).")
            lines.append(
                "  - Why this structure: expected catalyst-driven move while capping max loss to paid premium."
            )
            lines.append(
                f"  - Order legs: {', '.join(legs) if legs else 'submitted (legs unavailable)'}"
            )
            if execution.get("max_premium") is not None:
                lines.append(f"  - Premium cap used: ${float(execution.get('max_premium')):,.2f}")
            be_lo = strat.get("break_even_low_est")
            be_hi = strat.get("break_even_high_est")
            exp = strat.get("expiry")
            if be_lo is not None and be_hi is not None:
                lines.append(
                    f"  - Break-even estimate at expiry{f' {exp}' if exp else ''}: below ${float(be_lo):.2f} or above ${float(be_hi):.2f}"
                )
        elif execution:
            lines.append(
                f"  - Action: No order ({execution.get('status', 'skipped')} - {execution.get('reason') or execution.get('reasons')})"
            )
        else:
            lines.append("  - Action: No order (paper execution disabled)")

        if analysis.get("executive_summary"):
            lines.append(f"  - Thesis: {str(analysis.get('executive_summary')).strip()[:400]}")
        if analysis.get("clinical_assessment"):
            lines.append(
                f"  - Clinical rationale: {str(analysis.get('clinical_assessment')).strip()[:400]}"
            )
        if analysis.get("ip_assessment"):
            lines.append(f"  - IP rationale: {str(analysis.get('ip_assessment')).strip()[:300]}")
        if analysis.get("reasoning"):
            lines.append(f"  - Model reasoning: {str(analysis.get('reasoning')).strip()[:350]}")
        if gate_reasons:
            lines.append(f"  - Gate notes: {'; '.join(str(x) for x in gate_reasons)}")
        lines.append("")

    text = "\n".join(lines).strip()
    html = (
        '<html><body><pre style="white-space:pre-wrap;font-family:Arial,sans-serif;">'
        + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + "</pre></body></html>"
    )
    return subject, text, html


def main() -> int:
    p = argparse.ArgumentParser(description="Biotech catalyst scan (isolated from weekly pipeline)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated tickers (skips watchlist file)",
    )
    g.add_argument(
        "--from-watchlist",
        action="store_true",
        help="Use BIOTECH_TICKERS env or config/biotech_watchlist.txt",
    )
    p.add_argument(
        "--no-paper-execute",
        action="store_true",
        help="Skip Alpaca paper orders (analysis and logging only)",
    )
    p.add_argument(
        "--max-premium-pct-equity",
        type=float,
        default=0.02,
        help="Max premium vs equity (default 2%%)",
    )
    p.add_argument("--out-json", type=str, default="", help="Write combined results to this path")
    p.add_argument(
        "--email-to",
        type=str,
        default="",
        help="Biotech email recipient (default BIOTECH_RECIPIENT_EMAIL or RECIPIENT_EMAIL)",
    )
    p.add_argument(
        "--no-email",
        action="store_true",
        help="Disable biotech summary email",
    )
    p.add_argument(
        "--skip-readout-filter",
        action="store_true",
        help="Analyze every ticker even if no trial is in the readout window (not recommended)",
    )
    args = p.parse_args()

    tickers = _resolve_tickers(args)
    paper_execute = not bool(args.no_paper_execute)

    biotech_key = (settings.biotech_alpaca_api_key or "").strip()
    biotech_sec = (settings.biotech_alpaca_secret_key or "").strip()
    use_isolated = bool(biotech_key and biotech_sec)

    broker = None
    if paper_execute:
        if not use_isolated:
            logger.error(
                "Paper execute requires BIOTECH_ALPACA_API_KEY and BIOTECH_ALPACA_SECRET_KEY "
                "in .env (isolated paper account)."
            )
            return 1
        from src.broker.alpaca import AlpacaBroker

        broker = AlpacaBroker(api_key=biotech_key, secret_key=biotech_sec)
        acct = broker.get_account()
        logger.info("Biotech paper account", equity=acct.get("equity"), cash=acct.get("cash"))

    budget = BiotechRiskBudget(max_premium_pct_equity=float(args.max_premium_pct_equity))

    fwd = int(settings.biotech_readout_forward_days)
    grace = int(settings.biotech_readout_past_grace_days)

    biotech_intraweek = ""
    week_lc_md = ""
    lc_by_ticker: Dict[str, str] = {}
    try:
        biotech_intraweek = format_snapshots_markdown("biotech", days=7).strip()
        week_lc_md, lc_by_ticker = format_week_position_lifecycle_markdown("biotech", days=7)
        if week_lc_md.strip():
            biotech_intraweek = (
                biotech_intraweek + "\n\n" + week_lc_md.strip()
                if biotech_intraweek.strip()
                else week_lc_md.strip()
            )
    except Exception as e:
        logger.warning("Could not load biotech daily snapshots for context", error=str(e))

    results = []
    for t in tickers:
        logger.info("Building snapshot", ticker=t)
        snap = build_snapshot(t)
        if not args.skip_readout_filter and not snapshot_has_readout_catalyst(
            snap,
            forward_days=fwd,
            past_grace_days=grace,
        ):
            logger.info(
                "Skipping ticker — no trial in readout window",
                ticker=t,
                forward_days=fwd,
                past_grace_days=grace,
            )
            row = {
                "ticker": t,
                "skipped": True,
                "skip_reason": "no_trial_in_readout_window",
                "gates_ok": False,
                "gate_reasons": [],
                "analysis": None,
                "execution": None,
            }
            results.append(row)
            print(json.dumps(row, indent=2, default=str))
            continue

        logger.info("Analyzing", ticker=t)
        analysis = analyze_snapshot(snap, intraweek_context=biotech_intraweek)
        gates_ok, gate_reasons = apply_gates(snap, analysis)
        exec_result = None
        if paper_execute and broker and gates_ok:
            exec_result = execute_straddle_paper(broker, snap, budget)
        elif paper_execute and broker and not gates_ok:
            exec_result = {"status": "skipped", "reasons": gate_reasons}

        rec = BiotechRunRecord(
            snapshot=snap,
            analysis=analysis,
            gates_passed=gates_ok,
            execution=exec_result,
        )
        append_run(rec)
        results.append(
            {
                "ticker": t,
                "skipped": False,
                "gates_ok": gates_ok,
                "gate_reasons": gate_reasons,
                "analysis": analysis.model_dump(),
                "execution": exec_result,
            }
        )
        print(json.dumps(results[-1], indent=2, default=str))

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(results, indent=2, default=str))
        logger.info("Wrote results", path=args.out_json)

    if not args.no_email:
        recipient = (
            args.email_to
            or (settings.biotech_recipient_email or "").strip()
            or (settings.recipient_email or "").strip()
        )
        if recipient:
            subject, text_body, html_body = _build_biotech_email(
                results,
                fwd=fwd,
                grace=grace,
                position_lifecycle_by_ticker=lc_by_ticker,
                week_lifecycle_markdown=week_lc_md,
            )
            sent = get_email_notifier().send_email(
                recipient=recipient,
                subject=subject,
                body_text=text_body,
                body_html=html_body,
            )
            logger.info("Biotech summary email", recipient=recipient, sent=bool(sent))

    return 0


if __name__ == "__main__":
    sys.exit(main())
