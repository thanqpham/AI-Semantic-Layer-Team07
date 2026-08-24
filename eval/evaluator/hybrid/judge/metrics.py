"""Ragas-style AI-as-Judge metrics sharing the unified result contract (spec §8)."""

from __future__ import annotations

from eval.evaluator.hybrid.catalog import MetricSpec
from eval.evaluator.hybrid.contracts import MetricProvenance, MetricResult
from eval.evaluator.hybrid.engine import EvaluationContext
from eval.evaluator.hybrid.judge.base import JudgeRequest
from eval.evaluator.hybrid.judge.cache import content_hash, judge_cache_key
from eval.evaluator.hybrid.judge.output import weighted_score
from eval.evaluator.hybrid.judge.prompts import (
    PROMPT_VERSIONS,
    RUBRIC,
    RUBRIC_VERSION,
    judge_system_prompt,
    judge_user_prompt,
)
from eval.evaluator.hybrid.metrics.base import (
    CandidateFailure,
    error_result,
    not_applicable_result,
    reference_as,
    response_as,
    score_result,
)
from eval.evaluator.hybrid.samples import (
    EnrichmentReference,
    EvaluationSample,
    MetricReference,
)
from eval.evaluator.schemas import (
    CandidateEnrichmentOutput,
    CandidateMetricOutput,
)


def build_judge_metrics(specs: tuple[MetricSpec, ...]) -> dict[str, AiJudgeMetric]:
    """Instantiate judge metrics from catalog specs."""
    factory = {
        "business_semantic_correctness": BusinessSemanticCorrectness,
        "business_definition_correctness": BusinessDefinitionCorrectness,
        "formula_semantic_correctness": FormulaSemanticCorrectness,
    }
    return {spec.name: factory[spec.name](spec) for spec in specs if spec.name in factory}


def _field_lines(fields: dict[str, str], gap_fields: frozenset[str]) -> str:
    """Render 'key: value' lines, dropping fields declared as contract gaps."""
    return "\n".join(f"{key}: {value}" for key, value in fields.items() if key not in gap_fields)


class AiJudgeMetric:
    """Base: render prompts, run the judge lane, normalize to MetricResult."""

    metric_type = "ai_judge"

    def __init__(self, spec: MetricSpec) -> None:
        self.spec = spec

    @property
    def name(self) -> str:
        return self.spec.name

    def _render(self, sample: EvaluationSample, model: str, gap_fields: frozenset[str]) -> tuple[JudgeRequest, dict]:
        """Build the blinded judge request; implemented per metric."""
        raise NotImplementedError

    def _request(self, sample: EvaluationSample, user_prompt: str, model: str) -> JudgeRequest:
        prompt_version = PROMPT_VERSIONS[self.spec.name]
        return JudgeRequest(
            system_prompt=judge_system_prompt(),
            user_prompt=user_prompt,
            prompt_version=prompt_version,
            rubric_version=RUBRIC_VERSION,
            model=model,
            cache_key=judge_cache_key(
                sample.sample_id, content_hash(user_prompt), RUBRIC_VERSION, prompt_version, model
            ),
        )

    def _provenance(self, model: str) -> MetricProvenance:
        return MetricProvenance(
            rubric_version=RUBRIC_VERSION,
            prompt_version=PROMPT_VERSIONS[self.spec.name],
            model=model,
        )

    async def score(self, sample: EvaluationSample, context: EvaluationContext) -> MetricResult:
        """Run one judge call or explain why it cannot run."""
        if context.judge_runner is None:
            return not_applicable_result(self.spec, sample.sample_id, "judge runner unavailable")
        model = getattr(context.judge_runner.llm, "model_name", "unknown")
        gap_fields = frozenset(context.contract_gap_fields.get("metric", frozenset()))
        try:
            request, payload = self._render(sample, model, gap_fields)
        except (CandidateFailure, TypeError) as exc:
            return not_applicable_result(self.spec, sample.sample_id, f"candidate not judgeable: {exc}")
        try:
            verdict = await context.judge_runner.evaluate(request)
        except Exception as exc:  # judge-lane crashes can never abort the run
            return error_result(self.spec, sample.sample_id, exc)
        if verdict is None:
            return error_result(self.spec, sample.sample_id, RuntimeError("JUDGE_FAILED"))
        return score_result(
            self.spec,
            sample.sample_id,
            weighted_score(verdict, RUBRIC),
            reason=verdict.summary,
            details=payload,
            provenance=self._provenance(model),
        )


