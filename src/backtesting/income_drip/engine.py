"""Income drip backtest engine - momentum growth funded by dividend + option income."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.backtesting.growth_quality.universe import get_point_in_time_quality_universe
from src.backtesting.income_drip.dividend_universe import (
    get_dividend_universe_point_in_time,
    get_dividend_amount_trailing_12m,
)

logger = structlog.get_logger()


@dataclass
class Position:
    """Long equity position."""
    ticker: str
    shares: float
    cost_basis: float
    date_acquired: date
    sleeve: str  # "growth" or "ballast"


@dataclass
class CoveredCallPosition:
    """Covered call contract."""
    ticker: str
    contracts: float  # Number of contracts (1 contract = 100 shares)
    strike: float
    expiry: date
    premium_per_contract: float
    date_written: date


@dataclass
class Portfolio:
    """Two-sleeve portfolio with optional covered calls."""
    cash: float = 0.0
    positions: List[Position] = field(default_factory=list)
    covered_calls: List[CoveredCallPosition] = field(default_factory=list)
    accumulated_drip_cash: float = 0.0  # Cash to drip into growth at next rebalance
    trades: List[Dict] = field(default_factory=list)
    realized_pnl: float = 0.0
    
    def get_holdings(self) -> Dict[str, float]:
        """Get current holdings as {ticker: total_shares}."""
        holdings = {}
        for pos in self.positions:
            holdings[pos.ticker] = holdings.get(pos.ticker, 0.0) + pos.shares
        return holdings
    
    def get_holdings_by_sleeve(self, sleeve: str) -> Dict[str, float]:
        """Get holdings for a specific sleeve."""
        holdings = {}
        for pos in self.positions:
            if pos.sleeve == sleeve:
                holdings[pos.ticker] = holdings.get(pos.ticker, 0.0) + pos.shares
        return holdings
    
    def get_nav(self, prices: Dict[str, float]) -> float:
        """Calculate net asset value (including unrealized CC obligations)."""
        nav = self.cash + self.accumulated_drip_cash
        
        # Add position values
        for pos in self.positions:
            price = prices.get(pos.ticker, pos.cost_basis)
            nav += pos.shares * price
        
        # Subtract unrealized CC obligations (if ITM)
        for cc in self.covered_calls:
            price = prices.get(cc.ticker, cc.strike)
            if price > cc.strike:
                # ITM - we owe the difference
                intrinsic = (price - cc.strike) * 100 * cc.contracts
                nav -= intrinsic
        
        return nav
    
    def add_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        trade_date: date,
        sleeve: str,
    ) -> bool:
        """Buy shares."""
        cost = shares * price
        if cost > self.cash:
            logger.warning("Insufficient cash", ticker=ticker, cost=cost, cash=self.cash)
            return False
        
        self.cash -= cost
        self.positions.append(Position(
            ticker=ticker,
            shares=shares,
            cost_basis=price,
            date_acquired=trade_date,
            sleeve=sleeve,
        ))
        self.trades.append({
            "date": trade_date.isoformat(),
            "type": "buy",
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "sleeve": sleeve,
            "cash_change": -cost,
        })
        return True
    
    def sell_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        trade_date: date,
    ) -> bool:
        """Sell shares (FIFO)."""
        remaining = shares
        
        for i in range(len(self.positions) - 1, -1, -1):
            if self.positions[i].ticker != ticker:
                continue
            
            if remaining <= 0:
                break
            
            pos = self.positions[i]
            to_sell = min(pos.shares, remaining)
            proceeds = to_sell * price
            cost_basis_portion = to_sell * pos.cost_basis
            realized = proceeds - cost_basis_portion
            
            self.cash += proceeds
            self.realized_pnl += realized
            
            self.trades.append({
                "date": trade_date.isoformat(),
                "type": "sell",
                "ticker": ticker,
                "shares": to_sell,
                "price": price,
                "cost_basis": pos.cost_basis,
                "realized_pnl": realized,
                "sleeve": pos.sleeve,
                "cash_change": proceeds,
            })
            
            pos.shares -= to_sell
            remaining -= to_sell
            
            if pos.shares < 0.001:
                del self.positions[i]
        
        return remaining < 0.001


class IncomeDripBacktest:
    """
    Two-sleeve backtest: growth momentum + dividend ballast.
    
    Sleeves:
    - Growth: Arm C momentum names (12-1 month momentum, top 30)
    - Ballast: Dividend payers (yield-screened, top 20)
    
    Income drip mechanics:
    - Ballast pays dividends quarterly (accumulated)
    - Ballast may write light covered calls (partial overwrite or OTM)
    - All income (dividends + CC premiums) accumulates in drip_cash
    - At quarterly rebalance, drip_cash is deployed into growth sleeve
    """
    
    def __init__(
        self,
        start_date: str,
        end_date: str,
        initial_nav: float = 10_000.0,
        growth_weight: float = 0.80,
        ballast_weight: float = 0.20,
        rebalance_frequency: str = "quarterly",
        trading_cost_pct: float = 0.0007,  # 7 bps
        benchmark_ticker: str = "^SPXTR",
        # Covered call params (ballast only)
        cc_enabled: bool = False,
        cc_overwrite_pct: float = 0.50,  # 50% of ballast gets overwritten
        cc_otm_pct: float = 0.075,  # 7.5% OTM
        cc_tenor_days: int = 45,  # ~6-7 weeks
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.initial_nav = initial_nav
        self.growth_weight = growth_weight
        self.ballast_weight = ballast_weight
        self.rebalance_frequency = rebalance_frequency
        self.trading_cost_pct = trading_cost_pct
        self.benchmark_ticker = benchmark_ticker
        
        # CC params
        self.cc_enabled = cc_enabled
        self.cc_overwrite_pct = cc_overwrite_pct
        self.cc_otm_pct = cc_otm_pct
        self.cc_tenor_days = cc_tenor_days
        
        self.portfolio = Portfolio(cash=initial_nav)
        self.equity_curve: List[Tuple[str, float]] = []
        self.spy_curve: List[Tuple[str, float]] = []
        self.price_history: Dict[str, List[Tuple[date, float]]] = {}
        self.last_rebalance_date: Optional[date] = None
    
    def load_price_history(self, ticker: str, data_provider, cache=None):
        """Load historical prices for a ticker (with optional caching)."""
        try:
            if cache:
                prices = cache.get_prices(ticker, self.start_date, self.end_date, data_provider)
            else:
                prices = data_provider.get_prices(ticker, self.start_date, self.end_date)
            
            history = []
            for p in prices:
                d = p.time.date() if hasattr(p.time, "date") else p.time
                close = float(p.close)
                history.append((d, close))
            
            history.sort(key=lambda x: x[0])
            self.price_history[ticker] = history
            
            logger.info("Loaded price history", ticker=ticker, count=len(history))
            
        except Exception as e:
            logger.error("Failed to load prices", ticker=ticker, error=str(e))
            self.price_history[ticker] = []
    
    def get_price_on_date(self, ticker: str, d: date) -> Optional[float]:
        """Get closing price for ticker on date (or most recent prior)."""
        history = self.price_history.get(ticker, [])
        
        for i in range(len(history) - 1, -1, -1):
            if history[i][0] <= d:
                return history[i][1]
        
        return None
    
    def should_rebalance(self, trade_date: date) -> bool:
        """Determine if portfolio should rebalance on this date."""
        if self.last_rebalance_date is None:
            return True
        
        if self.rebalance_frequency == "quarterly":
            rebal_months = [1, 4, 7, 10]
            return (
                trade_date.month in rebal_months
                and self.last_rebalance_date.month != trade_date.month
            )
        
        return False
    
    def collect_dividends(
        self,
        trade_date: date,
        data_provider,
        cache=None,
    ):
        """
        Collect dividends for ballast holdings.
        
        Dividends are accumulated in drip_cash for deployment at next rebalance.
        """
        ballast_holdings = self.portfolio.get_holdings_by_sleeve("ballast")
        
        total_dividends = 0.0
        
        for ticker, shares in ballast_holdings.items():
            # Get dividends paid since last rebalance (or since start if first time)
            start = self.last_rebalance_date or date.fromisoformat(self.start_date)
            
            try:
                if cache:
                    dividends = cache.get_dividends(
                        ticker,
                        start.isoformat(),
                        trade_date.isoformat(),
                        data_provider,
                    )
                else:
                    dividends = data_provider.get_dividends(
                        ticker,
                        start.isoformat(),
                        trade_date.isoformat(),
                    )
                
                for div in dividends:
                    amount_per_share = div.amount
                    total_amount = shares * amount_per_share
                    total_dividends += total_amount
                    
                    self.portfolio.trades.append({
                        "date": trade_date.isoformat(),
                        "type": "dividend",
                        "ticker": ticker,
                        "shares": shares,
                        "amount_per_share": amount_per_share,
                        "total": total_amount,
                        "sleeve": "ballast",
                    })
            
            except Exception as e:
                logger.debug(f"Failed to fetch dividends for {ticker}: {e}")
        
        if total_dividends > 0:
            self.portfolio.accumulated_drip_cash += total_dividends
            logger.info(f"Collected dividends on {trade_date}", total=total_dividends)
    
    def write_covered_calls(
        self,
        trade_date: date,
        prices: Dict[str, float],
    ):
        """
        Write covered calls on ballast positions (if enabled).
        
        Light CC strategy:
        - Overwrite only cc_overwrite_pct of ballast positions
        - Strike at cc_otm_pct OTM
        - Tenor ~45 days
        - Use Black-Scholes for synthetic pricing
        """
        if not self.cc_enabled:
            return
        
        ballast_holdings = self.portfolio.get_holdings_by_sleeve("ballast")
        
        total_premiums = 0.0
        
        for ticker, shares in ballast_holdings.items():
            # Only overwrite cc_overwrite_pct of position
            shares_to_cover = shares * self.cc_overwrite_pct
            contracts = shares_to_cover / 100.0
            
            if contracts < 0.01:
                continue
            
            price = prices.get(ticker)
            if price is None or price <= 0:
                continue
            
            # Calculate strike
            strike = price * (1.0 + self.cc_otm_pct)
            
            # Round strike to nearest $0.50 or $1.00
            if strike < 25:
                strike = round(strike * 2) / 2.0
            else:
                strike = round(strike)
            
            # Calculate premium using synthetic Black-Scholes
            tenor_years = self.cc_tenor_days / 365.0
            
            # Get realized volatility for this ticker
            rv = self._get_realized_vol(ticker, trade_date)
            if rv is None:
                logger.debug(f"Skipping CC on {ticker} - no volatility data")
                continue
            
            # Synthetic pricing: use realized vol * 1.1 as proxy for IV
            # (Options typically trade at slight premium to realized)
            iv = rv * 1.1
            
            premium = self._black_scholes_call(
                S=price,
                K=strike,
                T=tenor_years,
                r=0.04,  # 4% risk-free rate
                sigma=iv,
            )
            
            if premium <= 0:
                continue
            
            total_premium = premium * contracts * 100  # Premium per contract is for 100 shares
            
            # Add to drip cash
            self.portfolio.accumulated_drip_cash += total_premium
            total_premiums += total_premium
            
            # Track CC position
            expiry = trade_date + timedelta(days=self.cc_tenor_days)
            self.portfolio.covered_calls.append(CoveredCallPosition(
                ticker=ticker,
                contracts=contracts,
                strike=strike,
                expiry=expiry,
                premium_per_contract=premium * 100,
                date_written=trade_date,
            ))
            
            self.portfolio.trades.append({
                "date": trade_date.isoformat(),
                "type": "write_cc",
                "ticker": ticker,
                "contracts": contracts,
                "strike": strike,
                "expiry": expiry.isoformat(),
                "premium_per_contract": premium * 100,
                "total_premium": total_premium,
                "sleeve": "ballast",
            })
        
        if total_premiums > 0:
            logger.info(f"Wrote covered calls on {trade_date}", total_premiums=total_premiums)
    
    def expire_covered_calls(
        self,
        trade_date: date,
        prices: Dict[str, float],
    ):
        """Expire or exercise covered calls that have reached expiry."""
        expired = []
        
        for i, cc in enumerate(self.portfolio.covered_calls):
            if cc.expiry > trade_date:
                continue
            
            # CC has expired
            price = prices.get(cc.ticker)
            if price is None:
                expired.append(i)
                continue
            
            if price > cc.strike:
                # ITM - shares called away
                shares_called = cc.contracts * 100
                
                # Sell shares at strike price
                self.portfolio.sell_position(cc.ticker, shares_called, cc.strike, trade_date)
                
                self.portfolio.trades.append({
                    "date": trade_date.isoformat(),
                    "type": "cc_exercise",
                    "ticker": cc.ticker,
                    "contracts": cc.contracts,
                    "strike": cc.strike,
                    "underlying_price": price,
                    "sleeve": "ballast",
                })
            else:
                # OTM - expires worthless (we keep premium, keep shares)
                self.portfolio.trades.append({
                    "date": trade_date.isoformat(),
                    "type": "cc_expire_otm",
                    "ticker": cc.ticker,
                    "contracts": cc.contracts,
                    "strike": cc.strike,
                    "underlying_price": price,
                    "sleeve": "ballast",
                })
            
            expired.append(i)
        
        # Remove expired CCs
        for i in reversed(expired):
            del self.portfolio.covered_calls[i]
    
    def _get_realized_vol(self, ticker: str, as_of_date: date, window: int = 21) -> Optional[float]:
        """Calculate annualized realized volatility."""
        history = self.price_history.get(ticker, [])
        
        # Get prices up to as_of_date
        prices_before = [p for d, p in history if d <= as_of_date]
        
        if len(prices_before) < window + 1:
            return None
        
        tail = prices_before[-window - 1:]
        returns = [math.log(tail[i] / tail[i - 1]) for i in range(1, len(tail)) if tail[i] > 0 and tail[i - 1] > 0]
        
        if len(returns) < 5:
            return None
        
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / max(1, len(returns) - 1)
        daily_vol = math.sqrt(variance)
        annual_vol = daily_vol * math.sqrt(252.0)
        
        return max(0.10, min(2.0, annual_vol))
    
    def _black_scholes_call(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
    ) -> float:
        """Black-Scholes call option price."""
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return max(0.0, S - K)
        
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        # Norm CDF approximation
        def norm_cdf(x: float) -> float:
            t = 1.0 / (1.0 + 0.2316419 * abs(x))
            d = 0.3989423 * math.exp(-x * x / 2.0)
            prob = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
            return 1.0 - prob if x >= 0 else prob
        
        call_price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        return max(0.0, call_price)
    
    def rebalance(
        self,
        trade_date: date,
        growth_universe: List[str],
        ballast_universe: List[str],
        prices: Dict[str, float],
    ):
        """
        Rebalance portfolio to target sleeve weights + drip accumulated cash into growth.
        
        Steps:
        1. Collect any pending dividends (already done before calling)
        2. Expire any matured CCs
        3. Combine cash + drip_cash for rebalancing
        4. Deploy to target sleeve weights (growth_weight%, ballast_weight%)
        5. Only trade deltas (not full liquidation/rebuild)
        6. Write new CCs on ballast (if enabled)
        """
        logger.info(f"Rebalancing on {trade_date}", drip_cash=self.portfolio.accumulated_drip_cash)
        
        # Expire CCs
        self.expire_covered_calls(trade_date, prices)
        
        # Calculate current NAV
        current_nav = self.portfolio.get_nav(prices)
        
        if current_nav <= 0:
            logger.warning("NAV <= 0, cannot rebalance")
            return
        
        # Combine regular cash + drip cash
        total_cash = self.portfolio.cash + self.portfolio.accumulated_drip_cash
        
        # Reset drip cash (we're deploying it now)
        drip_deployed = self.portfolio.accumulated_drip_cash
        self.portfolio.accumulated_drip_cash = 0.0
        self.portfolio.cash = total_cash
        
        logger.info(f"Deploying drip cash to growth", drip_cash=drip_deployed, total_cash=total_cash)
        
        # Get current holdings
        current_holdings = self.portfolio.get_holdings()
        
        # Target allocations based on TOTAL NAV (not just cash)
        # We use current_nav which includes both cash and positions
        growth_target_nav = current_nav * self.growth_weight
        ballast_target_nav = current_nav * self.ballast_weight
        
        # Calculate target $ values for each name
        target_values = {}
        
        # Growth names (equal weight within growth sleeve)
        if growth_universe:
            target_per_name = growth_target_nav / len(growth_universe)
            for ticker in growth_universe:
                if ticker in prices and prices[ticker] > 0:
                    target_values[ticker] = target_per_name
        
        # Ballast names (equal weight within ballast sleeve)
        if ballast_universe:
            target_per_name = ballast_target_nav / len(ballast_universe)
            for ticker in ballast_universe:
                if ticker in prices and prices[ticker] > 0:
                    target_values[ticker] = target_per_name
        
        # Sell positions no longer in target
        for ticker in list(current_holdings.keys()):
            if ticker not in target_values:
                price = prices.get(ticker)
                if price and price > 0:
                    shares = current_holdings[ticker]
                    net_price = price * (1.0 - self.trading_cost_pct)
                    self.portfolio.sell_position(ticker, shares, net_price, trade_date)
        
        # Adjust positions to target
        current_holdings = self.portfolio.get_holdings()  # Refresh after sells
        
        for ticker, target_value in target_values.items():
            price = prices.get(ticker)
            if not price or price <= 0:
                continue
            
            current_shares = current_holdings.get(ticker, 0.0)
            current_value = current_shares * price
            
            delta_value = target_value - current_value
            
            # Only trade if delta is significant (>$10 or >1% of target)
            if abs(delta_value) < max(10.0, target_value * 0.01):
                continue
            
            if delta_value > 0:
                # Buy more
                delta_shares = delta_value / price
                net_price = price * (1.0 + self.trading_cost_pct)
                
                # Determine sleeve
                if ticker in growth_universe:
                    sleeve = "growth"
                else:
                    sleeve = "ballast"
                
                self.portfolio.add_position(ticker, delta_shares, net_price, trade_date, sleeve)
            else:
                # Sell some
                delta_shares = abs(delta_value) / price
                net_price = price * (1.0 - self.trading_cost_pct)
                self.portfolio.sell_position(ticker, delta_shares, net_price, trade_date)
        
        # Write covered calls on ballast (if enabled)
        if self.cc_enabled:
            self.write_covered_calls(trade_date, prices)
    
    def run(
        self,
        data_provider,
        arm_name: str = "income_drip",
        cache=None,
    ) -> Dict:
        """Run backtest simulation."""
        logger.info(
            "Starting income drip backtest",
            start=self.start_date,
            end=self.end_date,
            nav=self.initial_nav,
            growth_weight=self.growth_weight,
            ballast_weight=self.ballast_weight,
            cc_enabled=self.cc_enabled,
            arm=arm_name,
        )
        
        # Load benchmark
        benchmark_loaded = False
        for candidate in [self.benchmark_ticker, "SPY"]:
            self.load_price_history(candidate, data_provider, cache)
            if self.price_history.get(candidate):
                self.benchmark_ticker = candidate
                benchmark_loaded = True
                logger.info("Loaded benchmark", ticker=candidate)
                break
        
        if not benchmark_loaded:
            logger.error("Benchmark price history required")
            return {}
        
        # Get trading dates from benchmark
        benchmark_history = self.price_history.get(self.benchmark_ticker, [])
        if not benchmark_history:
            return {}
        
        trading_dates = [d for d, _ in benchmark_history]
        
        # Initial benchmark level
        spy_start = benchmark_history[0][1]
        self.spy_curve.append((trading_dates[0].isoformat(), spy_start))
        
        # Initial NAV
        self.equity_curve.append((trading_dates[0].isoformat(), self.initial_nav))
        
        # Initial allocation on first day
        first_date = trading_dates[0]
        
        growth_universe = get_point_in_time_quality_universe(
            first_date,
            top_n=30,
            data_provider=data_provider,
        )
        ballast_universe = get_dividend_universe_point_in_time(
            first_date,
            top_n=20,
            data_provider=data_provider,
        )
        
        # Load price history for all tickers
        for ticker in set(growth_universe + ballast_universe):
            if ticker not in self.price_history:
                self.load_price_history(ticker, data_provider, cache)
        
        # Get prices for first day
        prices = {t: self.get_price_on_date(t, first_date) or 0.0 for t in set(growth_universe + ballast_universe)}
        
        # Initial rebalance
        self.rebalance(first_date, growth_universe, ballast_universe, prices)
        self.last_rebalance_date = first_date
        
        # Daily loop
        for i, trade_date in enumerate(trading_dates[1:], start=1):
            # Check if rebalance needed
            if self.should_rebalance(trade_date):
                # Collect dividends since last rebalance (do this BEFORE rebalancing)
                self.collect_dividends(trade_date, data_provider, cache)
                
                # Refresh universes
                growth_universe = get_point_in_time_quality_universe(
                    trade_date,
                    top_n=30,
                    data_provider=data_provider,
                )
                ballast_universe = get_dividend_universe_point_in_time(
                    trade_date,
                    top_n=20,
                    data_provider=data_provider,
                )
                
                # Load any new tickers
                for ticker in set(growth_universe + ballast_universe):
                    if ticker not in self.price_history:
                        self.load_price_history(ticker, data_provider, cache)
                
                # Get prices
                prices = {t: self.get_price_on_date(t, trade_date) or 0.0 for t in set(growth_universe + ballast_universe)}
                
                # Rebalance (this includes deploying drip cash)
                self.rebalance(trade_date, growth_universe, ballast_universe, prices)
                self.last_rebalance_date = trade_date
            
            # Record NAV
            all_tickers = set(pos.ticker for pos in self.portfolio.positions)
            prices = {t: self.get_price_on_date(t, trade_date) or 0.0 for t in all_tickers}
            nav = self.portfolio.get_nav(prices)
            self.equity_curve.append((trade_date.isoformat(), nav))
            
            # Record benchmark
            spy_price = self.get_price_on_date(self.benchmark_ticker, trade_date) or spy_start
            self.spy_curve.append((trade_date.isoformat(), spy_price))
            
            if i % 50 == 0:
                logger.info("Backtest progress", date=trade_date, nav=nav, progress=f"{i}/{len(trading_dates)}")
        
        # Calculate metrics
        from src.backtesting.growth_quality.metrics import calculate_metrics
        
        metrics = calculate_metrics(
            self.equity_curve,
            self.spy_curve,
            self.initial_nav,
            self.portfolio.trades,
        )
        
        logger.info("Backtest complete", arm=arm_name, metrics=metrics)
        
        return {
            "summary": metrics,
            "equity_curve": self.equity_curve,
            "spy_curve": self.spy_curve,
            "trades": self.portfolio.trades,
            "assumptions": {
                "start_date": self.start_date,
                "end_date": self.end_date,
                "initial_nav": self.initial_nav,
                "arm": arm_name,
                "growth_weight": self.growth_weight,
                "ballast_weight": self.ballast_weight,
                "rebalance_frequency": self.rebalance_frequency,
                "trading_cost_pct": self.trading_cost_pct,
                "cc_enabled": self.cc_enabled,
                "cc_overwrite_pct": self.cc_overwrite_pct,
                "cc_otm_pct": self.cc_otm_pct,
                "cc_tenor_days": self.cc_tenor_days,
            },
        }
    
    def save_results(self, output_dir: Path, arm_name: str = "generic"):
        """Save equity curve, trades, and summary to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Equity curve
        with open(output_dir / f"equity_curve_{arm_name}.csv", "w") as f:
            f.write("date,nav,spy\n")
            for (date_str, nav), (_, spy_level) in zip(self.equity_curve, self.spy_curve):
                f.write(f"{date_str},{nav},{spy_level}\n")
        
        # Trades
        with open(output_dir / f"trades_{arm_name}.json", "w") as f:
            json.dump(self.portfolio.trades, f, indent=2)
        
        # Summary
        from src.backtesting.growth_quality.metrics import calculate_metrics
        
        metrics = calculate_metrics(
            self.equity_curve,
            self.spy_curve,
            self.initial_nav,
            self.portfolio.trades,
        )
        
        metrics["arm"] = arm_name
        metrics["benchmark"] = self.benchmark_ticker
        
        with open(output_dir / f"summary_{arm_name}.json", "w") as f:
            json.dump(metrics, f, indent=2)
        
        logger.info("Results saved", output_dir=str(output_dir), arm=arm_name)
