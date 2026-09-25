#!/usr/bin/env python3
"""CLI to run wheel hybrid backtest."""

import argparse
import sys
from pathlib import Path

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
from src.backtesting.wheel_hybrid.universe import get_wheel_universe
from src.backtesting.wheel_hybrid.iv_provider import (
    NullIVProvider,
    SyntheticIVFromRealizedProvider,
    FileIVProvider,
)
from src.backtesting.wheel_hybrid.edge_gate import EdgeGate, EdgeGateConfig
from src.backtesting.wheel_hybrid.regime import RegimeDetector, RegimeConfig
from src.backtesting.wheel_hybrid.premium_model import realized_volatility
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def main():
    parser = argparse.ArgumentParser(
        description="Run wheel hybrid backtest with synthetic option pricing"
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--nav",
        type=float,
        default=10000.0,
        help="Initial NAV (default: 10000)",
    )
    parser.add_argument(
        "--wheel-pct",
        type=float,
        default=0.70,
        help="Wheel sleeve target percentage (default: 0.70)",
    )
    parser.add_argument(
        "--directional-pct",
        type=float,
        default=0.30,
        help="Directional sleeve target percentage (default: 0.30)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output directory for results",
    )
    parser.add_argument(
        "--universe",
        type=str,
        default="auto",
        choices=["bluechip", "expanded", "auto"],
        help="Universe selection: bluechip (6 names), expanded (~45 names), auto (date-based). Default: auto.",
    )
    parser.add_argument(
        "--custom-tickers",
        type=str,
        nargs="+",
        help="Custom universe (space-separated tickers). Overrides --universe.",
    )
    parser.add_argument(
        "--edge-mode",
        type=str,
        default="off",
        choices=["off", "synthetic", "file"],
        help="Edge gating mode: off (legacy), synthetic (research-only), file (real IV from CSV). Default: off.",
    )
    parser.add_argument(
        "--iv-csv",
        type=str,
        help="Path to IV data CSV (required for --edge-mode file)",
    )
    parser.add_argument(
        "--min-vrp",
        type=float,
        default=0.10,
        help="Minimum VRP (IV-RV spread) to write options. Default: 0.10 (10%%).",
    )
    parser.add_argument(
        "--min-iv-rank",
        type=float,
        help="Minimum IV rank to write options (0.0-1.0). Optional.",
    )
    parser.add_argument(
        "--synthetic-vrp-bump",
        type=float,
        default=0.15,
        help="Synthetic IV premium bump above realized vol (for --edge-mode synthetic). Default: 0.15 (15%%).",
    )
    parser.add_argument(
        "--enable-regime",
        action="store_true",
        help="Enable regime detection (HARVEST_VRP / HOLD_DELTA / DEFENSIVE)",
    )
    
    args = parser.parse_args()
    
    # Get universe
    if args.custom_tickers:
        universe = args.custom_tickers
    else:
        universe = get_wheel_universe(
            args.start,
            universe_type=args.universe,
        )
    
    logger.info(
        "Starting backtest",
        start=args.start,
        end=args.end,
        nav=args.nav,
        universe=universe,
        edge_mode=args.edge_mode,
    )
    
    # Initialize IV provider, edge gate, and regime detector based on edge mode
    iv_provider = None
    edge_gate = None
    regime_detector = None
    
    if args.edge_mode == "off":
        # Legacy mode: no edge gating
        logger.info("Edge gating disabled (legacy mode)")
    
    elif args.edge_mode == "synthetic":
        # Synthetic IV from realized vol + bump (research-only)
        logger.warning(
            "Using synthetic IV (RESEARCH-ONLY, NOT PRODUCTION EDGE)",
            vrp_bump=args.synthetic_vrp_bump,
        )
        
        # Helper to get realized vol for IV provider
        def get_realized_vol(symbol, as_of, window):
            # This will be called by synthetic IV provider
            # Return None for now (provider will handle)
            return None
        
        iv_provider = SyntheticIVFromRealizedProvider(
            realized_vol_provider=get_realized_vol,
            premium_bump=args.synthetic_vrp_bump,
        )
        
        # Create edge gate
        gate_config = EdgeGateConfig(
            enabled=True,
            min_vrp=args.min_vrp,
            min_iv_rank=args.min_iv_rank,
            fail_closed_when_no_iv=False,  # Synthetic always provides IV
        )
        edge_gate = EdgeGate(gate_config, iv_provider)
        
        # Create regime detector if enabled
        if args.enable_regime:
            regime_config = RegimeConfig(enabled=True)
            regime_detector = RegimeDetector(regime_config, iv_provider)
            logger.info("Regime detection enabled")
    
    elif args.edge_mode == "file":
        # Real IV from CSV file (Phase 2)
        if not args.iv_csv:
            logger.error("--iv-csv required for --edge-mode file")
            return 1
        
        logger.info("Using IV from file", path=args.iv_csv)
        iv_provider = FileIVProvider(args.iv_csv, format="csv")
        
        gate_config = EdgeGateConfig(
            enabled=True,
            min_vrp=args.min_vrp,
            min_iv_rank=args.min_iv_rank,
            fail_closed_when_no_iv=True,  # Fail safe if IV missing
        )
        edge_gate = EdgeGate(gate_config, iv_provider)
        
        if args.enable_regime:
            regime_config = RegimeConfig(enabled=True)
            regime_detector = RegimeDetector(regime_config, iv_provider)
            logger.info("Regime detection enabled")
    
    # Initialize backtest
    backtest = WheelHybridBacktest(
        start_date=args.start,
        end_date=args.end,
        initial_nav=args.nav,
        wheel_pct=args.wheel_pct,
        directional_pct=args.directional_pct,
        iv_provider=iv_provider,
        edge_gate=edge_gate,
        regime_detector=regime_detector,
    )
    
    # Run with Yahoo Finance provider
    data_provider = YahooFinanceProvider()
    
    results = backtest.run(universe, data_provider)
    
    if not results:
        logger.error("Backtest failed")
        return 1
    
    # Save results
    output_dir = Path(args.out)
    backtest.save_results(output_dir)
    
    # Print summary
    summary = results.get("summary", {})
    
    print("\n" + "=" * 60)
    print(f"Wheel Hybrid Backtest ({args.start} to {args.end})")
    print("=" * 60)
    print(f"Start NAV:        ${summary.get('start_nav', 0):,.2f}")
    print(f"End NAV:          ${summary.get('end_nav', 0):,.2f}")
    print(f"Absolute Return:  {summary.get('abs_return_pct', 0):+.2f}%")
    print(f"SPY Return:       {summary.get('spy_return_pct', 0):+.2f}%")
    print(f"Excess Return:    {summary.get('excess_return_pct', 0):+.2f}% / ${summary.get('excess_return_usd', 0):+,.2f}")
    print()
    print(f"Max Drawdown:     {summary.get('max_drawdown_pct', 0):.2f}%")
    print(f"Sharpe (rf=0%):   {summary.get('sharpe', 0):.2f}")
    print(f"Sortino (rf=0%):  {summary.get('sortino', 0):.2f}")
    print(f"Beta:             {summary.get('beta', 0):.2f}")
    print(f"Correlation:      {summary.get('correlation', 0):.2f}")
    print(f"Alpha (annual):   {summary.get('alpha_annual_pct', 0):+.2f}%")
    print()
    print(f"Hit Rate:         {summary.get('hit_rate_pct', 0):.1f}% ({summary.get('hit_sessions', 0)}/{summary.get('total_sessions', 0)} sessions)")
    print(f"Turnover:         {summary.get('turnover', 0):.2f}x")
    print(f"Premium Collected: ${summary.get('premium_collected', 0):,.2f}")
    print()
    
    trade_counts = summary.get("trade_counts", {})
    print("Trade Counts:")
    print(f"  CC Writes:      {trade_counts.get('cc_writes', 0)}")
    print(f"  CSP Writes:     {trade_counts.get('csp_writes', 0)}")
    print(f"  BTC Calls:      {trade_counts.get('btc_calls', 0)}")
    print(f"  BTC Puts:       {trade_counts.get('btc_puts', 0)}")
    print(f"  Call Assigns:   {trade_counts.get('assignments_call', 0)}")
    print(f"  Put Assigns:    {trade_counts.get('assignments_put', 0)}")
    print()
    print(f"Results saved: {output_dir}/")
    print("  - equity_curve.csv")
    print("  - trades.csv")
    print("  - summary.json")
    print("  - assumptions.json")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
