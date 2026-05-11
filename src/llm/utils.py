"""LLM utility functions"""

from __future__ import annotations

import json
import re
from typing import Optional, Type, TypeVar

from pydantic import BaseModel
import structlog

logger = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


def _is_deepseek_llm(llm: object) -> bool:
    """Detect whether this LLM is talking to DeepSeek's OpenAI-compatible API."""
    from langchain_openai import ChatOpenAI

    try:
        if isinstance(llm, ChatOpenAI):
            base_url = getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "")
            return isinstance(base_url, str) and "deepseek.com" in base_url
    except Exception:
        return False
    return False


def _normalize_json_keys(data: dict) -> dict:
    """
    Normalize keys so that quoted/escaped key names (e.g. '"signal"', '\\"action\\"') map to canonical names.
    DeepSeek sometimes returns JSON with escaped key names; this avoids KeyError in Pydantic.
    """
    canonical = {"signal", "confidence", "reasoning", "action", "quantity"}
    out = {}
    for k, v in data.items():
        # Strip optional surrounding quotes, backslash-escaped quotes, and any non-alphanumeric
        raw = k.strip().replace('\\"', "").replace("\\", "").strip()
        for char in '"\'\u201c\u201d\u2018\u2019':
            raw = raw.strip(char)
        key = raw.strip()
        # Match canonical by exact match or by "core" name (e.g. signal from "signal", "\"signal\"")
        if key in canonical:
            out[key] = v
        else:
            core = "".join(c for c in key if c.isalnum() or c == "_")
            out[core if core in canonical else k] = v
    return out


def _strip_trailing_commas_json(s: str) -> str:
    """Remove JSON-style trailing commas before } or ] (common LLM mistake)."""
    prev = None
    out = s
    while prev != out:
        prev = out
        out = re.sub(r",(\s*[\]}])", r"\1", out)
    return out


