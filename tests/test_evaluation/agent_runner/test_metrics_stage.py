"""Metrics collector: real create/approve path, first-suggestion, error path."""

from pathlib import Path

from eval.agent_runner.adapters import to_metric_candidate
from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.agent_runner.golden_view import MetricCaseView
from eval.agent_runner.metrics_stage import collect_metrics
from eval.dataset.loader import load_domain_dataset
from src.models.metric_definition import MetricDefinition, MetricSpec

GOLDEN_ROOT = Path("eval/golden_dataset")


def _definition(name: str, expression: str = "total_amount") -> MetricDefinition:
    """Build a minimal draft definition with a SUM-over-expression formula."""
    return MetricDefinition(
        schema_version=1,
        metric=MetricSpec(
            name=name,
            formula={"function": "SUM", "expression": expression},
            base_entity="fact_orders",
            filters=[],
            status="pending_approval",
        ),
    )


def _definition_with_formula(function: str, expression: str, base_entity: str) -> MetricDefinition:
    """Build a draft definition with explicit function/expression/base_entity."""
    return MetricDefinition(
        schema_version=1,
        metric=MetricSpec(
            name="m",
            formula={"function": function, "expression": expression},
            base_entity=base_entity,
            filters=[],
            status="pending_approval",
        ),
    )


async def _ecommerce_resolver() -> CanonicalResolver:
    """Load the ecommerce golden registry into a canonical resolver."""
    dataset = await load_domain_dataset(GOLDEN_ROOT, "ecommerce")
    return CanonicalResolver.from_dataset(dataset, {})


def _suggestion(definition: MetricDefinition):
    """Minimal stand-in for MetricSuggestionItem (definition + yaml_preview)."""
    return type("Suggestion", (), {"definition": definition, "yaml_preview": ""})()


async def test_to_metric_candidate_simple():
    candidate = to_metric_candidate(
        _definition("tong_doanh_thu"),
        allowed_dimensions=["dim_customer.customer_name"],
        source_table="fact_orders",
        resolver=await _ecommerce_resolver(),
    ).metric
    assert candidate.name == "tong_doanh_thu"
    assert candidate.business_name == "tong_doanh_thu"  # best-effort (D6)
    assert candidate.aggregation == "sum"
    assert candidate.field == "total_amount"
    assert candidate.sql_expression == "total_amount"
    assert candidate.metric_type == "simple"
    assert candidate.allowed_dimensions == ("dim_customer.customer_name",)
    assert candidate.business_formula == ""  # miss vĩnh viễn
    assert candidate.status == "draft"  # pending_approval maps to draft


async def test_to_metric_candidate_derived():
    definition = _definition("gia_tri_don_tb")
    definition.metric.formula.expression = "total_amount / order_count"
    candidate = to_metric_candidate(
        definition, allowed_dimensions=[], source_table="fact_orders", resolver=await _ecommerce_resolver()
    ).metric
    assert candidate.metric_type == "derived"
    assert candidate.field is None
    assert candidate.sql_expression == "total_amount / order_count"


async def test_to_metric_candidate_translates_timestamp_difference_for_evaluation():
    definition = _definition_with_formula("AVG", "TIMESTAMP_DIFF_HOURS(delivered_time, order_date)", "fact_orders")
    candidate = to_metric_candidate(
        definition, allowed_dimensions=[], source_table="fact_orders", resolver=await _ecommerce_resolver()
    ).metric
    assert candidate.metric_type == "derived"
    assert candidate.field is None
    assert candidate.sql_expression == "(julianday(delivered_time) - julianday(order_date)) * 24.0"


async def test_metric_candidate_resolves_canonical_and_unwraps_expression(enriched):
    ctx, conn_id, _raw = enriched
    resolver = await _ecommerce_resolver()

    definition = _definition_with_formula("SUM", "gross_amount - discount_amount", "fact_orders")
    candidate = to_metric_candidate(
        definition,
        allowed_dimensions=["fact_orders.order_status", "customers.city"],
        source_table="fact_orders",
        resolver=resolver,
    )
    metric = candidate.metric
    assert metric is not None
    assert metric.target_entity == "order"
    assert metric.source_table == "fact_orders"  # physical, matches golden convention
    assert metric.sql_expression == "gross_amount - discount_amount"  # aggregation lives in .aggregation
    assert metric.aggregation == "sum"
    assert list(metric.allowed_dimensions) == ["order.order_status", "customer.city"]


