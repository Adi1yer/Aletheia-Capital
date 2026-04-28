from __future__ import annotations

from src.utils.email import EmailNotifier


def _base_results():
    return {
        "timestamp": "2026-04-28T10:00:00",
        "tickers": ["A", "B"],
        "decisions": {
            "A": {"action": "hold", "confidence": 60, "reasoning": "x"},
            "B": {"action": "hold", "confidence": 55, "reasoning": "y"},
        },
        "portfolio": {"cash": 1000.0, "equity": 1000.0, "positions": {}},
        "execution_results": {},
        "covered_call_results": [],
        "covered_call_diagnostics": {"enabled": True, "execute_mode": True},
        "decision_diagnostics": {
            "buy_signal_count": 3,
            "sell_signal_on_held_count": 1,
            "buy_candidates_pre_rank": 3,
            "buy_candidates_post_rank": 2,
            "cc_scored_count": 10,
            "cc_passed_threshold_count": 4,
            "buy_blocked_by_risk_or_sizing_count": 2,
            "buy_blockers": {"risk_cap": 1, "cash_or_pending": 1},
        },
        "learning_context": {"feedback_refresh_ok": True, "scorecard_present": True},
    }


def test_text_email_contains_diagnostics_blocks():
    notifier = EmailNotifier()
    text = notifier._format_trading_results_text(_base_results(), past_perf=None, outlook=None)
    assert "DECISION DIAGNOSTICS" in text
    assert "Signals: bullish>=buy=3" in text
    assert "LEARNING CONTEXT" in text


def test_html_email_contains_diagnostics_blocks():
    notifier = EmailNotifier()
    html = notifier._format_trading_results_html(_base_results(), past_perf=None, outlook=None)
    assert "Decision Diagnostics" in html
    assert "Learning context" in html
