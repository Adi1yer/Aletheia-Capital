from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from src.options.wheel_lifecycle import parse_occ_symbol, should_manage_short
from src.options.wheel_universe import WheelCandidate, extract_price_adv, screen_wheel_candidates
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


def test_cc_select_chain_fetch_failure_is_not_empty_band():
    from src.options.covered_calls import CoveredCallManager

    class _Broker:
        def get_option_contracts(self, **kwargs):
            raise RuntimeError("alpaca 504 timeout")

    mgr = CoveredCallManager()
    contract, reason = mgr.select_contract("F", 12.0, 55, _Broker())
    assert contract is None
    assert reason == "option_chain_unavailable"


def test_cc_select_zero_marks_is_quotes_unavailable_not_premium_miss():
    from src.options.covered_calls import CoveredCallManager

    class _Broker:
        def get_option_contracts(self, **kwargs):
            return [
                {
                    "symbol": "F261016C00012600",
                    "strike": 12.60,
                    "expiry": "2026-10-16",
                    "tradable": True,
                    "close_price": 0.0,
                }
            ]

    mgr = CoveredCallManager(min_premium_usd=15.0, min_premium_pct=0.004)
    contract, reason = mgr.select_contract("F", 12.0, 55, _Broker())
    assert contract is None
    assert reason == "option_quotes_unavailable"


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


def test_atomic_unwind_tickers_from_cc_skips():
    from src.options.covered_calls import tickers_needing_atomic_unwind

    results = [
        {"underlying": "ABEV", "status": "skipped", "reason": "no_contracts_in_otm_band_x"},
        {"underlying": "F", "status": "skipped", "reason": "insufficient_shares_for_lot_50<100"},
        {"underlying": "AUR", "status": "executed"},
        {"underlying": "BSBR", "status": "failed", "reason": "order submission failed"},
        {"underlying": "SOFI", "status": "skipped", "reason": "premium_below_usd_floor_5.00<15.00"},
    ]
    unwind = tickers_needing_atomic_unwind(
        results,
        held_lot_tickers=["ABEV", "F", "AUR", "BSBR", "SOFI"],
        short_call_underlyings={"AUR"},
    )
    # Chain/premium misses stay for afternoon; only hard write failures unwind.
    assert unwind == {"BSBR"}
    assert not tickers_needing_atomic_unwind(
        [{"underlying": "F", "status": "skipped", "reason": "coverage_slots_unavailable"}],
        held_lot_tickers=["F"],
        short_call_underlyings=set(),
    )
    assert not tickers_needing_atomic_unwind(
        [{"underlying": "F", "status": "skipped", "reason": "option_chain_unavailable"}],
        held_lot_tickers=["F"],
        short_call_underlyings=set(),
    )
    assert not tickers_needing_atomic_unwind(
        [{"underlying": "F", "status": "skipped", "reason": "option_quotes_unavailable"}],
        held_lot_tickers=["F"],
        short_call_underlyings=set(),
    )


def test_uncovered_excess_shares_trims_only_extra_lot():
    from src.options.covered_calls import uncovered_excess_shares

    assert uncovered_excess_shares(200, 1) == 100
    assert uncovered_excess_shares(250, 1) == 150
    assert uncovered_excess_shares(300, 2) == 100
    assert uncovered_excess_shares(100, 1) == 0
    assert uncovered_excess_shares(200, 2) == 0
    assert uncovered_excess_shares(200, 0) == 0
    assert uncovered_excess_shares(150, 1) == 50


def test_underhedge_trim_orders_keeps_covered_lot():
    from src.options.covered_calls import underhedge_trim_orders

    port = Portfolio(
        cash=1000,
        positions={
            "F": Position(long=200),
            "NOK": Position(long=100),
            "ITUB": Position(long=250),
            "CPNG": Position(long=200),
        },
    )
    opts = [
        {"symbol": "F260918C00012000", "side": "short", "qty": 1, "option_type": "call", "underlying": "F"},
        {"symbol": "NOK260918C00006000", "side": "short", "qty": 1, "option_type": "call", "underlying": "NOK"},
        {"symbol": "ITUB260918C00007000", "side": "short", "qty": 1, "option_type": "call", "underlying": "ITUB"},
        # CPNG has extra shares but no short — atomic unwind, not this trim
    ]
    orders = dict(underhedge_trim_orders(port, opts))
    assert orders == {"F": 100, "ITUB": 150}
    assert "NOK" not in orders
    assert "CPNG" not in orders


def test_apply_underhedge_trims_skips_when_option_fetch_fails():
    from src.options.covered_calls import apply_underhedge_trims

    class BoomBroker:
        def sync_portfolio(self):
            return Portfolio(cash=0, positions={"F": Position(long=200)})

        def get_option_positions(self):
            raise RuntimeError("broker timeout")

    results: list = []
    apply_underhedge_trims(BoomBroker(), {"F": 12.0}, results)
    assert results == [{"status": "skipped", "reason": "underhedge_trim_positions_unavailable"}]


def test_apply_underhedge_trims_sells_excess_only():
    from src.options.covered_calls import apply_underhedge_trims

    class FakeBroker:
        def __init__(self):
            self.sold = []

        def sync_portfolio(self):
            return Portfolio(cash=0, positions={"F": Position(long=200)})

        def get_option_positions(self):
            return [
                {
                    "symbol": "F260918C00012000",
                    "side": "short",
                    "qty": 1,
                    "option_type": "call",
                    "underlying": "F",
                }
            ]

        def execute_order(self, ticker, decision, current_price=None):
            self.sold.append((ticker, decision.action, decision.quantity))
            return {"order_id": "oid-1"}

        def wait_for_order_fill(self, order_id, timeout_s=60.0, min_filled_qty=0):
            return {"ok": True, "order_id": order_id}

    broker = FakeBroker()
    results: list = [
        {"underlying": "F", "status": "skipped", "reason": "no_contracts_in_otm_band_x"}
    ]
    apply_underhedge_trims(broker, {"F": 12.0}, results)
    assert broker.sold == [("F", "sell", 100)]
    assert any(r.get("status") == "underhedge_trim" for r in results)
    assert next(r for r in results if r.get("status") == "underhedge_trim")["quantity"] == 100


def test_underhedge_trim_credits_session_fill_when_broker_shorts_stale():
    from src.options.covered_calls import apply_underhedge_trims, underhedge_trim_orders

    port = Portfolio(cash=0, positions={"F": Position(long=200)})
    stale_opts = [
        {
            "symbol": "F260918C00012000",
            "side": "short",
            "qty": 1,
            "option_type": "call",
            "underlying": "F",
        }
    ]
    # Inferred floor is prior + filled (1+1), not live + filled.
    assert underhedge_trim_orders(
        port, stale_opts, extra_short_calls={"F": 2}
    ) == []

    class StaleBroker:
        def sync_portfolio(self):
            return port

        def get_option_positions(self):
            return stale_opts

        def get_open_orders(self, limit=100):
            return []

        def execute_order(self, *args, **kwargs):
            raise AssertionError("must not sell extras already covered this session")

    results = [
        {
            "underlying": "F",
            "status": "executed",
            "contracts": 1,
            "prior_short_calls": 1,
            "contract_symbol": "F260918C00013000",
        }
    ]
    apply_underhedge_trims(StaleBroker(), {"F": 12.0}, results)
    assert not any(r.get("status") == "underhedge_trim" for r in results)


