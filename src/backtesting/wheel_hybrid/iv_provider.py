"""IV (Implied Volatility) provider protocols and implementations.

Phase 1: Scaffold with synthetic IV (research-only, NOT production edge)
Phase 2: Real market IV from Polygon/ThetaData/OPRA
"""

from datetime import date
from typing import Optional, Protocol
import structlog

logger = structlog.get_logger()


class IVProvider(Protocol):
    """Protocol for fetching implied volatility data."""
    
    def get_atm_iv(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
    ) -> Optional[float]:
        """
        Get at-the-money implied volatility for a symbol.
        
        Args:
            symbol: Ticker symbol
            as_of: Date for IV snapshot
            tenor_days: Option tenor in days (21 = ~3 weeks, 45 = ~6 weeks)
        
        Returns:
            ATM IV as decimal (0.25 = 25% annualized vol) or None if unavailable
        """
        ...
    
    def get_iv_rank(
        self,
        symbol: str,
        as_of: date,
        lookback_days: int = 252,
    ) -> Optional[float]:
        """
        Get IV rank: (current_iv - min_iv) / (max_iv - min_iv) over lookback.
        
        Returns:
            IV rank as decimal (0.0 to 1.0) or None if unavailable
        """
        ...
    
    def get_iv_rv_spread(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
        realized_vol: Optional[float] = None,
    ) -> Optional[float]:
        """
        Get IV-RV spread (volatility risk premium proxy).
        
        Args:
            symbol: Ticker symbol
            as_of: Date for snapshot
            tenor_days: Option tenor
            realized_vol: Pre-computed realized vol (if None, provider may calc)
        
        Returns:
            VRP = (IV - RV) / RV as decimal, or None if unavailable
        """
        ...


class NullIVProvider:
    """IV provider that returns None (no IV data available).
    
    Use case: Legacy mode, no IV gating.
    """
    
    def get_atm_iv(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
    ) -> Optional[float]:
        return None
    
    def get_iv_rank(
        self,
        symbol: str,
        as_of: date,
        lookback_days: int = 252,
    ) -> Optional[float]:
        return None
    
    def get_iv_rv_spread(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
        realized_vol: Optional[float] = None,
    ) -> Optional[float]:
        return None


class SyntheticIVFromRealizedProvider:
    """
    RESEARCH-ONLY: Synthetic IV from realized vol + optional premium bump.
    
    **NOT FOR PRODUCTION**. This provider uses historical realized volatility
    as a proxy for market IV, optionally adding a static premium (e.g. +20%).
    
    Use case:
    - Unit tests (deterministic IV without external data)
    - Dry-run backtests (sanity check regime logic before wiring real IV)
    - Proof-of-concept (validate edge gate plumbing works)
    
    **DOES NOT REPRESENT MARKET IV EDGE**. Real markets may have:
    - Time-varying VRP (premium changes with regime)
    - Skew (OTM puts > ATM > OTM calls)
    - Term structure (front ≠ back month)
    - Liquidity effects (wide spreads, stale quotes)
    
    Phase 2 will replace this with real market IV provider.
    """
    
    def __init__(
        self,
        realized_vol_provider,  # Callable: (symbol, as_of, window) -> float
        premium_bump: float = 0.0,  # e.g. 0.20 = +20% above realized
        iv_rank_mean: float = 0.50,  # Assume median rank when unknown
    ):
        """
        Args:
            realized_vol_provider: Function to compute realized vol
            premium_bump: Static premium to add (decimal, e.g. 0.20 = +20%)
            iv_rank_mean: Default IV rank when history unavailable
        """
        self.realized_vol_provider = realized_vol_provider
        self.premium_bump = premium_bump
        self.iv_rank_mean = iv_rank_mean
        
        logger.warning(
            "Using SyntheticIVFromRealizedProvider",
            premium_bump=premium_bump,
            notice="RESEARCH-ONLY, NOT PRODUCTION EDGE"
        )
    
    def get_atm_iv(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
    ) -> Optional[float]:
        """Synthetic IV = realized vol * (1 + premium_bump)."""
        rv = self.realized_vol_provider(symbol, as_of, tenor_days)
        if rv is None:
            return None
        return rv * (1.0 + self.premium_bump)
    
    def get_iv_rank(
        self,
        symbol: str,
        as_of: date,
        lookback_days: int = 252,
    ) -> Optional[float]:
        """Return static mean rank (no real IV history)."""
        return self.iv_rank_mean
    
    def get_iv_rv_spread(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
        realized_vol: Optional[float] = None,
    ) -> Optional[float]:
        """VRP = premium_bump (by construction)."""
        if realized_vol is None:
            realized_vol = self.realized_vol_provider(symbol, as_of, tenor_days)
        
        if realized_vol is None or realized_vol <= 0:
            return None
        
        # Synthetic IV = RV * (1 + bump), so VRP = bump
        return self.premium_bump


class FileIVProvider:
    """
    Read IV data from CSV/JSON files (for Phase 2 drop-in).
    
    File format (CSV):
        symbol,date,atm_iv_21d,atm_iv_45d,iv_rank
        AAPL,2020-01-02,0.25,0.24,0.45
        AAPL,2020-01-03,0.26,0.25,0.48
        ...
    
    Or JSON (one file per symbol):
        data/iv_cache/AAPL/2020-01-02.json:
        {"atm_iv_21d": 0.25, "atm_iv_45d": 0.24, "iv_rank": 0.45}
    """
    
    def __init__(self, data_path: str, format: str = "csv"):
        """
        Args:
            data_path: Path to CSV file or directory of JSON files
            format: "csv" or "json"
        """
        self.data_path = data_path
        self.format = format
        self.cache = {}  # {(symbol, date, tenor): iv_value}
        
        logger.info("FileIVProvider initialized", path=data_path, format=format)
    
    def _load_data(self):
        """Load IV data from disk (lazy load on first access)."""
        if self.cache:
            return  # Already loaded
        
        # TODO: Implement CSV/JSON parsing in Phase 2
        logger.warning("FileIVProvider._load_data not implemented (Phase 2)")
    
    def get_atm_iv(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
    ) -> Optional[float]:
        """Fetch IV from loaded cache."""
        self._load_data()
        return self.cache.get((symbol, as_of, tenor_days))
    
    def get_iv_rank(
        self,
        symbol: str,
        as_of: date,
        lookback_days: int = 252,
    ) -> Optional[float]:
        """Fetch IV rank from loaded cache."""
        self._load_data()
        return self.cache.get((symbol, as_of, "iv_rank"))
    
    def get_iv_rv_spread(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
        realized_vol: Optional[float] = None,
    ) -> Optional[float]:
        """Calculate VRP from IV and RV."""
        iv = self.get_atm_iv(symbol, as_of, tenor_days)
        if iv is None or realized_vol is None or realized_vol <= 0:
            return None
        
        return (iv - realized_vol) / realized_vol
