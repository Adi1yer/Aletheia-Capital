"""
Weekly scan + rebalancing runner.

This is the "official" weekly workflow:
- scan a liquid universe (default 500, adjustable)
- run agents
- rebalance deterministically based on aggregated confidence
- optionally execute trades
- cache the run (5y retention policy) and send a weekly email.

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
    p.add_argument("--min-buy-confidence", type=int, default=50, help="Min confidence to buy (default 50)")
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
    args = p.parse_args()

    # If you just run `python weekly_scan_rebalancing.py` with no arguments,
    # treat it as: --max-stocks 500 --execute --email-to <settings.recipient_email>.
    if len(sys.argv) == 1:
        args.max_stocks = 500
        args.execute = True
        default_recipient = (settings.recipient_email or "").strip()
        if default_recipient:
            args.email_to = default_recipient

    if args.max_stocks <= 0:
        raise SystemExit("--max-stocks must be > 0")

    # ── Require Alpaca keys — no fallbacks. Exit if missing or wrong. ──
    api_key = (settings.alpaca_api_key or "").strip()
    secret_key = (settings.alpaca_secret_key or "").strip()
    if not api_key or not secret_key:
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

    # ── Verify Alpaca connection before doing any real work. ──
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

    logger.info("Loading universe", max_stocks=args.max_stocks)
    universe = StockUniverse()
    tickers = universe.get_trading_universe(
        full_market=True,
        max_stocks=args.max_stocks,
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
    }

    pipeline = TradingPipeline(broker=broker)
    results = pipeline.run_weekly_trading(
        tickers=tickers,
        execute=bool(args.execute),
        scan_cache=scan_cache,
        run_config=run_config,
    )

    # Prune (keep 5 years by default)
    keep_weeks = getattr(settings, "scan_cache_keep_weeks", 260)
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
    main()