async def test_collect_metrics_creates_and_maps(enriched, monkeypatch):
    ctx, conn_id, _raw = enriched

    async def fake_generate(prompt, dialect, schema_dict=None, **kwargs):
        from tests.test_evaluation.agent_runner.conftest import slugify

        return [
            type(
                "Suggestion",
                (),
                {
                    "definition": _definition(f"m_{slugify(prompt)}", expression="gross_amount"),
                    "yaml_preview": "",
                },
            )()
        ], []

    monkeypatch.setattr("eval.agent_runner.metrics_stage.generate_metrics_from_prompt", fake_generate)
    cases = [MetricCaseView(case_id="m1", request="tổng doanh thu", canonical_context={}, tags=())]
    result = await collect_metrics(ctx, conn_id, cases, await _ecommerce_resolver())

    assert result.candidates["m1"].metric is not None
    assert result.candidates["m1"].error_code is None
    assert result.metric_ids["m1"] > 0


async def test_collect_metrics_candidate_reports_persisted_definition(enriched, monkeypatch):
    """Candidate must mirror the persisted (resolved) definition, not the LLM draft.

    The resolver auto-attaches the ``is_test_order`` hygiene filter at save time
    (metric_hygiene); compiled SQL already carries it, so the reported candidate
    must carry it too — otherwise filter scoring measures the draft, not the system.
    """
    ctx, conn_id, _raw = enriched

    async def fake_generate(prompt, dialect, schema_dict=None, **kwargs):
        return [_suggestion(_definition("m_hygiene", expression="gross_amount"))], []

    monkeypatch.setattr("eval.agent_runner.metrics_stage.generate_metrics_from_prompt", fake_generate)
    cases = [MetricCaseView(case_id="m1", request="tổng doanh thu", canonical_context={}, tags=())]
    result = await collect_metrics(ctx, conn_id, cases, await _ecommerce_resolver())

    metric = result.candidates["m1"].metric
    assert metric is not None
    conditions = [item.condition for item in metric.default_filters]
    # SQL boolean literals render uppercase (golden convention); the comparison
    # side canonicalizes booleans to 0/1 anyway.
    assert "is_test_order = FALSE" in conditions


async def test_collect_metrics_generation_failure(enriched, monkeypatch):
    ctx, conn_id, _raw = enriched

    async def failing_generate(prompt, dialect, **kwargs):
        raise ValueError("no metrics generated")

    monkeypatch.setattr("eval.agent_runner.metrics_stage.generate_metrics_from_prompt", failing_generate)
    cases = [MetricCaseView(case_id="m2", request="không rõ", canonical_context={}, tags=())]
    result = await collect_metrics(ctx, conn_id, cases, await _ecommerce_resolver())
    assert result.candidates["m2"].metric is None
    assert result.candidates["m2"].error_code == "AGENT_GENERATION_FAILED"
    assert "m2" not in result.metric_ids


async def test_collect_metrics_case_crash_isolated_and_accumulates(enriched, monkeypatch):
    """Real create_metric crash (unknown column) must not kill the run."""
    ctx, conn_id, _raw = enriched
    seen_existing: list[list[dict]] = []

    async def fake_generate(prompt, dialect, schema_dict=None, **kwargs):
        seen_existing.append(list(kwargs.get("existing_metrics")))  # snapshot at call time
        if prompt == "bad":
            return [_suggestion(_definition("m1", expression="nonexistent_column"))], []
        return [_suggestion(_definition("m2", expression="gross_amount"))], []

    monkeypatch.setattr("eval.agent_runner.metrics_stage.generate_metrics_from_prompt", fake_generate)
    cases = [
        MetricCaseView(case_id="m1", request="bad", canonical_context={}, tags=()),
        MetricCaseView(case_id="m2", request="doanh thu", canonical_context={}, tags=()),
    ]
    result = await collect_metrics(ctx, conn_id, cases, await _ecommerce_resolver())

    assert result.candidates["m1"].error_code == "AGENT_UNEXPECTED_ERROR"
    assert "m1" not in result.metric_ids
    assert result.candidates["m2"].error_code is None
    assert result.metric_ids["m2"] > 0
    assert seen_existing[0] == []  # first case starts with an empty dedupe context
    assert seen_existing[1] == []  # crashed case must contribute nothing
    allowed = result.candidates["m2"].metric.allowed_dimensions
    assert "order.order_status" in allowed
    assert all("." in dimension for dimension in allowed)
