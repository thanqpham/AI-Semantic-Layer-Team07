"""Emit opt-in agent trace events without coupling production to benchmark storage."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Protocol, TypeVar

from src.observability.langfuse_tracing import observation, trace_summary


class AgentTraceSink(Protocol):
    """Receive one unredacted event from an active trace context."""

    def record(self, kind: str, payload: Mapping[str, Any]) -> None:
        """Record an event synchronously without changing the caller result."""


_SINK: ContextVar[AgentTraceSink | None] = ContextVar("agent_trace_sink", default=None)
_NODE: ContextVar[str | None] = ContextVar("agent_trace_node", default=None)
_ACTION: ContextVar[str | None] = ContextVar("agent_trace_action", default=None)
_T = TypeVar("_T")


@contextmanager
def activate_trace(sink: AgentTraceSink):
    """Activate a trace sink for the current async task context."""
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


def _emit(kind: str, payload: Mapping[str, Any]) -> None:
    sink = _SINK.get()
    if sink is not None:
        sink.record(kind, payload)


def trace_transition(source: str, target: str) -> None:
    """Record a graph transition when a benchmark trace context is active."""
    _emit("transition", {"node": source, "action": target})


def trace_value(action: str, inputs: Mapping[str, Any], operation: Callable[[], _T]) -> _T:
    """Run a synchronous guardrail operation with optional action tracing."""
    with observation(action) as span:
        started = time.perf_counter()
        action_token = _ACTION.set(action)
        _emit("action_started", _action_started_payload(action, inputs))
        if span is not None:
            initial = trace_summary(**inputs)
            if initial is not None:
                span.update(input=initial)
        try:
            result = operation()
        except Exception as exc:
            _emit("action_failed", _action_payload(action, inputs, started, error=type(exc).__name__))
            if span is not None:
                span.update(output=trace_summary(status="failed", duration_ms=_elapsed_ms(started)))
            raise
        finally:
            _ACTION.reset(action_token)
        _emit("action_finished", _action_payload(action, inputs, started, observation=result))
        if span is not None:
            span.update(
                output=trace_summary(status="finished", duration_ms=_elapsed_ms(started), **_result_counts(result))
            )
        return result


async def trace_action(action: str, inputs: Mapping[str, Any], operation: Awaitable[_T]) -> _T:
    """Await an operation and record its observable action boundary when enabled."""
    with observation(action) as span:
        started = time.perf_counter()
        action_token = _ACTION.set(action)
        _emit("action_started", _action_started_payload(action, inputs))
        if span is not None:
            initial = trace_summary(**inputs)
            if initial is not None:
                span.update(input=initial)
        try:
            result = await operation
        except Exception as exc:
            _emit("action_failed", _action_payload(action, inputs, started, error=type(exc).__name__))
            if span is not None:
                span.update(output=trace_summary(status="failed", duration_ms=_elapsed_ms(started)))
            raise
        finally:
            _ACTION.reset(action_token)
        _emit("action_finished", _action_payload(action, inputs, started, observation=result))
        if span is not None:
            span.update(
                output=trace_summary(status="finished", duration_ms=_elapsed_ms(started), **_result_counts(result))
            )
        return result


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _result_counts(result: Any) -> dict[str, int]:
    for field, count_name in (("candidates", "proposal_count"), ("decisions", "reviewed_count")):
        items = getattr(result, field, None)
        if isinstance(items, list):
            return {count_name: len(items)}
    return {}


def _node_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "intent": state.get("intent"),
        "mode": state.get("proposal_mode"),
        "run_status": state.get("run_status"),
    }
    interpretation = state.get("interpretation")
    if isinstance(interpretation, dict):
        summary["parse_status"] = interpretation.get("status")
    for key in ("suggested_metrics", "reviewed_proposals", "items"):
        items = state.get(key)
        if isinstance(items, list):
            summary["reviewed_count" if key == "reviewed_proposals" else "proposal_count"] = len(items)
            if key == "items":
                summary["repair_count"] = sum(item.get("attempt") == 1 for item in items if isinstance(item, dict))
                for status in ("pass", "needs_revision", "needs_clarification", "rejected", "unsupported", "error"):
                    summary[f"{status}_count"] = sum(
                        (
                            item["report"].get("status")
                            if isinstance(item.get("report"), dict)
                            else getattr(item.get("report"), "status", None)
                        )
                        == status
                        for item in items
                        if isinstance(item, dict)
                    )
    for key in ("raw_schema", "enriched_schema"):
        schema = state.get(key)
        if isinstance(schema, dict) and isinstance(schema.get("tables"), (dict, list)):
            summary["table_count"] = len(schema["tables"])
    return summary


def trace_llm_usage(payload: Mapping[str, Any]) -> None:
    """Record normalized provider usage without retaining prompt or response content."""
    event = {"node": _NODE.get(), "action": _ACTION.get() or "llm_invoke", **dict(payload)}
    _emit("llm_usage", event)


def _action_payload(
    action: str,
    inputs: Mapping[str, Any],
    started: float,
    observation: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "node": _NODE.get(),
        "action": action,
        "inputs": dict(inputs),
        "observation": observation,
        "error_code": error,
        "latency_ms": (time.perf_counter() - started) * 1000,
    }


def _action_started_payload(action: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Attach the active graph node to a started action event."""
    return {"node": _NODE.get(), "action": action, "inputs": dict(inputs)}


def trace_node(
    name: str,
) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]]:
    """Decorate an async LangGraph node with start, finish, and failure events."""

    def decorate(function: Callable[..., Awaitable[dict[str, Any]]]) -> Callable[..., Awaitable[dict[str, Any]]]:
        @wraps(function)
        async def wrapped(state: Mapping[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            with observation(name, session_id=state.get("session_id"), agent=True) as span:
                started = time.perf_counter()
                node_token = _NODE.set(name)
                _emit("node_started", {"node": name, "state_before": dict(state)})
                if span is not None:
                    initial = trace_summary(**_node_summary(state))
                    if initial is not None:
                        span.update(input=initial)
                try:
                    output = await function(state, *args, **kwargs)
                except Exception as exc:
                    _emit("node_failed", _node_payload(name, state, started, error=type(exc).__name__))
                    if span is not None:
                        span.update(
                            output=trace_summary(
                                status="failed", duration_ms=_elapsed_ms(started), error_code="node_error"
                            )
                        )
                    raise
                finally:
                    _NODE.reset(node_token)
                kind = "node_failed" if output.get("error") else "node_finished"
                _emit(kind, _node_payload(name, state, started, output=output, error=output.get("error")))
                if span is not None and output.get("error"):
                    span.update(level="ERROR", status_message="node_error")
                if span is not None:
                    span.update(
                        output=trace_summary(
                            **_node_summary(output),
                            status="failed" if output.get("error") else "finished",
                            duration_ms=_elapsed_ms(started),
                            error_code="node_error" if output.get("error") else None,
                        )
                    )
                return output

        return wrapped

    return decorate


def _node_payload(
    name: str,
    state: Mapping[str, Any],
    started: float,
    output: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "node": name,
        "state_before": dict(state),
        "state_delta": dict(output or {}),
        "error_code": error,
        "latency_ms": (time.perf_counter() - started) * 1000,
    }
