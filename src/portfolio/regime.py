"""Market regime detection (SPY vs 200-day SMA) for rebalance knob adjustment."""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()


def detect_regime(
    data_provider,
    start_date: str,
    end_date: str,
    benchmark: str = "SPY",
) -> Dict[str, Any]:
    """
    Returns mode: accumulate | neutral | harvest, plus metadata for email.
    """
    out: Dict[str, Any] = {
        "mode": "neutral",
        "benchmark": benchmark,
        "last_close": None,
        "sma_200": None,
        "detail": "",
    }
    try:
        prices = data_provider.get_prices(benchmark, start_date, end_date)
        if prices is None or len(prices) < 200:
            out["detail"] = "insufficient SPY history"
            return out
        closes = prices["close"].astype(float)
        last = float(closes.iloc[-1])
        sma = float(closes.tail(200).mean())
        out["last_close"] = round(last, 2)
        out["sma_200"] = round(sma, 2)
        if last < sma * 0.99:
            out["mode"] = "harvest"
            out["detail"] = f"{benchmark} below 200d SMA"
        elif last > sma * 1.01:
            out["mode"] = "accumulate"
            out["detail"] = f"{benchmark} above 200d SMA"
        else:
            out["mode"] = "neutral"
            out["detail"] = f"{benchmark} near 200d SMA"
    except Exception as e:
        logger.warning("Regime detection failed", error=str(e))
        out["detail"] = str(e)
    return out


def apply_regime_to_run_config(run_config: Dict[str, Any], regime: Dict[str, Any]) -> Dict[str, Any]:
    """Adjust rebalance knobs when regime_mode is auto."""
    if str(run_config.get("regime_mode", "")).lower() not in ("auto", "on", "true", "1"):
        run_config["regime"] = regime
        return run_config

    mode = regime.get("mode", "neutral")
    run_config["regime"] = regime
    base_buy = int(run_config.get("min_buy_confidence", 50))
    base_sell = int(run_config.get("min_sell_confidence", 60))
    base_max_buy = int(run_config.get("max_buy_tickers", 30))
    base_buffer = float(run_config.get("cash_buffer_pct", 0.03))

    if mode == "harvest":
        run_config["min_buy_confidence"] = min(100, base_buy + 3)
        run_config["min_sell_confidence"] = max(0, base_sell - 2)
        run_config["max_buy_tickers"] = max(5, base_max_buy - 5)
        run_config["cash_buffer_pct"] = min(0.15, base_buffer + 0.01)
    elif mode == "accumulate":
        run_config["min_buy_confidence"] = max(0, base_buy - 2)
        run_config["max_buy_tickers"] = base_max_buy + 3
        run_config["cash_buffer_pct"] = max(0.01, base_buffer - 0.005)

    return run_config
