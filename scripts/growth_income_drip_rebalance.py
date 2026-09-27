"""Growth-income-drip paper track rebalancer.

Implements quarterly rebalance with:
- 80% growth sleeve (Arm C momentum)
- 20% dividend ballast
- Delta rebalance only
- Dividend drip into growth sleeve
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import structlog
from src.broker.alpaca import AlpacaBroker
from src.backtesting.growth_quality import MomentumSelector
from src.backtesting.income_drip import DividendBallastSelector, DividendDripManager
from src.performance.drip_track import (
    record_snapshot,
    get_latest_snapshot,
    is_quarterly_rebalance_due,
    record_last_rebalance,
    get_last_rebalance_date,
    TRACK_ID,
)
from src.utils.email import get_email_notifier

logger = structlog.get_logger()


def get_drip_broker() -> AlpacaBroker:
    """Create Alpaca broker using DRIP_ALPACA_* secrets."""
    api_key = os.getenv("DRIP_ALPACA_API_KEY")
    secret_key = os.getenv("DRIP_ALPACA_SECRET_KEY")
    base_url = os.getenv("DRIP_ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    
    if not api_key or not secret_key:
        raise ValueError(
            "Missing DRIP_ALPACA_API_KEY or DRIP_ALPACA_SECRET_KEY. "
            "Set these in GitHub Secrets for the drip paper account (requires separate Alpaca email)."
        )
    
    return AlpacaBroker(
        api_key=api_key,
        secret_key=secret_key,
        base_url=base_url,
    )


def get_liquid_universe(size: int = 200) -> List[str]:
    """Get a liquid universe of US equities."""
    # Use common liquid names for initial implementation
    # In production, this would query a data provider
    universe = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
        "V", "JPM", "JNJ", "WMT", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
        "KO", "PEP", "COST", "AVGO", "TMO", "LLY", "ORCL", "ACN", "MCD",
        "CSCO", "ABT", "DHR", "VZ", "ADBE", "NKE", "CRM", "TXN", "NEE",
        "PM", "UNP", "BMY", "QCOM", "HON", "UPS", "RTX", "INTC", "AMGN",
        "LOW", "COP", "T", "SBUX", "BA", "GE", "AMD", "IBM", "CAT", "INTU",
        "GS", "AXP", "DE", "MMC", "NOW", "PLD", "SPGI", "BLK", "SYK", "TGT",
        "MDLZ", "ISRG", "GILD", "CVS", "ZTS", "ADI", "MO", "CI", "DUK", "SO",
        "CB", "PGR", "TJX", "REGN", "BSX", "SCHW", "EOG", "CME", "NSC", "MMM",
        "APD", "ITW", "ICE", "NOC", "HUM", "FIS", "USB", "WM", "EMR", "SLB",
        "AON", "CL", "D", "PSA", "COF", "ADP", "GD", "EW", "SHW", "DG",
        "MCK", "ORLY", "EL", "TT", "HCA", "MAR", "SPG", "KMB", "AFL", "ECL",
        "NEM", "KLAC", "ROST", "APH", "AIG", "CTVA", "CARR", "CMG", "AZO", "PPG",
        "FDX", "PAYX", "MCHP", "MSI", "O", "MSCI", "IQV", "ROP", "DD", "TEL",
        "NXPI", "CPRT", "GPN", "GLW", "WELL", "CTAS", "KHC", "PCAR", "YUM", "EA",
        "IDXX", "FAST", "CMI", "VRTX", "A", "XEL", "AEP", "WEC", "DLR", "ES",
        "OTIS", "LHX", "AMT", "CCI", "PSX", "MPC", "VLO", "HES", "OXY", "DVN",
        "FTNT", "ANSS", "DOW", "STZ", "ALB", "SRE", "BKR", "DHI", "LEN", "PHM",
        "KEYS", "ROK", "ANET", "EXC", "FTV", "PKI", "TDY", "AWK", "AEE", "LNT",
    ]
    return universe[:size]


def calculate_target_allocations(
    growth_tickers: List[str],
    ballast_tickers: List[str],
    growth_weight: float,
    ballast_weight: float,
    total_equity: float,
) -> Dict[str, float]:
    """
    Calculate target dollar allocations for all positions.
    
    Args:
        growth_tickers: List of growth sleeve tickers
        ballast_tickers: List of ballast sleeve tickers
        growth_weight: Weight of growth sleeve (e.g., 0.80)
        ballast_weight: Weight of ballast sleeve (e.g., 0.20)
        total_equity: Total portfolio equity
        
    Returns:
        Dictionary mapping ticker to target dollar amount
    """
    targets = {}
    
    # Growth sleeve: equal weight within sleeve
    growth_equity = total_equity * growth_weight
    if growth_tickers:
        per_growth = growth_equity / len(growth_tickers)
        for ticker in growth_tickers:
            targets[ticker] = per_growth
    
    # Ballast sleeve: equal weight within sleeve
    ballast_equity = total_equity * ballast_weight
    if ballast_tickers:
        per_ballast = ballast_equity / len(ballast_tickers)
        for ticker in ballast_tickers:
            targets[ticker] = per_ballast
    
    return targets


def execute_delta_rebalance(
    broker: AlpacaBroker,
    target_allocations: Dict[str, float],
    current_positions: Dict[str, Dict],
    min_trade_usd: float = 100.0,
) -> Dict[str, List[Dict]]:
    """
    Execute delta rebalance: only trade the differences.
    
    Args:
        broker: Alpaca broker instance
        target_allocations: Target dollar amounts by ticker
        current_positions: Current positions from broker
        min_trade_usd: Minimum trade size in USD (default 100)
        
    Returns:
        Dictionary with 'buys', 'sells', and 'holds' lists
    """
    actions = {"buys": [], "sells": [], "holds": []}
    
    # Get current prices
    all_tickers = list(set(target_allocations.keys()) | set(current_positions.keys()))
    prices = {}
    for ticker in all_tickers:
        try:
            quote = broker.get_quote(ticker)
            prices[ticker] = quote.get("price", 0)
        except Exception as e:
            logger.warning("Failed to get price", ticker=ticker, error=str(e))
            prices[ticker] = 0
    
    # Calculate deltas and execute trades
    for ticker in all_tickers:
        target_usd = target_allocations.get(ticker, 0)
        current_qty = current_positions.get(ticker, {}).get("qty", 0)
        current_usd = current_qty * prices.get(ticker, 0)
        
        delta_usd = target_usd - current_usd
        
        # Skip small deltas
        if abs(delta_usd) < min_trade_usd:
            if current_qty > 0:
                actions["holds"].append({
                    "ticker": ticker,
                    "current_qty": current_qty,
                    "current_usd": current_usd,
                })
            continue
        
        price = prices.get(ticker, 0)
        if price <= 0:
            logger.warning("Invalid price for rebalance", ticker=ticker)
            continue
        
        # Calculate shares to trade
        delta_shares = int(delta_usd / price)
        
        if delta_shares > 0:
            # Buy
            try:
                order = broker.submit_market_order(
                    ticker,
                    delta_shares,
                    "buy",
                )
                actions["buys"].append({
                    "ticker": ticker,
                    "shares": delta_shares,
                    "target_usd": target_usd,
                    "order_id": order.get("id"),
                })
                logger.info("Submitted buy", ticker=ticker, shares=delta_shares)
            except Exception as e:
                logger.error("Buy failed", ticker=ticker, shares=delta_shares, error=str(e))
                
        elif delta_shares < 0:
            # Sell
            shares_to_sell = abs(delta_shares)
            if shares_to_sell > current_qty:
                shares_to_sell = current_qty
            
            if shares_to_sell > 0:
                try:
                    order = broker.submit_market_order(
                        ticker,
                        shares_to_sell,
                        "sell",
                    )
                    actions["sells"].append({
                        "ticker": ticker,
                        "shares": shares_to_sell,
                        "target_usd": target_usd,
                        "order_id": order.get("id"),
                    })
                    logger.info("Submitted sell", ticker=ticker, shares=shares_to_sell)
                except Exception as e:
                    logger.error("Sell failed", ticker=ticker, shares=shares_to_sell, error=str(e))
    
    return actions


def main():
    parser = argparse.ArgumentParser(
        description="Growth-income-drip quarterly rebalancer"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute trades (default: dry run)",
    )
    parser.add_argument(
        "--force-rebalance",
        action="store_true",
        help="Force quarterly rebalance even if not due",
    )
    parser.add_argument(
        "--growth-weight",
        type=float,
        default=0.80,
        help="Growth sleeve weight (default 0.80)",
    )
    parser.add_argument(
        "--ballast-weight",
        type=float,
        default=0.20,
        help="Ballast sleeve weight (default 0.20)",
    )
    
    args = parser.parse_args()
    
    logger.info(
        "Starting growth-income-drip rebalance",
        track_id=TRACK_ID,
        execute=args.execute,
    )
    
    # Get broker
    broker = get_drip_broker()
    
    # Get account info
    account = broker.get_account()
    nav = float(account.get("equity", 0))
    cash = float(account.get("cash", 0))
    
    # Get current positions
    positions = broker.get_positions()
    current_positions = {
        pos["symbol"]: {"qty": int(pos["qty"]), "market_value": float(pos["market_value"])}
        for pos in positions
    }
    
    logger.info(
        "Account snapshot",
        nav=nav,
        cash=cash,
        positions=len(current_positions),
    )
    
    # Check if quarterly rebalance is due
    last_rebalance = get_last_rebalance_date()
    rebalance_due = args.force_rebalance or is_quarterly_rebalance_due(last_rebalance)
    
    if rebalance_due and args.execute:
        logger.info("Quarterly rebalance due", last_rebalance=last_rebalance)
        
        # Get universe
        universe = get_liquid_universe(200)
        
        # Select growth sleeve (momentum)
        momentum = MomentumSelector(
            lookback_months=12,
            skip_months=1,
            top_n=30,
        )
        growth_tickers = momentum.select(universe)
        
        # Select ballast sleeve (dividends)
        ballast = DividendBallastSelector(
            min_dividend_yield=0.02,
            max_holdings=15,
        )
        ballast_tickers = ballast.select(universe)
        
        logger.info(
            "Selection complete",
            growth_count=len(growth_tickers),
            ballast_count=len(ballast_tickers),
        )
        
        # Calculate target allocations
        targets = calculate_target_allocations(
            growth_tickers,
            ballast_tickers,
            args.growth_weight,
            args.ballast_weight,
            nav,
        )
        
        # Execute delta rebalance
        actions = execute_delta_rebalance(
            broker,
            targets,
            current_positions,
        )
        
        logger.info(
            "Rebalance complete",
            buys=len(actions["buys"]),
            sells=len(actions["sells"]),
            holds=len(actions["holds"]),
        )
        
        # Record rebalance
        record_last_rebalance()
        
    else:
        logger.info("No rebalance due", last_rebalance=last_rebalance, force=args.force_rebalance)
    
    # Always record daily snapshot
    record_snapshot(
        nav=nav,
        cash_plus_stocks=cash + sum(p["market_value"] for p in current_positions.values()),
        positions=current_positions,
        run_config={
            "growth_weight": args.growth_weight,
            "ballast_weight": args.ballast_weight,
        },
    )
    
    logger.info("Snapshot recorded")
    
    # Send email notification
    try:
        notifier = get_email_notifier()
        if notifier:
            subject = f"[{TRACK_ID}] Daily Snapshot"
            body = f"""
Growth-Income-Drip Daily Snapshot

NAV: ${nav:,.2f}
Cash: ${cash:,.2f}
Positions: {len(current_positions)}

Rebalance Due: {rebalance_due}
Last Rebalance: {last_rebalance}

Track: {TRACK_ID}
            """
            notifier.send_email(subject, body)
            logger.info("Email sent")
    except Exception as e:
        logger.warning("Failed to send email", error=str(e))


if __name__ == "__main__":
    main()
