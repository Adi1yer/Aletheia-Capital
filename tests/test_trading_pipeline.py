"""Integration tests for trading pipeline"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.trading.pipeline import TradingPipeline


class TestTradingPipelineLearning:
    def test_merge_feedback_refresh_after_phase(self, tmp_path):
        pipeline = TradingPipeline.__new__(TradingPipeline)
        learning_context = {
            "scan_cache_run_count": 0,
            "ledger_run_count": 0,
        }

        class FakeCache:
            def list_runs(self, limit=500):
                return ["a", "b"]

        fake_meta = {
            "scan_cache_run_count": 2,
            "ledger_run_count": 2,
            "scorecard_agent_count": 3,
            "scorecard_pairs_used": 1,
            "scorecard_skip_reason": "",
            "wrote_scorecard_file": True,
            "wrote_agent_feedback": True,
            "scorecard_source": "scan_cache",
        }

        with patch(
            "src.backtesting.feedback.refresh_feedback_from_cache", return_value=fake_meta
        ), patch(
            "src.backtesting.agent_evaluator.load_scorecard",
            return_value={"agents": {"a": {}, "b": {}, "c": {}}},
        ):
            out = pipeline._merge_feedback_refresh(
                learning_context,
                FakeCache(),
                {"scorecard_run_pairs": 5},
                phase="after",
            )

        assert out["feedback_refresh_ok"] is True
        assert out["scan_cache_run_count_after"] == 2
        assert out["ledger_run_count_after"] == 2
        assert out["scorecard_present_after"] is True
        assert out["scorecard_present"] is True

    def test_merge_feedback_refresh_before_phase_sets_baseline(self):
        pipeline = TradingPipeline.__new__(TradingPipeline)
        learning_context = {"scan_cache_run_count": 0, "ledger_run_count": 1}

        class FakeCache:
            def list_runs(self, limit=500):
                return ["a"]

        fake_meta = {
            "scan_cache_run_count": 1,
            "ledger_run_count": 1,
            "scorecard_skip_reason": "need_at_least_2_cached_runs",
        }

        with patch(
            "src.backtesting.feedback.refresh_feedback_from_cache", return_value=fake_meta
        ), patch("src.backtesting.agent_evaluator.load_scorecard", return_value={"agents": {}}):
            out = pipeline._merge_feedback_refresh(
                learning_context,
                FakeCache(),
                {},
                phase="before",
            )

        assert out["scan_cache_run_count_before"] == 1
        assert out["ledger_run_count_before"] == 1
        assert out["scorecard_present"] is False

    def test_persist_learning_artifacts_appends_ledgers(self, tmp_path):
        pipeline = TradingPipeline.__new__(TradingPipeline)
        from src.portfolio.models import Portfolio

        portfolio = Portfolio(cash=10000.0, positions={})
        learning_context = {}

        with patch("src.performance.weekly_ledger.append_ledger_entry") as mock_weekly, patch(
            "src.performance.decision_ledger.append_decisions_from_run"
        ) as mock_decision, patch(
            "src.performance.options_ledger.append_cc_results"
        ) as mock_cc, patch(
            "src.performance.options_ledger.append_csp_results"
        ) as mock_csp, patch(
            "src.performance.fill_ledger.append_fills_from_run"
        ) as mock_fill, patch(
            "src.performance.portfolio_attribution.append_weekly_attribution",
            return_value={},
        ), patch(
            "src.performance.counterfactual_ledger.append_counterfactuals_from_run"
        ), patch(
            "src.performance.weekly_ledger.position_open_dates", return_value={}
        ), patch(
            "src.performance.weekly_ledger.build_tickers_from_run", return_value={}
        ):
            out = pipeline._persist_learning_artifacts(
                run_id="r1",
                run_date="2026-05-19",
                run_config={"active_agents": ["growth"], "regime": {"mode": "neutral"}},
                portfolio=portfolio,
                portfolio_after={"cash": 10000.0},
                agent_signals={},
                risk_analysis={},
                decisions={},
                execution_results={},
                cc_results=[],
                csp_results=[],
                scan_cache=None,
                learning_context=learning_context,
                recent_orders=[],
                agent_weights={},
            )

        mock_weekly.assert_called_once()
        mock_decision.assert_called_once()
        mock_cc.assert_called_once()
        mock_csp.assert_called_once()
        mock_fill.assert_called_once()
        assert out is learning_context

    def test_update_agent_weights_uses_ledger_fallback(self):
        pipeline = TradingPipeline.__new__(TradingPipeline)
        pipeline.performance_tracker = Mock()
        pipeline.registry = Mock()
        pipeline.registry.get_weights.return_value = {"growth": 1.0}
        pipeline.performance_tracker.load_from_scan_cache.return_value = 0
        pipeline.performance_tracker.load_from_weekly_ledger.return_value = 3
        pipeline.performance_tracker.calculate_weights_from_performance.return_value = (
            {},
            {"weight_changes": [], "weight_skips": []},
        )

        with patch("src.backtesting.agent_evaluator.load_scorecard", return_value={}), patch(
            "src.backtesting.agent_evaluator.blend_scorecard_metrics", return_value={}
        ):
            pipeline._update_agent_weights(
                scan_cache=Mock(),
                run_config={"regime": {"mode": "neutral"}},
                learning_context={"ledger_run_count_after": 3},
            )

        pipeline.performance_tracker.load_from_weekly_ledger.assert_called_once_with(limit_pairs=5)


class TestTradingPipeline:
    """Legacy integration placeholders"""

    @pytest.mark.skip(reason="Requires full system integration")
    def test_run_pipeline_dry_run(self):
        pass

    @pytest.mark.skip(reason="Requires full system integration")
    def test_run_pipeline_with_execution(self):
        pass

