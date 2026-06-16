from src.performance.canary_autopromoter import append_canary_result, evaluate_canary
from src.performance.cost_optimizer import compute_lane_utility, tune_lane_budget


def test_canary_autopromoter_consecutive_non_regressing(tmp_path):
    ledger = tmp_path / "canary.jsonl"
    cid = "candidate-v1"
    append_canary_result(cid, {"delta_accuracy_pp": 0.1}, path=ledger)
    append_canary_result(cid, {"delta_accuracy_pp": 0.0}, path=ledger)
    append_canary_result(cid, {"delta_accuracy_pp": 0.2}, path=ledger)
    verdict = evaluate_canary(cid, min_consecutive=3, path=ledger)
    assert verdict["promote"] is True


def test_cost_optimizer_lane_budget_tuning():
    results = {
        "decision_provenance": {
            "AAPL": {"raw": [{"agent": "lane:fundamentals", "confidence": 80}]},
            "MSFT": {"raw": [{"agent": "lane:technicals", "confidence": 35}]},
        }
    }
    utility = compute_lane_utility(results)
    tuned = tune_lane_budget({"fundamentals": 2, "technicals": 2}, utility)
    assert tuned["fundamentals"] >= 2
    assert tuned["technicals"] <= 2

