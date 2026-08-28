"""Normalize LangChain provider usage metadata into safe benchmark trace events."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.observability import trace_llm_usage


class BenchmarkUsageCallback(BaseCallbackHandler):
    """Emit one provider-reported usage event for each completed LLM request."""

    def __init__(self, provider: str, model: str) -> None:
        super().__init__()
        self._provider = provider
        self._model = model

    def on_llm_end(self, response: LLMResult, **_kwargs: Any) -> None:
        """Extract metadata before structured-output runnables discard the raw message."""
        trace_llm_usage(_payload(response, self._provider, self._model))


def _payload(response: LLMResult, provider: str, configured_model: str) -> dict[str, Any]:
    message = _message(response)
    metadata = getattr(message, "usage_metadata", None) if message is not None else None
    fallback = _mapping(getattr(response, "llm_output", None)).get("token_usage", {})
    usage = _mapping(metadata) or _mapping(fallback)
    model = _model_name(message, configured_model)
    input_tokens = _token(usage, "input_tokens", "prompt_tokens")
    output_tokens = _token(usage, "output_tokens", "completion_tokens")
    cached = _cached_tokens(usage)
    reasoning = _reasoning_tokens(usage)
    available = input_tokens is not None or output_tokens is not None
    return {
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "reasoning_tokens": reasoning,
        "usage_source": "provider_reported" if available else "unavailable",
        "token_precision": "exact" if available else "unavailable",
    }


def _message(response: LLMResult) -> Any:
    """Read the first generated message without assuming a specific provider class."""
    try:
        return response.generations[0][0].message
    except (AttributeError, IndexError):
        return None


def _model_name(message: Any, configured_model: str) -> str:
    """Prefer the provider's reported model while retaining configured fallback."""
    metadata = _mapping(getattr(message, "response_metadata", None))
    return str(metadata.get("model_name") or metadata.get("model") or configured_model)


def _token(usage: dict[str, Any], primary: str, fallback: str) -> int | None:
    """Read a non-negative token count from either normalized or provider-native keys."""
    return _integer(usage.get(primary) if primary in usage else usage.get(fallback))


def _cached_tokens(usage: dict[str, Any]) -> int | None:
    """Read cached input tokens from common LangChain and OpenAI detail fields."""
    details = _mapping(usage.get("input_token_details")) or _mapping(usage.get("prompt_tokens_details"))
    return _integer(details.get("cache_read") if "cache_read" in details else details.get("cached_tokens"))


def _reasoning_tokens(usage: dict[str, Any]) -> int | None:
    """Read optional provider-reported reasoning tokens without inferring them."""
    details = _mapping(usage.get("output_token_details")) or _mapping(usage.get("completion_tokens_details"))
    return _integer(details.get("reasoning") if "reasoning" in details else details.get("reasoning_tokens"))


def _mapping(value: Any) -> dict[str, Any]:
    """Return a plain mapping for tolerant metadata parsing."""
    return dict(value) if isinstance(value, dict) else {}


def _integer(value: Any) -> int | None:
    """Return only non-negative integer metadata values."""
    return int(value) if isinstance(value, int) and value >= 0 else None