def _unwrap_code_fences(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    parts = t.split("```", 2)
    inner = parts[1] if len(parts) >= 2 else parts[-1]
    inner = inner.strip()
    first_nl = inner.find("\n")
    if first_nl != -1 and inner[:first_nl].strip().lower() in ("json",):
        inner = inner[first_nl + 1 :]
    return inner.strip()


def _extract_balanced_json(text: str) -> Optional[str]:
    """Extract first top-level `{...}` with brace matching (respects strings)."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    i = start
    in_string = False
    escape = False
    while i < len(text):
        c = text[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    return None


def _parse_structured_text(text: str, output_model: Type[T]) -> T:
    """
    Parse JSON-like text into the desired Pydantic model.
    Handles code fences, balanced braces, trailing commas, and stray prose.
    """
    text = _unwrap_code_fences(text)
    if not text.strip():
        raise ValueError("Empty response from LLM")

    candidates: list[str] = []
    bal = _extract_balanced_json(text)
    if bal:
        candidates.append(bal)
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if end > start:
            candidates.append(text[start:end])

    last_err: Optional[Exception] = None
    data = None
    for raw_c in candidates:
        for cand in (raw_c, _strip_trailing_commas_json(raw_c)):
            try:
                data = json.loads(cand)
                last_err = None
                break
            except json.JSONDecodeError as e:
                last_err = e
                continue
        if data is not None:
            break
    if data is None:
        raise last_err or ValueError("Could not parse JSON from LLM response")
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object at the root")

    # Normalize keys (DeepSeek sometimes returns odd key spellings for agent JSON).
    data = _normalize_json_keys(data)
    raw_signal = data.get("signal")
    if raw_signal is not None:
        val = str(raw_signal).strip().lower()
        synonym_map = {
            "buy": "bullish",
            "strong buy": "bullish",
            "accumulate": "bullish",
            "overweight": "bullish",
            "sell": "bearish",
            "strong sell": "bearish",
            "underweight": "bearish",
            "short": "bearish",
            "overvalued": "bearish",
            "undervalued": "bullish",
            "hold": "neutral",
            "wait": "neutral",
        }
        if val in synonym_map:
            data["signal"] = synonym_map[val]
    return output_model.model_validate(data)


def _make_fallback_output(output_model: Type[T], error: str) -> T:
    """
    Create a safe neutral/hold fallback instance without raising,
    so agents and the PM keep working even if parsing fails.
    """
    fields = getattr(output_model, "model_fields", {}) or {}
    field_names = set(fields.keys())

    data: dict = {}

    if "action" in field_names:
        # PortfolioDecision-style
        data = {
            "action": "hold",
            "quantity": 0,
            "confidence": 0,
            "reasoning": f"Fallback decision due to LLM parse error: {error}",
        }
    elif "signal" in field_names:
        # Agent signal-style
        data = {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": f"Fallback signal due to LLM parse error: {error}",
        }

    try:
        return output_model.model_validate(data) if data else output_model()
    except Exception:
        # Last-resort: construct with minimal kwargs
        return output_model()  # type: ignore[call-arg]


def call_llm_with_retry(
    llm: object,
    prompt: object,
    output_model: Type[T],
    max_retries: int = 3,
) -> T:
    """
    Call LLM with structured output and retry logic.

    - For DeepSeek (OpenAI-compatible API that currently rejects `response_format`),
      we manually parse JSON from the text response.
    - For other providers (Ollama, Groq, etc.), we use LangChain's
      `with_structured_output` helper.
    """
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

    try:
        use_deepseek_path = _is_deepseek_llm(llm)
    except Exception:
        use_deepseek_path = False

    if isinstance(prompt, list):
        base_messages: list[BaseMessage] = list(prompt)
    else:
        base_messages = [prompt]

    for attempt in range(max_retries):
        try:
            messages = list(base_messages)

            if use_deepseek_path:
                raw = llm.invoke(messages)
                text = getattr(raw, "content", "") or str(raw)
                if not isinstance(text, str):
                    text = str(text)

                try:
                    parsed = _parse_structured_text(text, output_model)
                    fields = getattr(output_model, "model_fields", {}) or {}
                    data = {name: getattr(parsed, name) for name in fields}
                    return output_model.model_validate(data)
                except Exception as parse_err:
                    if attempt < max_retries - 1:
                        logger.warning(
                            "DeepSeek JSON parse failed; retrying with repair instruction",
                            attempt=attempt + 1,
                            error=str(parse_err),
                        )
                        base_messages = base_messages + [
                            AIMessage(content=text),
                            HumanMessage(
                                content=(
                                    "Your previous reply was not valid JSON or did not match the required schema. "
                                    "Respond with ONLY one JSON object with the same fields as specified. "
                                    "No markdown, no code fences (no ```), no text before or after the JSON."
                                )
                            ),
                        ]
                        continue
                    logger.info(
                        "DeepSeek structured parse failed; using fallback output",
                        error=str(parse_err),
                    )
                    return _make_fallback_output(output_model, str(parse_err))
            else:
                try:
                    llm_with_structure = llm.with_structured_output(output_model)
                    response = llm_with_structure.invoke(messages)
                    fields = getattr(output_model, "model_fields", {}) or {}
                    data = {name: getattr(response, name) for name in fields}
                    return output_model.model_validate(data)
                except Exception as non_ds_err:
                    logger.info(
                        "Structured output failed; using fallback output",
                        error=str(non_ds_err),
                    )
                    return _make_fallback_output(output_model, str(non_ds_err))
        except Exception as e:
            if attempt == max_retries - 1:
                logger.info(
                    "LLM call failed after retries; using fallback output",
                    error=str(e),
                    attempts=max_retries,
                )
                return _make_fallback_output(output_model, str(e))
            logger.warning("LLM call failed, retrying", attempt=attempt + 1, error=str(e))

    return _make_fallback_output(output_model, "LLM call failed")

