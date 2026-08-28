"""Run trace-aware scenarios under an opt-in product trace context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eval.benchmark.baseline import compare_baseline
from eval.benchmark.contracts import (
    BenchmarkGate,
    BenchmarkRunRequest,
    BenchmarkRunResult,
    ScenarioExecution,
    TraceEvent,
)
from eval.benchmark.scoring import aggregate_scores, benchmark_gates, overall_score, score_case
from eval.benchmark.tracer import BenchmarkTraceRecorder
from src.observability import activate_trace


@dataclass(frozen=True)
class _TrialResult:
    """Keep one execution together with the events emitted during its trial."""

    case_id: str
    events: tuple[TraceEvent, ...]
    execution: ScenarioExecution


async def run_benchmark(request: BenchmarkRunRequest) -> BenchmarkRunResult:
    """Execute all cases and produce a deterministic trace benchmark result."""
    recorder = BenchmarkTraceRecorder(request.run_id)
    trials = await _run_trials(request, recorder)
    scores = aggregate_scores(score_case(_case(request, row.case_id), row.events, row.execution) for row in trials)
    gates = tuple(
        gate for row in trials for gate in benchmark_gates(_case(request, row.case_id), row.events, row.execution)
    )
    return _result(request, recorder.events, tuple(row.execution for row in trials), scores, gates)


async def _run_trials(request: BenchmarkRunRequest, recorder: BenchmarkTraceRecorder) -> tuple[_TrialResult, ...]:
    """Run each configured case repeatedly in its own trace context."""
    rows: list[_TrialResult] = []
    with activate_trace(recorder):
        for case in request.cases:
            for trial in range(1, request.profile.trials + 1):
                rows.append(await _run_one(request, recorder, case.case_id, trial))
    return tuple(rows)


async def _run_one(
    request: BenchmarkRunRequest,
    recorder: BenchmarkTraceRecorder,
    case_id: str,
    trial: int,
) -> _TrialResult:
    """Run one case while isolating its event slice from adjacent trials."""
    case = _case(request, case_id)
    offset = len(recorder.events)
    with recorder.trial_context(case_id, trial):
        execution = await request.executor.execute(case)
    return _TrialResult(case_id=case_id, events=tuple(recorder.events[offset:]), execution=execution)


def _case(request: BenchmarkRunRequest, case_id: str):
    """Find one case by its unique identifier."""
    return next(case for case in request.cases if case.case_id == case_id)


def _result(
    request: BenchmarkRunRequest,
    events: list[TraceEvent],
    executions: tuple[ScenarioExecution, ...],
    scores: tuple[Any, ...],
    gates: tuple[BenchmarkGate, ...],
) -> BenchmarkRunResult:
    """Assemble aggregate status while keeping release integration advisory."""
    coverage = len(executions) / (len(request.cases) * request.profile.trials) if request.cases else 0.0
    critical = any(not gate.passed for gate in gates)
    score = overall_score(scores) if executions else None
    status = "INCOMPLETE" if coverage < 0.95 else "FAIL" if critical else "PASS" if score and score >= 90 else "WARN"
    provisional = BenchmarkRunResult(
        run_id=request.run_id,
        status=status,
        overall_score=score,
        coverage=coverage,
        profile=request.profile,
        scores=scores,
        gates=gates,
        events=tuple(events),
        executions=executions,
    )
    comparison = compare_baseline(provisional, request.baseline)
    warnings = _warnings(comparison, request.profile.regression_tolerance)
    return provisional.model_copy(update={"baseline": comparison, "warnings": warnings})


def _warnings(comparison, tolerance: float) -> tuple[str, ...]:
    """Emit advisory regression warnings without blocking the release pipeline."""
    if comparison is None or not comparison.compatible:
        return ()
    changes = {"latency": comparison.latency_delta, "cost": comparison.cost_delta}
    return tuple(
        f"{name} regressed by {value:.0%}" for name, value in changes.items() if value is not None and value > tolerance
    )
