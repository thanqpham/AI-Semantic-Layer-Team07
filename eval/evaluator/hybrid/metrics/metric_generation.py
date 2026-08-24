"""Deterministic business-metric generation metrics (spec §7.3)."""

from __future__ import annotations

from abc import abstractmethod

from eval.evaluator.hybrid.catalog import MetricSpec
from eval.evaluator.hybrid.contracts import MetricResult
from eval.evaluator.hybrid.engine import EvaluationContext
from eval.evaluator.hybrid.metrics.base import (
    DeterministicMetric,
    boolean_result,
    not_applicable_result,
    reference_as,
    response_as,
    set_match_result,
)
from eval.evaluator.hybrid.samples import EvaluationSample, MetricReference
from eval.evaluator.metric_eval import _identity
from eval.evaluator.schemas import CandidateMetricDefinition, CandidateMetricOutput
from eval.evaluator.scoring import match_sets
from eval.evaluator.sql_normalization import normalize_expression, unwrap_declared_aggregation
from eval.evaluator.text_similarity import compare_business_name


def build_metric_generation_metrics(specs: tuple[MetricSpec, ...]) -> dict[str, DeterministicMetric]:
    """Instantiate deterministic metric-generation metrics from catalog specs."""
    factory = {
        "metric_identity_accuracy": MetricIdentityAccuracy,
        "formula_equivalence": FormulaEquivalence,
        "sql_expression_equivalence": SqlExpressionEquivalence,
        "filter_accuracy": FilterAccuracy,
        "allowed_dimension_f1": AllowedDimensionF1,
    }
    return {spec.name: factory[spec.name](spec) for spec in specs if spec.name in factory}


class _NegativeCase(Exception):  # noqa: N818 — name is fixed by the metric contract
    """Signal an error-outcome sample, not a scoring failure."""

    def __init__(self, expected_error: str | None, actual_error: str | None) -> None:
        super().__init__(expected_error or "negative case")
        self.expected_error = expected_error
        self.actual_error = actual_error


def _positive_payload(sample: EvaluationSample) -> tuple[MetricReference, CandidateMetricDefinition]:
    """Return the reference/actual pair, raising _NegativeCase for outcome cases."""
    reference = reference_as(sample, MetricReference)
    response = response_as(sample, CandidateMetricOutput)
    negative = reference.expected_error is not None or response.error_code is not None
    if negative or reference.expected_metric is None or response.metric is None:
        raise _NegativeCase(reference.expected_error, response.error_code)
    return reference, response.metric


class MetricIdentityAccuracy(DeterministicMetric):
    """Score core identity match, or outcome match on negative cases."""

    async def _score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        try:
            reference, actual = _positive_payload(sample)
        except _NegativeCase as case:
            matched = case.expected_error is not None and case.expected_error == case.actual_error
            return boolean_result(self.spec, sample.sample_id, matched, "outcome comparison")
        return boolean_result(self.spec, sample.sample_id, _identity(reference.expected_metric) == _identity(actual))


class _PositiveOnlyMetric(DeterministicMetric):
    """Base for metrics that apply only to successful metric definitions."""

    async def _score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        try:
            return await self._score_positive(sample, context)
        except _NegativeCase:
            return not_applicable_result(self.spec, sample.sample_id, "negative case")

    @abstractmethod
    async def _score_positive(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        """Score one successful metric definition."""


class FormulaEquivalence(_PositiveOnlyMetric):
    """Compare business formulas, unless the field is a declared contract gap."""

    async def _score_positive(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        if "business_formula" in context.contract_gap_fields.get("metric", frozenset()):
            return not_applicable_result(self.spec, sample.sample_id, "contract gap (D6)")
        reference, actual = _positive_payload(sample)
        expected = reference.expected_metric
        result = await compare_business_name(
            actual.business_formula, (expected.business_formula,), context.config, context.text_provider
        )
        return boolean_result(self.spec, sample.sample_id, result.accepted)


class SqlExpressionEquivalence(_PositiveOnlyMetric):
    """Compare normalized SQL expressions, symmetric on aggregation wrappers.

    Each side strips one top-level aggregation wrapper only when it matches
    that side's own declared ``aggregation`` (golden and candidate both carry
    it), so a wrapped golden ``SUM(x)`` and a bare candidate ``x`` compare
    equal while contradicting wrappers still mismatch.
    """

    async def _score_positive(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        reference, actual = _positive_payload(sample)
        expected_sql = unwrap_declared_aggregation(
            reference.expected_metric.sql_expression, reference.expected_metric.aggregation
        )
        actual_sql = unwrap_declared_aggregation(actual.sql_expression, actual.aggregation)
        return boolean_result(self.spec, sample.sample_id, expected_sql == actual_sql)


class FilterAccuracy(_PositiveOnlyMetric):
    """Compare normalized default-filter condition sets."""

    async def _score_positive(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        reference, actual = _positive_payload(sample)
        expected = {normalize_expression(f.condition) for f in reference.expected_metric.default_filters}
        received = {normalize_expression(f.condition) for f in actual.default_filters}
        return boolean_result(self.spec, sample.sample_id, expected == received)


class AllowedDimensionF1(_PositiveOnlyMetric):
    """Set-match allowed dimensions."""

    async def _score_positive(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        reference, actual = _positive_payload(sample)
        match = match_sets(reference.expected_metric.allowed_dimensions, actual.allowed_dimensions)
        return set_match_result(self.spec, sample.sample_id, match)
