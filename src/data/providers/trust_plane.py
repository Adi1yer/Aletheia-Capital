"""Provider trust scoring and drift detection."""

from __future__ import annotations

from typing import Any, Dict, List


def update_provider_trust(
    metrics: Dict[str, int],
    *,
    provider: str,
    success: bool,
) -> Dict[str, float]:
    key = f"trust_{provider}"
    total_key = f"total_{provider}"
    metrics[total_key] = int(metrics.get(total_key, 0)) + 1
    if success:
        metrics[key] = int(metrics.get(key, 0)) + 1
    total = max(1, int(metrics.get(total_key, 1)))
    return {provider: round(int(metrics.get(key, 0)) / total, 4)}


def trust_ordered_providers(metrics: Dict[str, int], providers: List[str]) -> List[str]:
    scores = []
    for p in providers:
        total = max(1, int(metrics.get(f"total_{p}", 0)))
        trust = int(metrics.get(f"trust_{p}", 0)) / total
        scores.append((trust, p))
    scores.sort(reverse=True)
    return [p for _, p in scores]


def detect_provider_drift(
    left: Dict[str, Any],
    right: Dict[str, Any],
    *,
    metric: str = "current_price",
    threshold_pct: float = 2.0,
) -> List[Dict[str, Any]]:
    alarms: List[Dict[str, Any]] = []
    for ticker, lrow in (left or {}).items():
        rrow = (right or {}).get(ticker) or {}
        lval = float((lrow or {}).get(metric) or 0.0)
        rval = float((rrow or {}).get(metric) or 0.0)
        if lval <= 0 or rval <= 0:
            continue
        drift_pct = abs(rval - lval) / lval * 100.0
        if drift_pct >= threshold_pct:
            alarms.append(
                {
                    "ticker": ticker,
                    "metric": metric,
                    "left": lval,
                    "right": rval,
                    "drift_pct": round(drift_pct, 3),
                }
            )
    return alarms
