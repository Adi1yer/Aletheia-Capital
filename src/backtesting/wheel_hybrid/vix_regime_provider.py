"""FREE VIX/SPY regime provider for index-level volatility signals.

Uses public data only (no API keys):
- VIX: CBOE Volatility Index via yfinance ^VIX
- SPY: S&P 500 ETF realized vol from price history

Computes INDEX-LEVEL regime signals:
- VRP = (VIX - SPY RV) / SPY RV (both index measures)
- VIX percentile rank over trailing year
- VIX absolute level

DO NOT compare VIX to individual stock realized vol.
This is a macro/index regime signal, not name-specific IV edge.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Dict, List
import structlog

logger = structlog.get_logger()


class VixRegimeProvider:
    """
    FREE index-level regime provider using VIX and SPY.
    
    Provides macro volatility regime signals for wheel strategy:
    - VRP: VIX vs SPY realized vol (index VRP)
    - VIX percentile: VIX rank over trailing year
    - VIX level: Absolute VIX reading
    
    Use case:
    - Regime detection (HARVEST_VRP vs HOLD_DELTA vs DEFENSIVE)
    - Overwrite intensity scaling (write more when VRP rich, less when cheap)
    - NOT for name-level IV edge (VIX ≠ AAPL IV, MSFT IV, etc.)
    """
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        min_history_days: int = 400,  # ~1.5 years for percentile calc
    ):
        """
        Initialize VIX/SPY regime provider.
        
        Args:
            cache_dir: Directory for VIX cache (default: data/vix_cache)
            min_history_days: Minimum history for percentile calculation
        """
        if cache_dir is None:
            cache_dir = "data/vix_cache"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "vix_daily.csv"
        self.min_history_days = min_history_days
        
        self._vix_data = None  # Lazy load
        
        logger.info(
            "VixRegimeProvider initialized",
            cache_dir=cache_dir,
            source="yfinance ^VIX + SPY (free, no API key)",
            notice="INDEX-LEVEL regime (VIX vs SPY RV), not name-specific IV",
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
            raise RuntimeError(f"VixRegimeProvider: Cannot load VIX data: {e}")
    
    def get_vix(self, dt: date) -> Optional[float]:
        """
        Get VIX level for a date (as decimal: 0.18 = 18%).
        
        Args:
            dt: Date for VIX lookup
        
        Returns:
            VIX as decimal (0.18 = 18% annualized vol) or None if unavailable
        """
        self._ensure_loaded(dt)
        
        if self._vix_data is None or dt not in self._vix_data.index:
            return None
        
        vix_level = float(self._vix_data.loc[dt, "vix_close"])
        
        # VIX is quoted as percentage (e.g. 18.5), convert to decimal
        return vix_level / 100.0
    
    def get_vix_percentile(
        self,
        dt: date,
        lookback_days: int = 252,
    ) -> Optional[float]:
        """
        Calculate VIX percentile rank over lookback window.
        
        Args:
            dt: Date for percentile calculation
            lookback_days: Lookback window (default 252 = 1 year)
        
        Returns:
            Percentile rank 0.0-1.0, or None if insufficient history
        """
        self._ensure_loaded(dt)
        
        if self._vix_data is None or dt not in self._vix_data.index:
            return None
        
        # Get lookback window
        idx_pos = self._vix_data.index.get_loc(dt)
        if idx_pos < lookback_days:
            return None  # Insufficient history
        
        window = self._vix_data.iloc[idx_pos - lookback_days : idx_pos + 1]["vix_close"]
        current_vix = window.iloc[-1]
        
        # Percentile rank = (current - min) / (max - min)
        vix_min = window.min()
        vix_max = window.max()
        
        if vix_max <= vix_min:
            return 0.5  # Flat VIX → median rank
        
        percentile = (current_vix - vix_min) / (vix_max - vix_min)
        return float(percentile)
    
    def compute_index_vrp(
        self,
        dt: date,
        spy_realized_vol: float,
    ) -> Optional[float]:
        """
        Compute INDEX-LEVEL VRP: (VIX - SPY RV) / SPY RV.
        
        This is the proper FREE regime signal:
        - VIX: SPX 30-day implied vol (index)
        - SPY RV: S&P 500 ETF realized vol (index)
        - Both are INDEX measures (not name-specific)
        
        Args:
            dt: Date for VRP calculation
            spy_realized_vol: SPY realized vol from price history (decimal)
        
        Returns:
            Index VRP as decimal (0.20 = 20% premium), or None if VIX unavailable
        """
        if spy_realized_vol is None or spy_realized_vol <= 0:
            return None
        
        vix_iv = self.get_vix(dt)
        if vix_iv is None:
            return None
        
        # VRP = (IV - RV) / RV
        vrp = (vix_iv - spy_realized_vol) / spy_realized_vol
        return float(vrp)
    
    def get_regime_intensity(
        self,
        dt: date,
        spy_realized_vol: Optional[float] = None,
    ) -> float:
        """
        Calculate overwrite intensity from VIX regime.
        
        Uses VIX percentile and optionally VIX vs SPY RV for intensity:
        - VIX percentile < 30th → 0.3-0.5 (crushed vol, hold delta)
        - VIX percentile 30-70th → 0.5-0.8 (neutral)
        - VIX percentile > 70th → 0.8-1.0 (rich vol, write aggressively)
        
        If spy_realized_vol provided, also considers VRP:
        - VRP < 0 (VIX < SPY RV) → reduce intensity
        - VRP > 0.2 (VIX >> SPY RV) → boost intensity
        
        Args:
            dt: Date for regime calculation
            spy_realized_vol: Optional SPY realized vol for VRP adjustment
        
        Returns:
            Intensity 0.0-1.0 (fraction of eligible writes to execute)
        """
        vix_pct = self.get_vix_percentile(dt, lookback_days=252)
        
        # Base intensity from VIX percentile
        if vix_pct is None:
            # Fallback: use raw VIX level
            vix = self.get_vix(dt)
            if vix is None:
                return 1.0  # No data → default to always-on
            
            if vix < 0.15:
                return 0.5  # Low VIX
            elif vix > 0.25:
                return 1.0  # High VIX
            else:
                return 0.5 + 0.5 * (vix - 0.15) / 0.10
        
        # VIX percentile-based intensity
        if vix_pct < 0.30:
            base_intensity = 0.3 + 0.2 * (vix_pct / 0.30)  # 0.3-0.5
        elif vix_pct > 0.70:
            excess = (vix_pct - 0.70) / 0.30
            base_intensity = 0.8 + 0.2 * excess  # 0.8-1.0
        else:
            # Neutral zone (30-70th percentile)
            base_intensity = 0.5 + 0.3 * (vix_pct - 0.30) / 0.40  # 0.5-0.8
        
        # Adjust by VRP if SPY RV available
        if spy_realized_vol is not None and spy_realized_vol > 0:
            vrp = self.compute_index_vrp(dt, spy_realized_vol)
            if vrp is not None:
                # VRP < 0 → reduce intensity (vol is cheap)
                # VRP > 0.2 → boost intensity (vol is rich)
                if vrp < 0:
                    vrp_adj = max(0.5, 1.0 + vrp)  # -50% VRP → 0.5x multiplier
                elif vrp > 0.2:
                    vrp_adj = min(1.2, 1.0 + vrp / 2)  # +40% VRP → 1.2x multiplier
                else:
                    vrp_adj = 1.0  # Neutral VRP (0-20%)
                
                base_intensity *= vrp_adj
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, base_intensity))
