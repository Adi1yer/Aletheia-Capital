"""
Stock trading CLI: weekly/universe runs, optional `--execute`, scan cache when using
`--universe --weekly`. Install console entry: `poetry install` then `poetry run trade`
(same as `poetry run python src/main.py`).
"""

import argparse
import logging
import os
import sys
import time
import structlog
from src.trading.pipeline import TradingPipeline
from src.agents.initialize import initialize_agents
from src.config.settings import settings
from src.data.universe import StockUniverse
from src.utils.email import get_email_notifier
from src.scan_cache import ScanCache

# Configure logging
log_level = getattr(settings, 'log_level', 'INFO').upper()
try:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
except (KeyError, AttributeError, TypeError):
    # Fallback for structlog configuration
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

logger = structlog.get_logger()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="AI Hedge Fund Trading System")
    parser.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated list of ticker symbols (e.g., AAPL,MSFT,GOOGL). Use --universe for full market",
    )
    parser.add_argument(
        "--universe",
        action="store_true",
        help="Use full US stock market universe (filtered by liquidity)",
    )
    parser.add_argument(
        "--weekly",
        action="store_true",
        help="Mark this run as the official weekly scan (enables scan cache + pruning).",
    )
    parser.add_argument(
        "--max-stocks",
        type=int,
        default=200,
        help="Maximum number of stocks to trade (when using --universe). Default 200.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute trades (default: dry run)",
    )
    parser.add_argument(
        "--agents",
        type=str,
        help="Comma-separated list of agent keys to use (default: all)",
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="Send trading results via email",
    )
    parser.add_argument(
        "--email-to",
        type=str,
        help="Email recipient (overrides config default)",
    )
    parser.add_argument(
        "--crypto",
        action="store_true",
        help="Run crypto trading pipeline (BTC, ETH, etc.) instead of stocks",
    )
    parser.add_argument(
        "--crypto-tickers",
        type=str,
        default="BTC,ETH,SOL",
        help="Comma-separated crypto symbols when using --crypto (default: BTC,ETH,SOL)",
    )
    args = parser.parse_args()
    
    # Crypto mode: run crypto pipeline instead of stocks
    if args.crypto:
        if args.weekly:
            logger.error("--weekly is only valid for stock universe runs (not --crypto)")
            return
        os.environ.setdefault("CRYPTO_ENABLED", "true")
        from src.trading.crypto_pipeline import CryptoTradingPipeline
        from src.data.providers.crypto import CRYPTO_IDS
        crypto_tickers = [t.strip().upper() for t in args.crypto_tickers.split(",") if t.strip() and t.upper() in CRYPTO_IDS]
        if not crypto_tickers:
            crypto_tickers = ["BTC", "ETH", "SOL"]
        logger.info("Running crypto pipeline", tickers=crypto_tickers, execute=args.execute)
        pipeline = CryptoTradingPipeline()
        results = pipeline.run(
            tickers=crypto_tickers,
            execute=args.execute,
            scan_cache=None,
            run_config={"execute": args.execute, "crypto": True, "save_to_cache": False},
        )
        decisions = results.get("decisions", {})
        print("\n" + "=" * 80)
        print("CRYPTO TRADING DECISIONS")
        print("=" * 80)
        for ticker, dec in sorted(decisions.items(), key=lambda x: x[1].get("confidence", 0), reverse=True):
            d = dec if isinstance(dec, dict) else dec.model_dump()
            print(f"\n{ticker}: {d.get('action', 'hold')} {d.get('quantity', 0)} (confidence: {d.get('confidence', 0)}%)")
        if args.email or args.email_to:
            recipient = args.email_to or settings.recipient_email
            if recipient:
                get_email_notifier().send_trading_results(recipient, results)
        return

    # Get tickers
    if args.universe:
        logger.info("Using full US stock market universe")
        universe = StockUniverse()
        tickers = universe.get_trading_universe(
            full_market=True,
            max_stocks=args.max_stocks,
            apply_filters=True,
        )
        logger.info("Universe loaded", ticker_count=len(tickers))
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        logger.error("Must provide either --tickers or --universe")
        parser.print_help()
        return

    # Only official weekly universe runs are allowed to write to scan cache.
    if args.weekly and not args.universe:
        logger.error("--weekly requires --universe (weekly scans must be universe runs)")
        return

    # Deduplicate: preserve order, never process the same ticker twice in a run
    orig_count = len(tickers)
    tickers = list(dict.fromkeys(tickers))
    if len(tickers) < orig_count:
        logger.info("Removed duplicate tickers", removed=orig_count - len(tickers), final_count=len(tickers))

    if not tickers:
        logger.error("No valid tickers to trade")
        return
    
    logger.info("Starting trading system", ticker_count=len(tickers), execute=args.execute)
    
    # Initialize agents
    logger.info("Initializing agents")
    initialize_agents()
    
    # Scan cache: persist ONLY official weekly universe runs (never test/debug/exploratory)
    scan_cache = ScanCache() if (args.universe and args.weekly) else None
    run_config = {
        "execute": args.execute,
        "universe": args.universe,
        "max_stocks": args.max_stocks,
        "ticker_source": "universe" if args.universe else "tickers",
        "weekly": bool(args.weekly),
        "save_to_cache": bool(args.universe and args.weekly),
    }
    
    # Run trading pipeline
    pipeline = TradingPipeline()
    results = pipeline.run_weekly_trading(
        tickers=tickers,
        execute=args.execute,
        scan_cache=scan_cache,
        run_config=run_config,
    )

    # Optional prune after a weekly universe run (disabled when scan_cache_keep_weeks is 0)
    if args.universe and args.weekly and scan_cache is not None:
        keep_weeks = getattr(settings, "scan_cache_keep_weeks", 0)
        if keep_weeks > 0:
            scan_cache.prune_old_runs(keep_weeks=keep_weeks)

    # Print summary
    logger.info("Trading cycle complete", decision_count=len(results.get('decisions', {})))

    # Current state from Alpaca (positions + orders) when broker was used
    if results.get("broker_used"):
        portfolio = results.get("portfolio") or {}
        open_orders = results.get("open_orders") or []
        recent_orders = results.get("recent_orders") or []
        print("\n" + "="*80)
        print("CURRENT STATE FROM ALPACA")
        print("="*80)
        cash = portfolio.get("cash", 0)
        positions = portfolio.get("positions") or {}
        print(f"\nCash: ${cash:,.2f}")
        if positions:
            print("\nTop positions:")
            for sym, pos in list(positions.items())[:20]:
                long_qty = pos.get("long", 0) or 0
                short_qty = pos.get("short", 0) or 0
                if long_qty:
                    print(f"  {sym}: long {long_qty} (cost basis ${pos.get('long_cost_basis', 0):,.2f})")
                if short_qty:
                    print(f"  {sym}: short {short_qty}")
            if len(positions) > 20:
                print(f"  ... and {len(positions) - 20} more")
        else:
            print("\nPositions: none")
        if open_orders:
            print("\nOpen orders (pending):")
            for o in open_orders[:15]:
                print(f"  {o.get('symbol')} {o.get('side')} {o.get('qty')} @ {o.get('type', 'market')} (status: {o.get('status')})")
            if len(open_orders) > 15:
                print(f"  ... and {len(open_orders) - 15} more")
        else:
            print("\nOpen orders: none")
        if recent_orders:
            print("\nRecent orders (last 20):")
            for o in recent_orders[:10]:
                print(f"  {o.get('symbol')} {o.get('side')} {o.get('qty')} - {o.get('status')} {o.get('filled_at') or o.get('submitted_at') or ''}")
            if len(recent_orders) > 10:
                print(f"  ... and {len(recent_orders) - 10} more")
        print()

    # Print decisions summary (limit to top 20 for readability)
    print("="*80)
    print("TRADING DECISIONS SUMMARY")
    print("="*80)
    decisions = results.get('decisions', {})
    
    # Sort by confidence
    sorted_decisions = sorted(
        decisions.items(),
        key=lambda x: x[1].get('confidence', 0),
        reverse=True
    )
    
    # Show top decisions
    for ticker, decision in sorted_decisions[:20]:
        print(f"\n{ticker}:")
        print(f"  Action: {decision['action']}")
        print(f"  Quantity: {decision['quantity']}")
        print(f"  Confidence: {decision['confidence']}%")
        if len(decision.get('reasoning', '')) < 100:
            print(f"  Reasoning: {decision['reasoning']}")
    
    if len(sorted_decisions) > 20:
        print(f"\n... and {len(sorted_decisions) - 20} more decisions")
    
    if args.execute and results.get('execution_results'):
        print("\n" + "="*80)
        print("EXECUTION RESULTS")
        print("="*80)
        exec_res = results['execution_results']
        if exec_res.get('error'):
            print(exec_res['error'])
            print("(No orders were sent. Check ALPACA_API_KEY and ALPACA_SECRET_KEY in .env.)")
        else:
            executed = sum(1 for r in exec_res.values() if r and not isinstance(r, str))
            total = len([k for k in exec_res if k != 'error'])
            print(f"Orders executed: {executed} out of {total}")
    
    # Send email if requested
    if args.email or args.email_to:
        recipient = args.email_to or settings.recipient_email
        if recipient:
            email_notifier = get_email_notifier()
            email_notifier.send_trading_results(recipient, results)
            logger.info("Trading results email sent", recipient=recipient)
        else:
            logger.warning("No email recipient specified")

    print("\nPipeline finished successfully.")
    sys.stdout.flush()
    sys.stderr.flush()
    # Keep terminal open briefly when run interactively so output is visible
    if sys.stdout.isatty():
        try:
            time.sleep(3)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print("\nPipeline failed:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)

