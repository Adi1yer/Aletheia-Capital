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
    calculate_returns,
    TRACK_ID,
    START_DATE,
    START_NAV_USD,
)
from src.utils.email import get_email_notifier
from src.utils.drip_email import build_drip_daily_email
from src.portfolio.manager import PortfolioDecision

logger = structlog.get_logger()


def get_drip_broker() -> AlpacaBroker:
    """Create Alpaca broker using DRIP_ALPACA_* secrets."""
    api_key = os.getenv("DRIP_ALPACA_API_KEY")
    secret_key = os.getenv("DRIP_ALPACA_SECRET_KEY")
    
    if not api_key or not secret_key:
        raise ValueError(
            "Missing DRIP_ALPACA_API_KEY or DRIP_ALPACA_SECRET_KEY. "
            "Set these in GitHub Secrets for the drip paper account (requires separate Alpaca email)."
        )
    
    return AlpacaBroker(
        api_key=api_key,
        secret_key=secret_key,
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


def calculate_sleeve_breakdown(
    positions: Dict[str, Dict],
    growth_tickers: Optional[List[str]] = None,
    ballast_tickers: Optional[List[str]] = None,
) -> Tuple[float, float]:
    """
    Calculate growth and ballast sleeve market values from positions.
    
    Args:
        positions: Current positions dictionary
        growth_tickers: List of growth sleeve tickers (if known)
        ballast_tickers: List of ballast sleeve tickers (if known)
        
    Returns:
        Tuple of (growth_nav, ballast_nav)
    """
    growth_set = set(growth_tickers or [])
    ballast_set = set(ballast_tickers or [])
    
    growth_nav = 0.0
    ballast_nav = 0.0
    
    for ticker, pos in positions.items():
        market_value = pos.get("market_value", 0)
        if ticker in growth_set:
            growth_nav += market_value
        elif ticker in ballast_set:
            ballast_nav += market_value
        # If ticker is in neither set, we can't classify it
        # This happens when we don't have the latest selection data
    
    return growth_nav, ballast_nav


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


def has_excess_cash(cash: float, nav: float, threshold_pct: float = 0.10) -> bool:
    """
    Check if account has excess cash above threshold.
    
    Args:
        cash: Current cash balance
        nav: Net asset value
        threshold_pct: Threshold as percentage of NAV (default 10%)
        
    Returns:
        True if cash exceeds threshold
    """
    if nav <= 0:
        return False
    cash_pct = cash / nav
    return cash_pct > threshold_pct


def deploy_residual_cash(
    broker: AlpacaBroker,
    current_positions: Dict[str, Dict],
    cash_to_deploy: float,
    min_trade_usd: float = 100.0,
) -> Dict[str, List[Dict]]:
    """
    Deploy residual cash into current positions proportionally.
    
    This maintains the current portfolio allocation while deploying idle cash.
    
    Args:
        broker: Alpaca broker instance
        current_positions: Current positions from broker
        cash_to_deploy: Amount of cash to deploy
        min_trade_usd: Minimum trade size in USD (default 100)
        
    Returns:
        Dictionary with 'buys', 'sells', and 'holds' lists
    """
    actions = {"buys": [], "sells": [], "holds": []}
    
    if not current_positions or cash_to_deploy < min_trade_usd:
        logger.info("No positions or insufficient cash to deploy", 
                   positions=len(current_positions), 
                   cash=cash_to_deploy)
        return actions
    
    # Calculate total current market value
    total_market_value = sum(pos["market_value"] for pos in current_positions.values())
    
    if total_market_value <= 0:
        logger.warning("No market value in current positions")
        return actions
    
    # Get prices for all current positions
    tickers = list(current_positions.keys())
    
    try:
        prices = broker.get_last_equity_prices(tickers)
        logger.info("Fetched prices for residual cash deployment", 
                   count=len(prices), 
                   requested=len(tickers))
    except Exception as e:
        logger.error("Failed to fetch prices for residual cash deployment", error=str(e))
        return actions
    
    if not prices:
        logger.error("No prices available for residual cash deployment")
        return actions
    
    # Deploy cash proportionally to current positions
    trades_attempted = 0
    for ticker in tickers:
        price = prices.get(ticker, 0)
        
        if price <= 0:
            logger.warning("Skipping ticker with invalid price in residual deploy", 
                          ticker=ticker)
            continue
        
        # Calculate proportional allocation
        current_value = current_positions[ticker]["market_value"]
        proportion = current_value / total_market_value
        target_deploy = cash_to_deploy * proportion
        
        if target_deploy < min_trade_usd:
            continue
        
        # Calculate shares to buy
        shares_to_buy = int(target_deploy / price)
        
        if shares_to_buy <= 0:
            continue
        
        trades_attempted += 1
        try:
            decision = PortfolioDecision(
                action="buy",
                quantity=shares_to_buy,
                confidence=80,
                reasoning=f"Residual cash deployment (${target_deploy:.2f})",
            )
            order = broker.execute_order(ticker, decision, current_price=price)
            
            if order and order.get("success"):
                actions["buys"].append({
                    "ticker": ticker,
                    "shares": shares_to_buy,
                    "allocated_usd": target_deploy,
                    "order_id": order.get("order_id"),
                })
                logger.info("Submitted residual cash buy", 
                           ticker=ticker, 
                           shares=shares_to_buy)
            else:
                logger.error("Residual cash buy order failed", 
                            ticker=ticker, 
                            shares=shares_to_buy, 
                            result=order)
        except Exception as e:
            logger.error("Residual cash buy exception", 
                        ticker=ticker, 
                        shares=shares_to_buy, 
                        error=str(e))
    
    logger.info("Residual cash deployment complete", 
               trades_attempted=trades_attempted,
               trades_executed=len(actions["buys"]),
               total_deployed=sum(b["allocated_usd"] for b in actions["buys"]))
    
    return actions


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
    
    # Get current prices using batch API
    all_tickers = list(set(target_allocations.keys()) | set(current_positions.keys()))
    
    if not all_tickers:
        logger.info("No tickers to rebalance")
        return actions
    
    try:
        prices = broker.get_last_equity_prices(all_tickers)
        logger.info("Fetched prices", count=len(prices), requested=len(all_tickers))
    except Exception as e:
        logger.error("Failed to fetch prices in batch", error=str(e))
        raise RuntimeError(f"Price fetch failed for rebalance: {e}")
    
    # Check if we got any prices
    if not prices:
        logger.error("No prices available for any ticker", tickers=all_tickers[:10])
        raise RuntimeError(f"No prices available for {len(all_tickers)} tickers; cannot rebalance")
    
    # Warn about missing prices but continue
    missing_prices = [t for t in all_tickers if t not in prices or prices[t] <= 0]
    if missing_prices:
        logger.warning(
            "Missing prices for some tickers",
            count=len(missing_prices),
            tickers=missing_prices[:10],
        )
    
    # Calculate deltas and execute trades
    trades_attempted = 0
    for ticker in all_tickers:
        target_usd = target_allocations.get(ticker, 0)
        current_qty = current_positions.get(ticker, {}).get("qty", 0)
        price = prices.get(ticker, 0)
        
        if price <= 0:
            logger.warning("Skipping ticker with invalid price", ticker=ticker, target_usd=target_usd)
            continue
        
        current_usd = current_qty * price
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
        
        # Calculate shares to trade
        delta_shares = int(delta_usd / price)
        
        if delta_shares > 0:
            # Buy
            trades_attempted += 1
            try:
                decision = PortfolioDecision(
                    action="buy",
                    quantity=delta_shares,
                    confidence=80,
                    reasoning=f"Drip quarterly rebalance buy to ${target_usd:.2f}",
                )
                order = broker.execute_order(ticker, decision, current_price=price)
                
                if order and order.get("success"):
                    actions["buys"].append({
                        "ticker": ticker,
                        "shares": delta_shares,
                        "target_usd": target_usd,
                        "order_id": order.get("order_id"),
                    })
                    logger.info("Submitted buy", ticker=ticker, shares=delta_shares)
                else:
                    logger.error("Buy order failed", ticker=ticker, shares=delta_shares, result=order)
            except Exception as e:
                logger.error("Buy exception", ticker=ticker, shares=delta_shares, error=str(e))
                
        elif delta_shares < 0:
            # Sell
            shares_to_sell = abs(delta_shares)
            if shares_to_sell > current_qty:
                shares_to_sell = current_qty
            
            if shares_to_sell > 0:
                trades_attempted += 1
                try:
                    decision = PortfolioDecision(
                        action="sell",
                        quantity=shares_to_sell,
                        confidence=80,
                        reasoning=f"Drip quarterly rebalance sell to ${target_usd:.2f}",
                    )
                    order = broker.execute_order(ticker, decision, current_price=price)
                    
                    if order and order.get("success"):
                        actions["sells"].append({
                            "ticker": ticker,
                            "shares": shares_to_sell,
                            "target_usd": target_usd,
                            "order_id": order.get("order_id"),
                        })
                        logger.info("Submitted sell", ticker=ticker, shares=shares_to_sell)
                    else:
                        logger.error("Sell order failed", ticker=ticker, shares=shares_to_sell, result=order)
                except Exception as e:
                    logger.error("Sell exception", ticker=ticker, shares=shares_to_sell, error=str(e))
    
    # Validate that we executed at least some trades if targets exist
    total_executed = len(actions["buys"]) + len(actions["sells"])
    if trades_attempted > 0 and total_executed == 0:
        logger.error(
            "Zero trades executed despite non-empty targets",
            trades_attempted=trades_attempted,
            target_count=len(target_allocations),
        )
        raise RuntimeError(
            f"Rebalance failed: {trades_attempted} trades attempted but 0 executed. "
            "Check broker connectivity and credentials."
        )
    
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
        symbol: {"qty": int(pos["qty"]), "market_value": float(pos["market_value"])}
        for symbol, pos in positions.items()
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
        
    elif args.execute and has_excess_cash(cash, nav, threshold_pct=0.10):
        # Deploy residual cash into current positions if above 10% threshold
        logger.info(
            "Excess cash detected, deploying into current positions",
            cash=cash,
            nav=nav,
            cash_pct=cash/nav*100,
        )
        
        actions = deploy_residual_cash(
            broker,
            current_positions,
            cash,
        )
        
        logger.info(
            "Residual cash deployment complete",
            buys=len(actions["buys"]),
            total_deployed=sum(b.get("allocated_usd", 0) for b in actions["buys"]),
        )
        
    else:
        logger.info(
            "No action taken", 
            rebalance_due=rebalance_due, 
            execute=args.execute,
            cash_pct=cash/nav*100 if nav > 0 else 0,
        )
    
    # Fetch SPY data for benchmark comparison
    spy_level = None
    try:
        spy_prices = broker.get_last_equity_prices(["SPY"])
        spy_level = spy_prices.get("SPY")
        if spy_level:
            logger.info("Fetched SPY level", spy_level=spy_level)
    except Exception as e:
        logger.warning("Failed to fetch SPY data", error=str(e))
    
    # Calculate sleeve breakdown if we have selection data
    growth_nav = None
    ballast_nav = None
    growth_tickers = []
    ballast_tickers = []
    
    # Try to infer sleeve breakdown from latest snapshot or use current positions
    # For daily snapshots without rebalance, we don't have fresh selection data
    # So we'll leave growth_nav and ballast_nav as None unless we just rebalanced
    if rebalance_due and args.execute:
        # We have fresh selection data from rebalance
        try:
            universe = get_liquid_universe(200)
            momentum = MomentumSelector(lookback_months=12, skip_months=1, top_n=30)
            growth_tickers = momentum.select(universe)
            ballast = DividendBallastSelector(min_dividend_yield=0.02, max_holdings=15)
            ballast_tickers = ballast.select(universe)
            growth_nav, ballast_nav = calculate_sleeve_breakdown(
                current_positions, growth_tickers, ballast_tickers
            )
            logger.info("Calculated sleeve breakdown", growth_nav=growth_nav, ballast_nav=ballast_nav)
        except Exception as e:
            logger.warning("Failed to calculate sleeve breakdown", error=str(e))
    
    # Always record daily snapshot
    record_snapshot(
        nav=nav,
        cash_plus_stocks=cash + sum(p["market_value"] for p in current_positions.values()),
        positions=current_positions,
        run_config={
            "growth_weight": args.growth_weight,
            "ballast_weight": args.ballast_weight,
        },
        growth_nav=growth_nav,
        ballast_nav=ballast_nav,
        spy_level=spy_level,
    )
    
    logger.info("Snapshot recorded")
    
    # Load historical snapshots to calculate returns
    from src.performance.drip_track import snapshot_dir
    snapshots = []
    try:
        snap_dir = snapshot_dir()
        if snap_dir.exists():
            for snap_file in sorted(snap_dir.glob("snapshot_*.json")):
                try:
                    import json
                    with open(snap_file) as f:
                        snapshots.append(json.load(f))
                except Exception as e:
                    logger.warning("Failed to load snapshot", file=snap_file, error=str(e))
    except Exception as e:
        logger.warning("Failed to load snapshots", error=str(e))
    
    # Calculate returns for email
    returns = calculate_returns(snapshots) if snapshots else {}
    spy_since_start_pct = returns.get("spy_return_pct")
    excess_return_pct = returns.get("excess_return_pct")
    track_return_pct = returns.get("total_return_pct")
    
    # Send email notification
    try:
        recipient = os.getenv("RECIPIENT_EMAIL")
        if not recipient:
            logger.info("RECIPIENT_EMAIL not set, skipping email")
        else:
            notifier = get_email_notifier()
            if notifier:
                # Get fresh account info after trades for accurate email
                account = broker.get_account()
                email_nav = float(account.get("equity", 0))
                email_cash = float(account.get("cash", 0))
                email_positions = broker.get_positions()
                email_positions_dict = {
                    symbol: {"qty": int(pos["qty"]), "market_value": float(pos["market_value"])}
                    for symbol, pos in email_positions.items()
                }
                
                subject, body = build_drip_daily_email(
                    nav=email_nav,
                    cash=email_cash,
                    positions=email_positions_dict,
                    last_rebalance=str(last_rebalance) if last_rebalance else None,
                    rebalance_due=rebalance_due,
                    growth_nav=growth_nav,
                    ballast_nav=ballast_nav,
                    spy_since_start_pct=spy_since_start_pct,
                    excess_return_pct=excess_return_pct,
                    track_return_pct=track_return_pct,
                    track_id=TRACK_ID,
                    start_date=START_DATE.isoformat(),
                    start_nav=START_NAV_USD,
                )
                notifier.send_email(recipient, subject, body)
                logger.info("Email sent", recipient=recipient)
    except Exception as e:
        logger.warning("Failed to send email", error=str(e))


if __name__ == "__main__":
    main()
