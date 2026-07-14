"""Top factor-ranked candidate slice for agent triage."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from src.alpha.factors import rank_universe


def build_candidate_set(
    tickers: List[str],
    dossiers: Dict[str, Dict[str, Any]],
    *,
    top_n: int = 100,
    held: Optional[Set[str]] = None,
) -> Tuple[List[str], List[Tuple[str, float, Dict[str, float]]]]:
    held = held or set()
    ranked = rank_universe(tickers, dossiers)
    top = [t for t, _, _ in ranked[: max(1, int(top_n))]]
    deep: Set[str] = set(top) | {t for t in held if t in tickers}
    return sorted(deep), ranked
