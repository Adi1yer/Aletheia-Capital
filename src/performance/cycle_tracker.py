"""Track agent performance between trading cycles"""

from typing import Dict, List, Optional
from datetime import datetime
from src.agents.base import AgentSignal
from src.performance.tracker import PerformanceTracker
import structlog
import json
import os

logger = structlog.get_logger()


class CyclePerformanceTracker:
    """Tracks agent performance between trading cycles"""
    
    def __init__(self, data_dir: str = "data/performance"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.performance_tracker = PerformanceTracker(data_dir)
        self._previous_prices_file = os.path.join(data_dir, "previous_prices.json")
        self._previous_signals_file = os.path.join(data_dir, "previous_signals.json")
        logger.info("Initialized cycle performance tracker")
    
    def record_cycle(
        self,
        agent_signals: Dict[str, Dict[str, AgentSignal]],
        decisions: Dict[str, any],
        current_prices: Dict[str, float],
        date: str,
    ):
        """
        Record a trading cycle and calculate returns from previous cycle
        
        Args:
            agent_signals: Current agent signals
            decisions: Current trading decisions
            current_prices: Current prices
            date: Current date
        """
        # Load previous cycle data
        previous_prices = self._load_previous_prices()
        previous_signals = self._load_previous_signals()
        
        # Calculate returns for each agent if we have previous data
        if previous_prices and previous_signals:
            logger.info("Calculating agent returns from previous cycle")
            
            for agent_key, current_signals in agent_signals.items():
                if agent_key not in previous_signals:
                    continue
                
                prev_signals = previous_signals[agent_key]
                total_return = 0.0
                signal_count = 0
                
                for ticker, current_signal in current_signals.items():
                    if ticker not in prev_signals or ticker not in current_prices or ticker not in previous_prices:
                        continue
                    
                    prev_signal = prev_signals[ticker]
                    current_price = current_prices[ticker]
                    previous_price = previous_prices.get(ticker)
                    
                    if previous_price and previous_price > 0:
                        # Calculate price return
                        price_return_pct = ((current_price - previous_price) / previous_price) * 100
                        
                        # Calculate agent's contribution based on signal
                        # If agent was bullish and price went up, positive contribution
                        # If agent was bearish and price went down, positive contribution
                        if prev_signal.signal == "bullish" and price_return_pct > 0:
                            contribution = price_return_pct * (prev_signal.confidence / 100.0)
                            total_return += contribution
                            signal_count += 1
                        elif prev_signal.signal == "bearish" and price_return_pct < 0:
                            contribution = abs(price_return_pct) * (prev_signal.confidence / 100.0)
                            total_return += contribution
                            signal_count += 1
                        elif prev_signal.signal == "bullish" and price_return_pct < 0:
                            # Wrong direction - negative contribution
                            contribution = price_return_pct * (prev_signal.confidence / 100.0)
                            total_return += contribution
                            signal_count += 1
                        elif prev_signal.signal == "bearish" and price_return_pct > 0:
                            # Wrong direction - negative contribution
                            contribution = -price_return_pct * (prev_signal.confidence / 100.0)
                            total_return += contribution
                            signal_count += 1
                
                # Record performance
                if signal_count > 0:
                    avg_return = total_return / signal_count
                    self.performance_tracker.record_trade(
                        agent_key=agent_key,
                        ticker="portfolio",  # Aggregate across all tickers
                        action="cycle",
                        quantity=signal_count,
                        entry_price=0.0,
                        entry_date=date,
                        return_pct=avg_return,
                    )
                    logger.info(
                        "Recorded agent performance",
                        agent=agent_key,
                        avg_return_pct=avg_return,
                        signal_count=signal_count,
                    )
        
        # Save current cycle data for next cycle
        self._save_previous_prices(current_prices)
        self._save_previous_signals(agent_signals)
    
    def _load_previous_prices(self) -> Dict[str, float]:
        """Load previous cycle prices"""
        if os.path.exists(self._previous_prices_file):
            try:
                with open(self._previous_prices_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.debug("Error loading previous prices", error=str(e))
        return {}
    
    def _save_previous_prices(self, prices: Dict[str, float]):
        """Save current prices for next cycle"""
        try:
            with open(self._previous_prices_file, 'w') as f:
                json.dump(prices, f, indent=2)
        except Exception as e:
            logger.error("Error saving previous prices", error=str(e))
    
    def _load_previous_signals(self) -> Dict[str, Dict[str, AgentSignal]]:
        """Load previous cycle signals"""
        if os.path.exists(self._previous_signals_file):
            try:
                with open(self._previous_signals_file, 'r') as f:
                    data = json.load(f)
                    # Convert back to AgentSignal objects
                    result = {}
                    for agent_key, ticker_signals in data.items():
                        result[agent_key] = {}
                        for ticker, signal_data in ticker_signals.items():
                            # Reconstruct AgentSignal from dict
                            result[agent_key][ticker] = AgentSignal(
                                signal=signal_data.get('signal', 'neutral'),
                                confidence=signal_data.get('confidence', 50),
                                reasoning=signal_data.get('reasoning', ''),
                            )
                    return result
            except Exception as e:
                logger.debug("Error loading previous signals", error=str(e))
        return {}
    
    def _save_previous_signals(self, agent_signals: Dict[str, Dict[str, AgentSignal]]):
        """Save current signals for next cycle"""
        try:
            data = {}
            for agent_key, ticker_signals in agent_signals.items():
                data[agent_key] = {}
                for ticker, signal in ticker_signals.items():
                    data[agent_key][ticker] = {
                        'signal': signal.signal,
                        'confidence': signal.confidence,
                        'reasoning': signal.reasoning,
                    }
            
            with open(self._previous_signals_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Error saving previous signals", error=str(e))