class BusinessSemanticCorrectness(AiJudgeMetric):
    """Judge entity and dimension business names against golden labels."""

    def _render(self, sample: EvaluationSample, model: str, gap_fields: frozenset[str]) -> tuple[JudgeRequest, dict]:
        reference = reference_as(sample, EnrichmentReference)
        response = response_as(sample, CandidateEnrichmentOutput)
        if response.entities is None:
            raise CandidateFailure(response.error_code or "no entities")
        request_lines = [f"entity_refs: {', '.join(reference.entity_refs)}"]
        schema_lines = [
            f"{entity.entity}: dims=[{', '.join(d.name for d in entity.dimensions)}]"
            for entity in reference.canonical_entities
        ]
        reference_lines = [
            f"{entity.entity} -> {entity.business_name} ; dims: "
            + ", ".join(f"{d.name}={d.business_name}" for d in entity.dimensions)
            for entity in reference.canonical_entities
        ]
        response_lines = [
            f"{entity.entity} -> {entity.business_name} ; dims: "
            + ", ".join(f"{d.name}={d.business_name}" for d in entity.dimensions)
            for entity in response.entities
        ]
        user_prompt = judge_user_prompt(
            "Đánh giá tên nghiệp vụ của entity/dimension",
            "\n".join(request_lines),
            "\n".join(schema_lines),
            "\n".join(reference_lines),
            "\n".join(response_lines),
        )
        return self._request(sample, user_prompt, model), {"judged_entities": len(response_lines)}


class BusinessDefinitionCorrectness(AiJudgeMetric):
    """Judge the business definition text of a generated metric."""

    def _render(self, sample: EvaluationSample, model: str, gap_fields: frozenset[str]) -> tuple[JudgeRequest, dict]:
        reference = reference_as(sample, MetricReference)
        response = response_as(sample, CandidateMetricOutput)
        expected, actual = reference.expected_metric, response.metric
        if expected is None or actual is None:
            raise CandidateFailure("negative case")
        reference = _field_lines(
            {"description": expected.description, "business_formula": expected.business_formula}, gap_fields
        )
        response = _field_lines(
            {"description": actual.description, "business_formula": actual.business_formula}, gap_fields
        )
        user_prompt = judge_user_prompt(
            "Đánh giá mô tả nghiệp vụ của chỉ số",
            f"request: {sample.input!s}",
            f"target_entity: {expected.target_entity}; aggregation: {expected.aggregation}",
            reference,
            response,
        )
        return self._request(sample, user_prompt, model), {"metric": actual.name}


class FormulaSemanticCorrectness(AiJudgeMetric):
    """Judge formula and SQL-expression semantics of a generated metric."""

    def _render(self, sample: EvaluationSample, model: str, gap_fields: frozenset[str]) -> tuple[JudgeRequest, dict]:
        reference = reference_as(sample, MetricReference)
        response = response_as(sample, CandidateMetricOutput)
        expected, actual = reference.expected_metric, response.metric
        if expected is None or actual is None:
            raise CandidateFailure("negative case")
        reference = _field_lines(
            {"business_formula": expected.business_formula, "sql_expression": expected.sql_expression},
            gap_fields,
        )
        response = _field_lines(
            {"business_formula": actual.business_formula, "sql_expression": actual.sql_expression},
            gap_fields,
        )
        user_prompt = judge_user_prompt(
            "Đánh giá ngữ nghĩa công thức của chỉ số",
            f"request: {sample.input!s}",
            f"source_table: {expected.source_table}; field: {expected.field}",
            reference,
            response,
        )
        return self._request(sample, user_prompt, model), {"metric": actual.name}
