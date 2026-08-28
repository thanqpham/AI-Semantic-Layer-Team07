"""Deterministic query-compiler metrics with guarded execution (spec §7.4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from eval.evaluator.execution import EvaluationExecutionError, compare_query_result, execute_guarded_sql
from eval.evaluator.hybrid.catalog import MetricSpec
from eval.evaluator.hybrid.contracts import MetricResult
from eval.evaluator.hybrid.engine import EvaluationContext, ExecutionOutcome
from eval.evaluator.hybrid.metrics.base import (
    CandidateFailure,
    DeterministicMetric,
    boolean_result,
    clip_text,
    not_applicable_result,
    reference_as,
    score_result,
)
from eval.evaluator.hybrid.samples import EvaluationSample, QueryReference
from eval.evaluator.schemas import CandidateCompilerOutput, ExecutionResult
from eval.evaluator.sql_normalization import SqlValidationError, canonical_sql, structurally_equal


def build_compiler_metrics(specs: tuple[MetricSpec, ...]) -> dict[str, DeterministicMetric]:
    """Instantiate compiler metrics from catalog specs."""
    factory = {
        "request_validation_accuracy": RequestValidationAccuracy,
        "selection_preservation_accuracy": SelectionPreservationAccuracy,
        "invalid_selection_rejection": InvalidSelectionRejection,
        "sql_ast_equivalence": SqlAstEquivalence,
        "sql_execution_accuracy": SqlExecutionAccuracy,
        "result_schema_accuracy": ResultSchemaAccuracy,
    }
    return {spec.name: factory[spec.name](spec) for spec in specs if spec.name in factory}


def _payload(sample: EvaluationSample) -> tuple[QueryReference, CandidateCompilerOutput]:
    """Return the reference/response pair for a query-compilation sample."""
    reference = reference_as(sample, QueryReference)
    response = sample.response
    if response is None:
        raise _MissingCandidate()
    if not isinstance(response, CandidateCompilerOutput):
        raise TypeError("wrong response type for query_compilation")
    return reference, response


class _MissingCandidate(CandidateFailure):
    """Signal that no candidate response exists for this sample."""

    def __init__(self) -> None:
        super().__init__("no candidate response")


def _negative(reference: QueryReference, response: CandidateCompilerOutput) -> bool:
    return reference.expected_error is not None or response.error_code is not None


class RequestValidationAccuracy(DeterministicMetric):
    """Score primary-entity agreement, or outcome on negative cases.

    ``intent``/``domain`` are excluded: the deterministic pipeline has no
    classifier producing them (the adapter emits them empty by contract),
    so comparing them would measure the connector, not the agent.
    """

    async def _score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        reference, response = _payload(sample)
        if _negative(reference, response):
            matched = reference.expected_error is not None and reference.expected_error == response.error_code
            return boolean_result(
                self.spec, sample.sample_id, matched, "outcome comparison", _outcome_details(reference, response)
            )
        assert reference.expected is not None and response.canonical_query is not None
        expected_query, actual_query = reference.expected.canonical_query, response.canonical_query
        matched = expected_query.primary_entity == actual_query.primary_entity
        details = (
            None
            if matched
            else {
                "expected_entity": expected_query.primary_entity,
                "actual_entity": actual_query.primary_entity,
            }
        )
        return score_result(self.spec, sample.sample_id, 1.0 if matched else 0.0, details=details)


class SelectionPreservationAccuracy(DeterministicMetric):
    """Score metric and dimension selection preservation."""

    async def _score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        reference, response = _payload(sample)
        if _negative(reference, response):
            return not_applicable_result(self.spec, sample.sample_id, "negative case")
        assert reference.expected is not None and response.canonical_query is not None
        expected_query, actual_query = reference.expected.canonical_query, response.canonical_query
        checks = (
            set(expected_query.metrics) == set(actual_query.metrics),
            set(expected_query.dimensions) == set(actual_query.dimensions),
        )
        details = (
            None
            if all(checks)
            else {
                "expected_metrics": sorted(expected_query.metrics),
                "actual_metrics": sorted(actual_query.metrics),
                "expected_dimensions": sorted(expected_query.dimensions),
                "actual_dimensions": sorted(actual_query.dimensions),
            }
        )
        return score_result(self.spec, sample.sample_id, sum(checks) / len(checks), details=details)


class InvalidSelectionRejection(DeterministicMetric):
    """Score rejection behavior on negative compiler cases only."""

    async def _score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        reference, response = _payload(sample)
        if reference.expected_error is None:
            return not_applicable_result(self.spec, sample.sample_id, "positive case")
        matched = response.error_code == reference.expected_error
        return boolean_result(
            self.spec, sample.sample_id, matched, "outcome comparison", _outcome_details(reference, response)
        )


class SqlAstEquivalence(DeterministicMetric):
    """Compare compiled SQL ASTs against the golden dialect SQL."""

    async def _score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        reference, response = _payload(sample)
        if _negative(reference, response) or response.sql is None:
            return not_applicable_result(self.spec, sample.sample_id, "negative case")
        assert reference.expected is not None
        expected_sql = reference.expected.sql_by_dialect[context.config.execution_dialect]
        try:
            matched = structurally_equal(expected_sql, response.sql, "sqlite", ignore_limit=True)
        except SqlValidationError as exc:
            return boolean_result(self.spec, sample.sample_id, False, str(exc))
        details = None if matched else _ast_details(expected_sql, response.sql)
        return boolean_result(self.spec, sample.sample_id, matched, details=details)


class SqlExecutionAccuracy(DeterministicMetric):
    """Execute guarded SQL on isolated SQLite and compare result rows."""

    async def _score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        outcome_or_na = await _rows_for(sample, context)
        if isinstance(outcome_or_na, str):
            return not_applicable_result(self.spec, sample.sample_id, outcome_or_na)
        if outcome_or_na.rows is None:
            return boolean_result(self.spec, sample.sample_id, False, f"EXECUTION_FAILED: {outcome_or_na.failure}")
        reference = reference_as(sample, QueryReference)
        matched = compare_query_result(outcome_or_na.rows, reference.expected_rows, context.config)
        details = None if matched else _execution_details(outcome_or_na.rows, reference.expected_rows)
        return boolean_result(self.spec, sample.sample_id, matched, details=details)


class ResultSchemaAccuracy(DeterministicMetric):
    """Compare executed columns against the expected row schema."""

    async def _score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        outcome_or_na = await _rows_for(sample, context)
        if isinstance(outcome_or_na, str):
            return not_applicable_result(self.spec, sample.sample_id, outcome_or_na)
        if outcome_or_na.rows is None:
            return boolean_result(self.spec, sample.sample_id, False, f"EXECUTION_FAILED: {outcome_or_na.failure}")
        reference = reference_as(sample, QueryReference)
        rows = outcome_or_na.rows
        expected_columns = set(reference.expected_rows[0].keys()) if reference.expected_rows else set(rows.columns)
        matched = set(rows.columns) == expected_columns
        details = (
            None
            if matched
            else {
                "expected_columns": sorted(expected_columns),
                "actual_columns": sorted(rows.columns),
            }
        )
        return boolean_result(self.spec, sample.sample_id, matched, details=details)


async def _rows_for(sample: EvaluationSample, context: EvaluationContext) -> ExecutionOutcome | str:
    """Return the cached execution outcome, or a not-applicable reason."""
    reference, response = _payload(sample)
    if _negative(reference, response) or response.sql is None:
        return "negative case"
    if context.guardrail_adapter is None or context.dataset is None:
        return "execution prerequisites unavailable"
    if sample.sample_id in context.execution_cache:
        return context.execution_cache[sample.sample_id]
    result = await _execute_once(context, response.sql)
    context.execution_cache[sample.sample_id] = result
    return result


async def _execute_once(context: EvaluationContext, sql: str) -> ExecutionOutcome:
    """Run the guarded query once against the domain's isolated SQLite fixture."""
    assert context.dataset is not None
    source = context.dataset.domain_dir / "sources" / "sqlite"
    try:
        guarded = await context.guardrail_adapter.validate(sql, "sqlite")
        rows = await execute_guarded_sql(sql, source / "schema.sql", source / "seed_data.sql", guarded, context.config)
        return ExecutionOutcome(rows=rows)
    except (EvaluationExecutionError, SqlValidationError) as exc:
        return ExecutionOutcome(rows=None, failure=str(exc))


