"""Wheel hybrid backtest engine — daily simulation loop."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.backtesting.wheel_hybrid.portfolio import WheelPortfolio
from src.backtesting.wheel_hybrid.premium_model import (
    check_assignment_call,
    check_assignment_put,
    estimate_call_premium,
    estimate_option_mark,
    estimate_put_premium,
    realized_volatility,
    select_call_strike,
    select_call_strike_by_delta,
    select_put_strike,
)
from src.backtesting.wheel_hybrid.metrics import calculate_metrics

logger = structlog.get_logger()


class WheelHybridBacktest:
    """Simulate wheel hybrid strategy with synthetic option pricing."""
    
    def __init__(
        self,
        start_date: str,
        end_date: str,
        initial_nav: float = 10_000.0,
        wheel_pct: float = 0.70,
        directional_pct: float = 0.30,
        max_wheel_names: int = 4,
        max_directional_names: int = 5,
        max_lots_per_name: int = 3,
        cc_target_otm_pct: float = 0.05,
        cc_strike_mode: str = "otm_pct",
        cc_target_delta: float = 0.30,
        cc_dte_range: Tuple[int, int] = (21, 45),
        csp_dte_range: Tuple[int, int] = (14, 45),
        csp_score: int = 55,
        max_csp_collateral_pct: float = 0.45,
        cc_profit_take_pct: float = 0.60,
        manage_dte_threshold: int = 7,
        manage_itm_pct: float = 0.02,
        rf_rate: float = 0.0,
        vol_window: int = 21,
        iv_provider: Optional[object] = None,
        edge_gate: Optional[object] = None,
        regime_detector: Optional[object] = None,
        vix_regime_provider: Optional[object] = None,
        benchmark_ticker: str = "^SPXTR",
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.initial_nav = initial_nav
        self.wheel_pct = wheel_pct
        self.directional_pct = directional_pct
        self.max_wheel_names = max_wheel_names
        self.max_directional_names = max_directional_names
        self.max_lots_per_name = max_lots_per_name
        self.cc_target_otm_pct = cc_target_otm_pct
        self.cc_strike_mode = cc_strike_mode
        self.cc_target_delta = cc_target_delta
        self.cc_dte_range = cc_dte_range
        self.csp_dte_range = csp_dte_range
        self.csp_score = csp_score
        self.max_csp_collateral_pct = max_csp_collateral_pct
        self.cc_profit_take_pct = cc_profit_take_pct
        self.manage_dte_threshold = manage_dte_threshold
        self.manage_itm_pct = manage_itm_pct
        self.rf_rate = rf_rate
        self.vol_window = vol_window
        
        # Edge / regime components (optional, Phase 1 scaffold)
        self.iv_provider = iv_provider
        self.edge_gate = edge_gate
        self.regime_detector = regime_detector
        self.vix_regime_provider = vix_regime_provider
        
        # Benchmark (Phase 2: SPY total return via ^SPXTR, or fallback to SPY price-only)
        self.benchmark_ticker = benchmark_ticker
        
        self.portfolio = WheelPortfolio(initial_nav)
        self.equity_curve: List[Tuple[str, float]] = []
        self.spy_curve: List[Tuple[str, float]] = []  # Keep naming for compatibility
        
        # Historical price cache: {ticker: [(date, close, high, low), ...]}
        self.price_history: Dict[str, List[Tuple[date, float, float, float]]] = {}
    
    def load_price_history(
        self,
        ticker: str,
        data_provider,
    ):
        """Load historical prices for a ticker."""
        try:
            prices = data_provider.get_prices(ticker, self.start_date, self.end_date)
            
            history = []
            for p in prices:
                d = p.time.date() if hasattr(p.time, "date") else p.time
                close = float(p.close)
                high = float(p.high) if hasattr(p, "high") else close
                low = float(p.low) if hasattr(p, "low") else close
                history.append((d, close, high, low))
            
            history.sort(key=lambda x: x[0])
            self.price_history[ticker] = history
            
            logger.info("Loaded price history", ticker=ticker, count=len(history))
            
        except Exception as e:
            logger.error("Failed to load prices", ticker=ticker, error=str(e))
            self.price_history[ticker] = []
    
    def get_price_on_date(self, ticker: str, d: date) -> Optional[float]:
        """Get closing price for ticker on date (or most recent prior)."""
        history = self.price_history.get(ticker, [])
        
        for i in range(len(history) - 1, -1, -1):
            if history[i][0] <= d:
                return history[i][1]
        
        return None
    
    def get_price_history_for_vol(self, ticker: str, d: date, window: int) -> List[float]:
        """Get trailing price history for volatility calculation."""
        history = self.price_history.get(ticker, [])
        
        # Find all prices up to and including date d
        prices = [close for dt, close, _, _ in history if dt <= d]
        
        # Return last 'window + 1' prices (need window+1 for window returns)
        return prices[-(window + 1):] if len(prices) >= window + 1 else prices
    
    def run(
        self,
        universe: List[str],
        data_provider,
    ) -> Dict:
        """
        Run backtest simulation.
        
        Args:
            universe: List of tickers to consider.
            data_provider: Data provider with get_prices() method.
        
        Returns:
            Summary dict with metrics and paths.
        """
        logger.info(
            "Starting wheel hybrid backtest",
            start=self.start_date,
            end=self.end_date,
            nav=self.initial_nav,
            benchmark=self.benchmark_ticker,
        )
        
        # Load price history for all tickers + benchmark
        # Try ^SPXTR (SPY total return), fallback to SPY if unavailable
        benchmark_loaded = False
        for candidate in [self.benchmark_ticker, "SPY"]:
            self.load_price_history(candidate, data_provider)
            if self.price_history.get(candidate):
                self.benchmark_ticker = candidate
                benchmark_loaded = True
                logger.info("Loaded benchmark", ticker=candidate)
                break
        
        if not benchmark_loaded:
            logger.error("Benchmark price history required (tried ^SPXTR and SPY)")
            return {}
        
        # Ensure SPY is loaded for regime (VIX vs SPY RV)
        if "SPY" not in self.price_history:
            self.load_price_history("SPY", data_provider)
            if not self.price_history.get("SPY"):
                logger.warning("SPY not loaded; VIX regime may not work properly")
        
        # Load universe tickers
        for ticker in universe:
            if ticker not in self.price_history:
                self.load_price_history(ticker, data_provider)
        
        # Get trading dates from benchmark
        spy_history = self.price_history.get(self.benchmark_ticker, [])
        if not spy_history:
            logger.error("Benchmark price history required", ticker=self.benchmark_ticker)
            return {}
        
        trading_dates = [d for d, _, _, _ in spy_history]
        
        # Initial benchmark level
        spy_start = spy_history[0][1]
        self.spy_curve.append((trading_dates[0].isoformat(), spy_start))
        
        # Initial NAV
        self.equity_curve.append((trading_dates[0].isoformat(), self.initial_nav))
        
        # Daily loop
        for i, trade_date in enumerate(trading_dates[1:], start=1):
            self._daily_loop(trade_date, universe)
            
            # Record NAV
            prices = {t: self.get_price_on_date(t, trade_date) or 0.0 for t in universe}
            option_marks = self._calculate_option_marks(trade_date, prices)
            nav = self.portfolio.get_nav(prices, option_marks)
            self.equity_curve.append((trade_date.isoformat(), nav))
            
            # Record benchmark
            spy_price = self.get_price_on_date(self.benchmark_ticker, trade_date) or spy_start
            self.spy_curve.append((trade_date.isoformat(), spy_price))
            
            if i % 50 == 0:
                logger.info("Backtest progress", date=trade_date, nav=nav, progress=f"{i}/{len(trading_dates)}")
        
        # Calculate metrics
        metrics = calculate_metrics(
            self.equity_curve,
            self.spy_curve,
            self.initial_nav,
            self.portfolio.premium_collected_total,
            self.portfolio.trades,
        )
        
        logger.info("Backtest complete", metrics=metrics)
        
        return {
            "summary": metrics,
            "equity_curve": self.equity_curve,
            "spy_curve": self.spy_curve,
            "trades": self.portfolio.trades,
            "assumptions": {
                "start_date": self.start_date,
                "end_date": self.end_date,
                "initial_nav": self.initial_nav,
                "wheel_pct": self.wheel_pct,
                "directional_pct": self.directional_pct,
                "max_wheel_names": self.max_wheel_names,
                "max_directional_names": self.max_directional_names,
                "rf_rate": self.rf_rate,
                "vol_window": self.vol_window,
                "universe": universe,
            },
        }
    
    def _daily_loop(self, trade_date: date, universe: List[str]):
        """Execute daily decisions: expiries, rolls, writes, buys."""
        
        # 0. Update regime detector with index VRP (VIX vs SPY RV)
        if self.regime_detector is not None and self.vix_regime_provider is not None:
            spy_prices = self.get_price_history_for_vol("SPY", trade_date, self.vol_window)
            spy_rv = realized_volatility(spy_prices, self.vol_window)
            
            if spy_rv is not None and spy_rv > 0:
                index_vrp = self.vix_regime_provider.compute_index_vrp(trade_date, spy_rv)
                
                self.regime_detector.update(
                    trade_date=trade_date,
                    vrp_avg=index_vrp,  # INDEX VRP: VIX vs SPY RV
                    rv_avg=spy_rv,      # SPY realized vol
                    iv_rank_avg=self.vix_regime_provider.get_vix_percentile(trade_date),
                    equity_trend=None,  # Future: add SPY trend signal
                )
        
        # 1. Handle expirations and assignments
        self._process_expirations(trade_date, universe)
        
        # 2. Manage existing positions (BTC profit-taking, rolls)
        self._manage_positions(trade_date, universe)
        
        # 3. Allocate capital to wheel and directional
        self._allocate_capital(trade_date, universe)
    
    def _process_expirations(self, trade_date: date, universe: List[str]):
        """Check for option expirations and handle assignment."""
        
        # Calls
        for call in list(self.portfolio.short_calls):
            if call.expiry == trade_date:
                price = self.get_price_on_date(call.ticker, trade_date)
                if price is None:
                    # Force expire if no price data (don't leave orphan)
                    logger.warning("No price for call expiry, force expiring", ticker=call.ticker, expiry=call.expiry)
                    self.portfolio.expire_call(call.ticker, call.strike, call.expiry, trade_date)
                    continue
                
                if check_assignment_call(price, call.strike):
                    self.portfolio.assign_call(call.ticker, call.strike, call.expiry, trade_date)
                else:
                    self.portfolio.expire_call(call.ticker, call.strike, call.expiry, trade_date)
        
        # Puts
        for put in list(self.portfolio.short_puts):
            if put.expiry == trade_date:
                price = self.get_price_on_date(put.ticker, trade_date)
                if price is None:
                    # Force expire if no price data (don't leave orphan)
                    logger.warning("No price for put expiry, force expiring", ticker=put.ticker, expiry=put.expiry)
                    self.portfolio.expire_put(put.ticker, put.strike, put.expiry, trade_date)
                    continue
                
                if check_assignment_put(price, put.strike):
                    self.portfolio.assign_put(put.ticker, put.strike, put.expiry, trade_date)
                else:
                    self.portfolio.expire_put(put.ticker, put.strike, put.expiry, trade_date)
        
        # CLEANUP: Force expire any past-expiry options that weren't processed
        for call in list(self.portfolio.short_calls):
            if call.expiry < trade_date:
                logger.error("Orphaned expired call found, force closing", ticker=call.ticker, expiry=call.expiry, days_past=((trade_date - call.expiry).days))
                self.portfolio.expire_call(call.ticker, call.strike, call.expiry, trade_date)
        
        for put in list(self.portfolio.short_puts):
            if put.expiry < trade_date:
                logger.error("Orphaned expired put found, force closing", ticker=put.ticker, expiry=put.expiry, days_past=((trade_date - put.expiry).days))
                self.portfolio.expire_put(put.ticker, put.strike, put.expiry, trade_date)
    
    def _manage_positions(self, trade_date: date, universe: List[str]):
        """Manage existing short options: BTC profit-taking, rolls."""
        
        # Manage calls
        for call in list(self.portfolio.short_calls):
            dte = (call.expiry - trade_date).days
            price = self.get_price_on_date(call.ticker, trade_date)
            
            if price is None:
                continue
            
            # Calculate current mark
            vol_prices = self.get_price_history_for_vol(call.ticker, trade_date, self.vol_window)
            vol = realized_volatility(vol_prices, self.vol_window)
            
            if vol is None:
                continue
            
            current_mark = estimate_option_mark("call", price, call.strike, dte, vol, self.rf_rate)
            
            # BTC if profit target hit
            profit_pct = 1.0 - (current_mark / call.cost_basis_per_share) if call.cost_basis_per_share > 0 else 0.0
            
            if profit_pct >= self.cc_profit_take_pct:
                self.portfolio.buy_to_close_call(
                    call.ticker,
                    call.strike,
                    call.expiry,
                    current_mark,
                    trade_date,
                )
                continue
            
            # Roll if DTE low and ITM
            if dte <= self.manage_dte_threshold:
                otm_pct = (call.strike - price) / price if price > 0 else 0.0
                if otm_pct < -self.manage_itm_pct:
                    # ITM: attempt roll (simplified: just BTC here)
                    self.portfolio.buy_to_close_call(
                        call.ticker,
                        call.strike,
                        call.expiry,
                        current_mark,
                        trade_date,
                    )
        
        # Manage puts
        for put in list(self.portfolio.short_puts):
            dte = (put.expiry - trade_date).days
            price = self.get_price_on_date(put.ticker, trade_date)
            
            if price is None:
                continue
            
            vol_prices = self.get_price_history_for_vol(put.ticker, trade_date, self.vol_window)
            vol = realized_volatility(vol_prices, self.vol_window)
            
            if vol is None:
                continue
            
            current_mark = estimate_option_mark("put", price, put.strike, dte, vol, self.rf_rate)
            
            # BTC if profit target hit
            profit_pct = 1.0 - (current_mark / put.cost_basis_per_share) if put.cost_basis_per_share > 0 else 0.0
            
            if profit_pct >= self.cc_profit_take_pct:
                self.portfolio.buy_to_close_put(
                    put.ticker,
                    put.strike,
                    put.expiry,
                    current_mark,
                    trade_date,
                )
    
    def _allocate_capital(self, trade_date: date, universe: List[str]):
        """Allocate capital to wheel (lots + CSPs) and directional."""
        
        prices = {t: self.get_price_on_date(t, trade_date) for t in universe}
        prices = {t: p for t, p in prices.items() if p is not None and p > 0}
        
        if not prices:
            return
        
        # Calculate current allocations
        current_nav = self._estimate_nav(trade_date, prices)
        if current_nav <= 0:
            return
        
        wheel_mv = self.portfolio.get_wheel_market_value(prices)
        directional_mv = self.portfolio.get_directional_market_value(prices)
        
        target_wheel = current_nav * self.wheel_pct
        target_directional = current_nav * self.directional_pct
        
        # Buy wheel lots if under-allocated
        if wheel_mv < target_wheel * 0.9:
            self._buy_wheel_lots(trade_date, prices, target_wheel - wheel_mv)
        
        # Write covered calls on uncovered lots
        self._write_covered_calls(trade_date, prices)
        
        # Write CSPs if cash-heavy
        self._write_cash_secured_puts(trade_date, prices)
        
        # Buy directional if under-allocated
        if directional_mv < target_directional * 0.9:
            self._buy_directional(trade_date, prices, target_directional - directional_mv)
    
    def _buy_wheel_lots(self, trade_date: date, prices: Dict[str, float], target_amount: float):
        """Buy 100-share lots for wheel sleeve."""
        
        # Count existing lots per ticker
        lot_counts = {}
        for lot in self.portfolio.equity_lots:
            lot_counts[lot.ticker] = lot_counts.get(lot.ticker, 0) + 1
        
        # Filter universe: affordable, not maxed out
        candidates = []
        for ticker, price in prices.items():
            if price <= 0 or price > 35:
                continue
            
            lot_cost = price * 100
            if lot_cost > self.portfolio.cash * 0.8:
                continue
            
            if lot_counts.get(ticker, 0) >= self.max_lots_per_name:
                continue
            
            candidates.append((ticker, price, lot_cost))
        
        if not candidates:
            return
        
        # Sort by lowest cost (diversification)
        candidates.sort(key=lambda x: x[2])
        
        spent = 0.0
        for ticker, price, lot_cost in candidates:
            if spent >= target_amount:
                break
            
            if lot_cost > self.portfolio.cash:
                continue
            
            # Check total unique wheel names
            unique_wheel_tickers = {lot.ticker for lot in self.portfolio.equity_lots}
            if ticker not in unique_wheel_tickers and len(unique_wheel_tickers) >= self.max_wheel_names:
                continue
            
            success = self.portfolio.add_equity_lot(ticker, 100, price, trade_date)
            if success:
                spent += lot_cost
    
    def _write_covered_calls(self, trade_date: date, prices: Dict[str, float]):
        """Write covered calls on uncovered lots."""
        
        # Regime check: Skip CC writes in HOLD_DELTA or DEFENSIVE
        if self.regime_detector is not None:
            if not self.regime_detector.should_write_cc():
                logger.debug(
                    "Skipping CC writes (regime)",
                    date=trade_date,
                    regime=self.regime_detector.get_current_regime().value,
                )
                return
        
        # Find lots without matching short calls
        covered_tickers = {call.ticker for call in self.portfolio.short_calls}
        
        for lot in self.portfolio.equity_lots:
            if lot.ticker in covered_tickers:
                continue
            
            price = prices.get(lot.ticker)
            if price is None or price <= 0:
                continue
            
            # Calculate volatility
            vol_prices = self.get_price_history_for_vol(lot.ticker, trade_date, self.vol_window)
            vol = realized_volatility(vol_prices, self.vol_window)
            
            if vol is None:
                continue
            
            # Edge gate check: Only write if VRP edge detected
            if self.edge_gate is not None:
                allowed, reason = self.edge_gate.should_write_cc(
                    lot.ticker,
                    trade_date,
                    vol,
                    tenor_days=self.vol_window,
                )
                if not allowed:
                    logger.debug(
                        "CC write blocked by edge gate",
                        ticker=lot.ticker,
                        date=trade_date,
                        reason=reason,
                    )
                    continue
            
            # Select strike and expiry
            dte = (self.cc_dte_range[0] + self.cc_dte_range[1]) // 2
            
            if self.cc_strike_mode == "delta":
                strike = select_call_strike_by_delta(
                    price,
                    self.cc_target_delta,
                    dte,
                    vol,
                    self.rf_rate,
                )
            else:  # otm_pct mode (default)
                strike = select_call_strike(price, target_otm_pct=self.cc_target_otm_pct)
            
            expiry = trade_date + timedelta(days=dte)
            
            # Estimate premium
            premium_per_share = estimate_call_premium(price, strike, dte, vol, self.rf_rate)
            
            # Min premium check
            if premium_per_share * 100 < 15.0:
                continue
            
            self.portfolio.write_covered_call(
                lot.ticker,
                strike,
                expiry,
                premium_per_share,
                trade_date,
            )
            
            # Mark as covered
            covered_tickers.add(lot.ticker)
    
    def _write_cash_secured_puts(self, trade_date: date, prices: Dict[str, float]):
        """Write cash-secured puts when cash-heavy."""
        
        current_csp_collateral = self.portfolio.get_csp_collateral()
        current_nav = self._estimate_nav(trade_date, prices)
        
        if current_nav <= 0:
            return
        
        max_csp_collateral = current_nav * self.max_csp_collateral_pct
        available_for_csp = max_csp_collateral - current_csp_collateral
        
        if available_for_csp < 1000:
            return
        
        # Find candidates (not already sold puts)
        put_tickers = {put.ticker for put in self.portfolio.short_puts}
        
        candidates = []
        for ticker, price in prices.items():
            if ticker in put_tickers:
                continue
            
            if price <= 0 or price > 35:
                continue
            
            vol_prices = self.get_price_history_for_vol(ticker, trade_date, self.vol_window)
            vol = realized_volatility(vol_prices, self.vol_window)
            
            if vol is None:
                continue
            
            # Edge gate check: Only write if VRP edge detected
            if self.edge_gate is not None:
                allowed, reason = self.edge_gate.should_write_csp(
                    ticker,
                    trade_date,
                    vol,
                    tenor_days=self.vol_window,
                )
                if not allowed:
                    logger.debug(
                        "CSP write blocked by edge gate",
                        ticker=ticker,
                        date=trade_date,
                        reason=reason,
                    )
                    continue
            
            # Select strike
            strike = select_put_strike(price, self.csp_score)
            collateral = strike * 100
            
            if collateral > available_for_csp:
                continue
            
            # Estimate premium
            dte = (self.csp_dte_range[0] + self.csp_dte_range[1]) // 2
            premium_per_share = estimate_put_premium(price, strike, dte, vol, self.rf_rate)
            premium_total = premium_per_share * 100
            
            # Min premium and yield checks
            if premium_total < 25.0:
                continue
            
            annualized_yield = (premium_per_share / strike) * (365.0 / dte) * 100.0
            if annualized_yield < 8.0:
                continue
            
            candidates.append((ticker, price, strike, dte, premium_per_share, collateral))
        
        if not candidates:
            return
        
        # Sort by annualized yield (descending)
        candidates.sort(key=lambda x: (x[4] / x[2]) * (365.0 / x[3]), reverse=True)
        
        # Write top candidates
        for ticker, price, strike, dte, premium_per_share, collateral in candidates[:3]:
            expiry = trade_date + timedelta(days=dte)
            
            success = self.portfolio.write_cash_secured_put(
                ticker,
                strike,
                expiry,
                premium_per_share,
                trade_date,
            )
            
            if success:
                available_for_csp -= collateral
                if available_for_csp < 1000:
                    break
    
    def _buy_directional(self, trade_date: date, prices: Dict[str, float], target_amount: float):
        """Buy directional positions with residual cash."""
        
        # Count existing directional names
        directional_tickers = {pos.ticker for pos in self.portfolio.directional}
        
        if len(directional_tickers) >= self.max_directional_names:
            return
        
        # Simple heuristic: buy equal-weighted from available tickers
        candidates = [
            (ticker, price)
            for ticker, price in prices.items()
            if price > 0 and price <= 35 and ticker not in directional_tickers
        ]
        
        if not candidates:
            return
        
        # Limit to top few
        candidates = candidates[:self.max_directional_names - len(directional_tickers)]
        
        if not candidates:
            return
        
        per_ticker_budget = min(target_amount / len(candidates), self.portfolio.cash / len(candidates))
        
        for ticker, price in candidates:
            shares = per_ticker_budget / price
            
            if shares < 0.01:
                continue
            
            self.portfolio.add_directional_position(ticker, shares, price, trade_date)
    
    def _estimate_nav(self, trade_date: date, prices: Dict[str, float]) -> float:
        """Estimate current NAV."""
        option_marks = self._calculate_option_marks(trade_date, prices)
        return self.portfolio.get_nav(prices, option_marks)
    
    def _calculate_option_marks(self, trade_date: date, prices: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        """Calculate option marks for NAV."""
        marks = {}
        
        for ticker, price in prices.items():
            if price <= 0:
                continue
            
            vol_prices = self.get_price_history_for_vol(ticker, trade_date, self.vol_window)
            vol = realized_volatility(vol_prices, self.vol_window)
            
            if vol is None:
                continue
            
            marks[ticker] = {}
            
            # Calls
            for call in self.portfolio.short_calls:
                if call.ticker == ticker:
                    dte = (call.expiry - trade_date).days
                    mark = estimate_option_mark("call", price, call.strike, dte, vol, self.rf_rate)
                    key = f"call_{call.strike}_{call.expiry}"
                    marks[ticker][key] = mark
            
            # Puts
            for put in self.portfolio.short_puts:
                if put.ticker == ticker:
                    dte = (put.expiry - trade_date).days
                    mark = estimate_option_mark("put", price, put.strike, dte, vol, self.rf_rate)
                    key = f"put_{put.strike}_{put.expiry}"
                    marks[ticker][key] = mark
        
        return marks
    
    def save_results(self, output_dir: Path):
        """Save equity curve, trades, and summary to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Equity curve
        with open(output_dir / "equity_curve.csv", "w") as f:
            f.write("date,nav,spy\n")
            for (date_str, nav), (_, spy_level) in zip(self.equity_curve, self.spy_curve):
                f.write(f"{date_str},{nav},{spy_level}\n")
        
        # Trades
        with open(output_dir / "trades.csv", "w") as f:
            if self.portfolio.trades:
                keys = set()
                for t in self.portfolio.trades:
                    keys.update(t.keys())
                
                header = sorted(keys)
                f.write(",".join(header) + "\n")
                
                for t in self.portfolio.trades:
                    row = [str(t.get(k, "")) for k in header]
                    f.write(",".join(row) + "\n")
        
        # Summary
        metrics = calculate_metrics(
            self.equity_curve,
            self.spy_curve,
            self.initial_nav,
            self.portfolio.premium_collected_total,
            self.portfolio.trades,
        )
        
        # Add edge gate stats if enabled
        if self.edge_gate is not None:
            metrics["edge_gate"] = self.edge_gate.get_stats()
        
        # Add regime stats if enabled
        if self.regime_detector is not None:
            metrics["regime"] = self.regime_detector.get_stats()
        
        # Add benchmark metadata
        metrics["benchmark"] = self.benchmark_ticker
        
        with open(output_dir / "summary.json", "w") as f:
            json.dump(metrics, f, indent=2)
        
        # Assumptions
        assumptions = {
            "start_date": self.start_date,
            "benchmark": self.benchmark_ticker,
            "end_date": self.end_date,
            "initial_nav": self.initial_nav,
            "wheel_pct": self.wheel_pct,
            "directional_pct": self.directional_pct,
            "rf_rate": self.rf_rate,
            "vol_window": self.vol_window,
        }
        
        with open(output_dir / "assumptions.json", "w") as f:
            json.dump(assumptions, f, indent=2)
        
        logger.info("Results saved", output_dir=str(output_dir))
