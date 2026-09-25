"""Crisis/risk-off overlay for directional sleeve using SPY SMA200 gate.

Sleeve-level regime detection (NOT name-level momentum):
- Risk-on (SPY > SMA200): Hold SPY or equal-weight bluechip equities
- Risk-off (SPY ≤ SMA200): Park in BIL (cash proxy) or TLT (defensive bonds)

Rebalances monthly at month-end (or with hysteresis) to avoid daily churn.
Wheel sleeve (~70% NAV) remains always-on with no changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()


class CrisisRegime(Enum):
    """Market regime based on SPY vs SMA200."""
    RISK_ON = "risk_on"      # SPY > SMA200: hold risk assets
    RISK_OFF = "risk_off"    # SPY ≤ SMA200: park in defensive


@dataclass
class CrisisOverlayConfig:
    """Configuration for crisis overlay."""
    enabled: bool = False
    
    # Signal parameters
    sma_window: int = 200  # 200-day SMA for trend
    
    # Rebalance frequency
    rebalance_mode: str = "monthly"  # "monthly" or "signal_change"
    
    # Risk-on allocation
    risk_on_asset: str = "SPY"  # "SPY" or "equal_weight_bluechip"
    
    # Risk-off allocation
    risk_off_asset: str = "BIL"  # "BIL" (cash proxy) or "TLT" (bonds)
    
    # Hysteresis (optional, to reduce whipsaw)
    hysteresis_pct: float = 0.0  # e.g., 0.02 = 2% buffer zone


class CrisisOverlay:
    """
    Implements SPY SMA200 crisis overlay for directional sleeve.
    
    Logic:
    - Calculate SPY's 200-day SMA at end of each month
    - Risk-on: SPY close > SMA200 → hold risk_on_asset
    - Risk-off: SPY close ≤ SMA200 → hold risk_off_asset
    - Rebalance monthly (not daily) to minimize turnover
    """
    
    def __init__(self, config: CrisisOverlayConfig):
        self.config = config
        self.current_regime: CrisisRegime = CrisisRegime.RISK_ON
        self.last_rebalance_date: Optional[date] = None
        self.sma_history: List[Tuple[date, float]] = []  # (date, sma_value)
        
        # Stats tracking
        self.regime_changes: int = 0
        self.days_risk_on: int = 0
        self.days_risk_off: int = 0
        self.rebalances: int = 0
    
    def should_rebalance(
        self,
        trade_date: date,
        spy_price: float,
        spy_sma: float,
    ) -> Tuple[bool, CrisisRegime]:
        """
        Determine if we should rebalance and what the new regime is.
        
        Args:
            trade_date: Current trading date.
            spy_price: SPY closing price.
            spy_sma: SPY 200-day SMA.
        
        Returns:
            (should_rebalance, new_regime)
        """
        if not self.config.enabled:
            return (False, CrisisRegime.RISK_ON)
        
        # Determine new regime based on SPY vs SMA
        new_regime = self._calculate_regime(spy_price, spy_sma)
        
        # Check if it's time to rebalance
        if self.config.rebalance_mode == "monthly":
            # Rebalance at month-end (last trading day of month)
            if self.last_rebalance_date is None:
                # First time: rebalance immediately
                return (True, new_regime)
            
            # Check if we're in a new month
            if trade_date.month != self.last_rebalance_date.month or \
               trade_date.year != self.last_rebalance_date.year:
                return (True, new_regime)
            
            return (False, self.current_regime)
        
        elif self.config.rebalance_mode == "signal_change":
            # Rebalance only when regime changes (or first time)
            if self.last_rebalance_date is None:
                # First time: rebalance immediately
                return (True, new_regime)
            
            if new_regime != self.current_regime:
                return (True, new_regime)
            
            return (False, self.current_regime)
        
        return (False, self.current_regime)
    
    def _calculate_regime(self, spy_price: float, spy_sma: float) -> CrisisRegime:
        """
        Calculate regime based on SPY price vs SMA with optional hysteresis.
        
        Hysteresis logic (if enabled):
        - Currently RISK_ON: Need to fall below SMA * (1 - hysteresis) to switch to RISK_OFF
        - Currently RISK_OFF: Need to rise above SMA * (1 + hysteresis) to switch to RISK_ON
        """
        if self.config.hysteresis_pct == 0:
            # Simple threshold: SPY > SMA = risk-on
            return CrisisRegime.RISK_ON if spy_price > spy_sma else CrisisRegime.RISK_OFF
        
        # With hysteresis
        lower_threshold = spy_sma * (1 - self.config.hysteresis_pct)
        upper_threshold = spy_sma * (1 + self.config.hysteresis_pct)
        
        if self.current_regime == CrisisRegime.RISK_ON:
            # Need to fall below lower threshold to switch off
            return CrisisRegime.RISK_OFF if spy_price < lower_threshold else CrisisRegime.RISK_ON
        else:
            # Currently RISK_OFF: need to rise above upper threshold to switch on
            return CrisisRegime.RISK_ON if spy_price > upper_threshold else CrisisRegime.RISK_OFF
    
    def update_regime(self, trade_date: date, new_regime: CrisisRegime):
        """Update current regime and tracking stats."""
        if new_regime != self.current_regime:
            logger.info(
                "Crisis regime change",
                date=trade_date,
                old=self.current_regime.value,
                new=new_regime.value,
            )
            self.regime_changes += 1
        
        self.current_regime = new_regime
        self.last_rebalance_date = trade_date
        self.rebalances += 1
        
        # Update day counters
        if new_regime == CrisisRegime.RISK_ON:
            self.days_risk_on += 1
        else:
            self.days_risk_off += 1
    
    def get_target_allocation(self) -> str:
        """
        Get target asset for directional sleeve based on current regime.
        
        Returns:
            Ticker symbol (e.g., "SPY", "BIL", "TLT")
        """
        if not self.config.enabled:
            return self.config.risk_on_asset
        
        if self.current_regime == CrisisRegime.RISK_ON:
            return self.config.risk_on_asset
        else:
            return self.config.risk_off_asset
    
    def get_stats(self) -> Dict:
        """Return statistics for reporting."""
        total_days = self.days_risk_on + self.days_risk_off
        
        return {
            "enabled": self.config.enabled,
            "sma_window": self.config.sma_window,
            "risk_on_asset": self.config.risk_on_asset,
            "risk_off_asset": self.config.risk_off_asset,
            "current_regime": self.current_regime.value,
            "regime_changes": self.regime_changes,
            "rebalances": self.rebalances,
            "days_risk_on": self.days_risk_on,
            "days_risk_off": self.days_risk_off,
            "pct_days_risk_on": (self.days_risk_on / total_days * 100.0) if total_days > 0 else 0.0,
            "pct_days_risk_off": (self.days_risk_off / total_days * 100.0) if total_days > 0 else 0.0,
        }


def calculate_sma(prices: List[float], window: int) -> Optional[float]:
    """
    Calculate simple moving average.
    
    Args:
        prices: List of prices (most recent last).
        window: Number of periods for SMA.
    
    Returns:
        SMA value or None if insufficient data.
    """
    if len(prices) < window:
        return None
    
    return sum(prices[-window:]) / window
