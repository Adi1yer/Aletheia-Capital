"""Phase 12 system tests."""

from src.agents.champion_challenger import evaluate_challenger, register_challenger
from src.data.providers.trust_plane import detect_provider_drift, update_provider_trust
from src.ops.go_no_go import build_go_no_go_report
from src.ops.slo import evaluate_slos
from src.performance.alpha_lifecycle import evaluate_lane_retirement, update_lane_metrics
from src.portfolio.optimizer import optimize_allocations
from src.portfolio.regime_intelligence import apply_hysteresis, confidence_band
from src.trading.execution_tactics import select_execution_tactic
from src.trading.run_manifest import build_deployment_attestation
from src.utils.integrity import verify_run_integrity


def test_execution_tactic_selector_deterministic():
    a = select_execution_tactic(ticker="AAPL", action="buy", current_price=100.0, avg_daily_volume=5_000_000)
    b = select_execution_tactic(ticker="AAPL", action="buy", current_price=100.0, avg_daily_volume=5_000_000)
    assert a == b
    assert a["tactic"] in ("limit_improve", "market_standard", "limit_passive")


def test_portfolio_optimizer_constraints():
    out = optimize_allocations(
        [
            {"ticker": "AAPL", "score": 80, "price": 100.0, "sector": "tech"},
            {"ticker": "MSFT", "score": 75, "price": 200.0, "sector": "tech"},
        ],
        equity=100_000,
        cash_buffer_pct=0.05,
        max_position_pct=0.2,
        max_sector_pct=0.35,
    )
    assert "allocations" in out
    assert out["metrics"]["concentration"] <= 0.2 + 1e-6


def test_alpha_lifecycle_retirement(tmp_path):
    path = tmp_path / "lifecycle.json"
    for i in range(6):
        update_lane_metrics("lane:test", hit_rate=0.3, sample_n=10, path=path)
    verdict = evaluate_lane_retirement("lane:test", min_samples=6, stale_weeks=4, min_hit_rate=0.45, path=path)
    assert verdict["retire"] is True


def test_regime_hysteresis_confidence_band():
    regime = apply_hysteresis({"mode": "accumulate", "last_close": 101.0, "sma_200": 100.0})
    assert confidence_band(float(regime.get("confidence") or 0.0)) in ("low", "medium", "high")
    assert "stable_mode" in regime


def test_provider_trust_and_drift():
    metrics = {}
    update_provider_trust(metrics, provider="Yahoo", success=True)
    update_provider_trust(metrics, provider="Yahoo", success=False)
    alarms = detect_provider_drift({"AAPL": {"current_price": 100}}, {"AAPL": {"current_price": 105}})
    assert alarms and alarms[0]["drift_pct"] >= 2.0


def test_go_no_go_and_slo():
    results = {
        "decisions": {"AAPL": {"action": "buy"}},
        "agent_errors": {},
        "data_quality": {"score": 90},
        "execution_status": {"pending_count": 0, "filled_count": 1},
        "pretrade_simulation": {},
        "learning_context": {},
    }
    slo = evaluate_slos(results)
    gate = build_go_no_go_report({**results, "slo": slo})
    assert slo["ok"] is True
    assert gate["go"] is True


def test_champion_challenger_and_attestation():
    register_challenger("fundamentals", "fundamentals-v2")
    verdict = evaluate_challenger("fundamentals", champion_score=0.5, challenger_score=1.6)
    assert verdict["promote_challenger"] is True
    att = build_deployment_attestation(
        run_id="r1",
        promoted=True,
        promotion_reason="ok",
        rollback_trigger="slo",
        manifest_sha256="abc",
    )
    assert att["promoted"] is True


def test_verify_run_integrity_missing(tmp_path):
    out = verify_run_integrity(tmp_path)
    assert out["ok"] is False
