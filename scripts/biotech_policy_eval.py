#!/usr/bin/env python3
"""Evaluate biotech policy learning from thesis ledger (CI / manual)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.biotech.policy_learning import compute_biotech_policy, load_biotech_policy
from src.biotech.promotion_gates import evaluate_biotech_proposal
from src.biotech.thesis_ledger import format_scorecard_markdown, scorecard


def main() -> int:
    result = compute_biotech_policy(weeks=24)
    proposed = result.get("policy") or {}
    promotion = evaluate_biotech_proposal(proposed)
    out = {
        "policy": proposed,
        "adjustments": result.get("adjustments"),
        "promotion": promotion,
        "scorecard": scorecard(weeks=12),
    }
    Path("data/biotech").mkdir(parents=True, exist_ok=True)
    Path("data/biotech/biotech_policy_eval_latest.json").write_text(
        json.dumps(out, indent=2, default=str)
    )
    print(format_scorecard_markdown(out["scorecard"]))
    print()
    print("Promotion:", promotion.get("promote"), promotion.get("reason"))
    print("Saved data/biotech/biotech_policy_eval_latest.json")
    print("Current policy file:", load_biotech_policy())
    return 0


if __name__ == "__main__":
    sys.exit(main())
