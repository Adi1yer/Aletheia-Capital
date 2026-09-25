"""IV (Implied Volatility) provider protocols and implementations.

Phase 1: Scaffold with synthetic IV (research-only, NOT production edge)
Phase 2: Real market IV from Polygon/ThetaData/OPRA
"""

from datetime import date
from pathlib import Path
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


class CsvIVProvider:
    """
    Read IV data from CSV file (Phase 2 real IV drop-in).
    
    CSV format (atm_iv as decimal: 0.25 = 25% annualized vol):
        date,symbol,atm_iv,iv_rank
        2020-01-02,AAPL,0.2500,0.45
        2020-01-02,MSFT,0.1800,0.32
        2020-01-03,AAPL,0.2600,0.48
        ...
    
    Columns:
        - date: YYYY-MM-DD
        - symbol: ticker
        - atm_iv: ATM IV as decimal (0.25 = 25% vol)
        - iv_rank: IV rank 0.0-1.0 (optional, can be empty)
    
    Lookup: Deterministic by (symbol, date). Missing data returns None.
    """
    
    def __init__(self, csv_path: str, tenor_days: int = 21):
        """
        Args:
            csv_path: Path to IV CSV file
            tenor_days: Assume CSV IV represents this tenor (default 21d)
        """
        import csv
        from pathlib import Path
        
        self.csv_path = csv_path
        self.tenor_days = tenor_days
        self.cache = {}  # {(symbol, date): {"atm_iv": float, "iv_rank": float}}
        
        # Load CSV on init (fail fast if file missing/malformed)
        csv_file = Path(csv_path)
        if not csv_file.exists():
            raise FileNotFoundError(f"IV CSV not found: {csv_path}")
        
        with open(csv_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    symbol = row["symbol"].strip().upper()
                    date_str = row["date"].strip()
                    dt = date.fromisoformat(date_str)
                    
                    atm_iv_str = row["atm_iv"].strip()
                    atm_iv = float(atm_iv_str) if atm_iv_str else None
                    
                    iv_rank_str = row.get("iv_rank", "").strip()
                    iv_rank = float(iv_rank_str) if iv_rank_str else None
                    
                    self.cache[(symbol, dt)] = {
                        "atm_iv": atm_iv,
                        "iv_rank": iv_rank,
                    }
                except (KeyError, ValueError) as e:
                    logger.warning(
                        "Skipping malformed IV CSV row",
                        row=row,
                        error=str(e),
                    )
        
        logger.info(
            "CsvIVProvider loaded",
            path=csv_path,
            tenor_days=tenor_days,
            rows=len(self.cache),
        )
    
    def get_atm_iv(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
    ) -> Optional[float]:
        """Fetch ATM IV from cache (assumes tenor matches constructor tenor_days)."""
        entry = self.cache.get((symbol, as_of))
        if entry:
            return entry.get("atm_iv")
        return None
    
    def get_iv_rank(
        self,
        symbol: str,
        as_of: date,
        lookback_days: int = 252,
    ) -> Optional[float]:
        """Fetch IV rank from cache."""
        entry = self.cache.get((symbol, as_of))
        if entry:
            return entry.get("iv_rank")
        return None
    
    def get_iv_rv_spread(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
        realized_vol: Optional[float] = None,
    ) -> Optional[float]:
        """Calculate VRP = (IV - RV) / RV."""
        iv = self.get_atm_iv(symbol, as_of, tenor_days)
        if iv is None or realized_vol is None or realized_vol <= 0:
            return None
        
        return (iv - realized_vol) / realized_vol


# Legacy alias for backward compatibility
FileIVProvider = CsvIVProvider


class PolygonIVProvider:
    """
    Fetch IV data from Polygon.io API (Phase 2 optional adapter).
    
    Requires POLYGON_API_KEY environment variable.
    If key not set, raises clear error (does not fail CI silently).
    
    Cache layout: data/iv_cache/{symbol}/{date}.json
    - Fetches on-demand if cache miss
    - Writes to disk for offline replay
    
    API endpoints:
    - /v3/snapshot/options/{symbol} → ATM IV from option chain
    - Fallback: reconstruct IV from option quotes + Black-Scholes
    """
    
    def __init__(self, cache_dir: str = "data/iv_cache"):
        """
        Args:
            cache_dir: Directory for disk cache (gitignored)
        """
        import os
        from pathlib import Path
        
        self.api_key = os.environ.get("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError(
                "POLYGON_API_KEY environment variable not set. "
                "Get API key from https://polygon.io/ or use CsvIVProvider for offline replay."
            )
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            "PolygonIVProvider initialized",
            cache_dir=cache_dir,
            api_key_set=True,
        )
    
    def _get_cache_path(self, symbol: str, as_of: date) -> Path:
        """Get cache file path for symbol/date."""
        symbol_dir = self.cache_dir / symbol
        symbol_dir.mkdir(exist_ok=True)
        return symbol_dir / f"{as_of.isoformat()}.json"
    
    def _fetch_from_api(self, symbol: str, as_of: date) -> Optional[dict]:
        """
        Fetch IV from Polygon API (stub implementation).
        
        TODO: Implement actual API call in Phase 2:
        - GET https://api.polygon.io/v3/snapshot/options/{symbol}
        - Parse option chain for ATM strike
        - Extract implied_volatility field
        - Calculate IV rank from historical data
        """
        logger.warning(
            "PolygonIVProvider._fetch_from_api not fully implemented (Phase 2 stub)",
            symbol=symbol,
            as_of=as_of,
        )
        # Stub: return None (cache miss → provider returns None → gate may block)
        return None
    
    def _load_from_cache(self, symbol: str, as_of: date) -> Optional[dict]:
        """Load IV from disk cache."""
        import json
        
        cache_path = self._get_cache_path(symbol, as_of)
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to load IV from cache",
                symbol=symbol,
                as_of=as_of,
                error=str(e),
            )
            return None
    
    def _save_to_cache(self, symbol: str, as_of: date, data: dict):
        """Save IV to disk cache."""
        import json
        
        cache_path = self._get_cache_path(symbol, as_of)
        try:
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.warning(
                "Failed to save IV to cache",
                symbol=symbol,
                as_of=as_of,
                error=str(e),
            )
    
    def get_atm_iv(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
    ) -> Optional[float]:
        """Fetch ATM IV (cache → API → None)."""
        # Try cache first
        cached = self._load_from_cache(symbol, as_of)
        if cached:
            return cached.get("atm_iv")
        
        # Fetch from API
        data = self._fetch_from_api(symbol, as_of)
        if data:
            self._save_to_cache(symbol, as_of, data)
            return data.get("atm_iv")
        
        return None
    
    def get_iv_rank(
        self,
        symbol: str,
        as_of: date,
        lookback_days: int = 252,
    ) -> Optional[float]:
        """Fetch IV rank from cache or API."""
        cached = self._load_from_cache(symbol, as_of)
        if cached:
            return cached.get("iv_rank")
        
        data = self._fetch_from_api(symbol, as_of)
        if data:
            return data.get("iv_rank")
        
        return None
    
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
