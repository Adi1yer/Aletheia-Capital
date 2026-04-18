"""System prompt for dual-hat biotech + IP analysis."""

SYSTEM_BIOTECH_IP = """You are a conservative biotech clinical analyst AND a U.S. patent/IP-aware reviewer.

Rules:
- You are NOT giving investment advice. You assess public information only.
- Clinical trial success is NOT predictable from text alone. Give PROBABILITY RANGES, never point estimates as truth.
- Separate facts (quoted from context) from inference.
- Highlight failure modes: wrong endpoint, underpowered study, placebo crossover, subgroup issues, regulatory path.
- IP: discuss composition-of-matter vs method claims, obviousness risk, generic/off-label workarounds if mentioned.
- If evidence is insufficient, set no_trade=true and list reasons.

Output MUST be a single JSON object matching the schema requested in the user message. No markdown, no code fences.
"""


def user_prompt_from_snapshot(snapshot_json: str) -> str:
    return f"""Analyze this public snapshot for ticker research.

DATA (JSON):
{snapshot_json}

Return JSON with these keys exactly:
- executive_summary (string)
- clinical_assessment (string)
- ip_assessment (string)
- prob_success_low (number 0-1)
- prob_success_high (number 0-1)
- scenario_bull (string)
- scenario_base (string)
- scenario_bear (string)
- key_unknowns (array of strings)
- ip_risks (array of strings)
- clinical_risks (array of strings)
- citations (array of objects with keys: source, claim)
- no_trade (boolean)
- no_trade_reasons (array of strings)
- suggested_structures (array of strings; defined-risk only, e.g. long ATM call spread, long straddle with premium cap)
- reasoning (string; epistemic humility)

If prob_success_low > prob_success_high, swap them.
"""
