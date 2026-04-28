from __future__ import annotations

from types import SimpleNamespace

from src.biotech import candidate_discovery as cd
from src.biotech.models import BiotechSnapshot, TrialSummary


def test_discovery_filters_and_counts(monkeypatch):
    monkeypatch.setattr(
        cd.StockUniverse,
        "get_trading_universe",
        lambda self, **kwargs: ["AAA", "BBB", "CCC"],
    )
    profiles = {
        "AAA": {
            "ticker": "AAA",
            "is_biotech": True,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": True,
            "error": "",
        },
        "BBB": {
            "ticker": "BBB",
            "is_biotech": False,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": True,
            "error": "",
        },
        "CCC": {
            "ticker": "CCC",
            "is_biotech": True,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 1_000_000.0,
            "has_yf_options": True,
            "error": "",
        },
    }
    monkeypatch.setattr(cd, "_profile_ticker", lambda t: profiles[t])
    monkeypatch.setattr(
        cd,
        "build_snapshot",
        lambda t: BiotechSnapshot(
            ticker=t,
            as_of="2026-01-01",
            trials=[TrialSummary(nct_id="x", primary_completion_date="2026-05-01")],
        ),
    )
    monkeypatch.setattr(cd, "snapshot_has_readout_catalyst", lambda *args, **kwargs: True)

    tickers, diag = cd.discover_catalyst_candidates(
        forward_days=120,
        past_grace_days=45,
        max_universe=10,
        max_candidates=5,
        min_avg_dollar_volume=5_000_000.0,
        broker=None,
    )

    assert tickers == ["AAA"]
    assert diag["excluded_non_biotech"] == 1
    assert diag["excluded_illiquid"] == 1
    assert diag["selected_count"] == 1


def test_discovery_optionability_with_broker(monkeypatch):
    monkeypatch.setattr(
        cd.StockUniverse,
        "get_trading_universe",
        lambda self, **kwargs: ["AAA"],
    )
    monkeypatch.setattr(
        cd,
        "_profile_ticker",
        lambda t: {
            "ticker": t,
            "is_biotech": True,
            "last_price": 20.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": False,
            "error": "",
        },
    )
    monkeypatch.setattr(
        cd,
        "build_snapshot",
        lambda t: BiotechSnapshot(
            ticker=t,
            as_of="2026-01-01",
            trials=[TrialSummary(nct_id="x", primary_completion_date="2026-05-01")],
        ),
    )
    monkeypatch.setattr(cd, "snapshot_has_readout_catalyst", lambda *args, **kwargs: True)
    broker = SimpleNamespace(get_option_contracts=lambda **kwargs: [{"symbol": "AAA250C"}])

    tickers, diag = cd.discover_catalyst_candidates(
        forward_days=120,
        past_grace_days=45,
        max_universe=10,
        max_candidates=5,
        broker=broker,
    )
    assert tickers == ["AAA"]
    assert diag["excluded_non_optionable"] == 0
