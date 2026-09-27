"""Send weekly digest for growth-income-drip track."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import structlog
from src.performance.drip_track import (
    snapshot_dir,
    calculate_returns,
    TRACK_ID,
    START_DATE,
    START_NAV_USD,
)
from src.utils.email import get_email_notifier

logger = structlog.get_logger()


def load_recent_snapshots(days: int = 7) -> List[Dict]:
    """Load snapshots from the last N days."""
    snap_dir = snapshot_dir()
    if not snap_dir.exists():
        return []
    
    cutoff = datetime.now() - timedelta(days=days)
    snapshots = []
    
    for snap_file in sorted(snap_dir.glob("snapshot_*.json")):
        try:
            with open(snap_file) as f:
                snap = json.load(f)
                snap_date = datetime.fromisoformat(snap["date"])
                if snap_date >= cutoff:
                    snapshots.append(snap)
        except Exception as e:
            logger.warning("Failed to load snapshot", file=snap_file, error=str(e))
    
    return sorted(snapshots, key=lambda s: s["date"])


def format_digest(snapshots: List[Dict]) -> str:
    """Format weekly digest email body."""
    if not snapshots:
        return f"""
Growth-Income-Drip Weekly Digest

Track: {TRACK_ID}
Status: No snapshots available yet

This is the inaugural week. Daily snapshots will appear once the workflow runs.
"""
    
    latest = snapshots[-1]
    nav = latest["nav"]
    start_nav = START_NAV_USD
    
    # Calculate returns
    returns = calculate_returns(snapshots)
    total_return_pct = returns.get("total_return_pct", 0)
    sharpe = returns.get("sharpe_ratio", 0)
    
    # Week-over-week change
    if len(snapshots) >= 2:
        week_ago = snapshots[0]["nav"]
        wow_change = ((nav - week_ago) / week_ago) * 100 if week_ago > 0 else 0
    else:
        wow_change = 0
    
    # Position count
    positions = latest.get("positions", {})
    num_positions = len(positions)
    
    # Growth vs ballast
    growth_nav = latest.get("growth_nav", 0) or 0
    ballast_nav = latest.get("ballast_nav", 0) or 0
    dividend_cash = latest.get("dividend_cash", 0) or 0
    
    body = f"""
Growth-Income-Drip Weekly Digest

═══════════════════════════════════════
TRACK PERFORMANCE
═══════════════════════════════════════

Track: {TRACK_ID}
Started: {START_DATE}
Initial NAV: ${START_NAV_USD:,.2f}

Current NAV: ${nav:,.2f}
Total Return: {total_return_pct:+.2f}%
Week/Week: {wow_change:+.2f}%
Sharpe Ratio: {sharpe:.2f}

═══════════════════════════════════════
PORTFOLIO COMPOSITION
═══════════════════════════════════════

Total Positions: {num_positions}

Growth Sleeve: ${growth_nav:,.2f} (target 80%)
Ballast Sleeve: ${ballast_nav:,.2f} (target 20%)
Dividend Cash: ${dividend_cash:,.2f}

═══════════════════════════════════════
STRATEGY NOTES
═══════════════════════════════════════

• 80% growth (Arm C 12-1 momentum, ~30 names)
• 20% dividend ballast (~15 names)
• Quarterly delta rebalance only
• Dividends drip into growth at rebalance
• NO covered calls, NO vol-targeting

═══════════════════════════════════════
DATA SUMMARY
═══════════════════════════════════════

Snapshots This Week: {len(snapshots)}
Latest Snapshot: {latest["date"]}

Track honest framing:
Equity momentum drives beat-SPY alpha;
income is ballast/drip for stability.

"""
    
    return body


def main():
    logger.info("Generating drip weekly digest")
    
    # Load recent snapshots
    snapshots = load_recent_snapshots(days=7)
    
    logger.info("Loaded snapshots", count=len(snapshots))
    
    # Format email
    body = format_digest(snapshots)
    
    # Send email
    try:
        notifier = get_email_notifier()
        if notifier:
            subject = f"[{TRACK_ID}] Weekly Digest"
            notifier.send_email(subject, body)
            logger.info("Weekly digest sent")
        else:
            logger.warning("Email notifier not configured")
            print(body)
    except Exception as e:
        logger.error("Failed to send digest", error=str(e))
        print(body)


if __name__ == "__main__":
    main()