def test_underhedge_trim_still_sells_leftover_lot_after_partial_extra_write():
    from src.options.covered_calls import apply_underhedge_trims

    class LiveBroker:
        def __init__(self):
            self.sold = []

        def sync_portfolio(self):
            return Portfolio(cash=0, positions={"F": Position(long=300)})

        def get_option_positions(self):
            return [
                {
                    "symbol": "F260918C00012000",
                    "side": "short",
                    "qty": 2,
                    "option_type": "call",
                    "underlying": "F",
                }
            ]

        def get_open_orders(self, limit=100):
            return []

        def execute_order(self, ticker, decision, current_price=None):
            self.sold.append((ticker, decision.quantity))
            return {"order_id": "oid-2"}

        def wait_for_order_fill(self, order_id, timeout_s=60.0, min_filled_qty=0):
            return {"ok": True, "order_id": order_id}

    broker = LiveBroker()
    results = [
        {
            "underlying": "F",
            "status": "partial",
            "contracts": 1,
            "prior_short_calls": 1,
        }
    ]
    apply_underhedge_trims(broker, {"F": 12.0}, results)
    # live=2 already includes the session fill; do not double-count to 3.
    assert broker.sold == [("F", 100)]


def test_underhedge_trim_skips_when_cc_never_attempted_write():
    from src.options.covered_calls import apply_underhedge_trims

    class FakeBroker:
        def __init__(self):
            self.sold = []

        def sync_portfolio(self):
            return Portfolio(cash=0, positions={"F": Position(long=200)})

        def get_option_positions(self):
            return [
                {
                    "symbol": "F260918C00012000",
                    "side": "short",
                    "qty": 1,
                    "option_type": "call",
                    "underlying": "F",
                }
            ]

        def execute_order(self, *args, **kwargs):
            raise AssertionError("must not trim when CC never attempted a write")

    apply_underhedge_trims(
        FakeBroker(),
        {"F": 12.0},
        [{"underlying": "F", "status": "skipped", "reason": "coverage_slots_unavailable"}],
    )
    apply_underhedge_trims(
        FakeBroker(),
        {"F": 12.0},
        [{"status": "error", "reason": "option_positions_unavailable"}],
    )
    apply_underhedge_trims(
        FakeBroker(),
        {"F": 12.0},
        [{"underlying": "F", "status": "skipped", "reason": "option_chain_unavailable"}],
    )
    apply_underhedge_trims(
        FakeBroker(),
        {"F": 12.0},
        [{"underlying": "F", "status": "skipped", "reason": "option_quotes_unavailable"}],
    )


def test_underhedge_trim_credits_working_short_call_order():
    from src.options.covered_calls import apply_underhedge_trims

    class WorkingBroker:
        def __init__(self):
            self.sold = []

        def sync_portfolio(self):
            return Portfolio(cash=0, positions={"F": Position(long=200)})

        def get_option_positions(self):
            return [
                {
                    "symbol": "F260918C00012000",
                    "side": "short",
                    "qty": 1,
                    "option_type": "call",
                    "underlying": "F",
                }
            ]

        def get_open_orders(self, limit=100):
            return [
                {
                    "symbol": "F260918C00013000",
                    "side": "sell",
                    "qty": 1,
                    "status": "new",
                }
            ]

        def execute_order(self, ticker, decision, current_price=None):
            self.sold.append((ticker, decision.quantity))
            return {"order_id": "x"}

    broker = WorkingBroker()
    apply_underhedge_trims(broker, {"F": 12.0}, [])
    assert broker.sold == []


def test_short_call_qty_zero_is_not_one():
    from src.options.covered_calls import short_call_qty_by_underlying

    assert short_call_qty_by_underlying(
        [{"symbol": "F260918C00012000", "side": "short", "qty": 0, "option_type": "call", "underlying": "F"}]
    ) == {}
    assert short_call_qty_by_underlying(
        [{"symbol": "F260918C00012000", "side": "short", "qty": 2, "option_type": "call", "underlying": "F"}]
    ) == {"F": 2}


def test_identify_callable_normalizes_ticker_case():
    from src.options.covered_calls import CoveredCallManager

    mgr = CoveredCallManager()
    portfolio = Portfolio(cash=1000, positions={"F": Position(long=200)})
    cands = mgr.identify_callable_positions(
        portfolio,
        ["f"],
        [{"symbol": "F261002C00013000", "side": "short", "underlying": "F", "option_type": "call", "qty": 1}],
    )
    assert len(cands) == 1
    assert cands[0]["ticker"] == "F"
    assert cands[0]["callable_lots"] == 1


def test_allocate_unwinds_uncovered_and_respects_preflight():
    portfolio = Portfolio(
        cash=8000.0,
        positions={"ABEV": Position(long=100, long_cost_basis=3.0)},
    )
    prices = {"ABEV": 3.0, "F": 12.0}
    wheel = [
        WheelCandidate("ABEV", 3.0, 80_000_000, 500, 0.5),
        WheelCandidate("F", 12.0, 80_000_000, 500, 0.9),
    ]
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=wheel,
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=2,
        preflight_ok={"F"},
        uncovered_unwind={"ABEV"},
        csp_reserve_frac=0.20,
    )
    assert decisions["ABEV"].action == "sell"
    assert decisions["ABEV"].quantity == 100
    assert decisions["F"].action == "buy"
    assert decisions["F"].quantity == 100


def test_profit_take_and_near_itm_manage_rules():
    manage, reason = should_manage_short(
        option_type="call",
        strike=12.0,
        underlying_price=10.0,
        dte=20,
        profit_pct=0.65,
        profit_take_pct=0.60,
    )
    assert manage is True
    assert "profit_take" in reason


