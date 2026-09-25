"""Market regime detection for wheel strategy.

Regimes determine when to harvest VRP vs hold delta vs go defensive.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional
import structlog

from .iv_provider import IVProvider

logger = structlog.get_logger()


class RegimeState(Enum):
    """Market regime states for wheel strategy."""
    
    HARVEST_VRP = "harvest_vrp"
    """
    Harvest volatility risk premium (default wheel behavior).
    Conditions: VRP > 20%, IV rank > 40%
    Policy: Write CC/CSP at target strikes, 70% wheel / 30% directional
    """
    
    HOLD_DELTA = "hold_delta"
    """
    Preserve equity beta (melt-up / low VRP regime).
    Conditions: VRP < 10% OR (VRP < 20% AND equity uptrend)
    Policy: Skip CC writes or widen strikes to 15-20% OTM, boost directional to 50-60%
    Goal: Earn equity gains when overwriting would cap upside
    """
    
    DEFENSIVE = "defensive"
    """
    Reduce risk (crash / high realized vol regime).
    Conditions: Realized vol spike (21d RV > 40%) OR VRP inversion (< -10%)
    Policy: Reduce new risk, raise cash to 30-40%, BTC ITM options
    Goal: Preserve capital, reduce drawdown
    """


@dataclass
class RegimeConfig:
    """Configuration for regime detection."""
    
    enabled: bool = False
    """Enable regime detection (default: False for backward compatibility)"""
    
    # HARVEST_VRP thresholds
    harvest_min_vrp: float = 0.20
    """VRP > 20% → enter HARVEST_VRP"""
    
    harvest_min_iv_rank: float = 0.40
    """IV rank > 40% → favor HARVEST_VRP"""
    
    # HOLD_DELTA thresholds
    hold_max_vrp: float = 0.10
    """VRP < 10% → enter HOLD_DELTA"""
    
    hold_vrp_trend_threshold: float = 0.20
    """If VRP < 20% AND equity uptrend, enter HOLD_DELTA"""
    
    # DEFENSIVE thresholds
    defensive_rv_spike: float = 0.40
    """Realized vol > 40% → enter DEFENSIVE"""
    
    defensive_vrp_inversion: float = -0.10
    """VRP < -10% (IV < RV) → enter DEFENSIVE"""
    
    # Hysteresis
    min_days_in_regime: int = 3
    """Require 3+ days to switch regimes (avoid whipsaw)"""


class RegimeDetector:
    """
    Detect market regime for adaptive wheel strategy.
    
    Regimes:
    - HARVEST_VRP: Rich IV → write options aggressively
    - HOLD_DELTA: Cheap IV or melt-up → skip/thin CC writes, hold shares
    - DEFENSIVE: Crash or vol spike → reduce risk, raise cash
    
    State transitions use hysteresis (require N days confirmation).
    """
    
    def __init__(
        self,
        config: RegimeConfig,
        iv_provider: IVProvider,
    ):
        self.config = config
        self.iv_provider = iv_provider
        
        # Current state
        self.current_regime = RegimeState.HARVEST_VRP  # Start in harvest mode
        self.days_in_current_regime = 0
        self.pending_regime: Optional[RegimeState] = None
        self.pending_days = 0
        
        # Stats
        self.regime_history: list[tuple[date, RegimeState]] = []
        self.days_in_harvest = 0
        self.days_in_hold = 0
        self.days_in_defensive = 0
        
        if config.enabled:
            logger.info(
                "RegimeDetector enabled",
                harvest_min_vrp=config.harvest_min_vrp,
                hold_max_vrp=config.hold_max_vrp,
                defensive_rv_spike=config.defensive_rv_spike,
            )
        else:
            logger.info("RegimeDetector disabled (always HARVEST_VRP)")
    
    def update(
        self,
        trade_date: date,
        vrp_avg: Optional[float],  # Average VRP across universe
        rv_avg: Optional[float],  # Average realized vol across universe
        iv_rank_avg: Optional[float] = None,
        equity_trend: Optional[str] = None,  # "up", "down", "neutral"
    ) -> RegimeState:
        """
        Update regime state based on current market conditions.
        
        Args:
            trade_date: Current date
            vrp_avg: Average VRP (IV-RV spread) across universe
            rv_avg: Average realized vol across universe
            iv_rank_avg: Average IV rank (optional)
            equity_trend: Equity trend signal (optional)
        
        Returns:
            Current regime state
        """
        if not self.config.enabled:
            return RegimeState.HARVEST_VRP
        
        # Determine target regime based on conditions
        target_regime = self._determine_target_regime(
            vrp_avg, rv_avg, iv_rank_avg, equity_trend
        )
        
        # If target = current, reset pending and stay
        if target_regime == self.current_regime:
            self.pending_regime = None
            self.pending_days = 0
            self.days_in_current_regime += 1
        
        # If target != current, track pending days
        elif target_regime != self.current_regime:
            if self.pending_regime == target_regime:
                # Same pending target, increment counter
                self.pending_days += 1
            else:
                # New pending target, reset counter
                self.pending_regime = target_regime
                self.pending_days = 1
            
            # Switch if pending threshold met
            if self.pending_days >= self.config.min_days_in_regime:
                logger.info(
                    "Regime transition",
                    from_regime=self.current_regime.value,
                    to_regime=target_regime.value,
                    date=trade_date,
                    vrp=vrp_avg,
                    rv=rv_avg,
                )
                self.current_regime = target_regime
                self.days_in_current_regime = self.pending_days
                self.pending_regime = None
                self.pending_days = 0
                self.regime_history.append((trade_date, target_regime))
            else:
                # Still pending
                self.days_in_current_regime += 1
        
        # Track stats
        if self.current_regime == RegimeState.HARVEST_VRP:
            self.days_in_harvest += 1
        elif self.current_regime == RegimeState.HOLD_DELTA:
            self.days_in_hold += 1
        elif self.current_regime == RegimeState.DEFENSIVE:
            self.days_in_defensive += 1
        
        return self.current_regime
    
    def _determine_target_regime(
        self,
        vrp_avg: Optional[float],
        rv_avg: Optional[float],
        iv_rank_avg: Optional[float],
        equity_trend: Optional[str],
    ) -> RegimeState:
        """Determine target regime based on conditions."""
        
        # Default to HARVEST if missing data
        if vrp_avg is None or rv_avg is None:
            return RegimeState.HARVEST_VRP
        
        # DEFENSIVE: Realized vol spike OR VRP inversion
        if rv_avg > self.config.defensive_rv_spike:
            return RegimeState.DEFENSIVE
        
        if vrp_avg < self.config.defensive_vrp_inversion:
            return RegimeState.DEFENSIVE
        
        # HOLD_DELTA: Low VRP (< 10%) OR (moderate VRP + uptrend)
        if vrp_avg < self.config.hold_max_vrp:
            return RegimeState.HOLD_DELTA
        
        if (
            vrp_avg < self.config.hold_vrp_trend_threshold
            and equity_trend == "up"
        ):
            return RegimeState.HOLD_DELTA
        
        # HARVEST_VRP: Rich VRP (> 20%) AND decent IV rank
        if vrp_avg >= self.config.harvest_min_vrp:
            if iv_rank_avg is None or iv_rank_avg >= self.config.harvest_min_iv_rank:
                return RegimeState.HARVEST_VRP
        
        # Default to current regime if ambiguous (avoid flip-flop)
        return self.current_regime
    
    def get_current_regime(self) -> RegimeState:
        """Get current regime state."""
        return self.current_regime
    
    def should_write_cc(self) -> bool:
        """
        Check if covered calls should be written in current regime.
        
        Returns:
            True if CC writes allowed, False if should skip/thin
        """
        if not self.config.enabled:
            return True  # Always allow when disabled
        
        # HARVEST: Write CC aggressively
        if self.current_regime == RegimeState.HARVEST_VRP:
            return True
        
        # HOLD_DELTA: Skip or thin CC writes (preserve delta)
        if self.current_regime == RegimeState.HOLD_DELTA:
            return False  # Engine should skip or widen strikes
        
        # DEFENSIVE: Thin or stop CC writes
        if self.current_regime == RegimeState.DEFENSIVE:
            return False  # Reduce new risk
        
        return True
    
    def get_stats(self) -> dict:
        """Get regime statistics for reporting."""
        return {
            "current_regime": self.current_regime.value,
            "days_in_regime": self.days_in_current_regime,
            "days_in_harvest": self.days_in_harvest,
            "days_in_hold": self.days_in_hold,
            "days_in_defensive": self.days_in_defensive,
            "regime_transitions": len(self.regime_history),
            "regime_enabled": self.config.enabled,
        }
