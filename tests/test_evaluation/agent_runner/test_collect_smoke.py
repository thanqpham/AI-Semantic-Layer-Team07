"""End-to-end collect + evaluate without LLM (replay + monkeypatches)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from eval.agent_runner import (
    AgentCandidates,
    ProductionGuardrailAdapter,
    collect_candidates,
    prepare_run,
    write_candidates,
    write_resolver_diagnostics,
)
from eval.agent_runner.resolver import ResolverAttempt, ResolverTrace
from eval.dataset.loader import DomainDataset, load_domain_dataset
from eval.evaluator.hybrid import run_hybrid_evaluation
from eval.evaluator.hybrid.runner import HybridRunRequest
from eval.evaluator.schemas import CandidateGuardrailOutput, EvaluationConfig
from eval.run_eval import _contract_gap_fields

GOLDEN_ROOT = Path("eval/golden_dataset")


def _synthetic_dataset() -> DomainDataset:
    """Minimal in-memory dataset for canonical->physical translation tests."""
    from eval.dataset.models import (
        CanonicalDimensionDefinition,
        CanonicalEntityDefinition,
        DomainManifest,
        ManifestCaseFiles,
    )

    return DomainDataset(
        domain_dir=Path("synthetic"),
        manifest=DomainManifest(
            dataset_version="1.0.0",
            contract_version="1.0.0",
            domain="synthetic",
            supported_dialects=["sqlite"],
            frozen_evaluation_date=datetime(2026, 1, 1, tzinfo=UTC),
            ground_truth_source="synthetic",
            ground_truth_metric_count=1,
            case_files=ManifestCaseFiles(discovery="d", metric_definition="m", query="q", guardrail="g"),
        ),
        canonical_entities={
            "order": CanonicalEntityDefinition(
                entity="order",
                table_mapping="fact_orders",
                business_name="Don hang",
                dimensions=[
                    CanonicalDimensionDefinition(name="channel", business_name="Kenh", type="string", field="channel"),
                    CanonicalDimensionDefinition(
                        name="placement_date",
                        business_name="Ngay dat",
                        type="time",
                        field="order_date",
                    ),
                ],
                relationships=[],
            )
        },
        discovery_cases=[],
        metric_cases=[],
        query_cases=[],
        guardrail_cases=[],
        raw_schemas={},
        canonical_metrics={},
        expected_query_results={},
    )


def _patch_pipeline(monkeypatch):
    """Intercept LLM boundaries with deterministic fakes (no network)."""
    from tests.test_evaluation.agent_runner.conftest import slugify
    from tests.test_evaluation.agent_runner.metrics_stage_test_helper import (
        make_definition,
    )

    async def fake_generate(prompt, dialect, schema_dict=None, **kwargs):
        class Suggestion:
            definition = make_definition(f"m_{slugify(prompt)}")
            yaml_preview = ""

        return [Suggestion()], []

    async def fake_resolve(question, catalog, llm=None):
        first = catalog.metrics[0].name if catalog.metrics else ""
        from eval.agent_runner.resolver import ResolverSelection

        return ResolverSelection(metric_names=(first,), dimensions=(), filters=(), limit=100)

    monkeypatch.setattr("eval.agent_runner.metrics_stage.generate_metrics_from_prompt", fake_generate)
    monkeypatch.setattr("eval.agent_runner.query_stage.resolve_question", fake_resolve)


async def test_collect_and_evaluate_smoke(tmp_path, monkeypatch):
    ctx = await prepare_run(GOLDEN_ROOT, "ecommerce", tmp_path / "run")
    dataset = await load_domain_dataset(GOLDEN_ROOT, "ecommerce")
    _patch_pipeline(monkeypatch)

    from eval.agent_runner.discovery import introspect_target
    from tests.test_evaluation.agent_runner.conftest import _fake_enrichment

    raw = await introspect_target(ctx)
    candidates = await collect_candidates(
        ctx,
        dataset,
        query_mode="resolver",
        enrichment_override=_fake_enrichment(raw),
    )

    assert isinstance(candidates, AgentCandidates)
    assert len(candidates.discovery) == 4
    assert len(candidates.enrichment) == 4
    assert len(candidates.metrics) == 21
    assert len(candidates.compiler) == 39
    assert candidates.manifest["candidate_source"] == "agent_live"
    assert candidates.manifest["query_mode"] == "resolver"
    gaps = candidates.manifest["contract_gaps"]["metric"]
    assert "business_formula" in gaps and "default_time_grain" in gaps

    path = write_candidates(ctx.run_dir, candidates)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload["metrics"]) == set(candidates.metrics)
    assert set(payload["compiler"]) == set(candidates.compiler)
    assert set(payload["guardrail"]) == set(candidates.guardrail)
    assert payload["manifest"]["contract_gaps"]["metric"] == gaps

    config = EvaluationConfig()
    request = HybridRunRequest(
        dataset=dataset,
        config=config,
        discovery=candidates.discovery,
        enrichment=candidates.enrichment,
        metrics=candidates.metrics,
        compiler=candidates.compiler,
        guardrail=candidates.guardrail,
        guardrail_adapter=ProductionGuardrailAdapter(config),
        judge_runner=None,
        run_id="smoke-test",
        run_type="smoke",
        candidate_source="agent_live",
        profile="pipeline",
        contract_gap_fields=_contract_gap_fields(),
    )
    result = await run_hybrid_evaluation(request)

    # Falsifiable end-to-end assertions (final review I1): the guardrail lane
    # must be wired from collection into the engine's scored guardrail suite.
    golden_guardrail_ids = {case.case_id for case in dataset.guardrail_cases}
    assert golden_guardrail_ids
    assert set(candidates.guardrail) == golden_guardrail_ids
    gates = {gate.name: gate.passed for gate in result.quality_gates}
    assert gates["security_negative_guardrails"] is True
    # Secondary, honest: the status is one of the four contract statuses.
    assert result.status in {"PASS", "WARN", "FAIL", "INCOMPLETE"}


async def test_collect_guardrails_covers_golden_cases_and_round_trips(tmp_path):
    """Guardrail collection is pure (no LLM, no DB), covers every golden probe, persists."""
    from eval.agent_runner.collect import collect_guardrails
    from eval.agent_runner.golden_view import iter_guardrail_cases

    dataset = await load_domain_dataset(GOLDEN_ROOT, "ecommerce")
    probes = iter_guardrail_cases(dataset)
    assert len(probes) == len(dataset.guardrail_cases)
    assert not any(hasattr(probe, "expected") for probe in probes)

    guardrail = await collect_guardrails(probes)
    assert set(guardrail) == {probe.case_id for probe in probes}
    assert all(isinstance(item, CandidateGuardrailOutput) for item in guardrail.values())

    path = write_candidates(tmp_path, AgentCandidates(guardrail=guardrail))
    payload = json.loads(path.read_text(encoding="utf-8"))
    restored = {case_id: CandidateGuardrailOutput(**item) for case_id, item in payload["guardrail"].items()}
    assert restored == guardrail


async def test_collect_candidates_oracle_mode(tmp_path, monkeypatch):
    """Oracle mode: expected names map to persisted ids; error cases miss input."""
    ctx = await prepare_run(GOLDEN_ROOT, "ecommerce", tmp_path / "run")
    dataset = await load_domain_dataset(GOLDEN_ROOT, "ecommerce")
    _patch_pipeline(monkeypatch)

    from eval.agent_runner.discovery import introspect_target
    from tests.test_evaluation.agent_runner.conftest import _fake_enrichment

    raw = await introspect_target(ctx)
    candidates = await collect_candidates(
        ctx,
        dataset,
        query_mode="oracle",
        enrichment_override=_fake_enrichment(raw),
    )
    assert candidates.manifest["query_mode"] == "oracle"
    assert len(candidates.compiler) == 39
    for case in dataset.query_cases:
        if case.expected_error is None:
            continue
        got = candidates.compiler[case.case_id].error_code
        assert got != "ORACLE_INPUT_MISSING", case.case_id
    codes = [item.error_code for item in candidates.compiler.values() if item.error_code]
    assert "UNKNOWN_DIMENSION" not in codes  # canonical->physical gap is closed
    with_sql = [item for item in candidates.compiler.values() if item.sql]
    assert with_sql, "oracle mode must compile at least the dimension-free queries"


def test_physical_dimension_translates_canonical_to_physical():
    """Translation uses table_mapping plus the dimension's own field, never names."""
    from eval.agent_runner.collect import _physical_dimension

    dataset = _synthetic_dataset()
    assert _physical_dimension(dataset, "order.channel") == "fact_orders.channel"
    # YAML contract permits name != field: the physical column is field, not name.
    assert _physical_dimension(dataset, "order.placement_date") == "fact_orders.order_date"
    assert _physical_dimension(dataset, "warehouse.aisle") is None
    assert _physical_dimension(dataset, "order.nonexistent") is None