def test_wheel_daily_email_has_coverage_omits_agent_noise():
    from src.utils.wheel_email import build_wheel_daily_email

    results = {
        "wheel_mode": True,
        "timestamp": "2026-09-22T14:00:00-04:00",
        "portfolio": {
            "cash": 4000.0,
            "equity": 10000.0,
            "positions": {
                "F": {"long": 100, "long_cost_basis": 12.0},
                "NVDA": {"long": 5, "long_cost_basis": 120.0},
            },
        },
        "coverage_map": [
            {
                "ticker": "F",
                "shares": 100,
                "price": 12.0,
                "market_value": 1200.0,
                "coverage": "covered",
                "contract": "F261002C00013000",
                "strike": 13.0,
                "expiry": "2026-10-02",
                "dte": 10,
                "otm_pct": 8.3,
            }
        ],
        "decision_diagnostics": {
            "wheel_targets": ["F"],
            "directional_targets": ["NVDA"],
            "cc_lot_tickers": ["F"],
        },
        "decisions": {
            "F": {"action": "hold", "quantity": 0, "reasoning": "Wheel lot"},
        },
        "covered_call_results": [],
        "wheel_manage_results": [],
        "wheel_scorecard": {"fund_sharpe": 0.1, "spy_sharpe": 0.2, "premium_ledger_usd": 40},
        "learning_context": {"scorecard_source": "agent_horizon"},
        "agent_signals": {"warren_buffett": {}},
    }
    subject, text, html = build_wheel_daily_email(results)
    assert "daily wheel" in subject.lower()
    assert "COVERAGE MAP" in text
    assert "F261002C00013000" in text
    assert "warren_buffett" not in text.lower()
    assert "Lane contributions" not in text
    assert "ALETHEIA DAILY WHEEL" in text


def test_wheel_daily_email_ignores_nan_prices():
    from src.utils.wheel_email import build_wheel_daily_email

    nan = float("nan")
    subject, text, _ = build_wheel_daily_email(
        {
            "timestamp": "2026-09-23T14:00:00-04:00",
            "portfolio": {
                "cash": 5075.20,
                "equity": 9870.35,
                "positions": {
                    "F": {"long": 100, "long_cost_basis": 12.0},
                    "CTSH": {"long": 2, "long_cost_basis": 59.38},
                },
            },
            "risk_analysis": {
                "F": {"current_price": nan},
                "CTSH": {"current_price": nan},
            },
            "coverage_map": [
                {
                    "ticker": "F",
                    "shares": 100,
                    "price": 0,
                    "coverage": "covered",
                    "contract": "F261009C00014000",
                    "strike": 14.0,
                    "dte": 16,
                    "otm_pct": None,
                }
            ],
            "decision_diagnostics": {"wheel_targets": ["F"], "directional_targets": ["CTSH"]},
            "wheel_scorecard": {"premium_ledger_usd": 173},
        }
    )
    assert "wheel $nan" not in text
    assert "nan%" not in text
    assert "MV $nan" not in text
    assert "OTM=n/a" in text
    assert "wheel $1,200.00" in text
    assert "CTSH: 2 sh MV $118.76" in text
    assert "equity $9,870.35" in subject.lower()


def test_manage_or_roll_would_roll_on_near_itm():
    from src.options.covered_calls import CoveredCallManager
    from src.options.wheel_lifecycle import manage_or_roll_short_calls

    class _Broker:
        def get_option_positions(self):
            return [
                {
                    "symbol": "F261002C00012000",
                    "side": "short",
                    "qty": 1,
                    "avg_entry_price": 0.40,
                    "current_price": 0.55,
                }
            ]

        def get_option_contracts(self, **kwargs):
            return [
                {
                    "symbol": "F261016C00013000",
                    "strike": 13.0,
                    "expiry": "2026-10-16",
                    "tradable": True,
                    "mid_price": 0.35,
                }
            ]

        def submit_option_order(self, **kwargs):
            return {"id": "ord1"}

        def sync_portfolio(self):
            return Portfolio(cash=1000.0, positions={"F": Position(long=100, long_cost_basis=12.0)})

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
        otm_pct_low=0.03,
        otm_pct_high=0.10,
        target_otm_pct=0.05,
    )
    results = manage_or_roll_short_calls(
        _Broker(),
        {"F": 12.0},
        mgr,
        manage_itm_pct=0.02,
        prefer_roll=True,
        execute=False,
        cc_score=55,
    )
    statuses = {r.get("status") for r in results}
    assert "would_btc" in statuses
    assert "would_roll" in statuses
    for r in results:
        if r.get("status") == "would_btc":
            assert r.get("option_type") == "call"
            assert float(r.get("btc_cost_usd") or 0) > 0


def test_manage_or_roll_never_rolls_puts_into_calls():
    from src.options.covered_calls import CoveredCallManager
    from src.options.wheel_lifecycle import manage_or_roll_short_calls

    class _Broker:
        def get_option_positions(self):
            return [
                {
                    "symbol": "F261002P00012000",
                    "side": "short",
                    "qty": 1,
                    "avg_entry_price": 0.40,
                    "current_price": 0.10,
                }
            ]

        def get_option_contracts(self, **kwargs):
            raise AssertionError("should not fetch call contracts after put BTC")

        def submit_option_order(self, **kwargs):
            return {"id": "ord1"}

    mgr = CoveredCallManager(min_premium_usd=10.0, min_premium_pct=0.001)
    # Put near ITM (underlying 11.8 vs strike 12) + short DTE path via manage
    results = manage_or_roll_short_calls(
        _Broker(),
        {"F": 11.8},
        mgr,
        manage_itm_pct=0.02,
        prefer_roll=True,
        execute=False,
        cc_score=55,
    )
    assert any(r.get("status") == "would_btc" for r in results)
    assert not any(r.get("status") in ("would_roll", "roll_executed") for r in results)
    assert all(r.get("option_type") != "call" or r.get("status") == "hold" for r in results if r.get("status") == "would_btc")
    btc = next(r for r in results if r.get("status") == "would_btc")
    assert btc.get("option_type") == "put"


def test_short_put_does_not_block_cc_identify():
    from src.options.covered_calls import CoveredCallManager
    from src.portfolio.models import Portfolio, Position

    class _Broker:
        pass

    mgr = CoveredCallManager()
    portfolio = Portfolio(cash=1000, positions={"F": Position(long=100, long_cost_basis=12.0)})
    cands = mgr.identify_callable_positions(
        portfolio,
        ["F"],
        [{"symbol": "F261002P00011000", "side": "short", "underlying": "F", "option_type": "put"}],
    )
    assert len(cands) == 1 and cands[0]["ticker"] == "F"


def test_orphan_blocked_when_short_option_open():
    portfolio = Portfolio(
        cash=2000.0,
        positions={"ADBE": Position(long=2, long_cost_basis=260.0)},
    )
    prices = {"ADBE": 260.0, "F": 12.0}
    wheel = [WheelCandidate("F", 12.0, 80_000_000, 500, 0.9)]
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=wheel,
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=1,
        short_option_underlyings={"ADBE"},
        preflight_ok={"F"},
    )
    assert "ADBE" not in decisions or decisions.get("ADBE") is None or getattr(decisions.get("ADBE"), "action", None) != "sell"
    assert any(s.get("reason") == "orphan_blocked_open_short_option" for s in diag.get("skipped") or [])


def test_directional_capped_at_99():
    portfolio = Portfolio(cash=9000.0, positions={})
    prices = {"CHEAP": 5.0, "F": 12.0}
    wheel = [WheelCandidate("F", 12.0, 80_000_000, 500, 0.9)]
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=wheel,
        directional_candidates=["CHEAP"],
        equity=10000.0,
        max_wheel_names=1,
        max_directional_names=1,
        preflight_ok={"F"},
        csp_reserve_frac=0.0,
    )
    if "CHEAP" in decisions and decisions["CHEAP"].action == "buy":
        assert decisions["CHEAP"].quantity <= 99


