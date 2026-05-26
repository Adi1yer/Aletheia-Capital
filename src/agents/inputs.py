"""Typed agent inputs resolved from shared ticker dossier."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentInputs:
    ticker: str
    start_date: str
    end_date: str
    dossier: Dict[str, Any]
    extras: Dict[str, Any] = field(default_factory=dict)

    @property
    def metrics(self) -> List[Dict[str, Any]]:
        return self.dossier.get("metrics") or []

    @property
    def latest_metrics(self) -> Dict[str, Any]:
        return self.metrics[0] if self.metrics else {}

    @property
    def line_items(self) -> List[Dict[str, Any]]:
        return self.dossier.get("line_items") or []

    @property
    def trends(self) -> Dict[str, Any]:
        return self.dossier.get("trends") or {}

    @property
    def prices(self) -> Dict[str, Any]:
        return self.dossier.get("prices") or {}

    @property
    def technicals(self) -> Dict[str, Any]:
        return self.dossier.get("technicals") or {}

    @property
    def context(self) -> Dict[str, Any]:
        return self.dossier.get("context") or {}

    @property
    def benchmarks(self) -> Dict[str, Any]:
        return self.dossier.get("benchmarks") or {}

    @property
    def insider_summary(self) -> str:
        return self.dossier.get("insider_summary") or ""

    @property
    def news_titles(self) -> List[str]:
        return self.dossier.get("news_titles") or []


def resolve_agent_inputs(
    ticker: str,
    start_date: str,
    end_date: str,
    dossier: Optional[Dict[str, Any]],
    data_provider,
    extras: Optional[Dict[str, Any]] = None,
    financial_limit: int = 5,
) -> AgentInputs:
    """Use dossier when present; otherwise build minimal dossier for this ticker."""
    if dossier and dossier.get("version") == 2:
        d = dossier
    else:
        from src.data.ticker_dossier import build_ticker_dossier

        d = build_ticker_dossier(
            data_provider, ticker, start_date, end_date, financial_limit=financial_limit
        )
    return AgentInputs(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        dossier=d,
        extras=extras or {},
    )
