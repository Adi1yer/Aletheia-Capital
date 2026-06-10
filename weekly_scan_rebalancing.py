"""
Weekly scan + rebalancing runner.

This is the "official" weekly workflow:
- scan a liquid universe (default 500, adjustable)
- run agents
- rebalance deterministically based on aggregated confidence
- optionally execute trades
- cache the run (all runs retained by default) and send a weekly email.

Usage:
  Click "Run Python File" in Cursor (interpreter must be .venv/bin/python), or:
  poetry run python weekly_scan_rebalancing.py --max-stocks 500 --execute --email-to you@example.com
"""

import argparse
import os
import sys
from pathlib import Path

# Load .env from project root so Alpaca keys are found regardless of cwd.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.agents.initialize import initialize_agents
from src.config.settings import settings
from src.data.universe import StockUniverse
from src.scan_cache import ScanCache
from src.trading.pipeline import TradingPipeline
from src.utils.email import get_email_notifier

logger = structlog.get_logger()


def main() -> None:
    from src.fund.orchestrator import run_orchestrator

    run_orchestrator()

    p = argparse.ArgumentParser(description="Weekly scan + portfolio rebalancing")
    p.add_argument(
        "--max-stocks",
        type=int,
        default=500,
        help="Universe size to scan (default 500; when no args are given, 500 is used).",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Execute trades in Alpaca (when no args are given, this is treated as True).",
    )
    p.add_argument(
        "--email-to",
        type=str,
        default="",
        help="Email recipient (overrides config default). When no args are given, config RECIPIENT_EMAIL is used.",
    )

    # Rebalance knobs
    p.add_argument(
        "--min-buy-confidence", type=int, default=50, help="Min confidence to buy (default 50)"
    )
    p.add_argument(
        "--min-sell-confidence",
        type=int,
        default=60,
        help="Min confidence to sell existing longs (default 60)",
    )
    p.add_argument(
        "--cash-buffer-pct",
        type=float,
        default=0.03,
        help="Keep this % of equity in cash (default 0.03)",
    )
    p.add_argument(
        "--max-buy-tickers",
        type=int,
        default=30,
        help="Max number of buy names to allocate into (default 30)",
    )

    # Covered call strategy
    p.add_argument(
        "--enable-covered-calls",
        dest="enable_covered_calls",
        action="store_true",
        default=True,
        help="Enable covered-call strategy on hold tickers (default: enabled).",
    )
    p.add_argument(
        "--no-covered-calls",
        dest="enable_covered_calls",
        action="store_false",
        help="Disable covered-call strategy for this run.",
    )
    p.add_argument(
        "--min-cc-score",
        type=int,
        default=40,
        help="Minimum covered-call score to qualify (default 40)",
    )
    p.add_argument(
        "--earnings-blackout-days",
        type=int,
        default=14,
        help="Skip buys/CC/CSP within this many days of earnings (0=off)",
    )
    p.add_argument(
        "--stop-loss-pct",
        type=float,
        default=0.08,
        help="Bracket stop-loss fraction on new buys (default 0.08 = 8%%; set 0 to disable)",
    )
    p.add_argument(
        "--use-limit-orders",
        action="store_true",
        help="Use limit buys with small slippage buffer instead of market orders",
    )
    p.add_argument(
        "--limit-slippage-pct",
        type=float,
        default=0.002,
        help="Limit price = quote * (1 + this) for buys (default 0.002)",
    )
    p.add_argument(
        "--enable-cash-secured-puts",
        action="store_true",
        help="Enable cash-secured put writes after equity execution",
    )
    p.add_argument(
        "--min-csp-score",
        type=int,
        default=40,
        help="Minimum CSP score (default 40)",
    )
    p.add_argument(
        "--enable-conviction-rebalance",
        action="store_true",
        help="Sell weaker longs when much stronger buys exist",
    )
    p.add_argument(
        "--conviction-score-gap",
        type=int,
        default=25,
        help="Min gap vs best buy score to trigger conviction sell",
    )
    p.add_argument(
        "--enable-cash-rotation",
        action="store_true",
        help="When buys are cash-blocked, sell weakest held longs (not buy targets) to fund buys; see --cash-rotation-min-edge.",
    )
    p.add_argument(
        "--cash-rotation-min-edge",
        type=int,
        default=5,
        help="Minimum buy-confidence edge over held bullish metric to allow a rotation sell (default 5).",
    )
    p.add_argument(
        "--cash-rotation-min-buy-notional-usd",
        type=float,
        default=1500.0,
        help="Min dollar size for a buy to count as 'allocatable' for cash rotation (default 1500).",
    )
    p.add_argument(
        "--cash-rotation-min-buy-notional-pct-equity",
        type=float,
        default=0.02,
        help="Min buy size as fraction of equity (used with --cash-rotation-min-buy-notional-usd, whichever is larger).",
    )
    p.add_argument(
        "--max-cash-rotation-sells",
        type=int,
        default=3,
        help="Max cash-rotation sells per weekly rebalance (default 3).",
    )
    p.add_argument(
        "--min-hold-weeks-before-rotation",
        type=int,
        default=2,
        help="Skip cash-rotation sells for positions opened within N weeks (default 2).",
    )
    p.add_argument(
        "--min-csp-premium-usd",
        type=float,
        default=75.0,
        help="Minimum estimated CSP premium in USD (default 75).",
    )
    p.add_argument(
        "--min-csp-annualized-yield-pct",
        type=float,
        default=3.0,
        help="Minimum annualized CSP yield percent (default 3.0).",
    )
    p.add_argument(
        "--profile",
        type=str,
        choices=("balanced", "conservative", "aggressive"),
        default="balanced",
        help="Strategy profile preset for thresholds/rebalance knobs (default balanced).",
    )
    p.add_argument(
        "--agent-tier-mode",
        type=str,
        choices=("full", "tiered", "core"),
        default="tiered",
        help="Agent set: tiered (core+rotating extended), full (all), core only (default tiered).",
    )
    p.add_argument(
        "--agents",
        type=str,
        default="",
        help="Comma-separated agent keys override (runs only these agents).",
    )
    p.add_argument(
        "--run-profile",
        type=str,
        default="",
        help="Merge settings from config/run_profiles.json (e.g. ci-full, dev-smoke).",
    )
    p.add_argument(
        "--no-broker",
        action="store_true",
        help="Analysis-only: skip Alpaca key check and use empty portfolio.",
    )
    p.add_argument(
        "--no-llm-cache",
        action="store_true",
        help="Disable disk LLM response cache for this run.",
    )
    p.add_argument("--max-position-pct", type=float, default=0.20)
    p.add_argument("--max-sector-pct", type=float, default=0.35)
    p.add_argument("--max-csp-tickers", type=int, default=2)
    p.add_argument("--max-csp-collateral-pct", type=float, default=0.10)
    p.add_argument("--regime-mode", type=str, default="", help="auto to adjust knobs from SPY regime")
    p.add_argument("--wash-sale-days", type=int, default=0)
    args = p.parse_args()

    # If you just run `python weekly_scan_rebalancing.py` with no arguments,
    # treat it as: --max-stocks 500 --execute --email-to <settings.recipient_email>.
    if len(sys.argv) == 1:
        args.max_stocks = 500
        args.execute = True
        args.enable_covered_calls = True
        args.profile = "balanced"
        default_recipient = (settings.recipient_email or "").strip()
        if default_recipient:
            args.email_to = default_recipient

    # Balanced profile: modestly more active than conservative, with guarded conviction rotation.
    if args.profile == "balanced":
        args.min_buy_confidence = min(int(args.min_buy_confidence), 49)
        args.enable_conviction_rebalance = True
        args.conviction_score_gap = max(int(args.conviction_score_gap), 30)
        args.min_sell_confidence = max(int(args.min_sell_confidence), 60)
    elif args.profile == "conservative":
        args.min_buy_confidence = max(int(args.min_buy_confidence), 52)
        args.enable_conviction_rebalance = False
        args.min_sell_confidence = max(int(args.min_sell_confidence), 62)
    elif args.profile == "aggressive":
        args.min_buy_confidence = min(int(args.min_buy_confidence), 47)
        args.enable_conviction_rebalance = True
        args.conviction_score_gap = min(int(args.conviction_score_gap), 25)
        args.min_sell_confidence = min(int(args.min_sell_confidence), 58)

    if args.max_stocks <= 0:
        raise SystemExit("--max-stocks must be > 0")

    from src.trading.run_config import merge_run_profile

    profile_name = (args.run_profile or "").strip() or None
    profile_overrides = merge_run_profile({}, profile_name) if profile_name else {}
    broker_required = not args.no_broker and profile_overrides.get("broker_required", True)

    # ── Require Alpaca keys — no fallbacks. Exit if missing or wrong. ──
    api_key = (settings.alpaca_api_key or "").strip()
    secret_key = (settings.alpaca_secret_key or "").strip()
    if broker_required and (not api_key or not secret_key):
        logger.error(
            "Alpaca API keys are not configured. Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env. "
            "No fallback; exiting."
        )
        raise SystemExit(1)

    required_api_key = os.environ.get("REQUIRED_ALPACA_API_KEY", "").strip()
    if required_api_key and api_key != required_api_key:
        logger.error(
            "ALPACA_API_KEY does not match REQUIRED_ALPACA_API_KEY. Wrong key in use; exiting."
        )
        raise SystemExit(1)
    required_secret_key = os.environ.get("REQUIRED_ALPACA_SECRET_KEY", "").strip()
    if required_secret_key and secret_key != required_secret_key:
        logger.error(
            "ALPACA_SECRET_KEY does not match REQUIRED_ALPACA_SECRET_KEY. Wrong secret in use; exiting."
        )
        raise SystemExit(1)

    broker = None
    if broker_required:
        from src.broker.alpaca import AlpacaBroker

        try:
            broker = AlpacaBroker()
            acct = broker.get_account()
        except Exception as e:
            logger.error(
                "Alpaca rejected the API key or connection failed. "
                "Fix ALPACA_API_KEY and ALPACA_SECRET_KEY in .env, then retry.",
                error=str(e),
            )
            raise SystemExit(1)

        logger.info(
            "Alpaca connection verified",
            key_prefix=api_key[:4],
            cash=acct.get("cash"),
            equity=acct.get("equity"),
        )

    # ── Run the pipeline ──
    logger.info("Initializing agents")
    initialize_agents()

    max_stocks = int(profile_overrides.get("max_stocks", args.max_stocks))
    logger.info("Loading universe", max_stocks=max_stocks)
    universe = StockUniverse()
    tickers = universe.get_trading_universe(
        full_market=True,
        max_stocks=max_stocks,
        apply_filters=True,
        rank_by_market_cap=True,
    )
    if not tickers:
        raise SystemExit("Universe returned no tickers")

    scan_cache = ScanCache()
    run_config = {
        "execute": bool(args.execute),
        "universe": True,
        "weekly": True,
        "save_to_cache": True,
        "ticker_source": "universe",
        "max_stocks": int(args.max_stocks),
        "rebalance": True,
        "min_buy_confidence": int(args.min_buy_confidence),
        "min_sell_confidence": int(args.min_sell_confidence),
        "cash_buffer_pct": float(args.cash_buffer_pct),
        "max_buy_tickers": int(args.max_buy_tickers),
        "enable_covered_calls": bool(args.enable_covered_calls),
        "min_cc_score": int(args.min_cc_score),
        "earnings_blackout_days": int(args.earnings_blackout_days),
        "stop_loss_pct": args.stop_loss_pct,
        "use_limit_orders": bool(args.use_limit_orders),
        "limit_slippage_pct": float(args.limit_slippage_pct),
        "enable_cash_secured_puts": bool(args.enable_cash_secured_puts),
        "min_csp_score": int(args.min_csp_score),
        "enable_conviction_rebalance": bool(args.enable_conviction_rebalance),
        "conviction_score_gap": int(args.conviction_score_gap),
        "profile": str(args.profile),
        "enable_cash_rotation": bool(args.enable_cash_rotation),
        "cash_rotation_min_edge": int(args.cash_rotation_min_edge),
        "cash_rotation_min_buy_notional_usd": float(args.cash_rotation_min_buy_notional_usd),
        "cash_rotation_min_buy_notional_pct_equity": float(
            args.cash_rotation_min_buy_notional_pct_equity
        ),
        "agent_tier_mode": str(args.agent_tier_mode),
        "agent_tier_core_only": str(args.agent_tier_mode) == "core",
        "financial_limit": 1,
        "dossier_financial_limit": 5,
        "llm_cache": not args.no_llm_cache,
        "broker_required": broker_required,
        "max_position_pct": float(args.max_position_pct),
        "max_sector_pct": float(args.max_sector_pct),
        "max_csp_tickers": int(args.max_csp_tickers),
        "max_csp_collateral_pct": float(args.max_csp_collateral_pct),
        "regime_mode": (args.regime_mode or "").strip(),
        "wash_sale_days": int(args.wash_sale_days),
        "min_agent_weight_to_run": 0.15,
        "max_cash_rotation_sells": int(args.max_cash_rotation_sells),
        "min_hold_weeks_before_rotation": int(args.min_hold_weeks_before_rotation),
        "min_csp_premium_usd": float(args.min_csp_premium_usd),
        "min_csp_annualized_yield_pct": float(args.min_csp_annualized_yield_pct),
    }
    if profile_name:
        run_config = merge_run_profile(run_config, profile_name)
        run_config["run_profile"] = profile_name
    if (args.agents or "").strip():
        run_config["active_agent_keys"] = [
            a.strip() for a in args.agents.split(",") if a.strip()
        ]

    pipeline = TradingPipeline(broker=broker)
    results = pipeline.run_weekly_trading(
        tickers=tickers,
        execute=bool(args.execute),
        scan_cache=scan_cache,
        run_config=run_config,
    )

    # Optional prune — default settings never delete (scan_cache_keep_weeks=0).
    keep_weeks = getattr(settings, "scan_cache_keep_weeks", 0)
    if keep_weeks > 0:
        scan_cache.prune_old_runs(keep_weeks=keep_weeks)

    # ── Email (exactly once) ──
    recipient = (args.email_to or settings.recipient_email or "").strip()
    if recipient:
        get_email_notifier().send_trading_results(recipient, results)
        logger.info("Weekly email sent", recipient=recipient, run_id=results.get("run_id"))
    else:
        logger.info("No email recipient configured; skipping email")

    logger.info("Weekly scan + rebalancing complete", run_id=results.get("run_id"))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        try:
            from src.utils.alerts import send_alert

            send_alert("Weekly scan failed", str(e)[:500], {})
        except Exception:
            pass
        raise
