"""Edge gate: filter option writes based on IV/VRP signals.

Gates option writes to only harvest premium when market IV is rich vs realized vol.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional
import structlog

from .iv_provider import IVProvider

logger = structlog.get_logger()


@dataclass
class EdgeGateConfig:
    """Configuration for edge-gating option writes."""
    
    enabled: bool = False
    """Enable edge gating (default: False for backward compatibility)"""
    
    min_vrp: float = 0.10
    """Minimum IV-RV spread to write options (0.10 = 10% VRP)"""
    
    min_iv_rank: Optional[float] = None
    """Minimum IV rank to write (0.0-1.0), None = no filter"""
    
    min_premium_edge_after_cost_bps: Optional[int] = None
    """Minimum edge in bps after bid-ask cost, None = no filter"""
    
    fail_closed_when_no_iv: bool = True
    """
    If True and IV unavailable, refuse writes (safe default).
    If False and IV unavailable, allow writes (legacy behavior).
    """
    
    allow_ungated: bool = False
    """If True, override gate and allow all writes (legacy mode escape hatch)"""


class EdgeGate:
    """
    Gate option writes based on IV/VRP edge signals.
    
    When gate is enabled and IV data is available, only writes options when:
    - VRP (IV - RV) / RV > min_vrp
    - IV rank > min_iv_rank (if configured)
    - Premium edge > min_premium_edge_after_cost_bps (if configured)
    
    When gate is enabled but IV unavailable:
    - fail_closed_when_no_iv=True → refuse writes (safe)
    - fail_closed_when_no_iv=False → allow writes (legacy)
    
    When gate is disabled:
    - All writes allowed (current behavior)
    """
    
    def __init__(
        self,
        config: EdgeGateConfig,
        iv_provider: IVProvider,
    ):
        self.config = config
        self.iv_provider = iv_provider
        
        # Stats
        self.writes_allowed = 0
        self.writes_blocked_vrp = 0
        self.writes_blocked_iv_rank = 0
        self.writes_blocked_no_iv = 0
        self.writes_ungated = 0
        
        if config.enabled:
            logger.info(
                "EdgeGate enabled",
                min_vrp=config.min_vrp,
                min_iv_rank=config.min_iv_rank,
                fail_closed=config.fail_closed_when_no_iv,
            )
        else:
            logger.info("EdgeGate disabled (legacy mode)")
    
    def should_write_cc(
        self,
        symbol: str,
        trade_date: date,
        realized_vol: float,
        tenor_days: int = 21,
    ) -> tuple[bool, str]:
        """
        Check if covered call should be written.
        
        Args:
            symbol: Stock ticker
            trade_date: Date of potential write
            realized_vol: Historical realized volatility
            tenor_days: Option tenor in days
        
        Returns:
            (allowed, reason): (True, "edge detected") or (False, "insufficient VRP")
        """
        return self._should_write(
            symbol=symbol,
            trade_date=trade_date,
            realized_vol=realized_vol,
            tenor_days=tenor_days,
            option_type="CC",
        )
    
    def should_write_csp(
        self,
        symbol: str,
        trade_date: date,
        realized_vol: float,
        tenor_days: int = 21,
    ) -> tuple[bool, str]:
        """
        Check if cash-secured put should be written.
        
        Args:
            symbol: Stock ticker
            trade_date: Date of potential write
            realized_vol: Historical realized volatility
            tenor_days: Option tenor in days
        
        Returns:
            (allowed, reason): (True, "edge detected") or (False, "insufficient VRP")
        """
        return self._should_write(
            symbol=symbol,
            trade_date=trade_date,
            realized_vol=realized_vol,
            tenor_days=tenor_days,
            option_type="CSP",
        )
    
    def _should_write(
        self,
        symbol: str,
        trade_date: date,
        realized_vol: float,
        tenor_days: int,
        option_type: str,
    ) -> tuple[bool, str]:
        """Internal: common gating logic for CC and CSP."""
        
        # Gate disabled → allow all writes
        if not self.config.enabled:
            self.writes_ungated += 1
            return (True, "gate_disabled")
        
        # Allow ungated override (escape hatch for legacy mode)
        if self.config.allow_ungated:
            self.writes_ungated += 1
            return (True, "ungated_override")
        
        # Fetch IV data
        atm_iv = self.iv_provider.get_atm_iv(symbol, trade_date, tenor_days)
        
        # No IV available
        if atm_iv is None:
            if self.config.fail_closed_when_no_iv:
                self.writes_blocked_no_iv += 1
                logger.debug(
                    "Write blocked (no IV)",
                    symbol=symbol,
                    date=trade_date,
                    type=option_type,
                )
                return (False, "no_iv_data")
            else:
                # Legacy fallback: allow when IV missing
                self.writes_allowed += 1
                return (True, "iv_unavailable_fallback")
        
        # Check VRP threshold
        vrp = self.iv_provider.get_iv_rv_spread(
            symbol, trade_date, tenor_days, realized_vol
        )
        
        if vrp is None:
            # Could not compute VRP (missing RV?)
            if self.config.fail_closed_when_no_iv:
                self.writes_blocked_no_iv += 1
                return (False, "vrp_unavailable")
            else:
                self.writes_allowed += 1
                return (True, "vrp_unavailable_fallback")
        
        if vrp < self.config.min_vrp:
            self.writes_blocked_vrp += 1
            logger.debug(
                "Write blocked (VRP too low)",
                symbol=symbol,
                date=trade_date,
                vrp=vrp,
                min_vrp=self.config.min_vrp,
                iv=atm_iv,
                rv=realized_vol,
                type=option_type,
            )
            return (False, f"vrp_too_low:{vrp:.3f}<{self.config.min_vrp:.3f}")
        
        # Check IV rank threshold (if configured)
        if self.config.min_iv_rank is not None:
            iv_rank = self.iv_provider.get_iv_rank(symbol, trade_date)
            if iv_rank is not None and iv_rank < self.config.min_iv_rank:
                self.writes_blocked_iv_rank += 1
                logger.debug(
                    "Write blocked (IV rank too low)",
                    symbol=symbol,
                    date=trade_date,
                    iv_rank=iv_rank,
                    min_iv_rank=self.config.min_iv_rank,
                    type=option_type,
                )
                return (False, f"iv_rank_too_low:{iv_rank:.3f}<{self.config.min_iv_rank:.3f}")
        
        # All checks passed
        self.writes_allowed += 1
        logger.debug(
            "Write allowed (edge detected)",
            symbol=symbol,
            date=trade_date,
            vrp=vrp,
            iv=atm_iv,
            rv=realized_vol,
            type=option_type,
        )
        return (True, f"edge_detected:vrp={vrp:.3f}")
    
    def get_stats(self) -> dict:
        """Get gating statistics for reporting."""
        return {
            "writes_allowed": self.writes_allowed,
            "writes_blocked_vrp": self.writes_blocked_vrp,
            "writes_blocked_iv_rank": self.writes_blocked_iv_rank,
            "writes_blocked_no_iv": self.writes_blocked_no_iv,
            "writes_ungated": self.writes_ungated,
            "gate_enabled": self.config.enabled,
        }
