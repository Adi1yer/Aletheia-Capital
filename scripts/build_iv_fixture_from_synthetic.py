#!/usr/bin/env python3
"""
Generate IV CSV fixture from synthetic IV (research-only).

**NOT FOR PRODUCTION**. This script creates a CSV of synthetic implied volatility
data based on realized volatility + a premium bump. Use for:
- Unit tests (deterministic IV without market data subscription)
- Dry-run backtests (sanity check edge logic before wiring real IV)
- Local experimentation (no API key required)

The output CSV is labeled RESEARCH-ONLY and should NOT be used for live trading
or production edge validation.
"""

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.premium_model import realized_volatility
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def calculate_iv_rank(iv_history, current_iv, lookback=252):
    """Calculate IV rank from historical IV values."""
    if len(iv_history) < 10:
        return 0.50  # Default to median if insufficient history
    
    recent = iv_history[-lookback:]
    min_iv = min(recent)
    max_iv = max(recent)
    
    if max_iv <= min_iv:
        return 0.50
    
    return (current_iv - min_iv) / (max_iv - min_iv)


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic IV CSV fixture (RESEARCH-ONLY)"
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
        "--tickers",
        type=str,
        nargs="+",
        default=["AAPL", "MSFT", "SPY"],
        help="Tickers to generate IV for (default: AAPL MSFT SPY)",
    )
    parser.add_argument(
        "--premium-bump",
        type=float,
        default=0.15,
        help="Synthetic IV premium above realized vol (default: 0.15 = 15%%)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output CSV path",
    )
    parser.add_argument(
        "--tenor",
        type=int,
        default=21,
        help="IV tenor in days (default: 21)",
    )
    
    args = parser.parse_args()
    
    start_dt = date.fromisoformat(args.start)
    end_dt = date.fromisoformat(args.end)
    
    logger.info(
        "Generating synthetic IV CSV (RESEARCH-ONLY)",
        start=args.start,
        end=args.end,
        tickers=args.tickers,
        premium_bump=args.premium_bump,
        tenor_days=args.tenor,
        out=args.out,
    )
    
    data_provider = YahooFinanceProvider()
    
    # Fetch price history for all tickers (need extra for realized vol calc)
    lookback_days = 365  # Extra for RV calculation
    fetch_start = start_dt - timedelta(days=lookback_days)
    
    ticker_prices = {}
    for ticker in args.tickers:
        logger.info("Fetching prices", ticker=ticker)
        prices = data_provider.get_prices(ticker, fetch_start, end_dt)
        if not prices:
            logger.warning("No prices found, skipping", ticker=ticker)
            continue
        ticker_prices[ticker] = prices
    
    # Generate IV data
    output_rows = []
    
    for ticker in args.tickers:
        if ticker not in ticker_prices:
            continue
        
        prices = ticker_prices[ticker]
        price_dict = {p.time.date(): p.close for p in prices}
        
        # Build IV history for rank calculation
        iv_history = []
        
        # Generate IV for each day in range
        current = start_dt
        while current <= end_dt:
            # Get price history up to this date
            hist_prices = [
                price_dict[d]
                for d in sorted(price_dict.keys())
                if d <= current
            ]
            
            if len(hist_prices) < args.tenor + 10:
                current += timedelta(days=1)
                continue
            
            # Calculate realized vol
            rv = realized_volatility(hist_prices, window=args.tenor)
            
            if rv is None or rv <= 0:
                current += timedelta(days=1)
                continue
            
            # Synthetic IV = RV * (1 + premium_bump)
            synth_iv = rv * (1.0 + args.premium_bump)
            
            # Track for IV rank
            iv_history.append(synth_iv)
            
            # Calculate IV rank
            iv_rank = calculate_iv_rank(iv_history, synth_iv, lookback=252)
            
            # Add row
            output_rows.append({
                "date": current.isoformat(),
                "symbol": ticker,
                "atm_iv": f"{synth_iv:.4f}",
                "iv_rank": f"{iv_rank:.2f}",
            })
            
            current += timedelta(days=1)
    
    # Write CSV
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "symbol", "atm_iv", "iv_rank"])
        writer.writeheader()
        writer.writerows(output_rows)
    
    logger.info(
        "Synthetic IV CSV generated (RESEARCH-ONLY)",
        path=args.out,
        rows=len(output_rows),
    )
    
    print("\n" + "=" * 70)
    print("RESEARCH-ONLY SYNTHETIC IV CSV GENERATED")
    print("=" * 70)
    print(f"Output: {args.out}")
    print(f"Rows: {len(output_rows)}")
    print(f"Premium bump: {args.premium_bump:.1%}")
    print()
    print("⚠️  WARNING: This CSV uses SYNTHETIC IV, not market IV.")
    print("   - Do NOT use for production edge validation")
    print("   - Do NOT claim beat-SPY based on synthetic runs")
    print("   - Use ONLY for testing infrastructure plumbing")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
