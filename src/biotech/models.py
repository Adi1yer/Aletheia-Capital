"""Pydantic models for biotech catalyst pipeline."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TrialSummary(BaseModel):
    nct_id: str = ""
    title: str = ""
    status: str = ""
    phase: str = ""
    conditions: List[str] = Field(default_factory=list)
    sponsor: str = ""
    raw: Dict[str, Any] = Field(default_factory=dict)


class FilingRef(BaseModel):
    form: str = ""
    filed_at: str = ""
    url: str = ""


class BiotechSnapshot(BaseModel):
    ticker: str
    as_of: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    trials: List[TrialSummary] = Field(default_factory=list)
    filings: List[FilingRef] = Field(default_factory=list)
    news_titles: List[str] = Field(default_factory=list)
    last_price: Optional[float] = None
    raw_notes: str = ""


class BiotechAnalysisOutput(BaseModel):
    """Structured LLM output — probabilities are ranges, not oracle truth."""

    executive_summary: str = ""
    clinical_assessment: str = ""
    ip_assessment: str = ""
    prob_success_low: float = Field(0.0, ge=0.0, le=1.0)
    prob_success_high: float = Field(1.0, ge=0.0, le=1.0)
    scenario_bull: str = ""
    scenario_base: str = ""
    scenario_bear: str = ""
    key_unknowns: List[str] = Field(default_factory=list)
    ip_risks: List[str] = Field(default_factory=list)
    clinical_risks: List[str] = Field(default_factory=list)
    citations: List[Dict[str, str]] = Field(default_factory=list)
    no_trade: bool = True
    no_trade_reasons: List[str] = Field(default_factory=list)
    suggested_structures: List[str] = Field(
        default_factory=list,
        description="e.g. long ATM straddle, call spread — defined risk only",
    )
    reasoning: str = ""


class BiotechRunRecord(BaseModel):
    snapshot: BiotechSnapshot
    analysis: BiotechAnalysisOutput
    gates_passed: bool = False
    execution: Optional[Dict[str, Any]] = None
