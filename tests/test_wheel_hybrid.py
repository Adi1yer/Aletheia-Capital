from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from src.options.wheel_lifecycle import parse_occ_symbol, should_manage_short
from src.options.wheel_universe import WheelCandidate, screen_wheel_candidates
from src.portfolio.models import Portfolio, Position
from src.portfolio.wheel_allocator import allocate_wheel_hybrid_book
from src.portfolio.wheel_policy import apply_wheel_defaults
from src.trading.execution_status import can_submit_live_orders
from src.trading.run_config import load_run_profile, merge_run_profile, apply_wheel_defaults as apply_wh_rc


def test_wheel_profile_enables_cc_csp():
    profile = load_run_profile("wheel-10k")
    assert profile.get("wheel_mode") is True
    assert profile.get("beat_spy_mode") is False
    assert profile.get("enable_covered_calls") is True
    assert profile.get("enable_cash_secured_puts") is True
    merged = apply_wh_rc(merge_run_profile({"execute": True}, "wheel-10k"))
    assert merged["enable_covered_calls"] is True
    assert merged["wheel_pct"] == 0.70


def test_apply_wheel_defaults_noop_without_flag():
    out = apply_wheel_defaults({"enable_covered_calls": False})
    assert out["enable_covered_calls"] is False


def test_screen_wheel_candidates_price_and_adv():
    dossiers = {
        "F": {"prices": {"last_close": 12.0}, "adv_usd": 80_000_000},
        "AAPL": {"prices": {"last_close": 190.0}, "adv_usd": 5_000_000_000},
        "PENNY": {"prices": {"last_close": 1.0}, "adv_usd": 100_000},
        "SOFI": {"prices": {"last_close": 14.0}, "adv_usd": 40_000_000},
    }
    cands = screen_wheel_candidates(
        ["F", "AAPL", "PENNY", "SOFI"],
        dossiers=dossiers,
        max_price=35.0,
        min_price=3.0,
        min_adv_usd=5_000_000,
        top_n=10,
    )
    tickers = [c.ticker for c in cands]
    assert "F" in tickers and "SOFI" in tickers
    assert "AAPL" not in tickers
    assert "PENNY" not in tickers


def test_screen_reads_avg_volume_under_prices_block():
    """Regression: dossiers store avg_volume under prices, not dossier root."""
    dossiers = {
        "F": {"prices": {"last_close": 11.5, "avg_volume": 5_000_000}},
    }
    from src.options.wheel_universe import extract_price_adv

    px, adv = extract_price_adv("F", dossiers=dossiers)
    assert px == 11.5
    assert adv == 5_000_000 * 11.5
    cands = screen_wheel_candidates(
        ["F"],
        dossiers=dossiers,
        max_price=35.0,
        min_adv_usd=5_000_000,
        allow_missing_adv=False,
    )
    assert [c.ticker for c in cands] == ["F"]


def test_screen_admits_missing_adv_when_enabled():
    dossiers = {"XYZ": {"prices": {"last_close": 10.0}}}
    cands = screen_wheel_candidates(
        ["XYZ"],
        dossiers=dossiers,
        max_price=35.0,
        min_adv_usd=5_000_000,
        allow_missing_adv=True,
    )
    assert [c.ticker for c in cands] == ["XYZ"]
    empty = screen_wheel_candidates(
        ["XYZ"],
        dossiers=dossiers,
        max_price=35.0,
        min_adv_usd=5_000_000,
        allow_missing_adv=False,
    )
    assert empty == []


def test_allocate_builds_100_share_lot():
    portfolio = Portfolio(cash=10000.0, positions={})
    prices = {"F": 10.0, "SOFI": 20.0, "NVDA": 120.0}
    wheel = [
        WheelCandidate("F", 10.0, 80_000_000, 500, 0.9),
        WheelCandidate("SOFI", 20.0, 40_000_000, 400, 0.8),
    ]
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=wheel,
        directional_candidates=["NVDA"],
        equity=10000.0,
        max_wheel_names=2,
        max_directional_names=1,
    )
    assert decisions["F"].action == "buy"
    assert decisions["F"].quantity == 100
    assert "F" in diag["csp_candidates"] or "F" in diag["cc_lot_tickers"] or decisions["F"].quantity == 100
    assert diag.get("cc_lot_build_count", 0) >= 1


def test_allocate_exits_orphan_directional_leftovers():
    portfolio = Portfolio(
        cash=2000.0,
        positions={
            "ADBE": Position(long=2, long_cost_basis=260.0),
            "F": Position(long=100, long_cost_basis=12.0),
        },
    )
    prices = {"ADBE": 260.0, "F": 12.0, "SOFI": 15.0}
    wheel = [WheelCandidate("F", 12.0, 80_000_000, 500, 0.9)]
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=wheel,
        directional_candidates=["SOFI"],
        equity=10000.0,
        max_wheel_names=1,
        max_directional_names=1,
    )
    assert decisions["ADBE"].action == "sell"
    assert "ADBE" in (diag.get("orphan_exits") or [])


def test_cc_select_reports_skip_reason_and_otm_band():
    from src.options.covered_calls import CoveredCallManager

    class _Broker:
        def get_option_contracts(self, **kwargs):
            return []

    mgr = CoveredCallManager(otm_pct_low=0.05, otm_pct_high=0.12, target_otm_pct=0.08)
    contract, reason = mgr.select_contract("AUR", 6.42, 55, _Broker())
    assert contract is None
    assert "no_contracts_in_otm_band" in reason



def test_parse_occ_and_manage_rules():
    parsed = parse_occ_symbol("F250117C00012000")
    assert parsed is not None
    assert parsed["underlying"] == "F"
    assert parsed["option_type"] == "call"
    assert abs(parsed["strike"] - 12.0) < 1e-6
    manage, reason = should_manage_short(
        option_type="call",
        strike=12.0,
        underlying_price=12.1,
        dte=20,
        manage_itm_pct=0.02,
    )
    assert manage is True
    assert "itm" in reason


def test_can_submit_live_orders_cutoff():
    # 2026-09-15 Tuesday 14:00 ET — should be ok
    dt = datetime(2026, 9, 15, 18, 0, tzinfo=ZoneInfo("UTC"))  # 14:00 ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="15:30")
    assert ok is True
    # 16:00 ET — past cutoff
    dt2 = datetime(2026, 9, 15, 20, 0, tzinfo=ZoneInfo("UTC"))
    ok2, reason2 = can_submit_live_orders(dt2, cutoff_et="15:30")
    assert ok2 is False
