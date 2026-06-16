from __future__ import annotations

from src.utils.email import EmailNotifier


def _base_results():
    return {
        "timestamp": "2026-04-28T10:00:00",
        "tickers": ["A", "B"],
        "decisions": {
            "A": {"action": "hold", "confidence": 60, "reasoning": "x"},
            "B": {"action": "hold", "confidence": 55, "reasoning": "y"},
            "SMCI": {
                "action": "buy",
                "quantity": 10,
                "confidence": 85,
                "reasoning": "Cash rotation: fund SMCI buy",
            },
        },
        "portfolio": {"cash": 1000.0, "equity": 1000.0, "positions": {}},
        "execution_results": {
            "SMCI": {"status": "filled", "qty": 10},
        },
        "execution_status": {
            "had_live_execution": True,
            "run_in_rth": True,
            "submitted": 1,
            "filled": 1,
            "pending": 0,
            "partial": 0,
            "failed": 0,
            "by_ticker": {"SMCI": {"status": "filled", "broker_status": "filled"}},
            "note": "",
        },
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
            "enable_cash_rotation": True,
            "cash_rotation_skip_reason": "buy_meaningfully_allocatable",
            "cc_held_lot_count": 2,
            "cc_lot_build_count": 0,
            "lane_contributions": {"bullish": 4, "bearish": 2, "total": 6},
        },
        "llm_budget": {"used": 120, "remaining": 40},
        "agent_errors": {"growth_analyst": "timeout"},
        "learning_context": {
            "feedback_refresh_ok": True,
            "scorecard_present": False,
            "scan_cache_run_count_before": 1,
            "policy_calibration": {
                "min_buy_confidence": 62,
                "cash_rotation_min_edge": 12,
                "adjustments": [{"knob": "min_buy_confidence", "delta": 2, "reason": "test"}],
            },
            "weight_changes": [{"agent": "growth", "old": 1.0, "new": 1.1, "observations": 20}],
            "weight_skips": [],
        },
    }


def test_text_email_contains_diagnostics_blocks():
    notifier = EmailNotifier()
    text = notifier._format_trading_results_text(_base_results(), past_perf=None, outlook=None)
    assert "DECISION DIAGNOSTICS" in text
    assert "Signals: bullish>=buy=3" in text
    assert "LEARNING CONTEXT" in text
    assert "Learned policy" in text
    assert "LEARNING CHANGELOG" in text
    assert "DECISION DIAGNOSTICS" in text
    assert "SUBMITTED TRADES (THIS RUN)" in text
    assert "ORDER EXECUTION STATUS" in text
    assert "Lane contributions" in text
    assert "LLM budget" in text
    assert "Agent errors" in text


def test_html_email_contains_diagnostics_blocks():
    notifier = EmailNotifier()
    html = notifier._format_trading_results_html(_base_results(), past_perf=None, outlook=None)
    assert "Decision Diagnostics" in html
    assert "Learning context" in html
    assert "Scan cache (before / after)" in html
    assert "Decision Diagnostics" in html
    assert "Submitted trades (this run)" in html
    assert "Order execution status" in html
    assert "Run Observability" in html
    assert "Learned policy" in html
    assert "Learning changelog" in html
    assert "buy_conf=62" in html
