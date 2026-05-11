from __future__ import annotations

from types import SimpleNamespace

from src.biotech import candidate_discovery as cd
from src.biotech.models import BiotechSnapshot, TrialSummary


def test_load_discovery_blocklist_file_comments_and_env(tmp_path, monkeypatch):
    path = tmp_path / "block.txt"
    path.write_text("AAA  # inline\n# full-line comment\nBbB\n", encoding="utf-8")
    monkeypatch.delenv("BIOTECH_DISCOVERY_BLOCKLIST", raising=False)
    got = cd._load_discovery_blocklist(str(path), "ccc, aaa")
    assert got == {"AAA", "BBB", "CCC"}


def test_load_discovery_blocklist_missing_file():
    got = cd._load_discovery_blocklist("/nonexistent/does_not_exist_blocklist.txt", "ZZZ")
    assert got == {"ZZZ"}


def test_discovery_filters_and_counts(monkeypatch):
    monkeypatch.setattr(
        "src.data.universe.StockUniverse.get_trading_universe",
        lambda self, **kwargs: ["AAA", "BBB", "CCC"],
    )
    profiles = {
        "AAA": {
            "ticker": "AAA",
            "is_biotech": True,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": True,
            "market_cap": 2_000_000_000.0,
            "error": "",
        },
        "BBB": {
            "ticker": "BBB",
            "is_biotech": False,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": True,
            "market_cap": 2_000_000_000.0,
            "error": "",
        },
        "CCC": {
            "ticker": "CCC",
            "is_biotech": True,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 1_000_000.0,
            "has_yf_options": True,
            "market_cap": 2_000_000_000.0,
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
        "src.data.universe.StockUniverse.get_trading_universe",
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
            "market_cap": 3_000_000_000.0,
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


def test_discovery_blocklist(monkeypatch):
    monkeypatch.setattr(
        "src.data.universe.StockUniverse.get_trading_universe",
        lambda self, **kwargs: ["AAA", "DDD"],
    )
    profiles = {
        "AAA": {
            "ticker": "AAA",
            "is_biotech": True,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": True,
            "market_cap": 2_000_000_000.0,
            "error": "",
        },
        "DDD": {
            "ticker": "DDD",
            "is_biotech": True,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": True,
            "market_cap": 2_000_000_000.0,
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
        blocklist={"AAA"},
    )
    assert tickers == ["DDD"]
    assert diag["excluded_blocklist"] == 1


def test_discovery_market_cap_bounds(monkeypatch):
    monkeypatch.setattr(
        "src.data.universe.StockUniverse.get_trading_universe",
        lambda self, **kwargs: ["SMALL", "BIG"],
    )
    profiles = {
        "SMALL": {
            "ticker": "SMALL",
            "is_biotech": True,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": True,
            "market_cap": 100_000_000.0,
            "error": "",
        },
        "BIG": {
            "ticker": "BIG",
            "is_biotech": True,
            "last_price": 10.0,
            "avg_dollar_volume_30d": 30_000_000.0,
            "has_yf_options": True,
            "market_cap": 200_000_000_000.0,
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
        min_market_cap_usd=200_000_000.0,
        max_market_cap_usd=50_000_000_000.0,
    )
    assert tickers == []
    assert diag["excluded_market_cap_too_small"] == 1
    assert diag["excluded_market_cap_too_large"] == 1
