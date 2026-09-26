"""Growth quality backtest engine - concentrated liquid quality/growth equity."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.backtesting.growth_quality.portfolio import GrowthQualityPortfolio

logger = structlog.get_logger()


class GrowthQualityBacktest:
    """
    Simulate concentrated quality/growth long-only strategy.
    
    Supports multiple arms:
    - Arm A: QQQ buy-and-hold (Nasdaq-100 ETF)
    - Arm B: Equal-weight top N quality names
    - Arm C: Quality-screened large-cap universe
    """
    
    def __init__(
        self,
        start_date: str,
        end_date: str,
        initial_nav: float = 10_000.0,
        rebalance_frequency: str = "quarterly",  # "monthly", "quarterly", "annual", "none"
        top_n: Optional[int] = None,  # For Arm B/C
        trading_cost_pct: float = 0.0005,  # 5 bps round-trip
        benchmark_ticker: str = "^SPXTR",  # SPY total return
        universe_mode: str = "fixed",  # "fixed" or "point_in_time"
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.initial_nav = initial_nav
        self.rebalance_frequency = rebalance_frequency
        self.top_n = top_n
        self.trading_cost_pct = trading_cost_pct
        self.benchmark_ticker = benchmark_ticker
        self.universe_mode = universe_mode  # NEW: support point-in-time selection
        
        self.portfolio = GrowthQualityPortfolio(initial_nav)
        self.equity_curve: List[Tuple[str, float]] = []
        self.spy_curve: List[Tuple[str, float]] = []
        
        # Historical price cache: {ticker: [(date, close), ...]}
        self.price_history: Dict[str, List[Tuple[date, float]]] = {}
        
        # Track rebalance dates
        self.last_rebalance_date: Optional[date] = None
    
    def load_price_history(self, ticker: str, data_provider, cache=None):
        """Load historical prices for a ticker."""
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
        # Always rebalance on first call (initial allocation)
        if self.last_rebalance_date is None:
            return True
        
        # After initial allocation, "none" means buy-and-hold (no more rebalances)
        if self.rebalance_frequency == "none":
            return False
        
        if self.rebalance_frequency == "monthly":
            # Rebalance on first trading day of each month
            return trade_date.month != self.last_rebalance_date.month
        
        elif self.rebalance_frequency == "quarterly":
            # Rebalance quarterly (Jan, Apr, Jul, Oct)
            rebal_months = [1, 4, 7, 10]
            return (
                trade_date.month in rebal_months
                and (
                    self.last_rebalance_date.month not in rebal_months
                    or (trade_date.month != self.last_rebalance_date.month)
                )
            )
        
        elif self.rebalance_frequency == "annual":
            # Rebalance annually (January)
            return trade_date.month == 1 and self.last_rebalance_date.month != 1
        
        return False
    
    def run(
        self,
        universe: List[str],
        data_provider,
        arm_name: str = "generic",
        arm_type: str = "fixed",  # "fixed", "point_in_time_quality"
        cache=None,
    ) -> Dict:
        """
        Run backtest simulation.
        
        Args:
            universe: List of tickers (for fixed arms) or initial universe (for point-in-time)
            data_provider: Data provider with get_prices() method.
            arm_name: Name of strategy arm for logging.
            arm_type: Type of arm ("fixed", "point_in_time_quality")
        
        Returns:
            Summary dict with metrics and paths.
        """
        logger.info(
            "Starting growth/quality backtest",
            start=self.start_date,
            end=self.end_date,
            nav=self.initial_nav,
            universe=universe if arm_type == "fixed" else f"point-in-time (initial: {len(universe)} names)",
            arm=arm_name,
            rebalance=self.rebalance_frequency,
            benchmark=self.benchmark_ticker,
        )
        
        self.arm_type = arm_type  # Store for rebalance logic
        
        # Load price history for all tickers + benchmark
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
        
        # Load universe tickers
        for ticker in universe:
            if ticker not in self.price_history:
                self.load_price_history(ticker, data_provider, cache)
        
        # Get trading dates from benchmark
        benchmark_history = self.price_history.get(self.benchmark_ticker, [])
        if not benchmark_history:
            logger.error("Benchmark price history required", ticker=self.benchmark_ticker)
            return {}
        
        trading_dates = [d for d, _ in benchmark_history]
        
        # Initial benchmark level
        spy_start = benchmark_history[0][1]
        self.spy_curve.append((trading_dates[0].isoformat(), spy_start))
        
        # Initial NAV
        self.equity_curve.append((trading_dates[0].isoformat(), self.initial_nav))
        
        # Initial allocation on first day
        first_date = trading_dates[0]
        
        # For point-in-time arms, get universe as of first date
        if self.arm_type == "point_in_time_quality":
            from src.backtesting.growth_quality.universe import get_point_in_time_quality_universe
            universe = get_point_in_time_quality_universe(
                first_date,
                top_n=self.top_n or 30,
                data_provider=data_provider
            )
            logger.info(f"Point-in-time universe on {first_date}: {len(universe)} names")
            # Load prices for new names
            for ticker in universe:
                if ticker not in self.price_history:
                    self.load_price_history(ticker, data_provider)
        
        self._rebalance(first_date, universe)
        self.last_rebalance_date = first_date
        
        # Daily loop
        for i, trade_date in enumerate(trading_dates[1:], start=1):
            # Check if rebalance needed
            if self.should_rebalance(trade_date):
                # For point-in-time arms, refresh universe as of this date
                if self.arm_type == "point_in_time_quality":
                    from src.backtesting.growth_quality.universe import get_point_in_time_quality_universe
                    universe = get_point_in_time_quality_universe(
                        trade_date,
                        top_n=self.top_n or 30,
                        data_provider=data_provider
                    )
                logger.info(f"Point-in-time universe on {trade_date}: {len(universe)} names")
                # Load prices for any new names
                for ticker in universe:
                    if ticker not in self.price_history:
                        self.load_price_history(ticker, data_provider, cache)
                
                self._rebalance(trade_date, universe)
                self.last_rebalance_date = trade_date
            
            # Record NAV
            prices = {t: self.get_price_on_date(t, trade_date) or 0.0 for t in universe}
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
                "rebalance_frequency": self.rebalance_frequency,
                "top_n": self.top_n,
                "trading_cost_pct": self.trading_cost_pct,
                "universe": universe,
            },
        }
    
    def _rebalance(self, trade_date: date, universe: List[str]):
        """Rebalance portfolio to equal weight across universe."""
        prices = {}
        for ticker in universe:
            price = self.get_price_on_date(ticker, trade_date)
            if price is not None and price > 0:
                prices[ticker] = price
        
        if not prices:
            logger.warning("No valid prices for rebalance", date=trade_date)
            return
        
        # Equal weight across all tickers with valid prices
        n = len(prices)
        target_weight = 1.0 / n
        target_weights = {ticker: target_weight for ticker in prices}
        
        logger.info("Rebalancing", date=trade_date, tickers=list(prices.keys()), weight=target_weight)
        
        self.portfolio.rebalance_to_target_weights(
            target_weights,
            prices,
            trade_date,
            trading_cost_pct=self.trading_cost_pct,
        )
    
    def save_results(self, output_dir: Path, arm_name: str = "generic"):
        """Save equity curve, trades, and summary to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Equity curve
        with open(output_dir / f"equity_curve_{arm_name}.csv", "w") as f:
            f.write("date,nav,spy\n")
            for (date_str, nav), (_, spy_level) in zip(self.equity_curve, self.spy_curve):
                f.write(f"{date_str},{nav},{spy_level}\n")
        
        # Trades
        with open(output_dir / f"trades_{arm_name}.csv", "w") as f:
            if self.portfolio.trades:
                keys = set()
                for t in self.portfolio.trades:
                    keys.update(t.keys())
                
                header = sorted(keys)
                f.write(",".join(header) + "\n")
                
                for t in self.portfolio.trades:
                    row = [str(t.get(k, "")) for k in header]
                    f.write(",".join(row) + "\n")
        
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
        
        # Assumptions
        assumptions = {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_nav": self.initial_nav,
            "arm": arm_name,
            "rebalance_frequency": self.rebalance_frequency,
            "top_n": self.top_n,
            "trading_cost_pct": self.trading_cost_pct,
            "benchmark": self.benchmark_ticker,
        }
        
        with open(output_dir / f"assumptions_{arm_name}.json", "w") as f:
            json.dump(assumptions, f, indent=2)
        
        logger.info("Results saved", output_dir=str(output_dir), arm=arm_name)
