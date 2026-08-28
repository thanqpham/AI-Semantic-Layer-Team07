"""Context-local recorder that converts product events into redacted trace artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from eval.benchmark.contracts import TraceEvent
from eval.benchmark.redaction import digest_observation, redact_state_delta


class BenchmarkTraceRecorder:
    """Collect redacted benchmark events for one run without product persistence."""

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._case_id: ContextVar[str] = ContextVar("benchmark_case_id", default="unknown")
        self._trial: ContextVar[int] = ContextVar("benchmark_trial", default=1)
        self._iteration: ContextVar[int] = ContextVar("benchmark_iteration", default=0)
        self.events: list[TraceEvent] = []

    @contextmanager
    def trial_context(self, case_id: str, trial: int):
        """Bind all product events to one case and trial."""
        case_token = self._case_id.set(case_id)
        trial_token = self._trial.set(trial)
        iteration_token = self._iteration.set(0)
        try:
            yield
        finally:
            self._case_id.reset(case_token)
            self._trial.reset(trial_token)
            self._iteration.reset(iteration_token)

    def record(self, kind: str, payload: Mapping[str, Any]) -> None:
        """Convert one product event into a safe benchmark event."""
        self.events.append(self._event(kind, payload))

    def _event(self, kind: str, payload: Mapping[str, Any]) -> TraceEvent:
        iteration = self._next_iteration(kind)
        status = "failed" if kind.endswith("failed") else "started" if kind.endswith("started") else "finished"
        action = _text(payload.get("action"))
        node = _text(payload.get("node"))
        state_delta = redact_state_delta(_mapping(payload.get("state_delta")))
        observation = payload.get("observation")
        evidence = (action,) if action and status == "finished" else ()
        return TraceEvent(
            run_id=self._run_id,
            case_id=self._case_id.get(),
            trial=self._trial.get(),
            iteration=iteration,
            kind=kind,
            status=status,
            node=node,
            action=action,
            state_delta=state_delta,
            observation_digest=digest_observation(observation) if observation is not None else None,
            evidence_actions=evidence,
            error_code=_text(payload.get("error_code")),
            latency_ms=_number(payload.get("latency_ms")),
        )

    def _next_iteration(self, kind: str) -> int:
        if kind.endswith("started"):
            self._iteration.set(self._iteration.get() + 1)
        return max(1, self._iteration.get())


def _mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping or an empty value for artifact serialization."""
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    """Normalize optional event strings."""
    return str(value) if value is not None else None


def _number(value: Any) -> float | None:
    """Normalize optional non-negative latencies."""
    return float(value) if isinstance(value, (int, float)) and value >= 0 else None
