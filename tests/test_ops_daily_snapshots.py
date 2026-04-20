"""Tests for daily snapshot lifecycle helpers."""

from __future__ import annotations

from src.ops import daily_snapshots as ds


def test_lifecycle_delta_opened_straddle():
    prior = {
        "date": "2026-04-13",
        "option_positions": [],
    }
    current = {
        "date": "2026-04-14",
        "option_positions": [
            {
                "symbol": "ARVN260116C00030000",
                "underlying": "ARVN",
                "expiry": "2026-01-16",
                "type": "call",
                "strike": 30.0,
            },
            {
                "symbol": "ARVN260116P00030000",
                "underlying": "ARVN",
                "expiry": "2026-01-16",
                "type": "put",
                "strike": 30.0,
            },
        ],
    }
    d = ds._lifecycle_delta_dict(prior, current)
    assert "Opened (straddle groups)" in " ".join(d["notes"])


def test_lifecycle_delta_unchanged():
    legs = [
        {
            "symbol": "X260116C00010000",
            "underlying": "X",
            "expiry": "2026-01-16",
            "type": "call",
            "strike": 10.0,
        },
        {
            "symbol": "X260116P00010000",
            "underlying": "X",
            "expiry": "2026-01-16",
            "type": "put",
            "strike": 10.0,
        },
    ]
    p = {"date": "2026-04-13", "option_positions": legs}
    c = {"date": "2026-04-14", "option_positions": legs}
    d = ds._lifecycle_delta_dict(p, c)
    assert any("unchanged" in n.lower() for n in d["notes"])


def test_underlying_lifecycle_carried():
    legs = [
        {
            "symbol": "Z260116C00005000",
            "underlying": "Z",
            "expiry": "2026-01-16",
            "type": "call",
            "strike": 5.0,
        },
        {
            "symbol": "Z260116P00005000",
            "underlying": "Z",
            "expiry": "2026-01-16",
            "type": "put",
            "strike": 5.0,
        },
    ]
    old = {"date": "2026-04-10", "option_positions": legs}
    new = {"date": "2026-04-14", "option_positions": legs}
    m = ds._underlying_lifecycle_states(old, new)
    assert "Z" in m
    assert "carried" in m["Z"].lower()
