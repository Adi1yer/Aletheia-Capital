"""Agent performance tracking system"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import math
from pydantic import BaseModel
from src.agents.base import AgentSignal
import structlog
import json
import os

logger = structlog.get_logger()


class AgentPerformance(BaseModel):
    """Performance metrics for an agent"""
    agent_key: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_return_pct: float = 0.0
    average_return_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    max_drawdown: float = 0.0
    last_updated: Optional[datetime] = None
    trade_history: List[Dict] = []


class PerformanceTracker:
    """Tracks agent performance and calculates returns"""
    
    def __init__(self, data_dir: str = "data/performance"):
        """
        Initialize performance tracker
        
        Args:
            data_dir: Directory to store performance data
        """
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._performance: Dict[str, AgentPerformance] = {}
        self._load_performance()
        logger.info("Initialized performance tracker", agent_count=len(self._performance))
    
    def record_trade(
        self,
        agent_key: str,
        ticker: str,
        action: str,
        quantity: int,
        entry_price: float,
        entry_date: str,
        exit_price: Optional[float] = None,
        exit_date: Optional[str] = None,
        return_pct: Optional[float] = None,
    ):
        """
        Record a trade for an agent
        
        Args:
            agent_key: Agent identifier
            ticker: Stock ticker
            action: Trade action (buy/sell/short/cover)
            quantity: Number of shares
            entry_price: Entry price
            entry_date: Entry date
            exit_price: Exit price (if closed)
            exit_date: Exit date (if closed)
            return_pct: Return percentage (if closed)
        """
        if agent_key not in self._performance:
            self._performance[agent_key] = AgentPerformance(agent_key=agent_key)
        
        perf = self._performance[agent_key]
        
        trade = {
            'ticker': ticker,
            'action': action,
            'quantity': quantity,
            'entry_price': entry_price,
            'entry_date': entry_date,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'return_pct': return_pct,
            'timestamp': datetime.now().isoformat(),
        }
        
        perf.trade_history.append(trade)
        
        # Update metrics if trade is closed
        if return_pct is not None:
            perf.total_trades += 1
            perf.total_return_pct += return_pct
            
            if return_pct > 0:
                perf.winning_trades += 1
            elif return_pct < 0:
                perf.losing_trades += 1
            
            # Update average
            if perf.total_trades > 0:
                perf.average_return_pct = perf.total_return_pct / perf.total_trades
            
            # Update max drawdown
            if return_pct < perf.max_drawdown:
                perf.max_drawdown = return_pct
        
        perf.last_updated = datetime.now()
        self._save_performance()
    
    def calculate_agent_returns(
        self,
        agent_key: str,
        agent_signals: Dict[str, AgentSignal],
        decisions: Dict[str, Dict],
        current_prices: Dict[str, float],
        previous_prices: Dict[str, float],
    ) -> float:
        """
        Calculate agent's contribution to returns based on signals
        
        Args:
            agent_key: Agent identifier
            agent_signals: Signals from this agent
            decisions: Trading decisions made
            current_prices: Current prices
            previous_prices: Previous period prices
        
        Returns:
            Total return percentage for this agent
        """
        total_return = 0.0
        total_weight = 0.0
        
        for ticker, signal in agent_signals.items():
            if ticker not in decisions or ticker not in current_prices or ticker not in previous_prices:
                continue
            
            decision = decisions[ticker]
            current_price = current_prices[ticker]
            previous_price = previous_prices[ticker]
            
            # Calculate price change
            price_change_pct = ((current_price - previous_price) / previous_price * 100) if previous_price > 0 else 0
            
            # Agent's contribution based on signal alignment
            if decision['action'] in ['buy', 'cover']:
                # Agent was bullish - positive return if price went up
                if signal.signal == "bullish":
                    contribution = price_change_pct * (signal.confidence / 100.0)
                    total_return += contribution
                    total_weight += signal.confidence / 100.0
                elif signal.signal == "bearish":
                    # Agent was bearish but we bought - negative contribution
                    contribution = -price_change_pct * (signal.confidence / 100.0)
                    total_return += contribution
                    total_weight += signal.confidence / 100.0
            elif decision['action'] in ['sell', 'short']:
                # Agent was bearish - positive return if price went down
                if signal.signal == "bearish":
                    contribution = -price_change_pct * (signal.confidence / 100.0)
                    total_return += contribution
                    total_weight += signal.confidence / 100.0
                elif signal.signal == "bullish":
                    # Agent was bullish but we sold - negative contribution
                    contribution = price_change_pct * (signal.confidence / 100.0)
                    total_return += contribution
                    total_weight += signal.confidence / 100.0
        
        # Normalize by total weight
        if total_weight > 0:
            return total_return / total_weight
        
        return 0.0
    
    def get_performance(self, agent_key: str) -> Optional[AgentPerformance]:
        """Get performance for an agent"""
        return self._performance.get(agent_key)
    
    def get_all_performance(self) -> Dict[str, AgentPerformance]:
        """Get performance for all agents"""
        return self._performance.copy()
    
    def load_from_scan_cache(
        self,
        scan_cache: Any,
        limit: int = 5,
    ) -> int:
        """
        Load performance data from scan cache (consecutive run pairs).
        Computes agent hit rate and avg return from signals vs subsequent price changes.

        Returns:
            Number of agent-ticker observations added.
        """
        try:
            runs = scan_cache.list_runs(limit=limit + 1)
            if len(runs) < 2:
                return 0

            # Process most recent pair only to avoid duplicate counts across runs
            runs = sorted(runs, key=lambda r: r["run_date"])[-2:]
            added = 0
            for i in range(len(runs) - 1):
                curr_id, next_id = runs[i]["run_id"], runs[i + 1]["run_id"]
                try:
                    curr = scan_cache.load_run(curr_id)
                    next_run = scan_cache.load_run(next_id)
                except Exception as e:
                    logger.debug("Could not load scan cache runs", error=str(e))
                    continue

                signals = curr.get("signals") or {}
                curr_risk = curr.get("risk") or {}
                next_risk = next_run.get("risk") or {}

                curr_prices = {
                    t: float(r.get("current_price", 0) or 0)
                    for t, r in curr_risk.items()
                    if isinstance(r, dict)
                }
                next_prices = {
                    t: float(r.get("current_price", 0) or 0)
                    for t, r in next_risk.items()
                    if isinstance(r, dict)
                }

                common = set(curr_prices) & set(next_prices)
                if not common:
                    continue

                for agent_key, ticker_signals in signals.items():
                    if agent_key not in self._performance:
                        self._performance[agent_key] = AgentPerformance(agent_key=agent_key)

                    for ticker, sig in ticker_signals.items():
                        if ticker not in common:
                            continue
                        if not isinstance(sig, dict):
                            continue
                        prev_price = curr_prices.get(ticker) or 0
                        next_price = next_prices.get(ticker) or 0
                        if prev_price <= 0:
                            continue
                        ret_pct = ((next_price - prev_price) / prev_price) * 100

                        sig_val = sig.get("signal")
                        conf = int(sig.get("confidence", 50))
                        weight = conf / 100.0

                        if sig_val == "bullish":
                            contrib = ret_pct * weight if ret_pct > 0 else -abs(ret_pct) * weight
                        elif sig_val == "bearish":
                            contrib = (-ret_pct) * weight if ret_pct < 0 else -abs(ret_pct) * weight
                        else:
                            contrib = 0.0

                        self._performance[agent_key].trade_history.append({
                            "ticker": ticker,
                            "action": "scan_cache",
                            "quantity": 1,
                            "entry_price": prev_price,
                            "entry_date": runs[i]["run_date"],
                            "exit_price": next_price,
                            "exit_date": runs[i + 1]["run_date"],
                            "return_pct": contrib,
                            "timestamp": datetime.now().isoformat(),
                        })
                        self._performance[agent_key].total_trades += 1
                        self._performance[agent_key].total_return_pct += contrib
                        if contrib > 0:
                            self._performance[agent_key].winning_trades += 1
                        elif contrib < 0:
                            self._performance[agent_key].losing_trades += 1
                        if self._performance[agent_key].total_trades > 0:
                            self._performance[agent_key].average_return_pct = (
                                self._performance[agent_key].total_return_pct
                                / self._performance[agent_key].total_trades
                            )
                        self._performance[agent_key].last_updated = datetime.now()
                        added += 1

            if added > 0:
                self._save_performance()
                logger.info("Loaded performance from scan cache", observations=added)
            return added
        except Exception as e:
            logger.warning("Could not load from scan cache", error=str(e))
            return 0

    def _decay_weighted_avg_return(self, agent_key: str, half_life_weeks: float) -> Optional[float]:
        if half_life_weeks <= 0:
            return None
        perf = self._performance.get(agent_key)
        if not perf or not perf.trade_history:
            return None
        now = datetime.utcnow()
        num = 0.0
        den = 0.0
        lam = math.log(2) / max(half_life_weeks, 1e-6)
        for tr in perf.trade_history:
            exit_d = tr.get("exit_date") or tr.get("entry_date")
            if not exit_d:
                continue
            try:
                if isinstance(exit_d, str):
                    dt = datetime.strptime(str(exit_d)[:10], "%Y-%m-%d")
                else:
                    dt = exit_d
            except Exception:
                continue
            weeks = max(0.0, (now - dt).days / 7.0)
            w = math.exp(-lam * weeks)
            r = tr.get("return_pct")
            if r is None:
                continue
            num += float(r) * w
            den += w
        if den <= 0:
            return None
        return num / den

    def calculate_weights_from_performance(
        self,
        min_weight: float = 0.1,
        max_weight: float = 3.0,
        smoothing_factor: float = 0.3,
        scorecard_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
        decay_half_life_weeks: float = 0.0,
    ) -> Dict[str, float]:
        """
        Calculate new weights based on agent performance
        
        Args:
            min_weight: Minimum weight (default: 0.1)
            max_weight: Maximum weight (default: 3.0)
            smoothing_factor: How much to adjust weights (0.0 = no change, 1.0 = full adjustment)
            scorecard_metrics: Optional per-agent rows from agent scorecard (accuracy, cw return).
            decay_half_life_weeks: If >0, weight recent trade_history returns with exponential decay.
        
        Returns:
            Dictionary mapping agent_key to new weight
        """
        scorecard_metrics = scorecard_metrics or {}

        agent_keys = set(self._performance.keys()) | set(scorecard_metrics.keys())
        if not agent_keys:
            logger.warning("No performance data available, using equal weights")
            return {}

        agent_returns: Dict[str, float] = {}
        for agent_key in agent_keys:
            perf = self._performance.get(agent_key)
            base = 0.0
            if perf and perf.total_trades > 0:
                decayed = self._decay_weighted_avg_return(agent_key, decay_half_life_weeks)
                base = decayed if decayed is not None else perf.average_return_pct
            row = scorecard_metrics.get(agent_key)
            if isinstance(row, dict) and row.get("directional_observations", 0):
                acc = float(row.get("directional_accuracy") or 0)
                cw = float(row.get("confidence_weighted_return_pct") or 0)
                sc_score = acc * 50.0 + cw
                if perf and perf.total_trades > 0:
                    base = 0.5 * base + 0.5 * sc_score
                else:
                    base = sc_score
            agent_returns[agent_key] = base

        if not agent_returns:
            return {}
        
        # Find min and max returns for normalization
        min_return = min(agent_returns.values())
        max_return = max(agent_returns.values())
        return_range = max_return - min_return if max_return != min_return else 1.0
        
        # Calculate new weights
        new_weights = {}
        for agent_key, avg_return in agent_returns.items():
            # Normalize return to 0-1 scale
            if return_range > 0:
                normalized_return = (avg_return - min_return) / return_range
            else:
                normalized_return = 0.5  # Equal if all same
            
            # Map to weight range (better returns = higher weights)
            target_weight = min_weight + (normalized_return * (max_weight - min_weight))
            
            # Get current weight (assume 1.0 if not in performance)
            current_weight = 1.0
            if agent_key in self._performance:
                # Could use previous weight if stored
                pass
            
            # Smooth the adjustment
            new_weight = current_weight + (target_weight - current_weight) * smoothing_factor
            new_weight = max(min_weight, min(max_weight, new_weight))
            
            new_weights[agent_key] = new_weight
        
        logger.info("Calculated new weights from performance", weight_count=len(new_weights))
        return new_weights
    
    def _load_performance(self):
        """Load performance data from disk"""
        perf_file = os.path.join(self.data_dir, "agent_performance.json")
        if os.path.exists(perf_file):
            try:
                with open(perf_file, 'r') as f:
                    data = json.load(f)
                
                for agent_key, perf_data in data.items():
                    # Convert dates
                    if 'last_updated' in perf_data and perf_data['last_updated']:
                        perf_data['last_updated'] = datetime.fromisoformat(perf_data['last_updated'])
                    self._performance[agent_key] = AgentPerformance(**perf_data)
                
                logger.info("Loaded performance data", agent_count=len(self._performance))
            except Exception as e:
                logger.error("Error loading performance data", error=str(e))
    
    def _save_performance(self):
        """Save performance data to disk"""
        perf_file = os.path.join(self.data_dir, "agent_performance.json")
        try:
            data = {}
            for agent_key, perf in self._performance.items():
                perf_dict = perf.model_dump()
                # Convert datetime to string
                if perf_dict.get('last_updated'):
                    perf_dict['last_updated'] = perf.last_updated.isoformat()
                data[agent_key] = perf_dict
            
            with open(perf_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            
            logger.debug("Saved performance data", agent_count=len(self._performance))
        except Exception as e:
            logger.error("Error saving performance data", error=str(e))

