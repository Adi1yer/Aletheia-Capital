"""
Historical backtesting entrypoint (`src/backtest.py`).

This replays the trading pipeline over a date range using **price/volume data**
from the configured data provider (including its on-disk cache). It does **not**
load `data/scan_cache` JSON from weekly scans. For evaluation that uses cached
agent outputs from real runs, see `src/backtesting/agent_evaluator.py` and the
weekly pipeline’s `scan_cache` wiring. Learning from cached runs (scorecard + per-ticker
calibration for prompts) is implemented in `src/backtesting/agent_evaluator.py`,
`src/backtesting/learning_outcomes.py`, and `src/backtesting/feedback.py`.
"""

import argparse
import structlog
from src.backtesting.engine import BacktestingEngine
from src.data.universe import StockUniverse
from src.config.settings import settings

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

logger = structlog.get_logger()


def main():
    """Run backtest"""
    parser = argparse.ArgumentParser(description="Backtesting Engine")
    parser.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated list of ticker symbols",
    )
    parser.add_argument(
        "--universe",
        action="store_true",
        help="Use full US stock market universe",
    )
    parser.add_argument(
        "--max-stocks",
        type=int,
        default=100,
        help="Maximum number of stocks (when using --universe)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=100000.0,
        help="Initial cash (default: 100000)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Save results to JSON file",
    )
    
    args = parser.parse_args()
    
    # Get tickers
    if args.universe:
        logger.info("Using full US stock market universe")
        universe = StockUniverse()
        tickers = universe.get_trading_universe(
            full_market=True,
            max_stocks=args.max_stocks,
            apply_filters=True,
        )
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        logger.error("Must provide either --tickers or --universe")
        parser.print_help()
        return
    
    if not tickers:
        logger.error("No valid tickers to backtest")
        return
    
    logger.info(
        "Starting backtest",
        ticker_count=len(tickers),
        start_date=args.start_date,
        end_date=args.end_date,
        initial_cash=args.initial_cash,
    )
    
    # Run backtest
    engine = BacktestingEngine()
    result = engine.run_backtest(
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_cash=args.initial_cash,
        rebalance_frequency="weekly",
    )
    
    # Print results
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    print(f"Period: {result.start_date} to {result.end_date}")
    print(f"Initial Cash: ${result.initial_cash:,.2f}")
    print(f"Final Value: ${result.final_value:,.2f}")
    print(f"Total Return: {result.total_return_pct:.2f}%")
    print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}" if result.sharpe_ratio else "Sharpe Ratio: N/A")
    print(f"Max Drawdown: {result.max_drawdown:.2f}%")
    print(f"Total Trades: {result.total_trades}")
    print(f"Winning Trades: {result.winning_trades}")
    print(f"Losing Trades: {result.losing_trades}")
    
    if result.agent_performance:
        print("\n" + "-"*80)
        print("AGENT PERFORMANCE")
        print("-"*80)
        sorted_agents = sorted(
            result.agent_performance.items(),
            key=lambda x: x[1].get('average_return_pct', 0),
            reverse=True
        )
        for agent_key, perf in sorted_agents:
            print(f"{agent_key}:")
            print(f"  Avg Return: {perf.get('average_return_pct', 0):.2f}%")
            print(f"  Trades: {perf.get('total_trades', 0)}")
            print(f"  Win Rate: {(perf.get('winning_trades', 0) / perf.get('total_trades', 1) * 100):.1f}%")
    
    # Save to file if requested
    if args.output:
        import json
        with open(args.output, 'w') as f:
            json.dump(result.model_dump(), f, indent=2, default=str)
        logger.info("Results saved to file", file=args.output)
    
    logger.info("Backtest complete")


if __name__ == "__main__":
    main()

