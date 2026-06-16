import json
from pathlib import Path

from src.trading.replay import decision_hash


def test_golden_run_decision_hash_stable():
    p = Path("tests/fixtures/golden_run.json")
    payload = json.loads(p.read_text(encoding="utf-8"))
    got = decision_hash({"decisions": payload["decisions"]})
    assert got == payload["expected_hash"]

