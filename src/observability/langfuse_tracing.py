"""Export only agent observations with bounded, server-owned summaries."""

import logging
import math
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from src.config import get_settings

logger = logging.getLogger(__name__)


_ENUMS = {
    "intent": {"chitchat", "data_question", "metric_query", "semantic_query", "out_of_scope"},
    "parse_status": {"resolved", "needs_clarification", "error"},
    "run_status": {"completed", "partial", "needs_clarification", "error"},
    "status": {
        "started",
        "finished",
        "failed",
        "pass",
        "needs_revision",
        "needs_clarification",
        "rejected",
        "unsupported",
        "error",
    },
    "mode": {"requested", "discovery"},
    "db_type": {"postgresql", "mysql", "sqlite"},
    "error_code": {
        "node_error",
        "INVALID_AGENT_OUTPUT",
        "RATE_LIMITED",
        "QUOTA_EXHAUSTED",
        "PROVIDER_ERROR",
        "LLM_BUSY",
    },
}
_NUMBERS = {
    "proposal_count",
    "candidate_count",
    "reviewed_count",
    "pass_count",
    "needs_revision_count",
    "needs_clarification_count",
    "rejected_count",
    "unsupported_count",
    "error_count",
    "repair_count",
    "table_count",
    "family_count",
    "catalog_metrics",
    "sql_length",
    "attempt",
    "duration_ms",
    "reason_unresolved_assumption_count",
    "reason_missing_grain_count",
    "reason_variant_conflict_count",
    "reason_missing_ratio_count",
    "reason_technical_validation_count",
    "reason_reviewer_finding_count",
    "reason_builder_clarification_count",
    "reason_builder_unsupported_count",
    "reason_builder_rejected_count",
    "reason_invalid_agent_output_count",
    "reason_provider_failure_count",
    "reason_other_count",
}


def _mask_content(*, data: Any, **_kwargs: Any) -> Any:
    """Allow only finite, bounded summary values through the SDK mask."""
    if not isinstance(data, dict) or set(data) != {"trace_summary"}:
        return "[REDACTED]"
    summary = data["trace_summary"]
    if not isinstance(summary, dict):
        return "[REDACTED]"
    safe = {
        key: value
        for key, value in summary.items()
        if (key in _ENUMS and isinstance(value, str) and value in _ENUMS[key])
        or (key in _NUMBERS and type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1_000_000_000)
    }
    return {"trace_summary": safe} if safe else "[REDACTED]"


def _is_agent_span(span: Any) -> bool:
    """Keep standalone LLM calls and HTTP instrumentation out of Langfuse."""
    return span.attributes.get("langfuse.trace.metadata.agent_trace") == "1" and span.attributes.get(
        "langfuse.observation.type"
    ) in {"agent", "span", "generation", "chain", "tool", "retriever", "guardrail"}


def trace_summary(**values: Any) -> dict[str, Any] | None:
    """Validate a summary before passing it to any Langfuse observation."""
    result = _mask_content(data={"trace_summary": values})
    return result if isinstance(result, dict) else None


@lru_cache(maxsize=1)
def get_tracing_client() -> Any:
    """Initialize once per process; configuration changes require a restart."""
    settings = get_settings()
    if not settings.langfuse_tracing_enabled:
        return None
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse tracing disabled: public/secret key is missing")
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.app_env,
            mask=_mask_content,
            should_export_span=_is_agent_span,
        )
    except Exception:
        logger.warning("Langfuse initialization failed; tracing disabled")
        return None


def llm_trace_callbacks() -> list[BaseCallbackHandler]:
    """Attach the official integration to every provider used by get_llm()."""
    if get_tracing_client() is None:
        return []
    from langfuse.langchain import CallbackHandler

    class SafeCallbackHandler(CallbackHandler):
        def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
            # Provider error text can contain URLs, credentials or prompt content.
            super().on_llm_error(RuntimeError(type(error).__name__), **kwargs)

        def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
            super().on_chain_error(RuntimeError(type(error).__name__), **kwargs)

        def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
            super().on_tool_error(RuntimeError(type(error).__name__), **kwargs)

        def on_retriever_error(self, error: BaseException, **kwargs: Any) -> None:
            super().on_retriever_error(RuntimeError(type(error).__name__), **kwargs)

    return [SafeCallbackHandler(public_key=get_settings().langfuse_public_key)]


@contextmanager
def observation(name: str, *, session_id: str | None = None, agent: bool = False) -> Iterator[Any]:
    """Create a span without recording arguments, results or raw exceptions."""
    client = get_tracing_client()
    if client is None:
        yield None
        return
    from langfuse import propagate_attributes

    error = None
    with propagate_attributes(session_id=session_id, metadata={"agent_trace": "1"} if agent else None):
        with client.start_as_current_observation(name=name, as_type="agent" if agent else "span") as span:
            try:
                yield span
            except BaseException as exc:
                span.update(level="ERROR", status_message=type(exc).__name__)
                error = exc
    if error is not None:
        raise error


def shutdown_tracing() -> None:
    """Drain queued observations when the application stops."""
    client = get_tracing_client()
    if client is not None:
        try:
            client.shutdown()
        except Exception:
            logger.warning("Langfuse shutdown failed")
