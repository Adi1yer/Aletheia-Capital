from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.trading.execution_status import (
    build_execution_status,
    execution_subject_fragment,
    is_us_equity_rth,
    next_us_equity_open_after,
)


def test_is_us_equity_rth_weekday_session():
    # Tue 2026-06-16 10:00 ET
    dt = datetime(2026, 6, 16, 14, 0, tzinfo=ZoneInfo("UTC"))  # 10:00 ET (EDT)
    assert is_us_equity_rth(dt) is True


def test_is_us_equity_rth_after_close():
    # Tue 2026-06-16 18:00 ET
    dt = datetime(2026, 6, 16, 22, 0, tzinfo=ZoneInfo("UTC"))
    assert is_us_equity_rth(dt) is False


def test_next_open_after_friday_evening():
    # Fri 2026-06-12 20:00 ET → Mon Jun 15 9:30 AM ET
    dt = datetime(2026, 6, 13, 0, 0, tzinfo=ZoneInfo("UTC"))  # Fri 8pm ET
    nxt = next_us_equity_open_after(dt)
    assert nxt.weekday() == 0
    assert nxt.hour == 9 and nxt.minute == 30


def test_build_execution_status_after_hours_pending():
    execution_results = {
        "AAPL": {"success": True, "order_id": "oid-1", "side": "buy", "qty": 5},
    }
    status = build_execution_status(
        execution_results,
        open_orders=[],
        recent_orders=[],
        run_timestamp="2026-06-12T22:00:00-04:00",
    )
    assert status["run_in_rth"] is False
    assert status["submitted"] == 1
    assert status["pending"] == 1
    assert status["filled"] == 0
    assert status["by_ticker"]["AAPL"]["status"] == "pending"
    assert "outside us regular market hours" in status["note"].lower()


def test_build_execution_status_filled_from_recent_orders():
    execution_results = {
        "SMCI": {"success": True, "order_id": "oid-smci", "side": "buy", "qty": 10},
    }
    recent_orders = [
        {
            "id": "oid-smci",
            "symbol": "SMCI",
            "status": "filled",
            "qty": 10,
            "filled_qty": 10,
        }
    ]
    status = build_execution_status(
        execution_results,
        open_orders=[],
        recent_orders=recent_orders,
        run_timestamp="2026-06-16T14:00:00-04:00",
    )
    assert status["filled"] == 1
    assert status["by_ticker"]["SMCI"]["status"] == "filled"


def test_build_execution_status_partial_fill():
    execution_results = {
        "NVDA": {"success": True, "order_id": "oid-nvda", "side": "buy", "qty": 10},
    }
    open_orders = [
        {"id": "oid-nvda", "symbol": "NVDA", "status": "partially_filled", "qty": 10, "filled_qty": 4}
    ]
    status = build_execution_status(
        execution_results,
        open_orders=open_orders,
        recent_orders=[],
        run_timestamp="2026-06-16T14:00:00-04:00",
    )
    assert status["partial"] == 1
    assert status["by_ticker"]["NVDA"]["status"] == "partial"


def test_execution_subject_fragment_pending():
    frag = execution_subject_fragment(
        {
            "had_live_execution": True,
            "submitted": 3,
            "filled": 0,
            "pending": 3,
            "partial": 0,
            "failed": 0,
        }
    )
    assert frag == "3 Submitted (pending)"


def test_execution_subject_fragment_mixed():
    frag = execution_subject_fragment(
        {
            "had_live_execution": True,
            "submitted": 4,
            "filled": 2,
            "pending": 2,
            "partial": 0,
            "failed": 0,
        }
    )
    assert frag == "4 Submitted (2 filled, 2 pending)"
