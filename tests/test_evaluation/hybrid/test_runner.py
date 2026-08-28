"""Tests for the end-to-end hybrid runner on the mini dataset."""

from dataclasses import asdict

from eval.evaluator.hybrid.catalog import all_metric_specs
from eval.evaluator.hybrid.contracts import MetricResult
from eval.evaluator.hybrid.run_result import evaluate_gates
from eval.evaluator.hybrid.runner import (
    HybridRunRequest,
    _judge_error_warnings,
    _score_valid,
    run_hybrid_evaluation,
)
from eval.evaluator.hybrid.smoke import SmokeGuardrailAdapter, smoke_candidates
from eval.evaluator.schemas import EvaluationConfig
from tests.test_evaluation.hybrid.conftest import _executable_dataset


async def test_perfect_smoke_run_passes(mini_dataset) -> None:
    config = EvaluationConfig()
    candidates = await smoke_candidates(mini_dataset, config)
    result = await run_hybrid_evaluation(HybridRunRequest(dataset=mini_dataset, config=config, **asdict(candidates)))
    assert result.status == "PASS"
    assert result.overall_score is not None and result.overall_score >= 90.0
    assert result.coverage == 1.0
    assert result.score_valid is True


def _judge_error_result(metric: str, status: str, score: float | None = None) -> MetricResult:
    return MetricResult(
        sample_id="s1",
        metric=metric,
        metric_type="ai_judge",
        status=status,
        score=score,
        threshold=0.8,
    )


def _full_summary(without: str | None = None) -> dict[str, float | None]:
    """A summary where every required metric scored, except the named one."""
    return {spec.name: None if spec.name == without else 1.0 for spec in all_metric_specs()}


def test_judge_only_errors_do_not_invalidate_score() -> None:
    """One transient judge failure must not flip score_valid for the whole run."""
    gates = evaluate_gates((), "benchmark", "agent_live", "pipeline", "approved")
    results = (
        _judge_error_result("business_definition_correctness", "error"),
        _judge_error_result("business_definition_correctness", "not_applicable"),
    )
    summary = _full_summary(without="business_definition_correctness")
    assert _score_valid(gates, summary, results, "benchmark") is True
    assert _judge_error_warnings(results) == (
        "judge metric business_definition_correctness errored on 1 sample(s); scores treated as unavailable",
    )


def test_deterministic_errors_still_invalidate_score() -> None:
    gates = evaluate_gates((), "benchmark", "agent_live", "pipeline", "approved")
    results = (
        MetricResult(sample_id="s1", metric="table_f1", metric_type="deterministic", status="error", threshold=0.95),
    )
    assert _score_valid(gates, _full_summary(without="table_f1"), results, "benchmark") is False
    assert _judge_error_warnings(results) == ()


async def test_judge_metrics_not_applicable_without_runner(mini_dataset) -> None:
    candidates = await smoke_candidates(mini_dataset, EvaluationConfig())
    result = await run_hybrid_evaluation(
        HybridRunRequest(dataset=mini_dataset, config=EvaluationConfig(), **asdict(candidates))
    )
    judge = [r for r in result.results if r.metric_type == "ai_judge"]
    assert judge and all(r.status == "not_applicable" for r in judge)


async def test_missing_candidates_produce_failures_and_warnings(mini_dataset) -> None:
    result = await run_hybrid_evaluation(HybridRunRequest(dataset=mini_dataset, config=EvaluationConfig()))
    assert result.warnings, "missing responses must be reported"
    assert any(r.status == "failed" for r in result.results)
    assert result.status != "PASS"


async def test_benchmark_requires_deterministic_evidence(mini_dataset) -> None:
    candidates = await smoke_candidates(mini_dataset, EvaluationConfig())
    result = await run_hybrid_evaluation(
        HybridRunRequest(dataset=mini_dataset, config=EvaluationConfig(), run_type="benchmark", **asdict(candidates))
    )
    assert result.score_valid is False
    assert result.status == "INCOMPLETE"


async def test_benchmark_golden_derived_stays_invalid_with_execution(mini_dataset, tmp_path) -> None:
    dataset = _executable_dataset(mini_dataset, tmp_path)
    config = EvaluationConfig()
    candidates = await smoke_candidates(dataset, config)
    result = await run_hybrid_evaluation(
        HybridRunRequest(
            dataset=dataset,
            config=config,
            run_type="benchmark",
            guardrail_adapter=SmokeGuardrailAdapter(config),
            **asdict(candidates),
        )
    )
    assert not next(g for g in result.quality_gates if g.name == "release_evidence").passed
    assert result.score_valid is False
    assert result.status == "INCOMPLETE"


async def test_benchmark_agent_live_stays_valid_with_execution(mini_dataset, tmp_path) -> None:
    dataset = _executable_dataset(mini_dataset, tmp_path)
    config = EvaluationConfig()
    candidates = await smoke_candidates(dataset, config)
    result = await run_hybrid_evaluation(
        HybridRunRequest(
            dataset=dataset,
            config=config,
            run_type="benchmark",
            candidate_source="agent_live",
            guardrail_adapter=SmokeGuardrailAdapter(config),
            **asdict(candidates),
        )
    )
    assert result.score_valid is True
    assert result.status == "PASS"
