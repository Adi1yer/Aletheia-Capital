"""Edge gate for controlling wheel overwrites based on VIX regime.

The VRP (Volatility Risk Premium) thesis: index implied vol is often rich vs realized,
so selling premium via covered calls / CSPs should have positive edge over time.

This module implements a FREE regime gate using public VIX data (no single-name IV required):
- Write covered calls MORE aggressively when VIX is elevated (vol is rich)
- HOLD more delta / write less when VIX is crushed (vol is cheap)

This is a REGIME signal, NOT a claim about beat-SPY edge from name-level IV mispricing.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()


class EdgeMode(Enum):
    """Edge/regime modes for wheel overwrites."""

    ALWAYS_ON = "always_on"  # Write CCs every day regardless of regime
    VIX_GATED = "vix_gated"  # Gate based on VIX vs realized vol or VIX percentile


class EdgeGate:
    """
    Controls wheel overwrite aggressiveness based on VIX regime.

    Two primary gating strategies:
    1. VIX vs SPY realized vol: Write more when VIX > realized, hold when VIX < realized
    2. VIX percentile: Write more when VIX is in upper percentiles, hold when crushed

    Outputs a 0-1 "overwrite intensity" that scales:
    - How many lots to write CCs on (e.g., 0.0 = hold all, 0.5 = write half, 1.0 = write all)
    - CC strike selection bias (higher intensity = closer to ATM for more premium)
    - CSP aggressiveness (higher intensity = more puts, closer to ATM)
    """

    def __init__(
        self,
        mode: EdgeMode = EdgeMode.ALWAYS_ON,
        vix_provider=None,
        rv_lookback_days: int = 20,
        vix_percentile_threshold_low: float = 30.0,
        vix_percentile_threshold_high: float = 70.0,
    ):
        """
        Initialize edge gate.

        Args:
            mode: Edge mode (ALWAYS_ON or VIX_GATED)
            vix_provider: VixDataProvider instance (required for VIX_GATED mode)
            rv_lookback_days: Days for realized vol calculation (default: 20 ~= 1 month)
            vix_percentile_threshold_low: VIX percentile below which to reduce overwrites
            vix_percentile_threshold_high: VIX percentile above which to increase overwrites
        """
        self.mode = mode
        self.vix_provider = vix_provider
        self.rv_lookback_days = rv_lookback_days
        self.vix_pct_low = vix_percentile_threshold_low
        self.vix_pct_high = vix_percentile_threshold_high

        if mode == EdgeMode.VIX_GATED and vix_provider is None:
            raise ValueError("VIX_GATED mode requires vix_provider")

    def get_overwrite_intensity(
        self,
        dt: date,
        spy_prices: Optional[Dict[date, float]] = None,
    ) -> float:
        """
        Calculate overwrite intensity for a given date.

        Args:
            dt: Date for regime calculation
            spy_prices: Optional dict of {date: close} for SPY (for VIX vs RV comparison)

        Returns:
            Intensity from 0.0 (hold all delta) to 1.0 (write all lots aggressively)
        """
        if self.mode == EdgeMode.ALWAYS_ON:
            return 1.0

        if self.mode == EdgeMode.VIX_GATED:
            return self._calculate_vix_gated_intensity(dt, spy_prices)

        logger.warning("Unknown edge mode", mode=self.mode)
        return 1.0

    def _calculate_vix_gated_intensity(
        self,
        dt: date,
        spy_prices: Optional[Dict[date, float]],
    ) -> float:
        """Calculate intensity using VIX regime."""
        vix = self.vix_provider.get_vix(dt)
        if vix is None:
            logger.warning("VIX unavailable, defaulting to always-on", date=str(dt))
            return 1.0

        # Strategy 1: VIX percentile rank
        vix_pct = self.vix_provider.get_vix_percentile(dt, lookback_days=252)
        if vix_pct is not None:
            if vix_pct < self.vix_pct_low:
                # VIX is crushed (cheap vol) → hold more delta
                intensity = 0.3 + (vix_pct / self.vix_pct_low) * 0.4  # 0.3-0.7 range
            elif vix_pct > self.vix_pct_high:
                # VIX is elevated (rich vol) → write aggressively
                excess = (vix_pct - self.vix_pct_high) / (100.0 - self.vix_pct_high)
                intensity = 1.0  # Full intensity when VIX elevated
            else:
                # Neutral zone → moderate overwrites
                intensity = 0.7 + 0.3 * (vix_pct - self.vix_pct_low) / (
                    self.vix_pct_high - self.vix_pct_low
                )

            logger.debug(
                "VIX percentile regime",
                date=str(dt),
                vix=round(vix, 2),
                vix_percentile=round(vix_pct, 1),
                intensity=round(intensity, 2),
            )
            return intensity

        # Strategy 2: VIX vs realized vol (fallback if percentile unavailable)
        if spy_prices:
            rv = self._calculate_realized_vol(spy_prices, dt, self.rv_lookback_days)
            if rv is not None:
                vix_annualized = vix  # VIX is already annualized
                ratio = vix_annualized / rv if rv > 0 else 1.0

                if ratio < 0.8:
                    # VIX below RV → cheap vol → hold delta
                    intensity = 0.3 + 0.4 * max(0, ratio - 0.5) / 0.3
                elif ratio > 1.2:
                    # VIX above RV → rich vol → write aggressively
                    intensity = 1.0
                else:
                    # Neutral zone
                    intensity = 0.6 + 0.4 * (ratio - 0.8) / 0.4

                logger.debug(
                    "VIX vs RV regime",
                    date=str(dt),
                    vix=round(vix, 2),
                    realized_vol=round(rv, 2),
                    ratio=round(ratio, 2),
                    intensity=round(intensity, 2),
                )
                return intensity

        # Fallback: insufficient data → use raw VIX level
        if vix < 15:
            intensity = 0.5  # Low VIX → moderate
        elif vix > 25:
            intensity = 1.0  # High VIX → aggressive
        else:
            intensity = 0.5 + 0.5 * (vix - 15) / 10.0

        logger.debug(
            "VIX level regime (fallback)",
            date=str(dt),
            vix=round(vix, 2),
            intensity=round(intensity, 2),
        )
        return intensity

    @staticmethod
    def _calculate_realized_vol(
        prices: Dict[date, float],
        end_date: date,
        lookback_days: int,
    ) -> Optional[float]:
        """
        Calculate realized volatility (annualized) from price history.

        Args:
            prices: Dict of {date: close}
            end_date: End date for RV calculation
            lookback_days: Number of days to look back

        Returns:
            Annualized realized vol (e.g., 0.20 for 20%), or None if insufficient data
        """
        import numpy as np

        # Get prices up to end_date
        sorted_dates = sorted([d for d in prices.keys() if d <= end_date])
        if len(sorted_dates) < lookback_days + 1:
            return None

        # Get last lookback_days + 1 prices (need n+1 prices for n returns)
        recent = sorted_dates[-(lookback_days + 1) :]
        price_series = [prices[d] for d in recent]

        # Calculate log returns
        log_returns = np.diff(np.log(price_series))

        # Annualize (252 trading days)
        rv = np.std(log_returns) * np.sqrt(252)
        return float(rv)

    def should_write_cc(self, dt: date, spy_prices: Optional[Dict[date, float]] = None) -> bool:
        """
        Binary decision: should we write covered calls on this date?

        Args:
            dt: Date for decision
            spy_prices: Optional SPY price history

        Returns:
            True if intensity >= 0.5 (write), False otherwise (hold)
        """
        intensity = self.get_overwrite_intensity(dt, spy_prices)
        return intensity >= 0.5

    def get_regime_label(self, dt: date, spy_prices: Optional[Dict[date, float]] = None) -> str:
        """
        Get human-readable regime label for a date.

        Args:
            dt: Date for regime
            spy_prices: Optional SPY price history

        Returns:
            String label like "VIX_HIGH" or "VIX_CRUSHED"
        """
        if self.mode == EdgeMode.ALWAYS_ON:
            return "ALWAYS_ON"

        intensity = self.get_overwrite_intensity(dt, spy_prices)
        if intensity >= 0.9:
            return "VIX_HIGH"
        elif intensity >= 0.7:
            return "VIX_ELEVATED"
        elif intensity >= 0.5:
            return "VIX_NEUTRAL"
        elif intensity >= 0.3:
            return "VIX_LOW"
        else:
            return "VIX_CRUSHED"
