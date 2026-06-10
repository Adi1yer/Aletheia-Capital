#!/usr/bin/env python3
"""Historical biotech catalyst backtest (underlying-move proxy for straddle PnL)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from src.biotech.policy_learning import compute_biotech_policy
from src.biotech.thesis_ledger import format_scorecard_markdown, scorecard


def main() -> int:
    result = compute_biotech_policy(weeks=52)
    sc = scorecard(weeks=52)
    out = {
        "policy_proposal": result.get("policy"),
        "adjustments": result.get("adjustments"),
        "scorecard": sc,
        "note": "Backtest uses resolved thesis_ledger rows; full IV replay deferred.",
    }
    Path("data/biotech").mkdir(parents=True, exist_ok=True)
    out_path = Path("data/biotech/backtest_latest.json")
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(format_scorecard_markdown(sc))
    print(f"\nSaved {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