def test_resolver_operator_map_covers_canonical_operators():
    """Every shared canonical operator maps to a resolver word; 'like' does not."""
    from eval.agent_runner.collect import _RESOLVER_OPERATORS
    from eval.agent_runner.resolver import ALLOWED_OPERATORS

    assert _RESOLVER_OPERATORS == {
        "=": "eq",
        "!=": "neq",
        ">": "gt",
        ">=": "gte",
        "<": "lt",
        "<=": "lte",
        "in": "in",
        "not_in": "not_in",
    }
    assert "like" not in _RESOLVER_OPERATORS
    assert all(word in ALLOWED_OPERATORS for word in _RESOLVER_OPERATORS.values())


def test_oracle_filters_translate_dimensions_and_operators():
    """Filters get physical dimensions and resolver operators; unmappable -> None."""
    from eval.agent_runner.collect import _oracle_filters
    from eval.agent_runner.resolver import ALLOWED_OPERATORS
    from eval.dataset.models import WhereConditionExpectation

    dataset = _synthetic_dataset()
    filters = _oracle_filters(
        dataset,
        [
            WhereConditionExpectation(dimension="order.channel", operator="=", value="web"),
            WhereConditionExpectation(dimension="order.channel", operator="like", value="%x%"),
        ],
    )
    assert filters is not None
    assert filters[0].dimension == "fact_orders.channel"
    assert filters[0].operator == "eq"
    assert filters[0].value == "web"
    assert filters[1].operator == "like"  # passes through verbatim...
    assert "like" not in ALLOWED_OPERATORS  # ...and fails closed downstream
    unknown = _oracle_filters(
        dataset,
        [WhereConditionExpectation(dimension="ghost.col", operator="=", value=1)],
    )
    assert unknown is None


