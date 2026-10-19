"""Test Scan path never submits put BTC regardless of config.

The Scan path (pipeline.py:~1304) calls manage_or_roll_short_calls without passing
auto_put_buyback, so it defaults to False (L335) and put closes are always disabled.
"""

from __future__ import annotations

from unittest.mock import MagicMock


class MockBroker:
    """Mock broker for Scan put buyback tests."""

    def __init__(
        self,
        option_positions=None,
        submit_success=True,
    ):
        self.option_positions = option_positions or []
        self.submit_success = submit_success
        self.submitted_orders = []

    def get_option_positions(self):
        return self.option_positions

    def submit_option_order(self, contract_symbol, side, qty, *args, **kwargs):
        order = {
            "contract_symbol": contract_symbol,
            "side": side,
            "qty": qty,
            "id": f"mock-order-{len(self.submitted_orders) + 1}",
        }
        self.submitted_orders.append(order)
        if self.submit_success:
            return {"ok": True, "order": order}
        return {"ok": False}


from src.options.covered_calls import CoveredCallManager
from src.options.wheel_lifecycle import manage_or_roll_short_calls


def test_scan_put_buyback_never_submitted():
    """Scan path behavior: put BTC is never submitted because auto_put_buyback is not passed (defaults to False)."""
    import os

    # Even with AUTO_PUT_BUYBACK env set to "1", the Scan path doesn't pass it to manage_or_roll_short_calls
    os.environ["AUTO_PUT_BUYBACK"] = "1"
    os.environ["ENABLE_COVERED_CALLS"] = "1"

    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106P00015000",
                "underlying": "NU",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.60,
                "current_price": 0.20,
            }
        ],
        submit_success=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
    )

    # Scan path: manage_or_roll_short_calls called without auto_put_buyback arg
    # (pipeline.py:~1304 doesn't pass it, so default=False applies)
    results = manage_or_roll_short_calls(
        broker,
        {"NU": 14.70},
        mgr,
        manage_dte_threshold=7,
        manage_itm_pct=0.02,
        profit_take_pct=0.60,
        prefer_roll=True,
        execute=True,
        # auto_put_buyback NOT passed => defaults to False
    )

    # Verify no put BTC orders submitted
    assert len(broker.submitted_orders) == 0, "Scan path must never submit put BTC orders"

    # Verify put result is skipped due to allow_put_closes=False (auto_put_buyback not passed)
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) == 1
    assert put_results[0]["status"] == "skipped"
    # Either "allow_put_closes=False_blocked" or "AUTO_PUT_BUYBACK=0_skipped" format
    assert ("allow_put_closes=False_blocked" in put_results[0]["reason"] 
            or "AUTO_PUT_BUYBACK=0_skipped" in put_results[0]["reason"])

    # Cleanup
    os.environ.pop("AUTO_PUT_BUYBACK", None)
    os.environ.pop("ENABLE_COVERED_CALLS", None)
