"""Fund orchestrator tests."""

from src.fund.orchestrator import compute_weekly_metrics, default_allocation, workflow_risk_budget_pct


def test_default_allocation():
    alloc = default_allocation()
    assert "targets" in alloc
    assert sum(alloc["targets"].values()) > 0.9


def test_weekly_metrics_structure():
    m = compute_weekly_metrics()
    assert "workflows" in m
    assert "total_equity" in m


def test_risk_budget_default():
    assert workflow_risk_budget_pct("weekly-scan") >= 0
