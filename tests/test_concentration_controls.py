"""Tests for single-name concentration controls (25% threshold)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.portfolio.models import Portfolio, Position
from src.risk.concentration import (
    check_single_name_concentration,
    compute_concentration_trim,
    would_new_buy_breach_concentration,
)


@pytest.fixture
def mock_portfolio_clean():
    """Portfolio with no positions (10k cash)."""
    return Portfolio(cash=10000.0, positions={})


@pytest.fixture
def mock_portfolio_concentrated():
    """Portfolio with NOK at 26% concentration (breaches 25% threshold)."""
    return Portfolio(
        cash=7400.0,
        positions={
            "NOK": Position(long=650, short=0, long_cost_basis=4.0),
        },
    )


@pytest.fixture
def mock_portfolio_multiple():
    """Portfolio with multiple positions, NOK at 26%."""
    return Portfolio(
        cash=5000.0,
        positions={
            "NOK": Position(long=650, short=0, long_cost_basis=4.0),
            "F": Position(long=200, short=0, long_cost_basis=12.0),
            "T": Position(long=100, short=0, long_cost_basis=18.0),
        },
    )


@pytest.fixture
def mock_prices():
    """Mock current prices."""
    return {
        "NOK": 4.0,
        "F": 12.0,
        "T": 18.0,
        "SOFI": 7.5,
    }


# ============================================================================
# (a) New-buy gate at 25%: block any new buy that would reach 25%
# ============================================================================


def test_new_buy_gate_blocks_at_25pct_threshold(mock_portfolio_clean, mock_prices):
    """New buy gate blocks buy that would leave name at exactly 25%."""
    # 10k NAV, buying 333 shares @ $7.50 = $2,497.50 (24.975%)
    # Buying 334 shares @ $7.50 = $2,505.00 (25.05%) → BLOCKED
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="SOFI",
        buy_qty=334,
        price=7.5,
        portfolio=mock_portfolio_clean,
        current_prices=mock_prices,
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is True
    assert details["post_buy_weight_pct"] >= 25.0
    assert details["would_breach"] is True
    assert details["ticker"] == "SOFI"


def test_new_buy_gate_allows_just_under_25pct(mock_portfolio_clean, mock_prices):
    """New buy gate allows buy that leaves name just under 25%."""
    # 10k NAV, buying 333 shares @ $7.50 = $2,497.50 (24.975%) → OK
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="SOFI",
        buy_qty=333,
        price=7.5,
        portfolio=mock_portfolio_clean,
        current_prices=mock_prices,
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is False
    assert details["post_buy_weight_pct"] < 25.0
    assert details["would_breach"] is False


def test_new_buy_gate_accounts_for_existing_shares(mock_portfolio_multiple, mock_prices):
    """New buy gate accounts for existing shares when checking threshold."""
    # Portfolio has NOK=650 @ $4 = $2,600 (26% of 10k NAV)
    # Already breached; buying 1 more share would keep it breached
    
    equity = 7400.0 + 650 * 4.0 + 200 * 12.0 + 100 * 18.0  # ~10k
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="NOK",
        buy_qty=1,
        price=4.0,
        portfolio=mock_portfolio_multiple,
        current_prices=mock_prices,
        equity=equity,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is True
    assert details["held_qty"] == 650
    assert details["post_buy_qty"] == 651


def test_new_buy_gate_fails_closed_on_missing_price(mock_portfolio_clean, mock_prices):
    """New buy gate blocks (fail-closed) when price unavailable."""
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="UNKNOWN",
        buy_qty=100,
        price=0.0,  # Missing price
        portfolio=mock_portfolio_clean,
        current_prices={},
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is True
    assert "error" in details
    assert "fail_closed" in details["error"]


def test_new_buy_gate_fails_closed_on_missing_equity(mock_portfolio_clean, mock_prices):
    """New buy gate blocks (fail-closed) when equity unavailable."""
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="SOFI",
        buy_qty=100,
        price=7.5,
        portfolio=mock_portfolio_clean,
        current_prices=mock_prices,
        equity=0.0,  # Invalid equity
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is True
    assert "error" in details
    assert "fail_closed" in details["error"]


# ============================================================================
# (b) Auto-trim: compute and submit trim orders when enabled
# ============================================================================


def test_auto_trim_computes_trim_for_breach(mock_portfolio_concentrated, mock_prices):
    """Auto-trim computes correct trim quantity for name above threshold."""
    # NOK: 650 shares @ $4 = $2,600 (26% of 10k)
    # Target 20% = $2,000 → excess $600 → trim 150 shares
    
    trim_details = compute_concentration_trim(
        ticker="NOK",
        portfolio=mock_portfolio_concentrated,
        current_prices=mock_prices,
        equity=10000.0,
        threshold_pct=0.25,
        target_pct=0.20,
        min_trim_shares=10,
        fail_closed_on_missing_data=True,
        short_calls_by_underlying={},
    )
    
    assert trim_details is not None
    assert trim_details["status"] == "trim_needed"
    assert trim_details["trim_qty"] == 150
    assert trim_details["current_weight_pct"] == 26.0
    assert 19.0 < trim_details["post_trim_weight_pct"] < 21.0


def test_auto_trim_respects_min_trim_shares(mock_portfolio_concentrated, mock_prices):
    """Auto-trim skips trim when below min_trim_shares."""
    # Set min very high so 150-share trim is below min
    
    trim_details = compute_concentration_trim(
        ticker="NOK",
        portfolio=mock_portfolio_concentrated,
        current_prices=mock_prices,
        equity=10000.0,
        threshold_pct=0.25,
        target_pct=0.20,
        min_trim_shares=200,  # Higher than computed 150
        fail_closed_on_missing_data=True,
        short_calls_by_underlying={},
    )
    
    assert trim_details is not None
    assert trim_details["status"] == "trim_below_min"
    assert trim_details["trim_qty"] == 0
    assert trim_details["trim_qty_before_min"] < 200


def test_auto_trim_never_sells_short_call_collateral(mock_portfolio_concentrated, mock_prices):
    """Auto-trim never sells shares covering short calls."""
    # NOK: 650 shares, 5 short calls (500 shares collateral)
    # Only 150 shares available to sell
    
    trim_details = compute_concentration_trim(
        ticker="NOK",
        portfolio=mock_portfolio_concentrated,
        current_prices=mock_prices,
        equity=10000.0,
        threshold_pct=0.25,
        target_pct=0.20,
        min_trim_shares=10,
        fail_closed_on_missing_data=True,
        short_calls_by_underlying={"NOK": 5},  # 5 contracts = 500 shares
    )
    
    assert trim_details is not None
    assert trim_details["covered_shares"] == 500
    assert trim_details["available_to_sell"] == 150
    assert trim_details["trim_qty"] <= 150


def test_auto_trim_returns_none_when_no_breach(mock_portfolio_clean, mock_prices):
    """Auto-trim returns None when name not above threshold."""
    
    trim_details = compute_concentration_trim(
        ticker="NOK",
        portfolio=mock_portfolio_clean,
        current_prices=mock_prices,
        equity=10000.0,
        threshold_pct=0.25,
        target_pct=0.20,
        min_trim_shares=10,
        fail_closed_on_missing_data=True,
        short_calls_by_underlying={},
    )
    
    assert trim_details is None


def test_auto_trim_fails_closed_on_missing_data(mock_portfolio_concentrated, mock_prices):
    """Auto-trim returns None (fail-closed) when price missing."""
    
    trim_details = compute_concentration_trim(
        ticker="UNKNOWN",
        portfolio=mock_portfolio_concentrated,
        current_prices={},  # No prices
        equity=10000.0,
        threshold_pct=0.25,
        target_pct=0.20,
        min_trim_shares=10,
        fail_closed_on_missing_data=True,
        short_calls_by_underlying={},
    )
    
    assert trim_details is None


# ============================================================================
# (c) Daily Position Health Check fails on breach
# ============================================================================


def test_concentration_check_passes_when_all_under_threshold(mock_portfolio_multiple, mock_prices):
    """Concentration check passes when all names under 25%."""
    # Adjust NOK to be under threshold
    portfolio = Portfolio(
        cash=7600.0,
        positions={
            "NOK": Position(long=600, short=0, long_cost_basis=4.0),  # 24%
            "F": Position(long=200, short=0, long_cost_basis=12.0),
            "T": Position(long=100, short=0, long_cost_basis=18.0),
        },
    )
    
    equity = 7600.0 + 600 * 4.0 + 200 * 12.0 + 100 * 18.0
    
    passed, alerts, diagnostics = check_single_name_concentration(
        portfolio=portfolio,
        current_prices=mock_prices,
        equity=equity,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert passed is True
    assert len(alerts) == 0
    assert diagnostics["passed"] is True
    assert diagnostics["max_concentration_pct"] < 25.0


def test_concentration_check_fails_when_name_at_threshold(mock_portfolio_concentrated, mock_prices):
    """Concentration check fails when any name at or above 25%."""
    
    passed, alerts, diagnostics = check_single_name_concentration(
        portfolio=mock_portfolio_concentrated,
        current_prices=mock_prices,
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert passed is False
    assert len(alerts) == 1
    assert alerts[0]["ticker"] == "NOK"
    assert alerts[0]["weight_pct"] >= 25.0
    assert diagnostics["passed"] is False


def test_concentration_check_fails_closed_on_missing_prices(mock_portfolio_concentrated):
    """Concentration check fails (fail-closed) when prices unavailable."""
    
    passed, alerts, diagnostics = check_single_name_concentration(
        portfolio=mock_portfolio_concentrated,
        current_prices={},  # No prices
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert passed is False
    assert len(alerts) >= 1
    assert any("price_unavailable" in a.get("reason", "") for a in alerts)


# ============================================================================
# (d) Put path concentration check
# ============================================================================


def test_csp_concentration_check_blocks_assignment_breach(mock_portfolio_clean, mock_prices):
    """CSP path blocks put sell when assignment would breach 25%."""
    # 10k NAV, assignment of 100 shares @ $30 = $3,000 (30%) → BLOCKED
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="EXPENSIVE",
        buy_qty=100,  # Assignment = 100 shares
        price=30.0,
        portfolio=mock_portfolio_clean,
        current_prices={"EXPENSIVE": 30.0},
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is True
    assert details["post_buy_weight_pct"] >= 25.0


def test_csp_concentration_check_allows_safe_assignment(mock_portfolio_clean, mock_prices):
    """CSP path allows put sell when assignment stays under 25%."""
    # 10k NAV, assignment of 100 shares @ $20 = $2,000 (20%) → OK
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="SAFE",
        buy_qty=100,
        price=20.0,
        portfolio=mock_portfolio_clean,
        current_prices={"SAFE": 20.0},
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is False
    assert details["post_buy_weight_pct"] < 25.0


def test_csp_concentration_check_accounts_for_existing_shares(mock_portfolio_multiple, mock_prices):
    """CSP path accounts for existing shares when checking assignment."""
    # Portfolio has NOK=650 @ $4 = $2,600 (26% of 10k NAV)
    # Assignment of 100 more @ $4 = $3,000 (30%) → BLOCKED
    
    equity = 7400.0 + 650 * 4.0 + 200 * 12.0 + 100 * 18.0
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="NOK",
        buy_qty=100,
        price=4.0,
        portfolio=mock_portfolio_multiple,
        current_prices=mock_prices,
        equity=equity,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is True
    assert details["held_qty"] == 650
    assert details["post_buy_qty"] == 750


def test_csp_concentration_check_fails_closed_on_missing_nav(mock_portfolio_clean, mock_prices):
    """CSP path blocks (fail-closed) when NAV unavailable."""
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="SOFI",
        buy_qty=100,
        price=7.5,
        portfolio=mock_portfolio_clean,
        current_prices=mock_prices,
        equity=0.0,  # Invalid NAV
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert would_breach is True
    assert "error" in details
    assert "fail_closed" in details["error"]


# ============================================================================
# Integration tests with broker patches
# ============================================================================


@pytest.fixture
def mock_broker():
    """Mock AlpacaBroker for integration tests."""
    broker = MagicMock()
    broker.get_account.return_value = {"equity": 10000.0, "cash": 7400.0}
    broker.get_positions.return_value = [
        {"symbol": "NOK", "qty": 650, "side": "long", "current_price": 4.0},
    ]
    broker.get_option_positions.return_value = []
    
    # Mock portfolio
    portfolio = Portfolio(
        cash=7400.0,
        positions={"NOK": Position(long=650, short=0, long_cost_basis=4.0)},
    )
    broker.sync_portfolio.return_value = portfolio
    
    return broker


def test_csp_execute_with_concentration_check_integration(mock_broker, mock_prices):
    """Integration test: CSP execution checks concentration before selling puts."""
    from src.options.cash_secured_puts import CashSecuredPutManager
    
    manager = CashSecuredPutManager(
        min_premium_pct=0.003,
        min_premium_usd=25.0,
        min_annualized_yield_pct=8.0,
    )
    
    # Mock put contract selection
    mock_contract = {
        "symbol": "NOK241115P00004000",
        "underlying": "NOK",
        "strike": 4.0,
        "expiry": "2024-11-15",
        "tradable": True,
    }
    
    with patch.object(manager, "select_put_contract", return_value=mock_contract):
        results = manager.execute_cash_secured_puts(
            broker=mock_broker,
            csp_tickers=["NOK"],
            csp_scores={"NOK": 60},
            current_prices=mock_prices,
            max_collateral_usd=5000.0,
            wait_fill=False,
            collateral_already_used_usd=0.0,
            option_positions=[],
            concentration_threshold_pct=0.25,
        )
    
    # Should be skipped due to concentration breach
    assert len(results) == 1
    assert results[0]["status"] == "skipped"
    assert "concentration" in results[0]["reason"]


def test_concentration_trim_script_dry_run(tmp_path, mock_broker, mock_prices):
    """Integration test: auto-trim script dry-run."""
    import sys
    from scripts.concentration_auto_trim import main
    
    # Mock broker connection
    with patch("scripts.concentration_auto_trim.get_alpaca_broker", return_value=mock_broker):
        with patch.dict("os.environ", {"ENABLE_CONCENTRATION_TRIM": "1"}):
            exit_code = main(["--enable"])  # Force enable
    
    # Dry-run should succeed (exit 0)
    assert exit_code == 0


# ============================================================================
# Edge cases and error handling
# ============================================================================


def test_concentration_check_handles_empty_portfolio():
    """Concentration check handles empty portfolio gracefully."""
    portfolio = Portfolio(cash=10000.0, positions={})
    
    passed, alerts, diagnostics = check_single_name_concentration(
        portfolio=portfolio,
        current_prices={},
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    assert passed is True
    assert len(alerts) == 0
    assert diagnostics["positions_checked"] == 0


def test_new_buy_gate_handles_nan_values():
    """New buy gate handles NaN/inf values gracefully."""
    portfolio = Portfolio(cash=10000.0, positions={})
    
    would_breach, details = would_new_buy_breach_concentration(
        ticker="TEST",
        buy_qty=100,
        price=float("nan"),  # NaN price
        portfolio=portfolio,
        current_prices={},
        equity=10000.0,
        threshold_pct=0.25,
        fail_closed_on_missing_data=True,
    )
    
    # Should fail-closed on invalid data
    assert would_breach is True
    assert "error" in details


def test_trim_with_all_shares_covering_calls():
    """Trim handles case where all shares are collateral for short calls."""
    portfolio = Portfolio(
        cash=7400.0,
        positions={"NOK": Position(long=650, short=0, long_cost_basis=4.0)},
    )
    
    # All 650 shares cover 6.5 short calls (round to 7 contracts = 700 shares)
    trim_details = compute_concentration_trim(
        ticker="NOK",
        portfolio=portfolio,
        current_prices={"NOK": 4.0},
        equity=10000.0,
        threshold_pct=0.25,
        target_pct=0.20,
        min_trim_shares=10,
        fail_closed_on_missing_data=True,
        short_calls_by_underlying={"NOK": 7},  # All shares covered
    )
    
    # Should return trim_below_min (no shares available)
    assert trim_details is not None
    assert trim_details["trim_qty"] == 0
    assert trim_details["available_to_sell"] == 0
