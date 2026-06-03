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
