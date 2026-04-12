"""LLM utility functions"""

from typing import TypeVar, Type
from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
import json
import structlog

logger = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


def _is_deepseek_llm(llm: BaseChatModel) -> bool:
    """Detect whether this LLM is talking to DeepSeek's OpenAI-compatible API."""
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


def _parse_structured_text(text: str, output_model: Type[T]) -> T:
    """
    Parse JSON-like text into the desired Pydantic model.
    Handles common cases like code fences and extra commentary.
    """
    # Strip common markdown code fences
    text = text.strip()
    if not text:
        raise ValueError("Empty response from LLM")

    if text.startswith("```"):
        # Remove leading fence
        parts = text.split("```", 2)
        text = parts[-1].strip() if len(parts) == 3 else parts[-1].strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    # Heuristic: grab from first "{" to last "}" to isolate JSON object
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        candidate = text[start:end]
    else:
        candidate = text

    # Always use dict path so we can normalize keys (DeepSeek sometimes returns "\"signal\"" etc.).
    # Avoid model_validate_json(candidate) so we never build a model from unnormalized keys.
    data = json.loads(candidate)
    if isinstance(data, dict):
        data = _normalize_json_keys(data)
        # Normalize common synonyms for the \"signal\" field so validation doesn't fail
        # when the LLM says \"buy\"/\"sell\"/\"overvalued\" instead of bullish/bearish/neutral.
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
    llm: BaseChatModel,
    prompt: BaseMessage | list[BaseMessage],
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
    try:
        use_deepseek_path = _is_deepseek_llm(llm)
    except Exception:
        use_deepseek_path = False

    for attempt in range(max_retries):
        try:
            if isinstance(prompt, list):
                messages = prompt
            else:
                messages = [prompt]

            if use_deepseek_path:
                try:
                    raw = llm.invoke(messages)
                    text = getattr(raw, "content", "") or str(raw)
                    if not isinstance(text, str):
                        text = str(text)

                    parsed = _parse_structured_text(text, output_model)
                    fields = getattr(output_model, "model_fields", {}) or {}
                    data = {}
                    for name in fields:
                        data[name] = getattr(parsed, name)
                    return output_model.model_validate(data)
                except Exception as parse_err:
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

