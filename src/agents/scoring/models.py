"""Rule score output from deterministic agent lanes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal


@dataclass
class RuleScore:
    suggested_signal: Literal["bullish", "bearish", "neutral"]
    rule_confidence: int
    facts: Dict[str, Any] = field(default_factory=dict)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    lane: str = ""
    skip_llm: bool = False

    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.get("pass"))