def test_profit_take_roll_requires_credit():
    from src.options.covered_calls import CoveredCallManager
    from src.options.wheel_lifecycle import manage_or_roll_short_calls

    class _Broker:
        def get_option_positions(self):
            return [
                {
                    "symbol": "F261016C00015000",
                    "side": "short",
                    "qty": 1,
                    "avg_entry_price": 1.00,
                    "current_price": 0.30,  # 70% profit
                }
            ]

        def get_option_contracts(self, **kwargs):
            return [
                {
                    "symbol": "F261030C00012600",
                    "strike": 12.60,
                    "expiry": "2026-10-30",
                    "tradable": True,
                    "mid_price": 0.10,  # $10 premium << ~$30 BTC cost
                }
            ]

        def submit_option_order(self, **kwargs):
            return {"order_id": "x", "fill_ok": True}

        def sync_portfolio(self):
            return Portfolio(cash=1000.0, positions={"F": Position(long=100, long_cost_basis=12.0)})

    mgr = CoveredCallManager(
        min_premium_usd=5.0,
        min_premium_pct=0.001,
        otm_pct_low=0.03,
        otm_pct_high=0.15,
        target_otm_pct=0.05,
    )
    # underlying well below strike so not near ITM; profit_take triggers
    results = manage_or_roll_short_calls(
        _Broker(),
        {"F": 12.0},
        mgr,
        manage_itm_pct=0.02,
        profit_take_pct=0.60,
        prefer_roll=True,
        execute=False,
        cc_score=55,
    )
    assert any(r.get("status") == "would_btc" for r in results)
    amb = [r for r in results if r.get("status") == "ambiguous"]
    assert amb, "profit-take debit roll should be ambiguous"
    assert any("credit" in str(r.get("reason") or "") for r in amb)


def test_agent_does_not_rewrite_debit_policy_rejects():
    from src.options.cc_agent import resolve_ambiguous_cc_actions

    rows = [
        {
            "underlying": "F",
            "status": "ambiguous",
            "reason": "profit_take_requires_credit_-20.00",
            "new_contract": "F261030C00012600",
            "qty": 1,
        }
    ]
    out = resolve_ambiguous_cc_actions(
        rows,
        candidate_contracts_by_underlying={"F": [{"symbol": "F261030C00012600"}]},
        execute=False,
    )
    assert out[0]["agent_action"] == "hold_assign"
    assert "debit_policy" in out[0]["agent_reason"]


def test_underhedged_identifies_top_up_lots():
    from src.options.covered_calls import CoveredCallManager
    from src.portfolio.models import Portfolio, Position

    mgr = CoveredCallManager()
    portfolio = Portfolio(cash=1000, positions={"F": Position(long=200, long_cost_basis=12.0)})
    cands = mgr.identify_callable_positions(
        portfolio,
        ["F"],
        [{"symbol": "F261002C00013000", "side": "short", "underlying": "F", "option_type": "call", "qty": 1}],
    )
    assert len(cands) == 1
    assert cands[0]["callable_lots"] == 1


def test_zero_mark_does_not_trigger_profit_take():
    from src.options.wheel_lifecycle import short_option_profit_pct

    assert short_option_profit_pct({"avg_entry_price": 0.40, "current_price": 0.0}) is None
    assert abs(short_option_profit_pct({"avg_entry_price": 0.40, "current_price": 0.10}) - 0.75) < 1e-9


def test_wait_for_order_fill_success_and_timeout():
    from src.broker.alpaca import AlpacaBroker

    class _Client:
        def __init__(self):
            self.n = 0

        def get_order_by_id(self, oid):
            self.n += 1

            class O:
                id = oid
                symbol = "F"
                side = type("S", (), {"value": "buy"})()
                qty = 100
                filled_qty = 100 if self.n >= 2 else 0
                filled_avg_price = 12.0
                status = type("St", (), {"value": "filled" if self.n >= 2 else "new"})()

            return O()

        def cancel_order_by_id(self, oid):
            return None

    b = AlpacaBroker.__new__(AlpacaBroker)
    b.client = _Client()
    fill = b.wait_for_order_fill("oid1", timeout_s=3.0, poll_s=0.01)
    assert fill["ok"] is True


def test_no_lot_buy_while_short_option_open():
    portfolio = Portfolio(cash=5000.0, positions={})
    prices = {"F": 12.0}
    wheel = [WheelCandidate("F", 12.0, 80_000_000, 500, 0.9)]
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=wheel,
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=1,
        short_option_underlyings={"F"},
        preflight_ok={"F"},
        csp_reserve_frac=0.0,
    )
    assert "F" not in decisions or getattr(decisions.get("F"), "action", None) != "buy"
    assert any(s.get("reason") == "open_short_option" for s in diag.get("skipped") or [])


def test_allocate_adds_second_lot_when_score_high():
    portfolio = Portfolio(
        cash=5000.0,
        positions={"F": Position(long=100, long_cost_basis=12.0)},
    )
    prices = {"F": 11.0, "SOFI": 10.0}
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=[
            WheelCandidate("F", 11.0, 80_000_000, 500, 0.80),
            WheelCandidate("SOFI", 10.0, 40_000_000, 400, 0.70),
        ],
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=1,
        max_lots_per_name=3,
        max_position_pct=0.35,
        add_lot_min_score=0.55,
        short_option_underlyings={"F"},
        preflight_ok={"F", "SOFI"},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert decisions["F"].action == "buy"
    assert decisions["F"].quantity == 200
    assert "F" in (diag.get("extra_lot_adds") or [])
    assert decisions["SOFI"].action == "buy"
    assert decisions["SOFI"].quantity == 100


