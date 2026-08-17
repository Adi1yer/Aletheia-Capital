"""Concentrated Beat SPY win-plan tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.alpha.liquidity_gate import passes_buy_liquidity
from src.alpha.residual_mu import momentum_12_1, rank_residual_mu
from src.performance.beat_spy_gates import evaluate_beat_spy_gates
from src.portfolio.beat_spy_cadence import should_skip_new_buys
from src.portfolio.beat_spy_policy import apply_beat_spy_defaults
from src.portfolio.phase13_policy import apply_phase13_defaults


def _liq_dossier(sector: str, *, mcap: float = 5e10, avg_vol: float = 5_000_000, px: float = 100.0):
    return {
        "context": {"sector": sector, "market_cap": mcap},
        "prices": {"last_close": px, "avg_volume": avg_vol, "closes": [px] * 80},
        "metrics": [{"return_on_equity": 20.0, "price_to_earnings": 15.0, "market_cap": mcap}],
        "trends": {"return_1m_pct": 5.0, "return_3m_pct": 10.0},
    }


def test_beat_spy_overwrites_phase13_clamps():
    rc = apply_phase13_defaults(
        {
            "beat_spy_mode": True,
            "cash_buffer_pct": 0.04,
            "max_buy_tickers": 12,
            "max_position_pct": 0.10,
        }
    )
    rc = apply_beat_spy_defaults(rc)
    assert rc["cash_buffer_pct"] == 0.04
    assert rc["max_buy_tickers"] == 12
    assert rc["max_position_pct"] == 0.10
    assert rc["max_cash_rotation_sells"] == 20


def test_learned_policy_does_not_raise_buy_conf_in_beat_spy(tmp_path, monkeypatch):
    import src.performance.policy_calibration as pc

    monkeypatch.setattr(pc, "POLICY_PATH", tmp_path / "policy.json")
    monkeypatch.setattr(
        pc,
        "compute_policy",
        lambda rc, weeks=12, saved_policy=None: {
            "min_buy_confidence": 85,
            "min_sell_confidence": 55,
            "cash_rotation_min_edge": 20,
            "min_csp_premium_usd": 75,
            "adjustments": [],
        },
    )
    rc = {"beat_spy_mode": True, "min_buy_confidence": 62, "cash_rotation_min_edge": 12}
    pc.apply_learned_policy(rc, recompute=True, save=False)
    assert rc["min_buy_confidence"] == 62
    assert rc["cash_rotation_min_edge"] == 12


def test_liquidity_gate_rejects_small_caps():
    ok, reason = passes_buy_liquidity(
        {"context": {"market_cap": 5e8}, "prices": {"last_close": 20.0, "avg_volume": 1e6}},
        20.0,
    )
    assert ok is False
    assert reason == "mcap"
    ok, reason = passes_buy_liquidity(_liq_dossier("Information Technology"), 100.0)
    assert ok is True


def test_residual_mu_ranks_higher_momentum_first():
    tickers = ["WIN", "LOSE"]
    extra = {
        "WIN": [100.0] * 200 + [100.0 * (1.01**i) for i in range(60)],
        "LOSE": [100.0] * 200 + [100.0 * (0.99**i) for i in range(60)],
    }
    dossiers = {t: _liq_dossier("Information Technology") for t in tickers}
    mu, vols, diag = rank_residual_mu(tickers, dossiers, extra_closes=extra)
    assert mu["WIN"] > mu["LOSE"]
    assert diag["tickers_scored"] == 2
    assert vols["WIN"] > 0


def test_momentum_12_1_skips_recent_month():
    # Rally only in the last 21 sessions should be skipped by 12-1.
    closes = [100.0] * 231 + [130.0] * 21
    m = momentum_12_1(closes)
    assert m is not None
    assert abs(m) < 0.05


def test_allocator_exits_non_target_and_buys_liquid_leaders():
    from src.agents.base import AgentSignal
    from src.portfolio.manager import PortfolioManager
    from src.portfolio.models import Portfolio, Position

    pm = PortfolioManager()
    portfolio = Portfolio(cash=5_000.0)
    portfolio.positions["JPM"] = Position(long=70, long_cost_basis=100.0)
    tickers = ["JPM", "AAPL", "MSFT"]
    bull = AgentSignal(signal="bullish", confidence=90, reasoning="x")
    dossiers = {
        "JPM": _liq_dossier("Financials", px=100.0),
        "AAPL": _liq_dossier("Information Technology", px=100.0),
        "MSFT": _liq_dossier("Information Technology", px=100.0),
    }
    risk = {t: {"remaining_position_limit": 500_000.0, "current_price": 100.0} for t in tickers}
    decisions = pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals={"growth": {t: bull for t in tickers}},
        risk_analysis=risk,
        portfolio=portfolio,
        agent_weights={"growth": 1.0},
        min_buy_confidence=50,
        max_buy_tickers=2,
        max_sector_pct=0.30,
        max_position_pct=0.10,
        cash_buffer_pct=0.04,
        cash_floor_pct=0.03,
        cash_rotation_min_buy_notional_usd=250,
        enable_covered_calls=False,
        enable_cash_rotation=False,
        ticker_dossiers=dossiers,
        beat_spy_concentrated=True,
        beat_spy_mu={"AAPL": 1.0, "MSFT": 0.9, "JPM": 0.2},
        beat_spy_vol={"AAPL": 0.2, "MSFT": 0.2, "JPM": 0.2},
    )
    assert decisions["JPM"].action == "sell"
    buys = {t for t, d in decisions.items() if d.action == "buy" and d.quantity > 0}
    assert "AAPL" in buys
    assert "MSFT" in buys
    dd = pm._last_rebalance_diagnostics
    assert dd.get("beat_spy_concentrated") is True
    assert "JPM" in (dd.get("exited") or [])


def test_allocator_veto_and_illiquid_skip():
    from src.portfolio.beat_spy_allocator import allocate_beat_spy_book
    from src.portfolio.models import Portfolio

    portfolio = Portfolio(cash=10_000.0)
    tickers = ["AAPL", "ILLQ", "MSFT"]
    dossiers = {
        "AAPL": _liq_dossier("Information Technology"),
        "MSFT": _liq_dossier("Information Technology"),
        "ILLQ": _liq_dossier("Energy", mcap=5e8, avg_vol=1_000),
    }
    risk = {t: {"current_price": 100.0} for t in tickers}
    decisions, diag = allocate_beat_spy_book(
        tickers=tickers,
        portfolio=portfolio,
        risk_analysis=risk,
        ticker_dossiers=dossiers,
        beat_spy_mu={"ILLQ": 9.0, "AAPL": 1.0, "MSFT": 0.8},
        beat_spy_veto={"AAPL"},
        max_names=2,
    )
    buys = {t for t, d in decisions.items() if d.action == "buy"}
    assert "ILLQ" not in buys
    assert "AAPL" not in buys
    assert "MSFT" in buys
    assert any(r["ticker"] == "ILLQ" for r in diag["liquidity_rejects"])
    assert "AAPL" in diag["veto_skips"]


def test_cadence_skips_inside_interval(tmp_path):
    path = tmp_path / "rebalance.json"
    path.write_text('{"last_full_rebalance_at": "' + datetime.utcnow().isoformat() + 'Z"}')
    skip, diag = should_skip_new_buys(interval_weeks=2, path=path)
    assert skip is True
    skip2, _ = should_skip_new_buys(
        interval_weeks=2,
        now=datetime.utcnow() + timedelta(days=15),
        path=path,
    )
    assert skip2 is False


def test_month_gates():
    g = evaluate_beat_spy_gates({"weeks_recorded": 3, "information_ratio": 0.5, "gates": {}})
    assert g["month3"]["due"] is False
    g3 = evaluate_beat_spy_gates({"weeks_recorded": 12, "information_ratio": 0.1, "gates": {}})
    assert g3["month3"]["pass"] is True
    g3b = evaluate_beat_spy_gates({"weeks_recorded": 12, "information_ratio": -0.2, "gates": {}})
    assert g3b["month3"]["action"] == "redesign_factors_or_universe"
    g6 = evaluate_beat_spy_gates(
        {"weeks_recorded": 26, "information_ratio": 0.5, "gates": {"all_ok": True}}
    )
    assert g6["month6"]["pass"] is True
