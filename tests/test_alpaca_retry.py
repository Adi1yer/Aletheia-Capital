"""Tests for Alpaca transient retry helper."""

from __future__ import annotations

import pytest

from src.broker.alpaca import _is_transient_alpaca_error, alpaca_call_with_retry


def test_detects_alpaca_504_timeout():
    assert _is_transient_alpaca_error(Exception('{"code":50410000,"message":"request timed out"}'))
    assert _is_transient_alpaca_error(RuntimeError("Connection reset by peer"))
    assert not _is_transient_alpaca_error(RuntimeError("unauthorized"))


def test_retry_then_succeed(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError('{"code":50410000,"message":"request timed out"}')
        return {"ok": True}

    monkeypatch.setattr("src.broker.alpaca.time.sleep", lambda *_a, **_k: None)
    out = alpaca_call_with_retry(flaky, op="test", attempts=4, base_delay_sec=0.01)
    assert out == {"ok": True}
    assert calls["n"] == 3


def test_retry_exhausted_raises(monkeypatch):
    monkeypatch.setattr("src.broker.alpaca.time.sleep", lambda *_a, **_k: None)

    def always_timeout():
        raise RuntimeError('{"code":50410000,"message":"request timed out"}')

    with pytest.raises(RuntimeError, match="timed out"):
        alpaca_call_with_retry(always_timeout, op="test", attempts=3, base_delay_sec=0.01)


def test_cancel_stale_orders_zero_age_cancels_all():
    from src.broker.alpaca import AlpacaBroker

    broker = object.__new__(AlpacaBroker)
    cancelled = []
    broker.get_open_orders = lambda limit=50: [
        {"id": "1", "symbol": "AR", "submitted_at": "2026-08-17T16:01:00+00:00"},
        {"id": "2", "symbol": "APMD", "submitted_at": None},
    ]
    broker.cancel_order = lambda oid: cancelled.append(oid) or True
    out = AlpacaBroker.cancel_stale_orders(broker, max_age_hours=0)
    assert [c["id"] for c in out["cancelled"]] == ["1", "2"]
    assert out["skipped"] == []
    assert cancelled == ["1", "2"]


def test_cancel_stale_orders_positive_age_skips_fresh():
    from datetime import datetime, timedelta, timezone

    from src.broker.alpaca import AlpacaBroker

    broker = object.__new__(AlpacaBroker)
    cancelled = []
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    broker.get_open_orders = lambda limit=50: [
        {"id": "1", "symbol": "AR", "submitted_at": fresh},
    ]
    broker.cancel_order = lambda oid: cancelled.append(oid) or True
    out = AlpacaBroker.cancel_stale_orders(broker, max_age_hours=48)
    assert out["cancelled"] == []
    assert len(out["skipped"]) == 1
    assert cancelled == []


def test_tiny_failed_sell_does_not_block_wheel_lot_buys():
    from src.broker.alpaca import AlpacaBroker
    from src.portfolio.manager import PortfolioDecision

    broker = object.__new__(AlpacaBroker)
    submitted = []

    def execute_order(ticker, decision, **kwargs):
        submitted.append(ticker)
        if decision.action == "sell":
            return {"success": False, "error": "rejected"}
        return {"success": True, "order_id": f"buy-{ticker}"}

    broker.execute_order = execute_order
    broker.wait_for_order_fill = lambda *a, **k: {"ok": True}
    results = AlpacaBroker.execute_decisions(
        broker,
        {
            "CTSH": PortfolioDecision(
                action="sell", quantity=2, confidence=60, reasoning="Orphan exit"
            ),
            "F": PortfolioDecision(
                action="buy",
                quantity=100,
                confidence=75,
                reasoning="Wheel add-on lot (score 0.80, 2 lots, 70% sleeve)",
            ),
        },
        current_prices={"CTSH": 60.0, "F": 12.0},
        run_config={"wheel_mode": True},
    )
    assert "F" in submitted
    assert results["F"].get("success") is True
    assert results["F"].get("error") != "blocked_after_sell_fill_failure"


def test_lot_sell_fill_failure_still_blocks_wheel_buys():
    from src.broker.alpaca import AlpacaBroker
    from src.portfolio.manager import PortfolioDecision

    broker = object.__new__(AlpacaBroker)
    submitted = []

    def execute_order(ticker, decision, **kwargs):
        submitted.append(ticker)
        if decision.action == "sell":
            return {"success": True, "order_id": "sell-f"}
        return {"success": True, "order_id": f"buy-{ticker}"}

    broker.execute_order = execute_order
    broker.wait_for_order_fill = lambda *a, **k: {"ok": False, "status": "timeout"}
    results = AlpacaBroker.execute_decisions(
        broker,
        {
            "F": PortfolioDecision(
                action="sell",
                quantity=100,
                confidence=90,
                reasoning="Atomic CC rule: unwind lot — covered call write failed/skipped",
            ),
            "SOFI": PortfolioDecision(
                action="buy",
                quantity=100,
                confidence=70,
                reasoning="Wheel lot build toward 100 shares (70% sleeve)",
            ),
        },
        current_prices={"F": 12.0, "SOFI": 14.0},
        run_config={"wheel_mode": True},
    )
    assert "SOFI" not in submitted
    assert results["SOFI"].get("error") == "blocked_after_sell_fill_failure"


def test_wheel_addon_buy_is_clipped_into_100_share_orders():
    from src.broker.alpaca import AlpacaBroker
    from src.portfolio.manager import PortfolioDecision

    broker = object.__new__(AlpacaBroker)
    qtys = []

    def execute_order(ticker, decision, **kwargs):
        qtys.append(int(decision.quantity))
        return {"success": True, "order_id": f"buy-{len(qtys)}"}

    broker.execute_order = execute_order
    broker.wait_for_order_fill = lambda *a, **k: {"ok": True, "filled_qty": 100}
    results = AlpacaBroker.execute_decisions(
        broker,
        {
            "F": PortfolioDecision(
                action="buy",
                quantity=200,
                confidence=75,
                reasoning="Wheel add-on lot (score 0.80, 2 lots, 70% sleeve)",
            ),
        },
        current_prices={"F": 12.0},
        run_config={"wheel_mode": True},
    )
    assert qtys == [100, 100]
    assert results["F"]["fill"]["ok"] is True
    assert results["F"]["filled_qty"] == 200