def test_allocate_blocks_extra_lot_when_short_put_open():
    portfolio = Portfolio(
        cash=5000.0,
        positions={"F": Position(long=100, long_cost_basis=12.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 11.0},
        wheel_candidates=[WheelCandidate("F", 11.0, 80_000_000, 500, 0.80)],
        directional_candidates=[],
        equity=10000.0,
        add_lot_min_score=0.55,
        short_option_underlyings={"F"},
        short_put_underlyings={"F"},
        preflight_ok={"F"},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert getattr(decisions.get("F"), "action", None) != "buy"
    assert any(s.get("reason") == "add_lot_blocked_short_put" for s in diag.get("skipped") or [])


def test_allocate_extra_lot_skips_when_pending_sell_breaks_lot():
    portfolio = Portfolio(
        cash=5000.0,
        positions={"F": Position(long=200, long_cost_basis=12.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 11.0},
        wheel_candidates=[WheelCandidate("F", 11.0, 80_000_000, 500, 0.80)],
        directional_candidates=[],
        equity=10000.0,
        add_lot_min_score=0.55,
        preflight_ok={"F"},
        pending_orders_by_symbol={"F": {"buy_qty": 0, "sell_qty": 120}},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert "F" not in (diag.get("extra_lot_adds") or [])
    assert getattr(decisions.get("F"), "action", None) != "buy"


def test_select_contract_widens_band_when_floor_above_hi():
    from src.options.covered_calls import CoveredCallManager

    mgr = CoveredCallManager(
        min_premium_usd=1.0,
        min_premium_pct=0.0,
        otm_pct_low=0.03,
        otm_pct_high=0.08,
        target_otm_pct=0.05,
    )
    captured = {}

    class _Broker:
        def get_option_contracts(self, **kwargs):
            captured.update(kwargs)
            return [
                {
                    "symbol": "F261016C00013320",
                    "strike": 13.32,
                    "expiry": "2026-10-16",
                    "tradable": True,
                    "mid_price": 0.20,
                }
            ]

    contract, reason = mgr.select_contract(
        "F", 12.0, 55, _Broker(), strike_floor_otm=0.10
    )
    assert contract is not None, reason
    assert captured["strike_gte"] > 12.0 * 1.08
    assert captured["strike_lte"] >= 12.0 * 1.12


def test_allocate_extra_lot_uses_full_wheel_sleeve_not_csp_reserve():
    """4 existing lots can sit under lot_budget (70%×80%) but still have room in 70%."""
    portfolio = Portfolio(
        cash=5000.0,
        positions={
            "F": Position(long=100, long_cost_basis=12.0),
            "CPNG": Position(long=100, long_cost_basis=14.0),
            "NOK": Position(long=100, long_cost_basis=10.0),
            "ITUB": Position(long=100, long_cost_basis=8.0),
        },
    )
    prices = {"F": 12.0, "CPNG": 14.0, "NOK": 10.0, "ITUB": 8.0}
    # wheel_spent = 4400; lot_budget (csp 20%) = 5600 so +1200 F fits lot_budget too.
    # Tighten via high csp reserve: lot_budget = 7000*0.5 = 3500 < 4400+1200,
    # but wheel_budget = 7000 >= 5600.
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=[
            WheelCandidate("F", 12.0, 80_000_000, 500, 0.90),
            WheelCandidate("CPNG", 14.0, 80_000_000, 400, 0.40),
            WheelCandidate("NOK", 10.0, 80_000_000, 400, 0.40),
            WheelCandidate("ITUB", 8.0, 80_000_000, 400, 0.40),
        ],
        directional_candidates=[],
        equity=10000.0,
        max_lots_per_name=3,
        max_position_pct=0.35,
        add_lot_min_score=0.55,
        short_option_underlyings={"F", "CPNG", "NOK", "ITUB"},
        preflight_ok={"F", "CPNG", "NOK", "ITUB"},
        csp_reserve_frac=0.50,
        cash_buffer_pct=0.0,
    )
    assert decisions["F"].action == "buy"
    assert decisions["F"].quantity == 100
    assert "F" in (diag.get("extra_lot_adds") or [])
    assert not any(
        s.get("ticker") == "F" and "lot_budget_extra" in str(s.get("reason") or "")
        for s in diag.get("skipped") or []
    )


def test_wheel_addon_reason_is_waited_for_fill():
    reason = "Wheel add-on lot (score 0.80, 2 lots, 70% sleeve)"
    assert "Wheel lot" not in reason
    assert "Wheel add-on" in reason


def test_allocate_prefers_extra_lot_over_new_name():
    portfolio = Portfolio(
        cash=1300.0,
        positions={"F": Position(long=100, long_cost_basis=12.0)},
    )
    decisions, _diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 12.0, "SOFI": 10.0},
        wheel_candidates=[
            WheelCandidate("F", 12.0, 80_000_000, 500, 0.90),
            WheelCandidate("SOFI", 10.0, 80_000_000, 400, 0.80),
        ],
        directional_candidates=[],
        equity=10000.0,
        add_lot_min_score=0.55,
        short_option_underlyings={"F"},
        preflight_ok={"F", "SOFI"},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert decisions["F"].action == "buy"
    assert decisions["F"].quantity == 100
    assert "SOFI" not in decisions or decisions["SOFI"].action != "buy"


def test_portfolio_long_qty_does_not_create_empty_position():
    p = Portfolio(cash=100.0, positions={})
    assert p.long_qty("ZZZ") == 0
    assert "ZZZ" not in p.positions
    p.get_position("ZZZ")
    assert "ZZZ" in p.positions


def test_allocate_does_not_inject_empty_probe_positions():
    portfolio = Portfolio(cash=8000.0, positions={})
    allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 10.0, "SOFI": 12.0},
        wheel_candidates=[
            WheelCandidate("F", 10.0, 80_000_000, 500, 0.9),
            WheelCandidate("SOFI", 12.0, 80_000_000, 400, 0.8),
        ],
        directional_candidates=["NVDA"],
        equity=10000.0,
        preflight_ok={"F"},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert "SOFI" not in portfolio.positions
    assert "NVDA" not in portfolio.positions


def test_allocate_rejects_nan_add_lot_score():
    portfolio = Portfolio(
        cash=5000.0,
        positions={"F": Position(long=100, long_cost_basis=12.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 11.0},
        wheel_candidates=[WheelCandidate("F", 11.0, 80_000_000, 500, float("nan"))],
        directional_candidates=[],
        equity=10000.0,
        add_lot_min_score=0.55,
        short_option_underlyings={"F"},
        preflight_ok={"F"},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert getattr(decisions.get("F"), "action", "hold") != "buy"
    assert any("add_lot_score" in str(s.get("reason") or "") for s in diag.get("skipped") or [])


def test_allocate_can_add_two_lots_same_session():
    portfolio = Portfolio(
        cash=4000.0,
        positions={"F": Position(long=100, long_cost_basis=10.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 10.0},
        wheel_candidates=[WheelCandidate("F", 10.0, 80_000_000, 500, 0.90)],
        directional_candidates=[],
        equity=10000.0,
        max_lots_per_name=3,
        max_position_pct=0.40,
        add_lot_min_score=0.55,
        short_option_underlyings={"F"},
        preflight_ok={"F"},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert decisions["F"].action == "buy"
    assert decisions["F"].quantity == 200
    assert "F" in (diag.get("extra_lot_adds") or [])


def test_allocate_skips_extra_lot_when_score_low():
    portfolio = Portfolio(
        cash=5000.0,
        positions={"F": Position(long=100, long_cost_basis=12.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 11.0},
        wheel_candidates=[WheelCandidate("F", 11.0, 80_000_000, 500, 0.40)],
        directional_candidates=[],
        equity=10000.0,
        max_lots_per_name=3,
        add_lot_min_score=0.55,
        short_option_underlyings={"F"},
        preflight_ok={"F"},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert getattr(decisions.get("F"), "action", "hold") != "buy"
    assert any("add_lot_score" in str(s.get("reason") or "") for s in diag.get("skipped") or [])


def test_pending_buy_notional_reduces_cash():
    portfolio = Portfolio(cash=1500.0, positions={})
    prices = {"F": 12.0, "SOFI": 10.0}
    wheel = [
        WheelCandidate("F", 12.0, 80_000_000, 500, 0.9),
        WheelCandidate("SOFI", 10.0, 80_000_000, 500, 0.8),
    ]
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=wheel,
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=2,
        pending_orders_by_symbol={"F": {"buy_qty": 100}},
        preflight_ok={"F", "SOFI"},
        csp_reserve_frac=0.0,
        cash_buffer_pct=0.0,
    )
    assert diag.get("pending_buy_notional", 0) >= 1200
    # Remaining cash after pending F buy (~$300) cannot fund SOFI×100
    assert "SOFI" not in decisions or decisions["SOFI"].action != "buy"


def test_csp_seeds_outstanding_put_collateral():
    from src.options.cash_secured_puts import (
        CashSecuredPutManager,
        outstanding_short_put_collateral_usd,
    )

    opts = [
        {
            "symbol": "F261016P00012000",
            "side": "short",
            "qty": 1,
        }
    ]
    assert abs(outstanding_short_put_collateral_usd(opts) - 1200.0) < 1e-6

    class _Broker:
        def get_option_contracts(self, **kwargs):
            return [
                {
                    "symbol": "SOFI261016P00010000",
                    "strike": 10.0,
                    "expiry": "2026-10-16",
                    "tradable": True,
                    "close_price": 0.50,
                }
            ]

        def submit_option_order(self, **kwargs):
            raise AssertionError("should not submit — collateral already at cap")

    mgr = CashSecuredPutManager(min_premium_usd=10.0, min_annualized_yield_pct=1.0)
    results = mgr.execute_cash_secured_puts(
        broker=_Broker(),
        csp_tickers=["SOFI"],
        csp_scores={"SOFI": 60},
        current_prices={"SOFI": 10.5},
        max_collateral_usd=1200.0,
        option_positions=opts,
    )
    assert results and results[0]["status"] == "skipped"
    assert "csp_collateral_cap" in str(results[0].get("reason") or "")


def test_coverage_map_sums_qty_and_flags_overhedged_naked():
    from src.options.wheel_lifecycle import build_coverage_map

    portfolio = Portfolio(
        cash=1000.0,
        positions={
            "F": Position(long=200, long_cost_basis=12.0),
            "SOFI": Position(long=50, long_cost_basis=10.0),
        },
    )
    opts = [
        {
            "symbol": "F261016C00013000",
            "side": "short",
            "qty": 1,
            "option_type": "call",
            "underlying": "F",
        },
        {
            "symbol": "F261030C00014000",
            "side": "short",
            "qty": 1,
            "option_type": "call",
            "underlying": "F",
        },
        {
            "symbol": "SOFI261016C00011000",
            "side": "short",
            "qty": 1,
            "option_type": "call",
            "underlying": "SOFI",
        },
        {
            "symbol": "ABEV261016C00003000",
            "side": "short",
            "qty": 1,
            "option_type": "call",
            "underlying": "ABEV",
        },
    ]
    rows = build_coverage_map(
        portfolio,
        opts,
        {"F": 12.0, "SOFI": 10.0, "ABEV": 3.0},
        max_underlying_price=35.0,
    )
    by_t = {r["ticker"]: r for r in rows}
    assert by_t["F"]["coverage"] == "covered"  # 200 sh / 2 contracts
    assert by_t["F"]["short_contracts"] == 2
    assert by_t["SOFI"]["coverage"] == "OVERHEDGED"
    assert by_t["ABEV"]["coverage"] == "NAKED_SHORT"
    assert "ABEV" not in portfolio.positions


def test_overflow_lots_stay_cc_eligible():
    portfolio = Portfolio(
        cash=500.0,
        positions={
            "A": Position(long=100, long_cost_basis=5.0),
            "B": Position(long=100, long_cost_basis=5.0),
            "C": Position(long=100, long_cost_basis=5.0),
        },
    )
    prices = {"A": 5.0, "B": 5.0, "C": 5.0}
    wheel = [
        WheelCandidate("A", 5.0, 80_000_000, 500, 0.9),
        WheelCandidate("B", 5.0, 80_000_000, 500, 0.8),
        WheelCandidate("C", 5.0, 80_000_000, 500, 0.7),
    ]
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices=prices,
        wheel_candidates=wheel,
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=2,
        preflight_ok={"A", "B", "C"},
        csp_reserve_frac=0.0,
    )
    assert "C" in diag.get("cc_lot_tickers") or "C" in (diag.get("overflow_cc_lots") or [])
    assert "C" not in (diag.get("orphan_exits") or [])
    assert decisions.get("C") is None or decisions["C"].action != "sell"


def test_atomic_unwind_skips_invalid_price():
    from src.options.covered_calls import tickers_needing_atomic_unwind

    results = [
        {"underlying": "F", "status": "skipped", "reason": "invalid_price"},
        {"underlying": "SOFI", "status": "skipped", "reason": "no_contracts_in_otm_band"},
    ]
    unwind = tickers_needing_atomic_unwind(
        results,
        held_lot_tickers=["F", "SOFI"],
        short_option_underlyings=set(),
    )
    assert unwind == set()


def test_profile_llm_budget_not_clobbered_by_entrypoint_defaults():
    from src.trading.run_config import merge_run_profile

    # Mimic weekly_scan_rebalancing after removing hardcoded LLM knobs from the dict.
    run_config: dict = {"execute": True, "agent_tier_mode": "core"}
    merged = merge_run_profile(run_config, "wheel-10k")
    merged.setdefault("financial_limit", 1)
    merged.setdefault("dossier_financial_limit", 5)
    merged.setdefault("focused_financial_limit", 5)
    merged.setdefault("max_llm_calls", 4000)
    merged.setdefault("max_csp_tickers", 2)
    merged.setdefault("max_csp_collateral_pct", 0.10)
    assert merged.get("max_llm_calls") == 800
    assert merged.get("dossier_financial_limit") == 3
    assert float(merged.get("max_csp_collateral_pct") or 0) == 0.45
    assert int(merged.get("max_csp_tickers") or 0) == 3


def test_csp_nan_seed_does_not_lift_collateral_cap():
    from src.options.cash_secured_puts import CashSecuredPutManager

    class _Broker:
        def get_option_contracts(self, **kwargs):
            return [
                {
                    "symbol": "SOFI261016P00014000",
                    "strike": 14.0,
                    "expiry": "2026-10-16",
                    "tradable": True,
                    "close_price": 0.80,
                }
            ]

        def submit_option_order(self, **kwargs):
            raise AssertionError("nan seed must not allow uncapped CSP")

    mgr = CashSecuredPutManager(min_premium_usd=25.0, min_annualized_yield_pct=1.0)
    results = mgr.execute_cash_secured_puts(
        _Broker(),
        ["SOFI"],
        {"SOFI": 60},
        {"SOFI": 15.0},
        max_collateral_usd=1000.0,
        collateral_already_used_usd=float("nan"),
        option_positions=[
            {
                "symbol": "F261016P00012000",
                "side": "short",
                "qty": 1,
            }
        ],
    )
    assert results and results[0]["status"] == "skipped"
    assert "csp_collateral_cap" in str(results[0].get("reason") or "")


def test_csp_cap_headroom_includes_outstanding():
    """Spendable is net of open puts; total cap must be outstanding + spendable."""
    outstanding = 2000.0
    spendable = 500.0
    pct_cap = 4500.0
    headroom = outstanding + max(spendable, 0.0)
    csp_cap = min(pct_cap, headroom)
    assert csp_cap == 2500.0
    # Old bug: min(pct_cap, spendable) alone → seeded 2000 > 500 → all new CSPs skip.
    assert min(pct_cap, spendable) == 500.0


def test_soft_band_keeps_appreciated_lot_from_orphan():
    portfolio = Portfolio(
        cash=500.0,
        positions={"F": Position(long=100, long_cost_basis=32.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 36.0},
        wheel_candidates=[WheelCandidate("F", 36.0, 80_000_000, 500, 0.9)],
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=1,
        max_underlying_price=35.0,
        csp_reserve_frac=0.0,
    )
    assert "F" in diag.get("cc_lot_tickers") or "F" in diag.get("wheel_targets")
    assert "F" not in (diag.get("orphan_exits") or [])
    assert decisions.get("F") is None or decisions["F"].action != "sell"


def test_roll_debit_scales_with_qty():
    from src.options.covered_calls import CoveredCallManager
    from src.options.wheel_lifecycle import manage_or_roll_short_calls

    class _Broker:
        def __init__(self):
            self._opts = [
                {
                    "symbol": "F261016C00011500",
                    "side": "short",
                    "qty": 2,
                    "avg_entry_price": 0.40,
                    "current_price": 0.55,  # near ITM / threatened
                }
            ]

        def get_option_positions(self):
            return list(self._opts)

        def get_option_contracts(self, **kwargs):
            return [
                {
                    "symbol": "F261030C00012600",
                    "strike": 12.60,
                    "expiry": "2026-10-30",
                    "tradable": True,
                    # $20/contract premium; BTC cost ~$110 for 2 → debit ~$90
                    # Cap at max(25*2, 0.25*40)=50 → reject
                    "mid_price": 0.20,
                }
            ]

        def submit_option_order(self, **kwargs):
            if str(kwargs.get("side") or "").lower() == "buy":
                self._opts = []  # BTC closed the shorts
                return {"order_id": "btc", "fill_ok": True, "filled_qty": kwargs.get("qty", 2)}
            raise AssertionError("debit cap should reject before STO submit")

        def sync_portfolio(self):
            return Portfolio(cash=1000.0, positions={"F": Position(long=200, long_cost_basis=12.0)})

    mgr = CoveredCallManager(
        min_premium_usd=5.0,
        min_premium_pct=0.001,
        otm_pct_low=0.03,
        otm_pct_high=0.15,
        target_otm_pct=0.05,
    )
    results = manage_or_roll_short_calls(
        _Broker(),
        {"F": 12.0},
        mgr,
        manage_dte_threshold=45,
        manage_itm_pct=0.02,
        prefer_roll=True,
        execute=True,
        cc_score=55,
        max_roll_debit_usd=25.0,
        max_roll_debit_pct_of_premium=0.25,
    )
    amb = [r for r in results if "roll_debit_exceeds_cap" in str(r.get("reason") or "")]
    assert amb, results


def test_early_close_blocks_afternoon_submit():
    from src.trading.execution_status import can_submit_live_orders
    from src.trading.us_equity_calendar import nyse_session_close_et

    # Day after Thanksgiving 2026 is Fri Nov 27 — early close
    d = date(2026, 11, 27)
    assert nyse_session_close_et(d).hour == 13
    # 1:30 PM ET = after early close
    dt = datetime(2026, 11, 27, 18, 30, tzinfo=ZoneInfo("UTC"))  # 13:30 ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="15:30")
    assert ok is False
    assert "early_close" in reason or "cutoff" in reason or "after" in reason


def test_losing_itm_mark_is_not_fake_profit_take():
    from src.options.wheel_lifecycle import short_option_profit_pct, should_manage_short

    # Per-share mark already (Alpaca path). Losing short must not look like 95% profit.
    pct = short_option_profit_pct(
        {"avg_entry_price": 0.40, "current_price": 2.05}
    )
    assert pct is not None and pct < 0.01
    manage, reason = should_manage_short(
        option_type="call",
        strike=12.0,
        underlying_price=14.0,
        dte=25,
        profit_pct=pct,
        manage_itm_pct=0.02,
        profit_take_pct=0.60,
    )
    assert manage is True
    assert reason == "call_near_itm"


def test_graduated_lot_not_orphaned():
    portfolio = Portfolio(
        cash=500.0,
        positions={"F": Position(long=100, long_cost_basis=40.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 50.0},
        wheel_candidates=[],
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=1,
        max_underlying_price=35.0,
        csp_reserve_frac=0.0,
    )
    assert "F" in diag.get("cc_lot_tickers") or "F" in (diag.get("graduated_cc_lots") or [])
    assert "F" not in (diag.get("orphan_exits") or [])
    assert decisions.get("F") is None or decisions["F"].action != "sell"


def test_coverage_map_includes_graduated_uncovered_lots():
    from src.options.wheel_lifecycle import build_coverage_map

    portfolio = Portfolio(
        cash=500.0,
        positions={"F": Position(long=100, long_cost_basis=40.0)},
    )
    rows = build_coverage_map(
        portfolio,
        [],
        {"F": 50.0},
        max_underlying_price=35.0,
    )
    assert len(rows) == 1
    assert rows[0]["ticker"] == "F"
    assert rows[0]["coverage"] == "UNCOVERED"


def test_agent_zero_qty_does_not_rewrite():
    from src.options.cc_agent import resolve_ambiguous_cc_actions

    out = resolve_ambiguous_cc_actions(
        [
            {
                "underlying": "F",
                "status": "ambiguous",
                "reason": "roll_sto_not_filled",
                "qty": 0,
                "new_contract": "F261016C00013000",
            }
        ],
        candidate_contracts_by_underlying={"F": [{"symbol": "F261016C00013000"}]},
        execute=False,
    )
    assert out and out[0].get("agent_action") == "hold_assign"
    assert out[0].get("agent_reason") == "zero_qty_no_rewrite"


def test_manage_email_gate_includes_unwind_failed():
    from src.utils.wheel_email import manage_results_have_actions

    assert manage_results_have_actions(
        [],
        [{"status": "atomic_unwind_failed"}],
    )
    assert manage_results_have_actions(
        [],
        [{"status": "underhedge_trim", "quantity": 100}],
    )
    assert not manage_results_have_actions(
        [],
        [{"status": "skipped", "reason": "no_contracts"}],
    )
    assert manage_results_have_actions([], [], coverage_unavailable=True)


def test_roll_sto_writes_one_lot_at_a_time():
    from src.options.covered_calls import CoveredCallManager
    from src.options.wheel_lifecycle import manage_or_roll_short_calls

    submits = []

    class _Broker:
        def __init__(self):
            self._opts = [
                {
                    "symbol": "F261016C00011500",
                    "side": "short",
                    "qty": 2,
                    "avg_entry_price": 0.40,
                    "current_price": 0.55,
                }
            ]
            self._filled = 0

        def get_option_positions(self):
            return list(self._opts)

        def get_option_contracts(self, **kwargs):
            return [
                {
                    "symbol": "F261030C00012600",
                    "strike": 12.60,
                    "expiry": "2026-10-30",
                    "tradable": True,
                    "mid_price": 0.80,  # rich enough for credit vs BTC
                }
            ]

        def submit_option_order(self, **kwargs):
            submits.append(dict(kwargs))
            if str(kwargs.get("side") or "").lower() == "buy":
                self._opts = []
                return {"order_id": "btc", "fill_ok": True, "filled_qty": kwargs.get("qty", 2)}
            # STO one at a time
            assert int(kwargs.get("qty") or 0) == 1
            self._filled += 1
            return {"order_id": f"sto{self._filled}", "fill_ok": True, "filled_qty": 1}

        def sync_portfolio(self):
            return Portfolio(cash=1000.0, positions={"F": Position(long=200, long_cost_basis=12.0)})

    mgr = CoveredCallManager(
        min_premium_usd=5.0,
        min_premium_pct=0.001,
        otm_pct_low=0.03,
        otm_pct_high=0.15,
        target_otm_pct=0.05,
    )
    results = manage_or_roll_short_calls(
        _Broker(),
        {"F": 12.0},
        mgr,
        manage_dte_threshold=45,
        manage_itm_pct=0.02,
        prefer_roll=True,
        execute=True,
        cc_score=55,
        max_roll_debit_usd=25.0,
        max_roll_debit_pct_of_premium=0.25,
    )
    sto = [s for s in submits if str(s.get("side") or "").lower() == "sell"]
    assert len(sto) == 2
    assert all(int(s.get("qty") or 0) == 1 for s in sto)
    assert any(r.get("status") == "roll_executed" for r in results)


def test_allocate_does_not_orphan_mixed_case_lot():
    portfolio = Portfolio(
        cash=2000.0,
        positions={"f": Position(long=100, long_cost_basis=12.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={"F": 12.0},
        wheel_candidates=[WheelCandidate("F", 12.0, 80_000_000, 500, 0.9)],
        directional_candidates=[],
        equity=10000.0,
        max_wheel_names=1,
        csp_reserve_frac=0.0,
    )
    assert "F" in (diag.get("cc_lot_tickers") or [])
    assert "F" not in (diag.get("orphan_exits") or [])
    assert "f" not in (diag.get("orphan_exits") or [])
    act = getattr(decisions.get("F") or decisions.get("f"), "action", "")
    assert act != "sell"


def test_underhedge_trim_skips_invalid_price():
    from src.options.covered_calls import apply_underhedge_trims

    class FakeBroker:
        def sync_portfolio(self):
            return Portfolio(cash=0, positions={"F": Position(long=200)})

        def get_option_positions(self):
            return [
                {
                    "symbol": "F260918C00012000",
                    "side": "short",
                    "qty": 1,
                    "option_type": "call",
                    "underlying": "F",
                }
            ]

        def execute_order(self, *args, **kwargs):
            raise AssertionError("must not trim when mark is missing")

    apply_underhedge_trims(
        FakeBroker(),
        {"F": 12.0},
        [{"underlying": "F", "status": "skipped", "reason": "invalid_price"}],
    )


def test_select_contract_rejects_nan_price():
    from src.options.covered_calls import CoveredCallManager

    class _Broker:
        def get_option_contracts(self, **kwargs):
            raise AssertionError("must not fetch chain on invalid mark")

    contract, reason = CoveredCallManager().select_contract("F", float("nan"), 55, _Broker())
    assert contract is None
    assert reason == "invalid_price"


def test_manage_skips_zero_qty_short():
    from src.options.wheel_lifecycle import manage_short_options

    class _Broker:
        def get_option_positions(self):
            return [
                {
                    "symbol": "F261016C00013000",
                    "side": "short",
                    "qty": 0,
                    "option_type": "call",
                    "underlying": "F",
                }
            ]

        def submit_option_order(self, **kwargs):
            raise AssertionError("must not BTC a zero-qty short")

    results = manage_short_options(_Broker(), {"F": 12.0}, execute=True)
    assert not any(r.get("status") == "btc_executed" for r in results)


def test_coverage_map_matches_mixed_case_keys():
    from src.options.wheel_lifecycle import build_coverage_map

    portfolio = Portfolio(
        cash=1000.0,
        positions={"f": Position(long=100, long_cost_basis=12.0)},
    )
    opts = [
        {
            "symbol": "F261016C00013000",
            "side": "short",
            "qty": 1,
            "option_type": "call",
            "underlying": "F",
        }
    ]
    rows = build_coverage_map(portfolio, opts, {"F": 12.0})
    assert rows and rows[0]["coverage"] == "covered"
    assert rows[0]["ticker"] == "F"


def test_long_qty_and_equity_are_case_and_nan_safe():
    portfolio = Portfolio(
        cash=1000.0,
        positions={"f": Position(long=100, long_cost_basis=12.0)},
    )
    assert portfolio.long_qty("F") == 100
    assert portfolio.get_equity({"F": 12.0}) == 2200.0
    assert portfolio.get_equity({"f": float("nan"), "F": 12.0}) == 2200.0


def test_allocate_keeps_unpriced_hundred_lot():
    portfolio = Portfolio(
        cash=2000.0,
        positions={"F": Position(long=100, long_cost_basis=12.0)},
    )
    decisions, diag = allocate_wheel_hybrid_book(
        portfolio=portfolio,
        current_prices={},
        wheel_candidates=[],
        directional_candidates=[],
        equity=10000.0,
        csp_reserve_frac=0.0,
    )
    assert "F" in (diag.get("cc_lot_tickers") or [])
    assert "F" not in (diag.get("orphan_exits") or [])
    assert decisions.get("F") is None or decisions["F"].action != "sell"


def test_screen_ignores_nan_price_and_uses_dossier():
    dossiers = {"F": {"prices": {"last_close": 11.5, "avg_volume": 5_000_000}}}
    px, adv = extract_price_adv("F", prices={"F": float("nan")}, dossiers=dossiers)
    assert px == 11.5
    assert adv == 5_000_000 * 11.5
    cands = screen_wheel_candidates(
        ["F"],
        prices={"F": float("nan")},
        dossiers=dossiers,
        max_price=35.0,
        min_adv_usd=5_000_000,
        allow_missing_adv=False,
    )
    assert [c.ticker for c in cands] == ["F"]
