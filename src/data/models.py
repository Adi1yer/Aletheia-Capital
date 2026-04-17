"""Data models for market data, financials, and news"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Price(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class FinancialMetrics(BaseModel):
    ticker: str
    report_period: datetime
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    price_to_book_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    roe: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    free_cash_flow_growth: Optional[float] = None
    interest_coverage: Optional[float] = None
    book_value_growth: Optional[float] = None


class LineItem(BaseModel):
    """Financial statement line item"""
    ticker: str
    report_period: datetime
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    free_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None
    depreciation_and_amortization: Optional[float] = None
    working_capital: Optional[float] = None
    total_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    interest_expense: Optional[float] = None
    operating_income: Optional[float] = None
    ebit: Optional[float] = None
    ebitda: Optional[float] = None
    outstanding_shares: Optional[int] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    shareholders_equity: Optional[float] = None
    dividends_and_other_cash_distributions: Optional[float] = None
    issuance_or_purchase_of_equity_shares: Optional[float] = None
    gross_profit: Optional[float] = None


class InsiderTrade(BaseModel):
    ticker: str
    filing_date: datetime
    transaction_date: Optional[datetime] = None
    transaction_type: Optional[str] = None
    shares: Optional[int] = None
    price: Optional[float] = None
    value: Optional[float] = None


class CompanyNews(BaseModel):
    ticker: str
    date: datetime
    title: str
    url: Optional[str] = None
    summary: Optional[str] = None
