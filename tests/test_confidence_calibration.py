"""Tests for confidence calibration."""

from __future__ import annotations

from src.performance.confidence_calibration import build_from_scorecard, calibrate_confidence, save_calibration


def test_calibrate_confidence_from_bins(tmp_path):
    path = tmp_path / "conf.json"
    payload = build_from_scorecard(
        {
            "agents": {
                "growth": {
                    "directional_accuracy": 0.55,
                    "directional_observations": 40,
                }
            }
        }
    )
    save_calibration(payload, path=path)
    out = calibrate_confidence("growth", 85, path=path)
    assert 30 <= out <= 95


def test_build_from_scorecard_uses_empirical_bin_rows():
    payload = build_from_scorecard(
        {"agents": {"growth": {"directional_accuracy": 0.5, "directional_observations": 10}}},
        decision_rows=[
            {"agents_for": ["growth"], "confidence": 82, "directionally_correct": True},
            {"agents_for": ["growth"], "confidence": 84, "directionally_correct": False},
            {"agents_for": ["growth"], "confidence": 86, "directionally_correct": True},
        ],
    )
    b = payload["agents"]["growth"]["bins"]["80-91"]
    assert b["observations"] == 3
    assert abs(float(b["empirical_hit_rate"]) - (2 / 3)) < 0.01
