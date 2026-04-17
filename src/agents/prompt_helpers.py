"""Shared helpers for building agent prompts (insider, analyst, index context)."""

from typing import List, Dict, Any, Optional

from src.data.models import InsiderTrade

# Instruction so DeepSeek (and other LLMs) return parseable JSON without markdown or extra text.
JSON_ONLY_INSTRUCTION = (
    "Respond with ONLY a single valid JSON object. "
    "Do not use markdown, code fences (no ```), or any text before or after the JSON. "
    "Your entire response must be parseable as JSON. "
    "For any field named `signal`, you MUST use exactly one of these lowercase strings: "
    "\"bullish\", \"bearish\", or \"neutral\" (do not use words like buy, sell, overvalued, etc.)."
)
AGENT_JSON_EXAMPLE = '{{"signal":"neutral","confidence":50,"reasoning":"Brief reason"}}'
PM_JSON_EXAMPLE = '{{"action":"hold","quantity":0,"confidence":0,"reasoning":"Brief reason"}}'


def format_insider_for_prompt(
    trades: List[InsiderTrade],
    max_entries: int = 15,
) -> str:
    """Format insider trades for inclusion in agent prompts."""
    if not trades:
        return "No recent insider transaction data available."
    lines = []
    for t in trades[:max_entries]:
        parts = [t.transaction_type or "?", str(t.shares) + " shares" if t.shares is not None else "?", t.filing_date.strftime("%Y-%m-%d")]
        if t.price is not None:
            parts.append(f"@ ${t.price:.2f}")
        if t.value is not None:
            parts.append(f"(${t.value:,.0f})")
        lines.append("  " + " ".join(str(p) for p in parts))
    return "Recent insider activity:\n" + "\n".join(lines) if lines else "No recent insider transaction data available."


def format_analyst_for_prompt(recommendations: List[Dict[str, Any]], max_periods: int = 4) -> str:
    """Format analyst recommendation trends for prompts."""
    if not recommendations:
        return "No analyst recommendation data available."
    lines = []
    for r in recommendations[:max_periods]:
        period = r.get("period", "N/A")
        sb, b, h, s, ss = r.get("strongBuy"), r.get("buy"), r.get("hold"), r.get("sell"), r.get("strongSell")
        parts = [f"Period {period}:"]
        if sb is not None:
            parts.append(f"StrongBuy={sb}")
        if b is not None:
            parts.append(f"Buy={b}")
        if h is not None:
            parts.append(f"Hold={h}")
        if s is not None:
            parts.append(f"Sell={s}")
        if ss is not None:
            parts.append(f"StrongSell={ss}")
        lines.append("  " + " ".join(parts))
    return "Analyst recommendation trends:\n" + "\n".join(lines) if lines else "No analyst recommendation data available."


def compute_return_vs_index(
    ticker_prices: List[Any],
    index_prices: List[Any],
) -> Optional[float]:
    """
    Return (ticker return % - index return %) over the period.
    Both lists must have at least 2 elements with .close attribute.
    """
    if not ticker_prices or not index_prices or len(ticker_prices) < 2 or len(index_prices) < 2:
        return None
    ticker_ret = (ticker_prices[-1].close - ticker_prices[0].close) / ticker_prices[0].close * 100
    index_ret = (index_prices[-1].close - index_prices[0].close) / index_prices[0].close * 100
    return round(ticker_ret - index_ret, 2)


def with_performance_feedback(system_text: str, agent) -> str:
    """Append cached scorecard blurb for this agent (registry key = name lower + underscores)."""
    try:
        from src.backtesting.feedback import block_for_agent

        key = agent.name.lower().replace(" ", "_")
        block = block_for_agent(key)
        if block:
            return system_text + "\n\n## Historical signal calibration (weak prior):\n" + block
    except Exception:
        pass
    return system_text
