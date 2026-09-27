"""Official growth-income-drip-v1 paper track: quarterly rebalance, dividend drip.

Official scoreboard NAV is Alpaca equity. Growth/ballast sleeves tracked separately.
Never reset start_date / start_nav without a new track id.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

TRACK_ID = "growth-income-drip-v1"
START_DATE = date(2026, 9, 27)
START_NAV_USD = 10_000.0
RISK_FREE_ANNUAL = 0.0
PERIODS_PER_YEAR = 252.0
SNAPSHOT_DIR = Path("data/performance/growth_income_drip_v1")
LAST_SUCCESS_NAME = "last_successful_run_et.txt"

FINGERPRINT_KEYS = (
    "track_id",
    "start_date",
    "start_nav_usd",
    "growth_weight",
    "ballast_weight",
    "rebalance_frequency",
    "momentum_lookback_months",
    "momentum_skip_months",
    "momentum_top_n",
    "dividend_drip_to_growth",
    "cost_bps",
)


def _finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def config_fingerprint(run_config: Optional[Dict[str, Any]] = None) -> str:
    cfg = dict(run_config or {})
    payload = {
        "track_id": TRACK_ID,
        "start_date": START_DATE.isoformat(),
        "start_nav_usd": START_NAV_USD,
    }
    for k in FINGERPRINT_KEYS:
        if k in ("track_id", "start_date", "start_nav_usd"):
            continue
        if k in cfg:
            payload[k] = cfg.get(k)
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def snapshot_dir(root: Optional[Path] = None) -> Path:
    return Path(root) if root is not None else SNAPSHOT_DIR


def record_snapshot(
    nav: float,
    cash_plus_stocks: float,
    positions: Dict[str, Any],
    run_config: Optional[Dict[str, Any]] = None,
    run_date: Optional[date] = None,
    growth_nav: Optional[float] = None,
    ballast_nav: Optional[float] = None,
    dividend_cash: Optional[float] = None,
) -> Path:
    """
    Record a daily snapshot of the drip track.
    
    Args:
        nav: Alpaca account equity (official NAV)
        cash_plus_stocks: Cash + stock market value
        positions: Current positions dictionary
        run_config: Run configuration
        run_date: Date of snapshot (default: today)
        growth_nav: Growth sleeve NAV
        ballast_nav: Ballast sleeve NAV
        dividend_cash: Accumulated dividend cash
        
    Returns:
        Path to snapshot file
    """
    if run_date is None:
        run_date = datetime.now(ET).date()
        
    snap_dir = snapshot_dir()
    snap_dir.mkdir(parents=True, exist_ok=True)
    
    snapshot = {
        "track_id": TRACK_ID,
        "date": run_date.isoformat(),
        "nav": nav,
        "cash_plus_stocks": cash_plus_stocks,
        "start_date": START_DATE.isoformat(),
        "start_nav": START_NAV_USD,
        "growth_nav": growth_nav,
        "ballast_nav": ballast_nav,
        "dividend_cash": dividend_cash,
        "positions": positions,
        "config_fingerprint": config_fingerprint(run_config),
        "timestamp": datetime.now(ET).isoformat(),
    }
    
    snap_file = snap_dir / f"snapshot_{run_date.isoformat()}.json"
    with open(snap_file, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
        
    return snap_file


def get_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Load the most recent snapshot."""
    snap_dir = snapshot_dir()
    if not snap_dir.exists():
        return None
        
    snapshots = sorted(snap_dir.glob("snapshot_*.json"))
    if not snapshots:
        return None
        
    with open(snapshots[-1]) as f:
        return json.load(f)


def calculate_returns(
    snapshots: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Calculate return metrics from snapshots.
    
    Args:
        snapshots: List of snapshot dictionaries
        
    Returns:
        Dictionary with return metrics
    """
    if not snapshots:
        return {}
        
    sorted_snaps = sorted(snapshots, key=lambda s: s["date"])
    
    start_nav = START_NAV_USD
    current_nav = sorted_snaps[-1]["nav"]
    
    total_return = (current_nav - start_nav) / start_nav
    
    # Calculate daily returns
    daily_returns = []
    for i in range(1, len(sorted_snaps)):
        prev_nav = sorted_snaps[i-1]["nav"]
        curr_nav = sorted_snaps[i]["nav"]
        if prev_nav > 0:
            daily_returns.append((curr_nav - prev_nav) / prev_nav)
    
    # Calculate metrics
    if daily_returns:
        avg_daily = sum(daily_returns) / len(daily_returns)
        std_daily = math.sqrt(
            sum((r - avg_daily) ** 2 for r in daily_returns) / len(daily_returns)
        ) if len(daily_returns) > 1 else 0.0
        
        sharpe = (
            (avg_daily * PERIODS_PER_YEAR) / (std_daily * math.sqrt(PERIODS_PER_YEAR))
            if std_daily > 0 else 0.0
        )
    else:
        sharpe = 0.0
    
    return {
        "start_date": START_DATE.isoformat(),
        "latest_date": sorted_snaps[-1]["date"],
        "start_nav": start_nav,
        "current_nav": current_nav,
        "total_return_pct": total_return * 100,
        "sharpe_ratio": sharpe,
        "num_snapshots": len(sorted_snaps),
    }


def is_quarterly_rebalance_due(last_rebalance: Optional[date] = None) -> bool:
    """
    Check if quarterly rebalance is due.
    
    Args:
        last_rebalance: Date of last rebalance
        
    Returns:
        True if rebalance is due
    """
    today = datetime.now(ET).date()
    
    # If no last rebalance, check if we're in a quarter-end month
    if last_rebalance is None:
        return today.month in [3, 6, 9, 12] and today.day >= 15
    
    # Check if 3 months have passed
    months_since = (today.year - last_rebalance.year) * 12 + (today.month - last_rebalance.month)
    return months_since >= 3


def record_last_rebalance(rebalance_date: Optional[date] = None):
    """Record the date of last rebalance."""
    if rebalance_date is None:
        rebalance_date = datetime.now(ET).date()
        
    snap_dir = snapshot_dir()
    snap_dir.mkdir(parents=True, exist_ok=True)
    
    rebalance_file = snap_dir / "last_rebalance.txt"
    with open(rebalance_file, "w") as f:
        f.write(rebalance_date.isoformat())


def get_last_rebalance_date() -> Optional[date]:
    """Get the date of the last rebalance."""
    snap_dir = snapshot_dir()
    rebalance_file = snap_dir / "last_rebalance.txt"
    
    if not rebalance_file.exists():
        return None
        
    try:
        with open(rebalance_file) as f:
            date_str = f.read().strip()
            return date.fromisoformat(date_str)
    except Exception:
        return None
