from __future__ import annotations

from src.biotech import discovery_ladder as dl


def test_ladder_strict_returns_when_candidates_found(monkeypatch):
    calls = []

    def fake_discover(**kwargs):
        calls.append(kwargs)
        if kwargs.get("min_phase") == 2:
            return ["AAA"], {"discovery_stage": "strict", "selected_count": 1}
        return [], {"selected_count": 0}

    monkeypatch.setattr(dl, "discover_catalyst_candidates", fake_discover)
    tickers, _, meta = dl.run_discovery_ladder(
        forward_days=120,
        past_grace_days=45,
        fallback_forward_days=180,
        fallback_past_grace_days=60,
        max_universe=320,
        max_candidates=5,
        broker=None,
        policy={"discovery_min_phase": 2, "readout_max_forward_days": 90},
    )
    assert tickers == ["AAA"]
    assert meta["discovery_stage"] == "strict"
    assert len(calls) == 1


def test_ladder_falls_through_to_relaxed(monkeypatch):
    calls = []

    def fake_discover(**kwargs):
        calls.append(kwargs)
        if kwargs.get("min_phase") == 1:
            return ["BBB"], {"selected_count": 1, "near_miss_summaries": []}
        return [], {"selected_count": 0, "near_miss_summaries": [{"ticker": "X"}]}

    monkeypatch.setattr(dl, "discover_catalyst_candidates", fake_discover)
    tickers, _, meta = dl.run_discovery_ladder(
        forward_days=120,
        past_grace_days=45,
        fallback_forward_days=180,
        fallback_past_grace_days=60,
        max_universe=320,
        max_candidates=5,
        broker=None,
        policy={"discovery_min_phase": 2, "readout_max_forward_days": 90},
    )
    assert tickers == ["BBB"]
    assert meta["discovery_stage"] == "relaxed"
    assert len(calls) == 2


def test_ladder_watchlist_stage(monkeypatch):
    monkeypatch.setattr(dl, "load_biotech_tickers", lambda: ["MRNA", "VRTX"])

    def fake_discover(**kwargs):
        if kwargs.get("seed_tickers"):
            return ["MRNA"], {"selected_count": 1}
        return [], {"selected_count": 0}

    monkeypatch.setattr(dl, "discover_catalyst_candidates", fake_discover)
    tickers, _, meta = dl.run_discovery_ladder(
        forward_days=120,
        past_grace_days=45,
        fallback_forward_days=180,
        fallback_past_grace_days=60,
        max_universe=320,
        max_candidates=5,
        broker=None,
        policy={"discovery_min_phase": 2, "readout_max_forward_days": 90},
    )
    assert tickers == ["MRNA"]
    assert meta["discovery_stage"] == "watchlist"
