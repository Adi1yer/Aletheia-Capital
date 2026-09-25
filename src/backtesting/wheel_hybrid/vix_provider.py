"""Free VIX data provider using yfinance (no API key required).

VIX data from CBOE via Yahoo Finance is:
- Free and reliable for historical backtests
- Daily closes available back to 1990
- No rate limits for reasonable usage
- Suitable for regime gating (not single-name IV edge)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import structlog

logger = structlog.get_logger()


class VixDataProvider:
    """
    Free VIX data provider using yfinance.

    Caches VIX data locally to avoid repeated downloads and enable CI reproducibility.
    VIX is the CBOE Volatility Index representing 30-day SPX implied volatility.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize VIX data provider with optional local cache.

        Args:
            cache_dir: Directory for caching VIX data (default: data/vix_cache)
        """
        if cache_dir is None:
            cache_dir = str(Path(__file__).parent.parent.parent.parent / "data" / "vix_cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "vix_daily.parquet"
        self._data: Optional[pd.DataFrame] = None

    def _load_cache(self) -> bool:
        """Load VIX data from cache if available."""
        if not self.cache_file.exists():
            return False
        try:
            self._data = pd.read_parquet(self.cache_file)
            logger.info(
                "Loaded VIX data from cache",
                entries=len(self._data),
                date_range=f"{self._data.index.min()} to {self._data.index.max()}",
            )
            return True
        except Exception as e:
            logger.warning("Failed to load VIX cache", error=str(e))
            return False

    def _save_cache(self):
        """Save VIX data to cache."""
        if self._data is None:
            return
        try:
            self._data.to_parquet(self.cache_file)
            logger.info("Saved VIX data to cache", entries=len(self._data))
        except Exception as e:
            logger.warning("Failed to save VIX cache", error=str(e))

    def _download_vix(self, start_date: Optional[date] = None, end_date: Optional[date] = None):
        """Download VIX data from yfinance."""
        import yfinance as yf

        # Default to downloading 10 years of history
        if start_date is None:
            start_date = date.today() - timedelta(days=3650)
        if end_date is None:
            end_date = date.today()

        logger.info(
            "Downloading VIX data from yfinance",
            start_date=str(start_date),
            end_date=str(end_date),
        )

        try:
            vix = yf.Ticker("^VIX")
            df = vix.history(start=start_date, end=end_date + timedelta(days=1))

            if df.empty:
                raise ValueError("No VIX data returned from yfinance")

            # Convert to daily close format
            df = df[["Close"]].copy()
            df.columns = ["vix_close"]
            df.index = pd.to_datetime(df.index).date

            self._data = df
            self._save_cache()

            logger.info(
                "Downloaded VIX data",
                entries=len(df),
                date_range=f"{df.index.min()} to {df.index.max()}",
            )

        except Exception as e:
            logger.error("Failed to download VIX data", error=str(e))
            raise

    def ensure_data_loaded(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ):
        """Ensure VIX data is loaded for the requested date range."""
        if self._data is not None:
            return

        # Try cache first
        if self._load_cache():
            # Check if cache covers requested range
            if start_date and end_date:
                cache_start = self._data.index.min()
                cache_end = self._data.index.max()
                if cache_start <= start_date and cache_end >= end_date:
                    return

        # Download if cache miss or insufficient range
        self._download_vix(start_date, end_date)

    def get_vix(self, dt: date) -> Optional[float]:
        """
        Get VIX close for a specific date.

        Args:
            dt: Date for which to retrieve VIX

        Returns:
            VIX close value, or None if unavailable
        """
        self.ensure_data_loaded()
        if self._data is None or dt not in self._data.index:
            return None
        return float(self._data.loc[dt, "vix_close"])

    def get_vix_range(self, start_date: date, end_date: date) -> Dict[date, float]:
        """
        Get VIX time series over a date range.

        Args:
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            Dict mapping dates to VIX close values
        """
        self.ensure_data_loaded(start_date, end_date)
        if self._data is None:
            return {}

        mask = (self._data.index >= start_date) & (self._data.index <= end_date)
        subset = self._data.loc[mask]
        return {dt: float(val) for dt, val in subset["vix_close"].items()}

    def get_vix_percentile(self, dt: date, lookback_days: int = 252) -> Optional[float]:
        """
        Get VIX percentile rank over a lookback window.

        Args:
            dt: Date for percentile calculation
            lookback_days: Number of trading days to look back (default: 1 year)

        Returns:
            Percentile rank (0-100), or None if insufficient data
        """
        self.ensure_data_loaded()
        if self._data is None or dt not in self._data.index:
            return None

        # Get lookback window
        idx_pos = self._data.index.get_loc(dt)
        if idx_pos < lookback_days:
            return None

        window = self._data.iloc[idx_pos - lookback_days : idx_pos + 1]["vix_close"]
        current_vix = window.iloc[-1]

        # Calculate percentile rank
        percentile = (window < current_vix).sum() / len(window) * 100.0
        return float(percentile)
