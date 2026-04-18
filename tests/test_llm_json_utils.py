"""Tests for LLM JSON extraction helpers (used by DeepSeek path)."""

from pydantic import BaseModel

from src.llm.utils import (
    _extract_balanced_json,
    _parse_structured_text,
    _strip_trailing_commas_json,
)


class _Tiny(BaseModel):
    signal: str = ""
    confidence: int = 0


def test_strip_trailing_commas():
    s = '{"a": 1, "b": 2,}'
    fixed = _strip_trailing_commas_json(s)
    assert fixed == '{"a": 1, "b": 2}'


def test_extract_balanced_nested():
    text = 'prefix {"outer": {"inner": 1}} tail'
    got = _extract_balanced_json(text)
    assert got == '{"outer": {"inner": 1}}'


def test_parse_structured_text_with_noise():
    raw = """Here is JSON:
```json
{"signal": "bullish", "confidence": 50, "reasoning": "ok"}
```
"""
    out = _parse_structured_text(raw, _Tiny)
    assert out.signal == "bullish"
    assert out.confidence == 50
