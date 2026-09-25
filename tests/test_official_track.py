"""Official track metrics, digest blocks, and missed-run email."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.performance.official_track import (
    START_DATE,
    START_NAV_USD,
    TRACK_ID,
    build_track_record,
    config_fingerprint,
    missed_run_due,
    save_snapshot,
    snapshot_from_results,
    weekly_slice,
)
from src.utils.wheel_email import (
    build_missed_run_email,
    build_wheel_daily_email,
    build_wheel_weekly_email,
)

ET = ZoneInfo("America/New_York")


def _snap(day: str, nav: float, spy: float, turnover: float = 100.0, **extra):
    row = {
        "track_id": TRACK_ID,
        "date": day,
        "official_nav_usd": nav,
        "spy_level": spy,
        "turnover_usd": turnover,
        "option_credit_closes": extra.get("option_credit_closes", 1),
        "option_closes": extra.get("option_closes", 1),
        "config_fingerprint": "abc123def456",
        "positions_summary": extra.get("positions_summary") or {"F": 100},
        "actions": extra.get("actions") or {"rolls": 1, "btc": 0},
        "fill_failures": extra.get("fill_failures") or [],
        "coverage_alerts": extra.get("coverage_alerts") or [],
        "premium_ledger_usd": extra.get("premium_ledger_usd", 200.0),
    }
    return row


def test_sample_results_fixture_renders():
    import json
    from pathlib import Path

    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "official_track_sample_results.json").read_text()
    )
    subject, text, _ = build_wheel_daily_email(raw)
    assert "equity $9,797.20" in subject
    assert "TRACK RECORD" in text
    assert "OPS HEALTH" in text
    assert "samplefp0001" in text


def test_fingerprint_stable_for_same_knobs():
    a = config_fingerprint({"wheel_pct": 0.7, "max_position_pct": 0.35})
    b = config_fingerprint({"wheel_pct": 0.7, "max_position_pct": 0.35, "noise": 1})
    assert a == b
    assert len(a) == 12
    c = config_fingerprint({"wheel_pct": 0.8, "max_position_pct": 0.35})
    assert a != c


def test_track_record_math_vs_start_and_spy(tmp_path: Path):
    snaps = [
        _snap("2026-09-21", 10000.0, 100.0),
        _snap("2026-09-22", 10100.0, 101.0),
        _snap("2026-09-23", 9900.0, 102.0),
        _snap("2026-09-24", 10200.0, 103.0),
        _snap("2026-09-25", 10300.0, 104.0),
    ]
    for s in snaps:
        save_snapshot(s, root=tmp_path)
    from src.performance.official_track import load_snapshots

    tr = build_track_record(load_snapshots(tmp_path), asof=date(2026, 9, 25))
    assert tr["start_nav_usd"] == START_NAV_USD
    assert tr["start_date"] == START_DATE.isoformat()
    assert tr["current_nav_usd"] == 10300.0
    assert tr["abs_return_pct"] == 3.0
    assert tr["abs_return_usd"] == 300.0
    # SPY 100 → 104 = +4%
    assert tr["spy_return_pct"] == 4.0
    assert tr["excess_return_pct"] == -1.0
    assert tr["excess_return_usd"] == -100.0
    assert tr["max_drawdown_pct"] is not None
    assert tr["max_drawdown_pct"] < 0
    assert tr["hit_sessions"] == 3  # +1%, -2%, +3%, +1% vs prior snap
    assert tr["return_sessions"] == 4
    assert tr["option_credit_hit_pct"] == 100.0
    assert tr["turnover_5"] is not None


def test_sharpe_none_until_four_returns():
    snaps = [_snap("2026-09-21", 10000.0, 100.0), _snap("2026-09-22", 10100.0, 101.0)]
    tr = build_track_record(snaps, asof=date(2026, 9, 22))
    assert tr["sharpe"] is None
    assert tr["sortino"] is None
    assert tr["beta"] is None


def test_daily_email_subject_has_nav_and_excess():
    results = {
        "timestamp": "2026-09-25T14:00:00-04:00",
        "portfolio": {"cash": 3000.0, "equity": 9797.20, "positions": {}},
        "track_record": {
            "track_id": TRACK_ID,
            "start_date": "2026-09-21",
            "start_nav_usd": 10000,
            "current_nav_usd": 9797.20,
            "abs_return_pct": -2.03,
            "abs_return_usd": -202.80,
            "spy_return_pct": 1.2,
            "excess_return_pct": -3.23,
            "excess_return_usd": -323.0,
            "max_drawdown_pct": -2.03,
            "current_drawdown_pct": -2.03,
            "sharpe": None,
            "sortino": None,
            "risk_free_annual": 0.0,
            "hit_rate_pct": 50.0,
            "hit_sessions": 2,
            "return_sessions": 4,
            "sessions_with_email": 4,
            "sessions_expected": 5,
            "config_fingerprint": "deadbeef0001",
        },
        "ops_health": {
            "morning": "ok",
            "afternoon": "skip",
            "clock": "10:32 ET",
            "expected_window": "10:30 ET",
            "broker_ok": True,
            "buying_power": 2467.0,
            "orders": {"submitted": 5, "filled": 5},
        },
        "config_fingerprint": "deadbeef0001",
        "wheel_scorecard": {"premium_ledger_usd": 376},
    }
    subject, text, _ = build_wheel_daily_email(results)
    assert "2026-09-25" in subject
    assert "equity $9,797.20" in subject
    assert "SPY +1.20%" in subject
    assert "excess -3.23%" in subject
    assert "TRACK RECORD" in text
    assert "OPS HEALTH" in text
    assert "deadbeef0001" in text
    assert "Morning OK" in text


def test_nan_sleeves_print_na_not_nan():
    nan = float("nan")
    subject, text, _ = build_wheel_daily_email(
        {
            "timestamp": "2026-09-23T14:00:00-04:00",
            "portfolio": {"cash": nan, "equity": nan, "positions": {}},
            "wheel_scorecard": {"premium_ledger_usd": nan},
        }
    )
    assert "nan%" not in text.lower()
    assert "n/a" in text
    assert "excess" in subject.lower()


def test_missed_run_email_and_watchdog():
    subject, text, _ = build_missed_run_email(
        day_label="2026-09-28",
        reason="missed_morning:2026-09-28:last=2026-09-25",
        last_success="2026-09-25",
    )
    assert subject == "Aletheia daily wheel — MISSED RUN — 2026-09-28"
    assert "MISSED RUN" in text
    assert "2026-09-25" in text

    monday = datetime(2026, 9, 28, 18, 0, tzinfo=ET)
    due, reason = missed_run_due(
        now=monday, last_success=date(2026, 9, 25), force=False
    )
    assert due is True
    assert "missed_morning" in reason
    due2, _ = missed_run_due(now=monday, last_success=date(2026, 9, 28))
    assert due2 is False


def test_weekly_digest_has_week_and_since_start():
    snaps = [
        _snap("2026-09-21", 10000.0, 100.0, premium_ledger_usd=100),
        _snap("2026-09-22", 10100.0, 101.0, premium_ledger_usd=150),
        _snap("2026-09-23", 9900.0, 102.0, premium_ledger_usd=180),
        _snap("2026-09-24", 10200.0, 103.0, premium_ledger_usd=220),
        _snap("2026-09-25", 10300.0, 104.0, premium_ledger_usd=280),
    ]
    week = weekly_slice(snaps, date(2026, 9, 25))
    assert [s["date"] for s in week] == [s["date"] for s in snaps]
    tr = build_track_record(snaps, asof=date(2026, 9, 25))
    subject, text, _ = build_wheel_weekly_email(
        friday_label="2026-09-25",
        track=tr,
        week_snaps=week,
        fingerprint="abc123def456",
    )
    assert subject.startswith("Aletheia weekly wheel — 2026-09-25")
    assert "equity $10,300.00" in subject
    assert "Week NAV:" in text
    assert "TRACK RECORD" in text
    assert "No silent resets" in text
    assert "abc123def456" in text
    assert "2026-09-21" in text


def test_snapshot_from_results_counts_actions():
    snap = snapshot_from_results(
        {
            "timestamp": "2026-09-25T14:00:00-04:00",
            "portfolio": {
                "cash": 3000,
                "equity": 9800,
                "positions": {"F": {"long": 100}},
            },
            "decisions": {"F": {"action": "sell", "quantity": 1}},
            "execution_results": {"F": {"fill": {"ok": False}}},
            "csp_results": [{"status": "executed", "estimated_premium": 40, "underlying": "LI"}],
            "covered_call_results": [],
            "wheel_manage_results": [
                {"status": "roll_executed", "est_net_credit": 25.5},
            ],
            "execution_status": {"submitted": 1, "filled": 0, "failed": 1},
            "coverage_map": [{"ticker": "F", "coverage": "covered"}],
        },
        run_config={"wheel_pct": 0.7},
    )
    assert snap["actions"]["sells"] == 1
    assert snap["actions"]["csp"] == 1
    assert snap["actions"]["rolls"] == 1
    assert any("fill_failed" in x for x in snap["fill_failures"])
    assert snap["track_id"] == TRACK_ID
