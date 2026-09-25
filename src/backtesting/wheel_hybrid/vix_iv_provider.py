"""FREE VIX-based IV provider using public CBOE data (no API key required).

VIX represents 30-day SPX implied volatility from option prices. This provider:
- Uses yfinance to fetch historical VIX (^VIX) — free and reliable
- Caches data locally for CI reproducibility  
- Returns VIX as a regime/IV signal for all symbols (index-level proxy)

IMPORTANT: This is a REGIME signal, not single-name IV edge.
- VIX applies to SPX/SPY, not individual stocks
- Individual stock IV ≠ VIX (name-specific factors matter)
- Use for regime gating (high VIX → write more, low VIX → hold delta)
- NOT a claim about name-level VRP or beat-SPY edge
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger()


class VixIVProvider:
    """
    FREE VIX-based IV provider for regime gating (NO API KEY).
    
    Uses CBOE VIX (^VIX via yfinance) as a proxy for market-wide implied vol.
    Applies VIX level to all symbols as a regime signal.
    
    Use case: 
    - Free regime gating without paid IV data
    - Index-level vol signal for wheel strategy
    - Backtest VRP thesis using public data
    
    Limitations:
    - VIX is SPX IV, not single-name IV (AAPL IV ≠ VIX)
    - No skew, term structure, or name-specific factors
    - Regime signal only, not stock-specific edge
    
    For production single-name IV edge, use:
    - CsvIVProvider (offline test data)
    - PolygonIVProvider (paid real-time data)
    """
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        min_history_days: int = 2000,  # ~8 years to cover typical backtest windows
    ):
        """
        Initialize VIX provider with local caching.
        
        Args:
            cache_dir: Directory for VIX cache (default: data/vix_cache)
            min_history_days: Minimum history to load (for IV rank calc)
        """
        if cache_dir is None:
            cache_dir = "data/vix_cache"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "vix_daily.csv"
        self.min_history_days = min_history_days
        
        self._vix_data = None  # Lazy load
        
        logger.info(
            "VixIVProvider initialized",
            cache_dir=cache_dir,
            source="yfinance ^VIX (free, no API key)",
            notice="REGIME SIGNAL ONLY (index-level vol, not name-specific IV)",
        )
    
    def _ensure_loaded(self, as_of: Optional[date] = None):
        """Lazy-load VIX data from cache or yfinance."""
        if self._vix_data is not None:
            return
        
        # Try cache first
        if self.cache_file.exists():
            try:
                import pandas as pd
                self._vix_data = pd.read_csv(self.cache_file, index_col=0, parse_dates=True)
                self._vix_data.index = pd.to_datetime(self._vix_data.index).date
                logger.info(
                    "Loaded VIX from cache",
                    entries=len(self._vix_data),
                    date_range=f"{self._vix_data.index.min()} to {self._vix_data.index.max()}",
                )
                return
            except Exception as e:
                logger.warning("Failed to load VIX cache", error=str(e))
        
        # Download from yfinance
        self._download_vix(as_of)
    
    def _download_vix(self, as_of: Optional[date] = None):
        """Download VIX data from yfinance and cache locally."""
        import pandas as pd
        import yfinance as yf
        
        if as_of is None:
            as_of = date.today()
        
        # Load from 2000 onwards to cover most backtest windows
        start = date(2000, 1, 1)
        end = max(as_of + timedelta(days=1), date.today())
        
        logger.info(
            "Downloading VIX from yfinance",
            start=str(start),
            end=str(end),
        )
        
        try:
            vix = yf.Ticker("^VIX")
            df = vix.history(start=start, end=end)
            
            if df.empty:
                raise ValueError("No VIX data returned from yfinance")
            
            # Convert to daily close format
            df = df[["Close"]].copy()
            df.columns = ["vix_close"]
            df.index = pd.to_datetime(df.index).date
            
            self._vix_data = df
            
            # Save cache
            df.to_csv(self.cache_file)
            
            logger.info(
                "Downloaded and cached VIX",
                entries=len(df),
                date_range=f"{df.index.min()} to {df.index.max()}",
            )
        
        except Exception as e:
            logger.error("Failed to download VIX", error=str(e))
            raise RuntimeError(f"VixIVProvider: Cannot load VIX data: {e}")
    
    def get_atm_iv(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
    ) -> Optional[float]:
        """
        Return VIX level as ATM IV proxy (index-level, not name-specific).
        
        VIX represents 30-day SPX IV. For 21-day tenor, return VIX as-is.
        For other tenors, could apply term structure adjustment (not impl).
        
        Args:
            symbol: Ignored (VIX applies to all symbols as regime signal)
            as_of: Date for VIX lookup
            tenor_days: Option tenor (VIX is ~30d, returned for all tenors)
        
        Returns:
            VIX level as decimal (0.18 = 18% annualized vol) or None if unavailable
        """
        self._ensure_loaded(as_of)
        
        if self._vix_data is None or as_of not in self._vix_data.index:
            return None
        
        vix_level = float(self._vix_data.loc[as_of, "vix_close"])
        
        # VIX is quoted as percentage (e.g. 18.5), convert to decimal
        return vix_level / 100.0
    
    def get_iv_rank(
        self,
        symbol: str,
        as_of: date,
        lookback_days: int = 252,
    ) -> Optional[float]:
        """
        Calculate VIX percentile rank over lookback window.
        
        IV rank = (current_vix - min_vix) / (max_vix - min_vix) over lookback.
        
        Args:
            symbol: Ignored (VIX percentile applies to all as regime signal)
            as_of: Date for IV rank calculation
            lookback_days: Lookback window (default 252 = 1 year)
        
        Returns:
            IV rank 0.0-1.0, or None if insufficient history
        """
        self._ensure_loaded(as_of)
        
        if self._vix_data is None or as_of not in self._vix_data.index:
            return None
        
        # Get lookback window
        idx_pos = self._vix_data.index.get_loc(as_of)
        if idx_pos < lookback_days:
            return None  # Insufficient history
        
        window = self._vix_data.iloc[idx_pos - lookback_days : idx_pos + 1]["vix_close"]
        current_vix = window.iloc[-1]
        
        # IV rank = (current - min) / (max - min)
        vix_min = window.min()
        vix_max = window.max()
        
        if vix_max <= vix_min:
            return 0.5  # Flat VIX → median rank
        
        iv_rank = (current_vix - vix_min) / (vix_max - vix_min)
        return float(iv_rank)
    
    def get_iv_rv_spread(
        self,
        symbol: str,
        as_of: date,
        tenor_days: int = 21,
        realized_vol: Optional[float] = None,
    ) -> Optional[float]:
        """
        Calculate VRP = (VIX - RV) / RV.
        
        Uses VIX as IV proxy and provided RV (typically SPY 21d realized vol).
        
        IMPORTANT: This is an index-level VRP signal (SPX vol vs SPY realized).
        Individual stock VRP ≠ index VRP.
        
        Args:
            symbol: Symbol for RV (typically SPY for index comparison)
            as_of: Date for VRP calculation
            tenor_days: Option tenor (match RV window)
            realized_vol: Pre-computed realized vol (required)
        
        Returns:
            VRP as decimal (0.20 = 20% premium), or None if data missing
        """
        if realized_vol is None or realized_vol <= 0:
            return None
        
        vix_iv = self.get_atm_iv(symbol, as_of, tenor_days)
        if vix_iv is None:
            return None
        
        # VRP = (IV - RV) / RV
        vrp = (vix_iv - realized_vol) / realized_vol
        return float(vrp)