def _outcome_details(reference: QueryReference, response: CandidateCompilerOutput) -> dict[str, JsonValue]:
    """Capture both outcomes for one negative-case comparison."""
    return {"expected_error": reference.expected_error, "actual_error": response.error_code}


def _ast_details(expected_sql: str, actual_sql: str) -> dict[str, JsonValue]:
    """Capture both canonical comparison strings for one AST mismatch."""
    return {
        "expected": clip_text(canonical_sql(expected_sql, "sqlite", ignore_limit=True), 500),
        "actual": clip_text(canonical_sql(actual_sql, "sqlite", ignore_limit=True), 500),
    }


def _execution_details(
    actual: ExecutionResult,
    expected_rows: Sequence[Mapping[str, JsonValue]],
) -> dict[str, JsonValue]:
    """Summarize columns, row counts, and first rows of both sides of a mismatch."""
    return {
        "expected_columns": list(expected_rows[0].keys()) if expected_rows else list(actual.columns),
        "actual_columns": list(actual.columns),
        "expected_row_count": len(expected_rows),
        "actual_row_count": len(actual.rows),
        "expected_rows_preview": list(expected_rows[:5]),
        "actual_rows_preview": [dict(zip(actual.columns, row, strict=True)) for row in actual.rows[:5]],
    }
