"""Emit opt-in agent trace events without coupling production to benchmark storage."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Protocol, TypeVar


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
    started = time.perf_counter()
    action_token = _ACTION.set(action)
    _emit("action_started", _action_started_payload(action, inputs))
    try:
        result = operation()
    except Exception as exc:
        _emit("action_failed", _action_payload(action, inputs, started, error=type(exc).__name__))
        raise
    finally:
        _ACTION.reset(action_token)
    _emit("action_finished", _action_payload(action, inputs, started, observation=result))
    return result


async def trace_action(action: str, inputs: Mapping[str, Any], operation: Awaitable[_T]) -> _T:
    """Await an operation and record its observable action boundary when enabled."""
    started = time.perf_counter()
    action_token = _ACTION.set(action)
    _emit("action_started", _action_started_payload(action, inputs))
    try:
        result = await operation
    except Exception as exc:
        _emit("action_failed", _action_payload(action, inputs, started, error=type(exc).__name__))
        raise
    finally:
        _ACTION.reset(action_token)
    _emit("action_finished", _action_payload(action, inputs, started, observation=result))
    return result


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
            started = time.perf_counter()
            node_token = _NODE.set(name)
            _emit("node_started", {"node": name, "state_before": dict(state)})
            try:
                output = await function(state, *args, **kwargs)
            except Exception as exc:
                _emit("node_failed", _node_payload(name, state, started, error=type(exc).__name__))
                raise
            finally:
                _NODE.reset(node_token)
            kind = "node_failed" if output.get("error") else "node_finished"
            _emit(kind, _node_payload(name, state, started, output=output, error=output.get("error")))
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
