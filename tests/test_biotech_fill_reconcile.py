"""Fill reconciliation for biotech straddle legs."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.biotech.fill_reconcile import reconcile_straddle_orders


def test_reconcile_both_legs_filled():
    broker = MagicMock()
    broker.get_recent_orders.return_value = [
        {
            "id": "1",
            "symbol": "AAA260117C00050000",
            "status": "filled",
            "filled_qty": 1,
            "filled_avg_price": 2.5,
        },
        {
            "id": "2",
            "symbol": "AAA260117P00050000",
            "status": "filled",
            "filled_qty": 1,
            "filled_avg_price": 2.0,
        },
    ]
    leg_orders = [
        {"contract": "AAA260117C00050000"},
        {"contract": "AAA260117P00050000"},
    ]
    out = reconcile_straddle_orders(broker, leg_orders)
    assert out["status"] == "filled"
    assert out["total_premium_filled"] == 450.0
