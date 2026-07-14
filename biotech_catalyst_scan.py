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
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.biotech.analyzer import analyze_snapshot
from src.biotech.discovery_ladder import run_discovery_ladder
from src.biotech.calibration import apply_gates
from src.biotech.dataset import append_run
from src.biotech.ingest import build_snapshot
from src.biotech.models import BiotechRunRecord
from src.biotech.outcome_resolver import resolve_open_thesis_entries
from src.biotech.readout_window import snapshot_has_readout_catalyst
from src.biotech.risk_biotech import BiotechRiskBudget
from src.biotech.thesis_ledger import (
    append_thesis_entry,
    build_entry_from_execution,
    catalyst_fields_from_snapshot,
    format_past_trades_context,
    format_scorecard_markdown,
    scorecard,
)
from src.biotech.watchlist import load_biotech_tickers
from src.config.settings import settings
from src.ops.daily_snapshots import (
    format_snapshots_markdown,
    format_week_position_lifecycle_markdown,
)
from src.utils.email import get_email_notifier

logger = structlog.get_logger()


def _run_id() -> str:
    return f"biotech-{date.today().isoformat()}"


def _execute_arm(
    arm: str,
    broker: Any,
    snap: Any,
    analysis: Any,
    budget: BiotechRiskBudget,
    *,
    gates_ok: bool,
    gate_reasons: List[str],
    run_id: str,
    run_date: str,
    catalyst: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Run one arm; return (exec_result, trade_id)."""
    from src.biotech.execution import execute_straddle_paper

    if arm == "llm_gated" and not gates_ok:
        return {"status": "skipped", "reasons": gate_reasons, "arm": arm}, None

    from src.biotech.policy_learning import get_active_policy

    policy = get_active_policy()
    exec_result = execute_straddle_paper(broker, snap, budget, arm=arm, policy=policy)
    trade_id = None
    if isinstance(exec_result, dict) and exec_result.get("status") in ("filled", "submitted", "partial"):
        entry = build_entry_from_execution(
            ticker=snap.ticker,
            arm=arm,
            run_id=run_id,
            run_date=run_date,
            snap=snap,
            analysis=analysis,
            gates_ok=gates_ok,
            gate_reasons=gate_reasons,
            exec_result=exec_result,
            catalyst=catalyst,
        )
        trade_id = append_thesis_entry(entry)
        if exec_result.get("status") == "filled":
            try:
                from src.utils.alerts import send_alert

                send_alert(
                    f"Biotech straddle ({arm})",
                    f"{snap.ticker}: paper straddle opened",
                    exec_result,
                )
            except Exception:
                pass
    return exec_result, trade_id


def _resolve_tickers(args: argparse.Namespace) -> list[str]:
    if args.discover_candidates:
        return []
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
    discovery_info: Dict[str, Any] | None = None,
    ladder_meta: Dict[str, Any] | None = None,
    learning_markdown: str = "",
) -> tuple[str, str, str]:
    analyzed = [r for r in results if not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]
    gates_passed = sum(1 for r in analyzed if r.get("gates_ok"))

    def _arm_executed(ex: Any, arm: str) -> bool:
        if not isinstance(ex, dict):
            return False
        arm_ex = ex.get(arm) if "mechanical" in ex or "llm_gated" in ex else ex
        return isinstance(arm_ex, dict) and arm_ex.get("status") in ("filled", "submitted", "partial")

    mech_n = sum(1 for r in analyzed if _arm_executed(r.get("execution"), "mechanical"))
    llm_n = sum(1 for r in analyzed if _arm_executed(r.get("execution"), "llm_gated"))

    stage = (ladder_meta or {}).get("discovery_stage") or (discovery_info or {}).get("discovery_stage")
    dry_prefix = "DRY RUN - " if len(analyzed) == 0 else ""
    subject = (
        f"{dry_prefix}Biotech Weekly Catalyst Scan - {len(analyzed)} analyzed, "
        f"{gates_passed} gates passed, mech={mech_n} llm={llm_n}, {len(skipped)} skipped"
    )
    if stage:
        subject += f" [stage={stage}]"

    lines: List[str] = []
    try:
        lines.append(format_scorecard_markdown(scorecard(weeks=12)))
        lines.append("")
    except Exception:
        pass
    if learning_markdown.strip():
        lines.append(learning_markdown.strip())
        lines.append("")
    try:
        from src.biotech.counterfactual_ledger import recent_for_email

        cf = recent_for_email()
        if cf:
            lines.append("MISSED CATALYST OPPORTUNITIES (no_trade / gates blocked)")
            lines.append("-" * 70)
            for r in cf:
                lines.append(
                    f"  {r.get('ticker')}: move_5d={r.get('move_5d_pct', 'n/a')}% "
                    f"reasons={'; '.join(r.get('gate_reasons') or [])[:80]}"
                )
            lines.append("")
    except Exception:
        pass
    lines.append("BIOTECH WEEKLY CATALYST RESULTS")
    lines.append("=" * 70)
    lines.append(f"Readout window: today-{grace}d to today+{fwd}d")
    lines.append(
        f"Summary: analyzed={len(analyzed)}, gates_passed={gates_passed}, "
        f"mechanical_executed={mech_n}, llm_gated_executed={llm_n}, skipped_no_window={len(skipped)}"
    )
    d_info = discovery_info or {}
    if d_info:
        lines.append(
            "Discovery: "
            f"seed={int(d_info.get('seed_count', 0))}, "
            f"profiled={int(d_info.get('profiled_count', 0))}, "
            f"candidates={int(d_info.get('candidate_count', 0))}, "
            f"selected={int(d_info.get('selected_count', 0))}"
        )
        lines.append(
            "Exclusions: "
            f"non_biotech={int(d_info.get('excluded_non_biotech', 0))}, "
            f"illiquid={int(d_info.get('excluded_illiquid', 0))}, "
            f"cap_too_small={int(d_info.get('excluded_market_cap_too_small', 0))}, "
            f"cap_too_large={int(d_info.get('excluded_market_cap_too_large', 0))}, "
            f"missing_cap={int(d_info.get('excluded_missing_market_cap', 0))}, "
            f"blocklist={int(d_info.get('excluded_blocklist', 0))}, "
            f"non_optionable={int(d_info.get('excluded_non_optionable', 0))}, "
            f"no_readout_window={int(d_info.get('excluded_no_readout_window', 0))}"
        )
        rd_cap_disp = d_info.get("discovery_readout_max_forward_days")
        lines.append(
            "Discovery readout gates: "
            f"min_phase={int(d_info.get('discovery_min_phase', 0))}, "
            f"readout_max_forward_days={rd_cap_disp if rd_cap_disp is not None else 'off'}"
        )
    lm = ladder_meta or {}
    if lm.get("discovery_stage"):
        lines.append(f"Discovery stage: {lm.get('discovery_stage')}")
        for st in lm.get("stages") or []:
            lines.append(
                f"  Ladder {st.get('stage')}: selected={int(st.get('selected_count', 0))}"
            )
    near_miss = lm.get("near_miss_summaries") or d_info.get("near_miss_summaries") or []
    if near_miss and len(analyzed) == 0:
        lines.append("Near-miss tickers (screened biotech, no readout in window):")
        for nm in near_miss[:20]:
            lines.append(
                f"  {nm.get('ticker')}: {nm.get('reason', 'n/a')} "
                f"phase={nm.get('phase', 'n/a')} readout={nm.get('readout_date', 'n/a')}"
            )
    lines.append("")
    try:
        from src.biotech.pnl_ledger import weekly_summary

        ledger = weekly_summary()
        if ledger.get("count"):
            lines.append("STRADDLE P&L LEDGER (paper)")
            lines.append("-" * 70)
            lines.append(f"  Total entries: {ledger['count']}")
            for ent in ledger.get("entries") or []:
                lines.append(
                    f"  {ent.get('ticker')}: {ent.get('status')} "
                    f"premium={ent.get('premium')} @ {str(ent.get('recorded_at', ''))[:10]}"
                )
            lines.append("")
    except Exception:
        pass
    d_cal = (discovery_info or {}).get("candidate_summaries") or []
    if d_cal:
        lines.append("CATALYST CALENDAR (discovery candidates, readout window)")
        lines.append("-" * 70)
        for c in d_cal[:25]:
            lines.append(
                f"  {c.get('ticker')}: phase={c.get('phase')} "
                f"readout~{c.get('readout_date', 'n/a')}"
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
        catalyst = row.get("catalyst") or {}
        lines.append(f"{t}:")
        if catalyst.get("nct_id"):
            lines.append(
                f"  - Catalyst: {catalyst.get('nct_id')} readout~{catalyst.get('readout_date_expected', 'n/a')} "
                f"phase={catalyst.get('phase', 'n/a')}"
            )
        lines.append(f"  - Gates passed: {bool(row.get('gates_ok'))}")
        lu = str(t).strip().upper()
        if lu in lc_map:
            lines.append(f"  - {lc_map[lu]}")
        else:
            lines.append(
                "  - Position lifecycle: no option legs for this underlying in the 7d snapshot window "
                "(isolated biotech paper book shows no carried straddle on this symbol, or snapshot gap)."
            )

        for arm_label in ("mechanical", "llm_gated"):
            arm_ex = execution.get(arm_label) if isinstance(execution, dict) else None
            if not arm_ex:
                continue
            st = arm_ex.get("status", "skipped")
            if st in ("filled", "submitted", "partial"):
                orders = arm_ex.get("orders") or []
                legs = [o.get("contract", "?") for o in orders if isinstance(o, dict)]
                strat = arm_ex.get("strategy") or {}
                lines.append(f"  - [{arm_label}] Executed {strat.get('type', 'straddle')} ({st}).")
                lines.append(f"    Legs: {', '.join(legs) if legs else 'n/a'}")
                prem = arm_ex.get("premium_filled_usd") or strat.get("estimated_premium_total")
                if prem:
                    lines.append(f"    Premium: ${float(prem):,.2f}")
            else:
                lines.append(
                    f"  - [{arm_label}] No order ({st}: {arm_ex.get('reason') or arm_ex.get('reasons')})"
                )

        if not execution:
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
    g = p.add_mutually_exclusive_group(required=False)
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
    g.add_argument(
        "--discover-candidates",
        action="store_true",
        help="Discover catalyst-first biotech candidates from broad market universe (default)",
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
    p.add_argument(
        "--max-discovery-universe",
        type=int,
        default=320,
        help="Max broad-market names considered during catalyst-first discovery",
    )
    p.add_argument(
        "--max-discovery-candidates",
        type=int,
        default=20,
        help="Max catalyst-first candidates to analyze after filters",
    )
    p.add_argument(
        "--fallback-forward-days",
        type=int,
        default=180,
        help="Forward readout window for fallback discovery if strict window yields zero",
    )
    p.add_argument(
        "--fallback-past-grace-days",
        type=int,
        default=60,
        help="Past grace days for fallback discovery if strict window yields zero",
    )
    p.add_argument(
        "--discovery-min-market-cap-usd",
        type=float,
        default=None,
        help="Minimum market cap for discovery (default from BIOTECH_DISCOVERY_MIN_MARKET_CAP_USD; 0 disables)",
    )
    p.add_argument(
        "--discovery-max-market-cap-usd",
        type=float,
        default=None,
        help="Maximum market cap for discovery (default from BIOTECH_DISCOVERY_MAX_MARKET_CAP_USD; 0 disables)",
    )
    p.add_argument(
        "--discovery-allow-missing-market-cap",
        action="store_true",
        help="Allow names with unknown Yahoo marketCap through discovery (default: exclude)",
    )
    p.add_argument(
        "--discovery-min-phase",
        type=int,
        default=None,
        help="Minimum trial phase (0=off; default BIOTECH_DISCOVERY_MIN_PHASE)",
    )
    p.add_argument(
        "--discovery-readout-max-forward-days",
        type=int,
        default=None,
        help="Cap forward readout horizon (0=use full forward window; default BIOTECH_DISCOVERY_READOUT_MAX_FORWARD_DAYS)",
    )
    p.add_argument(
        "--no-mechanical-arm",
        action="store_true",
        help="Disable mechanical straddle arm (A/B control)",
    )
    p.add_argument(
        "--no-llm-gated-arm",
        action="store_true",
        help="Disable LLM-gated straddle arm",
    )
    args = p.parse_args()
    if not args.tickers and not args.from_watchlist and not args.discover_candidates:
        args.discover_candidates = True

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

    run_id = _run_id()
    run_date = date.today().isoformat()

    from src.biotech.policy_learning import (
        compute_biotech_policy,
        get_active_policy,
        policy_summary_for_prompt,
        save_biotech_policy,
    )
    from src.biotech.promotion_gates import evaluate_biotech_proposal
    from src.biotech.learning_changelog import append_biotech_changelog, format_learning_markdown
    from src.biotech.counterfactual_ledger import resolve_counterfactuals

    active_policy = get_active_policy()
    learning_markdown = ""

    if broker:
        try:
            n = resolve_open_thesis_entries(broker)
            logger.info("Pre-run thesis resolve", updated=n)
        except Exception as e:
            logger.warning("Pre-run thesis resolve failed", error=str(e))
        try:
            from src.biotech.exit_policy import evaluate_open_straddles_for_exit

            exits = evaluate_open_straddles_for_exit(broker)
            if exits:
                logger.info("Exit policy actions", count=len(exits))
        except Exception as e:
            logger.warning("Exit policy skipped", error=str(e))

    try:
        resolve_counterfactuals()
    except Exception:
        pass

    policy_result = compute_biotech_policy(weeks=24)
    proposed = policy_result.get("policy") or active_policy
    promotion = evaluate_biotech_proposal(proposed)
    if promotion.get("promote"):
        save_biotech_policy(proposed)
        active_policy = proposed
    learning_markdown = format_learning_markdown(
        policy_result=policy_result,
        promotion=promotion,
    )
    sc = scorecard(weeks=12)
    append_biotech_changelog(
        run_id=run_id,
        run_date=run_date,
        policy_adjustments=policy_result.get("adjustments"),
        scorecard=sc,
        promoted=promotion.get("promote"),
        promotion_reason=str(promotion.get("reason") or ""),
    )
    try:
        from src.biotech.cross_feed import save_cross_feed

        save_cross_feed(weeks=4)
    except Exception:
        pass

    mech_enabled = (
        bool(active_policy.get("mechanical_arm_enabled", True))
        and not args.no_mechanical_arm
    )
    llm_arm_enabled = (
        bool(active_policy.get("llm_gated_arm_enabled", True))
        and not args.no_llm_gated_arm
    )
    # Phase 13: freeze mechanical until enough closed trades for learning.
    try:
        from src.biotech.policy_learning import DISCOVERY_MIN_CLOSED_TRADES, closed_rows
        from src.performance.auto_throttle import apply_throttle_to_run_config

        n_closed = len(closed_rows(weeks=24))
        thr = apply_throttle_to_run_config({})
        force_off = bool((thr.get("auto_throttle") or {}).get("throttled")) or bool(
            thr.get("biotech_mechanical_force_off")
        )
        if force_off or n_closed < int(DISCOVERY_MIN_CLOSED_TRADES):
            if mech_enabled:
                logger.info(
                    "Mechanical arm hard-off (Phase 13)",
                    closed=n_closed,
                    need=int(DISCOVERY_MIN_CLOSED_TRADES),
                    auto_throttle=force_off,
                )
            mech_enabled = False
    except Exception as e:
        logger.warning("Mechanical arm sample gate failed", error=str(e))
        mech_enabled = False

    # One-time / ongoing ghost prune of open straddles with past no-topline catalysts
    if paper_execute and broker:
        try:
            from src.biotech.ghost_prune import prune_ghost_open_straddles

            pruned = prune_ghost_open_straddles(broker, close_legs=True)
            if pruned:
                logger.info("Ghost straddles pruned", count=len(pruned))
        except Exception as e:
            logger.warning("Ghost prune failed", error=str(e))

    past_trades_ctx = format_past_trades_context(weeks=12)
    policy_prompt = policy_summary_for_prompt(policy_result)

    prem_pct = float(active_policy.get("max_premium_pct_equity", args.max_premium_pct_equity))
    budget = BiotechRiskBudget(max_premium_pct_equity=prem_pct)
    arm_budget = budget
    if broker:
        from src.biotech.risk_biotech import equity_from_alpaca_account

        arm_budget = budget.per_arm_budget(equity_from_alpaca_account(broker.get_account()))

    fwd = int(settings.biotech_readout_forward_days)
    grace = int(settings.biotech_readout_past_grace_days)
    scan_min_phase = (
        int(settings.biotech_discovery_min_phase)
        if args.discovery_min_phase is None
        else int(args.discovery_min_phase)
    )
    _rd_raw = (
        int(settings.biotech_discovery_readout_max_forward_days)
        if args.discovery_readout_max_forward_days is None
        else int(args.discovery_readout_max_forward_days)
    )
    scan_readout_max_forward_days: Optional[int] = _rd_raw if _rd_raw > 0 else None

    discovery_kw: Dict[str, Any] = {}
    if args.discovery_min_market_cap_usd is not None:
        discovery_kw["min_market_cap_usd"] = float(args.discovery_min_market_cap_usd)
    if args.discovery_max_market_cap_usd is not None:
        discovery_kw["max_market_cap_usd"] = float(args.discovery_max_market_cap_usd)
    if args.discovery_allow_missing_market_cap:
        discovery_kw["exclude_missing_market_cap"] = False
    if args.discovery_min_phase is not None:
        discovery_kw["min_phase"] = int(args.discovery_min_phase)
    if args.discovery_readout_max_forward_days is not None:
        discovery_kw["readout_max_forward_days"] = int(args.discovery_readout_max_forward_days)

    # Phase / readout-horizon caps apply only in catalyst-first discovery, not watchlist/--tickers.
    if args.discover_candidates:
        readout_loop_min_phase = scan_min_phase
        readout_loop_max_forward_days = scan_readout_max_forward_days
    else:
        readout_loop_min_phase = 0
        readout_loop_max_forward_days = None

    discovery_info: Dict[str, Any] = {}
    ladder_meta: Dict[str, Any] = {}
    if args.discover_candidates:
        tickers, discovery_info, ladder_meta = run_discovery_ladder(
            forward_days=fwd,
            past_grace_days=grace,
            fallback_forward_days=int(args.fallback_forward_days),
            fallback_past_grace_days=int(args.fallback_past_grace_days),
            max_universe=int(args.max_discovery_universe),
            max_candidates=int(args.max_discovery_candidates),
            broker=broker,
            policy=active_policy,
            discovery_kw=discovery_kw,
        )
    if not tickers:
        logger.warning(
            "No biotech candidates selected",
            discovery=discovery_info,
            ladder=ladder_meta,
        )

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
            min_phase=readout_loop_min_phase,
            readout_max_forward_days=readout_loop_max_forward_days,
        ):
            logger.info(
                "Skipping ticker — no trial in readout window",
                ticker=t,
                forward_days=fwd,
                past_grace_days=grace,
                min_phase=readout_loop_min_phase,
                readout_max_forward_days=readout_loop_max_forward_days,
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
        phase_hint = ""
        catalyst_pre = catalyst_fields_from_snapshot(
            snap,
            forward_days=fwd,
            past_grace_days=grace,
            min_phase=readout_loop_min_phase,
            readout_max_forward_days=readout_loop_max_forward_days,
        )
        phase_hint = catalyst_pre.get("phase", "")
        past_for_ticker = format_past_trades_context(
            weeks=12, ticker=t, phase=phase_hint
        )
        analysis = analyze_snapshot(
            snap,
            intraweek_context=biotech_intraweek,
            past_trades_context=past_for_ticker or past_trades_ctx,
            policy_summary=policy_prompt,
        )
        gates_ok, gate_reasons = apply_gates(snap, analysis, policy=active_policy)
        catalyst = catalyst_pre
        if analysis.no_trade or not gates_ok:
            try:
                from src.biotech.counterfactual_ledger import append_counterfactual
                from src.biotech.execution import propose_straddle_legs

                legs = propose_straddle_legs(broker, t, float(snap.last_price or 0)) if broker else None
                est = 0.0
                if legs and broker:
                    c, p = legs["call"], legs["put"]
                    est = float(c.get("close_price", 0) or 0) * 100 + float(
                        p.get("close_price", 0) or 0
                    ) * 100
                append_counterfactual(
                    run_id=run_id,
                    run_date=run_date,
                    ticker=t,
                    catalyst=catalyst,
                    analysis=analysis,
                    gate_reasons=gate_reasons,
                    premium_est_usd=est,
                )
            except Exception:
                pass

        exec_arms: Dict[str, Any] = {}
        if paper_execute and broker:
            from src.biotech.thesis_ledger import open_entries

            max_open = int(active_policy.get("max_open_straddles", 5) or 5)
            open_n = len(open_entries())
            if open_n >= max_open:
                logger.info(
                    "Skip new straddles: open cap reached",
                    open=open_n,
                    max_open=max_open,
                    ticker=t,
                )
            else:
                # Prefer LLM-gated live fill when both arms enabled (avoid double same structure).
                run_mech = mech_enabled
                run_llm = llm_arm_enabled
                if run_mech and run_llm and gates_ok:
                    run_mech = False
                if run_mech:
                    mech_res, _ = _execute_arm(
                        "mechanical",
                        broker,
                        snap,
                        analysis,
                        arm_budget,
                        gates_ok=True,
                        gate_reasons=[],
                        run_id=run_id,
                        run_date=run_date,
                        catalyst=catalyst,
                    )
                    if mech_res:
                        exec_arms["mechanical"] = mech_res
                        open_n += 1
                if run_llm and open_n < max_open:
                    llm_res, _ = _execute_arm(
                        "llm_gated",
                        broker,
                        snap,
                        analysis,
                        arm_budget,
                        gates_ok=gates_ok,
                        gate_reasons=gate_reasons,
                        run_id=run_id,
                        run_date=run_date,
                        catalyst=catalyst,
                    )
                    if llm_res:
                        exec_arms["llm_gated"] = llm_res
                        open_n += 1

        exec_result = exec_arms if exec_arms else None

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
                "catalyst": catalyst,
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
                discovery_info=discovery_info,
                ladder_meta=ladder_meta,
                learning_markdown=learning_markdown,
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
