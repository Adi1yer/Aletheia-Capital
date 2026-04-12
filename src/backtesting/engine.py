"""Backtesting engine for trading strategies"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel
from src.trading.pipeline import TradingPipeline
from src.agents.initialize import initialize_agents
from src.data.providers.aggregator import get_data_provider
from src.portfolio.models import Portfolio
from src.performance.tracker import PerformanceTracker
import structlog
import pandas as pd

logger = structlog.get_logger()


class BacktestResult(BaseModel):
    """Backtest results"""
    start_date: str
    end_date: str
    initial_cash: float
    final_value: float
    total_return_pct: float
    sharpe_ratio: Optional[float] = None
    max_drawdown: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    agent_performance: Dict[str, Dict] = {}
    daily_returns: List[float] = []
    equity_curve: List[Dict] = []


class BacktestingEngine:
    """Backtesting engine for trading strategies"""
    
    def __init__(self):
        self.data_provider = get_data_provider()
        self.performance_tracker = PerformanceTracker()
        logger.info("Initialized backtesting engine")
    
    def run_backtest(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        initial_cash: float = 100000.0,
        rebalance_frequency: str = "weekly",
    ) -> BacktestResult:
        """
        Run backtest on historical data
        
        Args:
            tickers: List of tickers to backtest
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            initial_cash: Starting cash
            rebalance_frequency: How often to rebalance (weekly, daily)
        
        Returns:
            BacktestResult with performance metrics
        """
        logger.info(
            "Starting backtest",
            tickers=len(tickers),
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
        )
        
        # Initialize portfolio
        portfolio = Portfolio(cash=initial_cash)
        
        # Parse dates
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        
        # Determine rebalance dates
        if rebalance_frequency == "weekly":
            delta = timedelta(weeks=1)
        else:
            delta = timedelta(days=1)
        
        current_date = start
        equity_curve = []
        daily_returns = []
        previous_equity = initial_cash
        
        # Track prices for performance calculation
        previous_prices = {}
        current_prices = {}
        
        # Initialize agents
        initialize_agents()
        pipeline = TradingPipeline()
        
        # Run backtest
        while current_date <= end:
            date_str = current_date.strftime("%Y-%m-%d")
            logger.info("Backtesting date", date=date_str)
            
            # Get current prices
            for ticker in tickers:
                try:
                    prices = self.data_provider.get_prices(
                        ticker,
                        (current_date - timedelta(days=5)).strftime("%Y-%m-%d"),
                        date_str,
                    )
                    if prices:
                        current_prices[ticker] = prices[-1].close
                except Exception as e:
                    logger.debug("Error fetching price", ticker=ticker, error=str(e))
                    continue
            
            # Calculate current equity
            current_equity = portfolio.get_equity(current_prices)
            equity_curve.append({
                'date': date_str,
                'equity': current_equity,
                'cash': portfolio.cash,
            })
            
            # Calculate daily return
            if previous_equity > 0:
                daily_return = ((current_equity - previous_equity) / previous_equity) * 100
                daily_returns.append(daily_return)
            
            previous_equity = current_equity
            
            # Rebalance if it's time
            if current_date == start or (current_date - start).days % 7 == 0:
                logger.info("Rebalancing portfolio", date=date_str)
                
                # Run trading pipeline for this date
                try:
                    # Calculate date range for analysis (3 months back)
                    analysis_start = (current_date - relativedelta(months=3)).strftime("%Y-%m-%d")
                    analysis_end = date_str
                    
                    # Refresh data
                    pipeline._refresh_data(tickers, analysis_start, analysis_end)
                    
                    # Run agents
                    agent_signals = pipeline._run_agents(tickers, analysis_start, analysis_end)
                    
                    # Calculate risk limits
                    risk_analysis = pipeline.risk_manager.calculate_position_limits(
                        tickers, portfolio, analysis_start, analysis_end
                    )
                    
                    # Get agent weights (use current weights)
                    from src.agents.registry import get_registry
                    registry = get_registry()
                    agent_weights = registry.get_weights()
                    
                    # Generate decisions
                    decisions = pipeline.portfolio_manager.generate_decisions(
                        tickers=tickers,
                        agent_signals=agent_signals,
                        risk_analysis=risk_analysis,
                        portfolio=portfolio,
                        agent_weights=agent_weights,
                    )
                    
                    # Execute trades (simulated)
                    self._execute_trades_simulated(portfolio, decisions, current_prices, date_str)
                    
                    # Track agent performance
                    if previous_prices:
                        for agent_key, ticker_signals in agent_signals.items():
                            return_pct = self.performance_tracker.calculate_agent_returns(
                                agent_key,
                                ticker_signals,
                                {t: d.model_dump() for t, d in decisions.items()},
                                current_prices,
                                previous_prices,
                            )
                            # Record performance
                            if agent_key not in self.performance_tracker._performance:
                                from src.performance.tracker import AgentPerformance
                                self.performance_tracker._performance[agent_key] = AgentPerformance(agent_key=agent_key)
                            
                            perf = self.performance_tracker._performance[agent_key]
                            perf.total_trades += 1
                            perf.total_return_pct += return_pct
                            if perf.total_trades > 0:
                                perf.average_return_pct = perf.total_return_pct / perf.total_trades
                    
                    previous_prices = current_prices.copy()
                    
                except Exception as e:
                    logger.error("Error during backtest rebalance", date=date_str, error=str(e))
                    continue
            
            # Move to next date
            current_date += delta
        
        # Calculate final metrics
        final_value = portfolio.get_equity(current_prices) if current_prices else portfolio.cash
        total_return_pct = ((final_value - initial_cash) / initial_cash * 100) if initial_cash > 0 else 0.0
        
        # Calculate Sharpe ratio
        sharpe_ratio = None
        if daily_returns and len(daily_returns) > 1:
            returns_series = pd.Series(daily_returns)
            if returns_series.std() > 0:
                sharpe_ratio = (returns_series.mean() / returns_series.std()) * (252 ** 0.5)  # Annualized
        
        # Calculate max drawdown
        max_drawdown = 0.0
        if equity_curve:
            peak = initial_cash
            for point in equity_curve:
                equity = point['equity']
                if equity > peak:
                    peak = equity
                drawdown = ((equity - peak) / peak * 100) if peak > 0 else 0
                if drawdown < max_drawdown:
                    max_drawdown = drawdown
        
        # Get agent performance
        agent_performance = {}
        for agent_key, perf in self.performance_tracker.get_all_performance().items():
            agent_performance[agent_key] = {
                'average_return_pct': perf.average_return_pct,
                'total_trades': perf.total_trades,
                'winning_trades': perf.winning_trades,
                'losing_trades': perf.losing_trades,
            }
        
        result = BacktestResult(
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            final_value=final_value,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            total_trades=sum(p.total_trades for p in self.performance_tracker.get_all_performance().values()),
            winning_trades=sum(p.winning_trades for p in self.performance_tracker.get_all_performance().values()),
            losing_trades=sum(p.losing_trades for p in self.performance_tracker.get_all_performance().values()),
            agent_performance=agent_performance,
            daily_returns=daily_returns,
            equity_curve=equity_curve,
        )
        
        logger.info(
            "Backtest complete",
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
        )
        
        return result
    
    def _execute_trades_simulated(
        self,
        portfolio: Portfolio,
        decisions: Dict[str, any],
        current_prices: Dict[str, float],
        date: str,
    ):
        """Execute trades in simulation (backtest)"""
        for ticker, decision in decisions.items():
            if ticker not in current_prices or current_prices[ticker] <= 0:
                continue
            
            price = current_prices[ticker]
            action = decision.action if hasattr(decision, 'action') else decision.get('action')
            quantity = decision.quantity if hasattr(decision, 'quantity') else decision.get('quantity', 0)
            
            if quantity == 0 or action == "hold":
                continue
            
            position = portfolio.get_position(ticker)
            
            if action == "buy":
                cost = quantity * price
                if portfolio.cash >= cost:
                    portfolio.cash -= cost
                    position.long += quantity
                    position.long_cost_basis = ((position.long_cost_basis * (position.long - quantity)) + cost) / position.long if position.long > 0 else price
            
            elif action == "sell":
                if position.long >= quantity:
                    proceeds = quantity * price
                    portfolio.cash += proceeds
                    position.long -= quantity
            
            elif action == "short":
                # Simplified short simulation
                proceeds = quantity * price
                portfolio.cash += proceeds
                position.short += quantity
                position.short_cost_basis = price
                position.short_margin_used += proceeds * 0.5  # 50% margin requirement
            
            elif action == "cover":
                if position.short >= quantity:
                    cost = quantity * price
                    if portfolio.cash >= cost:
                        portfolio.cash -= cost
                        position.short -= quantity
                        # Calculate P&L
                        pnl = (position.short_cost_basis - price) * quantity
                        portfolio.cash += pnl  # Simplified