def _failed_trace(question: str) -> ResolverTrace:
    """One trace whose single attempt was rejected as invalid output."""
    trace = ResolverTrace(question=question, catalog_size={"metrics": 2, "dimensions": 1, "relationships": 0})
    trace.attempts.append(
        ResolverAttempt(raw_output="not json", error_code="RESOLVER_INVALID_OUTPUT", error_message="JSON parse failed")
    )
    trace.outcome = "RESOLVER_INVALID_OUTPUT"
    return trace


def test_write_resolver_diagnostics_round_trip(tmp_path):
    candidates = AgentCandidates(resolver_diagnostics={"ecommerce_query_002": _failed_trace("?")}, query_cases_total=3)
    path = write_resolver_diagnostics(tmp_path, candidates)
    assert path == tmp_path / "resolver-diagnostics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["summary"] == {
        "query_cases_total": 3,
        "cases_with_failed_attempts": 1,
        "outcomes": {"RESOLVER_INVALID_OUTPUT": 1},
    }
    case = payload["cases"]["ecommerce_query_002"]
    assert case["question"] == "?"
    assert case["catalog_size"] == {"metrics": 2, "dimensions": 1, "relationships": 0}
    assert case["attempts"][0]["raw_output"] == "not json"
    assert case["outcome"] == "RESOLVER_INVALID_OUTPUT"


def test_write_resolver_diagnostics_empty_writes_nothing(tmp_path):
    assert write_resolver_diagnostics(tmp_path, AgentCandidates()) is None
    assert not (tmp_path / "resolver-diagnostics.json").exists()
