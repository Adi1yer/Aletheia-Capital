"""IV provider interface and implementations for wheel-hybrid backtests.

Supports:
- Paid IV providers (Massive, Polygon, Theta) - scaffolding only, not implemented
- CSV IV provider for Phase 2 testing
- Free VIX-based regime gating (this module)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()


class IVProvider(ABC):
    """Abstract interface for implied volatility data providers."""

    @abstractmethod
    def get_iv(self, symbol: str, dt: date) -> Optional[float]:
        """
        Get 30-day implied volatility for a symbol on a date.

        Args:
            symbol: Ticker symbol (e.g., 'SPY', 'AAPL')
            dt: Date for which to retrieve IV

        Returns:
            IV as a decimal (e.g., 0.20 for 20% IV), or None if unavailable
        """
        pass

    @abstractmethod
    def get_iv_range(self, symbol: str, start_date: date, end_date: date) -> Dict[date, float]:
        """
        Get IV time series for a symbol over a date range.

        Args:
            symbol: Ticker symbol
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            Dict mapping dates to IV values (missing dates excluded)
        """
        pass


class CsvIVProvider(IVProvider):
    """CSV-based IV provider for Phase 2 testing with committed IV snapshots.

    Expected CSV format:
        date,symbol,iv_30d
        2020-01-02,SPY,0.123
        2020-01-02,AAPL,0.215
    """

    def __init__(self, csv_path: str):
        """
        Initialize CSV IV provider.

        Args:
            csv_path: Path to CSV file with IV data
        """
        self.csv_path = csv_path
        self._cache: Dict[tuple, float] = {}
        self._load_csv()

    def _load_csv(self):
        """Load CSV into memory cache."""
        import pandas as pd

        try:
            df = pd.read_csv(self.csv_path)
            df["date"] = pd.to_datetime(df["date"]).dt.date
            for _, row in df.iterrows():
                key = (str(row["symbol"]).upper(), row["date"])
                self._cache[key] = float(row["iv_30d"])
            logger.info(
                "Loaded CSV IV provider",
                path=self.csv_path,
                entries=len(self._cache),
            )
        except Exception as e:
            logger.error("Failed to load CSV IV provider", error=str(e), path=self.csv_path)
            raise

    def get_iv(self, symbol: str, dt: date) -> Optional[float]:
        """Get IV for a symbol on a specific date."""
        return self._cache.get((symbol.upper(), dt))

    def get_iv_range(self, symbol: str, start_date: date, end_date: date) -> Dict[date, float]:
        """Get IV time series for a date range."""
        result = {}
        symbol = symbol.upper()
        for key, iv in self._cache.items():
            if key[0] == symbol and start_date <= key[1] <= end_date:
                result[key[1]] = iv
        return result


class NoOpIVProvider(IVProvider):
    """No-op IV provider that always returns None (for always-on mode)."""

    def get_iv(self, symbol: str, dt: date) -> Optional[float]:
        """Always returns None."""
        return None

    def get_iv_range(self, symbol: str, start_date: date, end_date: date) -> Dict[date, float]:
        """Always returns empty dict."""
        return {}
