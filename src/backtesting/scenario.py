"""Run the weekly pipeline under alternate weights, thresholds, or agent subsets."""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Set

import structlog

logger = structlog.get_logger()


def run_with_weight_overrides(
    pipeline: Any,
    tickers: List[str],
    base_run_config: Dict[str, Any],
    weight_multipliers: Dict[str, float],
    scan_cache: Optional[Any] = None,
    execute: bool = False,
) -> Dict[str, Any]:
    """Multiply registry weights by per-agent multipliers. Restores weights after the run."""
    registry = pipeline.registry
    old = registry.get_weights()
    try:
        new_w = {k: max(0.05, old.get(k, 1.0) * float(weight_multipliers.get(k, 1.0))) for k in old}
        for k, w in new_w.items():
            registry.update_weight(k, w)
        cfg = copy.deepcopy(base_run_config)
        cfg["execute"] = execute
        cfg["scenario"] = {"weight_multipliers": weight_multipliers}
        return pipeline.run_weekly_trading(tickers=tickers, execute=execute, scan_cache=scan_cache, run_config=cfg)
    finally:
        for k, w in old.items():
            registry.update_weight(k, w)
        registry.save_weights_to_config()


def run_with_agent_dropout(
    pipeline: Any,
    tickers: List[str],
    base_run_config: Dict[str, Any],
    dropped_agent_keys: Set[str],
    scan_cache: Optional[Any] = None,
    execute: bool = False,
) -> Dict[str, Any]:
    """Push dropped agents to minimal weight temporarily."""
    registry = pipeline.registry
    old = registry.get_weights()
    try:
        for k in old:
            if k in dropped_agent_keys:
                registry.update_weight(k, 0.05)
        cfg = copy.deepcopy(base_run_config)
        cfg["execute"] = execute
        cfg["scenario"] = {"dropped": sorted(dropped_agent_keys)}
        return pipeline.run_weekly_trading(tickers=tickers, execute=execute, scan_cache=scan_cache, run_config=cfg)
    finally:
        for k, w in old.items():
            registry.update_weight(k, w)
        registry.save_weights_to_config()


def run_threshold_grid(
    pipeline_factory: Callable[[], Any],
    tickers: List[str],
    base_run_config: Dict[str, Any],
    min_buy_grid: List[int],
    min_sell_grid: List[int],
) -> List[Dict[str, Any]]:
    """Dry-run only: sweep thresholds."""
    results = []
    for mb in min_buy_grid:
        for ms in min_sell_grid:
            pipe = pipeline_factory()
            cfg = copy.deepcopy(base_run_config)
            cfg["execute"] = False
            cfg["min_buy_confidence"] = mb
            cfg["min_sell_confidence"] = ms
            cfg["scenario"] = {"grid": {"min_buy": mb, "min_sell": ms}}
            out = pipe.run_weekly_trading(tickers=tickers, execute=False, scan_cache=None, run_config=cfg)
            buys = sum(1 for d in out.get("decisions", {}).values() if d.get("action") == "buy")
            sells = sum(1 for d in out.get("decisions", {}).values() if d.get("action") == "sell")
            results.append({"min_buy": mb, "min_sell": ms, "buys": buys, "sells": sells})
            logger.info("Scenario grid point", min_buy=mb, min_sell=ms, buys=buys, sells=sells)
    return results
