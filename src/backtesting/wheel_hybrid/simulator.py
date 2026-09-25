"""Wheel-hybrid strategy backtest simulator.

Simulates a simplified wheel-hybrid strategy:
- 70% capital: 100-share wheel lots with covered calls
- 30% capital: directional long-only sleeve
- Option premium collection from CCs and CSPs
- VIX-gated regime control (optional)

Simplifications vs live trading:
- No intraday prices, fill timing, or slippage models
- No option chain selection (assumes 5% OTM calls available)
- No assignment mechanics (assumes always rolled)
- No margin / buying power calculations
- Focus on regime gating effectiveness, not execution details
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd
import structlog

from src.backtesting.wheel_hybrid.edge_gate import EdgeGate, EdgeMode
from src.backtesting.wheel_hybrid.vix_provider import VixDataProvider

logger = structlog.get_logger()


@dataclass
class Position:
    """Position in a single stock."""

    symbol: str
    quantity: int  # Long shares
    cost_basis: float  # Avg cost per share
    has_covered_call: bool = False  # True if CC written on this lot


@dataclass
class BacktestState:
    """Backtest state at a point in time."""

    date: date
    cash: float
    positions: Dict[str, Position] = field(default_factory=dict)
    equity: float = 0.0  # Total portfolio value
    premium_collected: float = 0.0  # Cumulative option premium


@dataclass
class BacktestResult:
    """Results from a backtest run."""

    start_date: date
    end_date: date
    initial_capital: float
    final_equity: float
    total_return: float
    premium_collected: float
    num_cc_writes: int
    num_csp_writes: int
    daily_equity: pd.Series
    edge_mode: str
    metadata: Dict = field(default_factory=dict)


class WheelHybridSimulator:
    """
    Simplified wheel-hybrid backtest simulator.

    Strategy:
    - Buy 100-share lots in wheel universe (assume 10-20 bluechip names)
    - Write 5% OTM covered calls (assume $0.40-1.00 premium per contract ~= 1-3% monthly)
    - CSPs to enter new lots when cash-heavy
    - Directional sleeve holds residual capital
    - VIX gate controls CC write intensity
    """

    def __init__(
        self,
        universe: List[str],
        start_date: date,
        end_date: date,
        initial_capital: float = 10000.0,
        wheel_pct: float = 0.70,
        max_wheel_names: int = 4,
        cc_premium_pct: float = 0.01,  # ~1% monthly premium estimate
        edge_gate: Optional[EdgeGate] = None,
    ):
        """
        Initialize simulator.

        Args:
            universe: List of ticker symbols for wheel candidates
            start_date: Backtest start date
            end_date: Backtest end date
            initial_capital: Starting capital
            wheel_pct: Target % of equity for wheel sleeve
            max_wheel_names: Max number of wheel positions
            cc_premium_pct: Estimated monthly CC premium as % of position value
            edge_gate: Optional EdgeGate for VIX regime control
        """
        self.universe = universe
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.wheel_pct = wheel_pct
        self.max_wheel_names = max_wheel_names
        self.cc_premium_pct = cc_premium_pct
        self.edge_gate = edge_gate or EdgeGate(mode=EdgeMode.ALWAYS_ON)

        self._price_data: Optional[pd.DataFrame] = None
        self._spy_prices: Optional[Dict[date, float]] = None

    def _load_price_data(self):
        """Load historical price data for universe + SPY."""
        import yfinance as yf

        logger.info(
            "Downloading price data",
            universe_size=len(self.universe),
            start=str(self.start_date),
            end=str(self.end_date),
        )

        tickers = list(set(self.universe + ["SPY"]))
        data = yf.download(
            tickers,
            start=self.start_date,
            end=self.end_date + timedelta(days=1),
            progress=False,
        )

        # Extract adjusted close prices
        if "Adj Close" in data.columns:
            closes = data["Adj Close"]
        else:
            closes = data["Close"]

        # Handle single ticker case
        if len(tickers) == 1:
            closes = pd.DataFrame({tickers[0]: closes})

        self._price_data = closes.ffill()

        # Extract SPY prices for RV calculation
        if "SPY" in self._price_data.columns:
            self._spy_prices = {
                dt.date(): float(price)
                for dt, price in self._price_data["SPY"].items()
                if pd.notna(price)
            }

        logger.info(
            "Loaded price data",
            days=len(self._price_data),
            tickers=len(self._price_data.columns),
        )

    def _get_price(self, symbol: str, dt: date) -> Optional[float]:
        """Get closing price for a symbol on a date."""
        if self._price_data is None or symbol not in self._price_data.columns:
            return None
        try:
            timestamp = pd.Timestamp(dt)
            if timestamp not in self._price_data.index:
                return None
            price = self._price_data.loc[timestamp, symbol]
            return float(price) if pd.notna(price) else None
        except Exception:
            return None

    def _select_wheel_candidates(self, dt: date, state: BacktestState) -> List[str]:
        """
        Select best wheel candidates for this date.

        Simple heuristic: prefer names with highest recent price stability
        and not already at max position size.
        """
        candidates = []
        for symbol in self.universe:
            if symbol in state.positions:
                continue
            price = self._get_price(symbol, dt)
            if price and 5.0 <= price <= 50.0:  # Reasonable wheel price range
                candidates.append(symbol)

        # Return top N by alphabetical order (simple deterministic selection)
        return sorted(candidates)[: self.max_wheel_names]

    def _calculate_equity(self, state: BacktestState, dt: date) -> float:
        """Calculate total portfolio equity."""
        equity = state.cash
        for pos in state.positions.values():
            price = self._get_price(pos.symbol, dt)
            if price:
                equity += pos.quantity * price
        return equity

    def _write_covered_calls(self, state: BacktestState, dt: date) -> int:
        """
        Write covered calls on eligible lots based on edge gate.

        Returns number of CCs written.
        """
        intensity = self.edge_gate.get_overwrite_intensity(dt, self._spy_prices)

        writes = 0
        eligible_positions = [
            pos for pos in state.positions.values() if pos.quantity == 100 and not pos.has_covered_call
        ]

        # Write CCs on fraction of positions based on intensity
        num_to_write = int(len(eligible_positions) * intensity)

        for pos in eligible_positions[:num_to_write]:
            price = self._get_price(pos.symbol, dt)
            if price:
                # Estimate premium: ~1% of position value per month
                premium = pos.quantity * price * self.cc_premium_pct
                state.cash += premium
                state.premium_collected += premium
                pos.has_covered_call = True
                writes += 1

        return writes

    def _rebalance(self, state: BacktestState, dt: date):
        """Daily rebalance: allocate to wheel sleeve, write CCs."""
        state.equity = self._calculate_equity(state, dt)

        # Calculate target wheel allocation
        target_wheel_value = state.equity * self.wheel_pct
        current_wheel_value = sum(
            self._get_price(pos.symbol, dt) * pos.quantity
            for pos in state.positions.values()
            if (price := self._get_price(pos.symbol, dt)) is not None
        )

        # Add new wheel lots if under target
        while current_wheel_value < target_wheel_value * 0.95 and len(state.positions) < self.max_wheel_names:
            candidates = self._select_wheel_candidates(dt, state)
            if not candidates:
                break

            symbol = candidates[0]
            price = self._get_price(symbol, dt)
            if not price:
                break

            lot_cost = 100 * price
            if state.cash >= lot_cost:
                # Buy 100-share lot
                state.cash -= lot_cost
                state.positions[symbol] = Position(
                    symbol=symbol,
                    quantity=100,
                    cost_basis=price,
                    has_covered_call=False,
                )
                current_wheel_value += lot_cost

        # Write covered calls
        self._write_covered_calls(state, dt)

    def run(self) -> BacktestResult:
        """
        Run the backtest.

        Returns:
            BacktestResult with performance metrics
        """
        self._load_price_data()

        # Initialize state
        state = BacktestState(
            date=self.start_date,
            cash=self.initial_capital,
        )

        # Track daily equity
        daily_equity = {}
        cc_writes = 0
        csp_writes = 0

        # Iterate through trading days
        trading_days = pd.date_range(self.start_date, self.end_date, freq="B")

        for dt_ts in trading_days:
            dt = dt_ts.date()
            state.date = dt

            # Monthly CC rollover (assume we write CCs monthly)
            if dt.day == 1 or dt == self.start_date:
                # Reset CC flags for new month
                for pos in state.positions.values():
                    pos.has_covered_call = False

            # Daily rebalance
            self._rebalance(state, dt)
            cc_writes += self._write_covered_calls(state, dt)

            # Track equity
            state.equity = self._calculate_equity(state, dt)
            daily_equity[dt] = state.equity

        # Calculate final metrics
        final_equity = state.equity
        total_return = (final_equity / self.initial_capital - 1.0) * 100.0

        result = BacktestResult(
            start_date=self.start_date,
            end_date=self.end_date,
            initial_capital=self.initial_capital,
            final_equity=final_equity,
            total_return=total_return,
            premium_collected=state.premium_collected,
            num_cc_writes=cc_writes,
            num_csp_writes=csp_writes,
            daily_equity=pd.Series(daily_equity),
            edge_mode=self.edge_gate.mode.value,
            metadata={
                "wheel_pct": self.wheel_pct,
                "max_wheel_names": self.max_wheel_names,
                "universe_size": len(self.universe),
            },
        )

        logger.info(
            "Backtest complete",
            edge_mode=result.edge_mode,
            total_return_pct=round(result.total_return, 2),
            final_equity=round(result.final_equity, 2),
            premium_collected=round(result.premium_collected, 2),
        )

        return result
