"""Query collector: resolver mode happy path, resolver error, oracle mode."""

from pathlib import Path

import pytest

from eval.agent_runner.adapters import to_compiler_candidate
from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.agent_runner.golden_view import MetricCaseView, QueryCaseView
from eval.agent_runner.metrics_stage import collect_metrics
from eval.agent_runner.query_stage import OracleInput, collect_queries
from eval.agent_runner.resolver import (
    CatalogMetric,
    ResolverCatalog,
    ResolverError,
    ResolverFilter,
    ResolverSelection,
)
from eval.dataset.loader import load_domain_dataset
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.services.query_compiler import CompiledQuery
from tests.test_evaluation.agent_runner.metrics_stage_test_helper import make_definition


@pytest.fixture
async def approved_metric(enriched, monkeypatch):
    """Create + approve one real metric via monkeypatched generation."""
    ctx, conn_id, _raw = enriched

    async def fake_generate(prompt, dialect, schema_dict=None, **kwargs):
        class Suggestion:
            definition = make_definition("m_doanh_thu")
            yaml_preview = ""

        return [Suggestion()], []

    monkeypatch.setattr("eval.agent_runner.metrics_stage.generate_metrics_from_prompt", fake_generate)
    dataset = await load_domain_dataset(Path("eval/golden_dataset"), "ecommerce")
    resolver = CanonicalResolver.from_dataset(dataset, {})
    result = await collect_metrics(ctx, conn_id, [MetricCaseView("mc1", "tổng doanh thu", {}, ())], resolver)
    return ctx, conn_id, result.metric_ids["mc1"]


def _fake_selection():
    return ResolverSelection(
        metric_names=("m_doanh_thu",),
        dimensions=(),
        filters=(),
        limit=100,
    )


def _fake_catalog():
    return ResolverCatalog(
        metrics=(CatalogMetric("m_doanh_thu", None, "fact_orders", "sum"),),
        dimensions=(),
    )


def _compiler_resolver(metric_id: int) -> CanonicalResolver:
    """Empty-registry resolver: physical names stay raw, only the metric id maps."""
    return CanonicalResolver({}, {metric_id: "m_doanh_thu"})


async def test_collect_queries_resolver_mode_compiles(approved_metric, monkeypatch):
    ctx, conn_id, metric_id = approved_metric

    async def fake_resolve(question, catalog, llm=None):
        return _fake_selection()

    async def fake_catalog(db, conn):
        return _fake_catalog()

    monkeypatch.setattr("eval.agent_runner.query_stage.resolve_question", fake_resolve)
    monkeypatch.setattr("eval.agent_runner.query_stage.build_catalog", fake_catalog)

    cases = [QueryCaseView(case_id="q1", question="doanh thu?", tags=())]
    candidates = await collect_queries(ctx, conn_id, cases, resolver=_compiler_resolver(metric_id))
    candidate = candidates["q1"]
    assert candidate.error_code is None
    assert candidate.sql and candidate.sql.upper().startswith("SELECT")
    assert candidate.canonical_query.primary_entity == "fact_orders"
    assert candidate.canonical_query.metrics == ("m_doanh_thu",)


async def test_collect_queries_resolver_error(approved_metric, monkeypatch):
    ctx, conn_id, _mid = approved_metric

    async def failing_resolve(question, catalog, llm=None):
        raise ResolverError("UNKNOWN_METRIC")

    async def fake_catalog(db, conn):
        return ResolverCatalog((), ())

    monkeypatch.setattr("eval.agent_runner.query_stage.resolve_question", failing_resolve)
    monkeypatch.setattr("eval.agent_runner.query_stage.build_catalog", fake_catalog)

    cases = [QueryCaseView(case_id="q2", question="?", tags=())]
    candidates = await collect_queries(ctx, conn_id, cases, resolver=_compiler_resolver(_mid))
    assert candidates["q2"].error_code == "UNKNOWN_METRIC"
    assert candidates["q2"].sql is None


async def test_collect_queries_oracle_mode(approved_metric):
    ctx, conn_id, metric_id = approved_metric
    cases = [QueryCaseView(case_id="q3", question="doanh thu?", tags=())]
    oracle = {"q3": OracleInput(metric_ids=(metric_id,), dimensions=(), filters=())}
    candidates = await collect_queries(
        ctx, conn_id, cases, mode="oracle", oracle_inputs=oracle, resolver=_compiler_resolver(metric_id)
    )
    assert candidates["q3"].error_code is None
    assert "SUM" in candidates["q3"].sql.upper()


async def test_collect_queries_oracle_input_missing(approved_metric):
    ctx, conn_id, _mid = approved_metric
    cases = [QueryCaseView(case_id="q4", question="doanh thu?", tags=())]
    candidates = await collect_queries(ctx, conn_id, cases, mode="oracle", resolver=_compiler_resolver(_mid))
    assert candidates["q4"].error_code == "ORACLE_INPUT_MISSING"


async def test_collect_queries_oracle_unknown_metric_id(approved_metric):
    ctx, conn_id, _mid = approved_metric
    cases = [QueryCaseView(case_id="q5", question="doanh thu?", tags=())]
    oracle = {"q5": OracleInput(metric_ids=(999999,), dimensions=(), filters=())}
    candidates = await collect_queries(
        ctx, conn_id, cases, mode="oracle", oracle_inputs=oracle, resolver=_compiler_resolver(_mid)
    )
    assert candidates["q5"].error_code == "UNKNOWN_REFERENCE"


async def test_collect_queries_unknown_metric_name(approved_metric, monkeypatch):
    ctx, conn_id, _mid = approved_metric

    async def fake_resolve(question, catalog, llm=None):
        return ResolverSelection(metric_names=("khong_ton_tai",), dimensions=(), filters=(), limit=100)

    async def fake_catalog(db, conn):
        return _fake_catalog()

    monkeypatch.setattr("eval.agent_runner.query_stage.resolve_question", fake_resolve)
    monkeypatch.setattr("eval.agent_runner.query_stage.build_catalog", fake_catalog)

    cases = [QueryCaseView(case_id="q6", question="?", tags=())]
    candidates = await collect_queries(ctx, conn_id, cases, resolver=_compiler_resolver(_mid))
    assert candidates["q6"].error_code == "UNKNOWN_METRIC"


async def test_collect_queries_resolver_dimension_filter_join(approved_metric, monkeypatch):
    """Dimension + filter + join path land in SQL and the canonical query."""
    ctx, conn_id, metric_id = approved_metric

    async def fake_resolve(question, catalog, llm=None):
        return ResolverSelection(
            metric_names=("m_doanh_thu",),
            dimensions=("customers.city",),
            filters=(ResolverFilter("fact_orders.order_status", "eq", "completed"),),
            limit=50,
        )

    async def fake_catalog(db, conn):
        return _fake_catalog()

    monkeypatch.setattr("eval.agent_runner.query_stage.resolve_question", fake_resolve)
    monkeypatch.setattr("eval.agent_runner.query_stage.build_catalog", fake_catalog)

    cases = [QueryCaseView(case_id="q7", question="doanh thu theo thành phố?", tags=())]
    candidates = await collect_queries(ctx, conn_id, cases, resolver=_compiler_resolver(metric_id))
    candidate = candidates["q7"]
    assert candidate.error_code is None
    assert "WHERE" in candidate.sql.upper()
    assert "GROUP BY" in candidate.sql.upper()
    assert "LIMIT 50" in candidate.sql.upper()
    canonical = candidate.canonical_query
    assert canonical.dimensions == ("customers.city",)
    assert canonical.where_conditions[0].dimension == "fact_orders.order_status"
    assert canonical.where_conditions[0].operator == "="
    assert canonical.where_conditions[0].value == "completed"
    assert canonical.entities_in_path == ("fact_orders", "customers")


def test_to_compiler_candidate_maps_metadata():
    """Pure adapter: compiled metadata + spec map onto the candidate contract."""
    compiled = CompiledQuery(
        sql="SELECT 1",
        parameters={},
        metadata={
            "base_entity": "fact_orders",
            "metrics": {"metric_7": "m_doanh_thu"},
            "dimensions": {},
            "relationship_ids": [11],
        },
    )
    spec = SemanticQuerySpec(
        metric_ids=[7],
        dimensions=[DimensionSelection(column_id=3, time_grain=None)],
        filters=[SemanticQueryFilter(column_id=4, operator="is_null", value=None)],
        limit=10,
    )
    candidate = to_compiler_candidate(
        compiled,
        spec=spec,
        dimension_names=["customers.city"],
        filter_names=["fact_orders.deleted_at"],
        relationship_entities=("fact_orders", "customers"),
        resolver=_compiler_resolver(7),
    )
    canonical = candidate.canonical_query
    assert candidate.sql == "SELECT 1"
    assert candidate.error_code is None
    assert canonical.primary_entity == "fact_orders"
    assert canonical.metrics == ("m_doanh_thu",)
    assert canonical.dimensions == ("customers.city",)
    assert canonical.entities_in_path == ("fact_orders", "customers")
    assert canonical.intent == ""
    assert canonical.domain == ""
    assert canonical.time_filters == ()
    # is_null has no representation in the frozen candidate contract (v1).
    assert canonical.where_conditions == ()


def _engine_shaped_compiled() -> CompiledQuery:
    """Compiled SQL shaped like the real compiler's output (schema qualifier + binds)."""
    return CompiledQuery(
        sql=(
            'SELECT "fact_orders"."status" AS "dimension_4"\n'
            'FROM "__default__"."fact_orders"\n'
            'WHERE "fact_orders"."is_test_order" = :runtime_0\n'
            '  AND "fact_orders"."status" IN (:runtime_1, :runtime_2)\n'
            "LIMIT 100"
        ),
        parameters={"runtime_0": False, "runtime_1": "completed", "runtime_2": "new'order"},
        metadata={"base_entity": "fact_orders", "metrics": {"metric_7": "m_doanh_thu"}, "dimensions": {}},
    )


def test_to_compiler_candidate_normalizes_sql_for_engine():
    """Adapter strips the namespace placeholder and inlines bind parameters."""
    spec = SemanticQuerySpec(metric_ids=[7], dimensions=[], filters=[], limit=100)
    candidate = to_compiler_candidate(
        _engine_shaped_compiled(), spec=spec, dimension_names=[], filter_names=[], resolver=_compiler_resolver(7)
    )
    assert '"__default__".' not in candidate.sql
    assert ":runtime_" not in candidate.sql
    assert 'FROM "fact_orders"' in candidate.sql
    assert '"is_test_order" = FALSE' in candidate.sql
    assert "IN ('completed', 'new''order')" in candidate.sql


def test_normalized_sql_executes_on_schema_less_sqlite():
    """The normalized SQL must run on a schema-less SQLite like the engine fixture."""
    import sqlite3

    spec = SemanticQuerySpec(metric_ids=[7], dimensions=[], filters=[], limit=100)
    candidate = to_compiler_candidate(
        _engine_shaped_compiled(), spec=spec, dimension_names=[], filter_names=[], resolver=_compiler_resolver(7)
    )
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute('CREATE TABLE fact_orders ("status" TEXT, "is_test_order" BOOLEAN)')
        connection.execute("INSERT INTO fact_orders VALUES ('completed', 0)")
        rows = connection.execute(candidate.sql).fetchall()
        assert rows == [("completed",)]
    finally:
        connection.close()


def test_sql_literal_renders_bound_value_kinds():
    """Literal rendering covers every value kind the compiler's bind map holds."""
    from datetime import date, datetime

    from eval.agent_runner.adapters import _sql_literal

    assert _sql_literal(date(2024, 1, 2)) == "'2024-01-02'"
    assert _sql_literal(datetime(2024, 1, 2, 3, 4, 5)) == "'2024-01-02 03:04:05'"
    assert _sql_literal(3.5) == "3.5"
    assert _sql_literal(None) == "NULL"
    assert _sql_literal(("a", 1)) == "('a', 1)"


async def test_to_compiler_candidate_registry_backed_canonical_outcomes():
    """Real golden registry: canonical entity/dimensions/metric AND re-aliased columns."""
    dataset = await load_domain_dataset(Path("eval/golden_dataset"), "ecommerce")
    resolver = CanonicalResolver.from_dataset(dataset, {"ecommerce_metric_001": 7})
    compiled = CompiledQuery(
        sql=(
            'SELECT "fact_orders"."channel" AS "dimension_4",\n'
            '  SUM("fact_orders"."gross_amount") AS "metric_7"\n'
            'FROM "__default__"."fact_orders"\nLIMIT 100'
        ),
        parameters={},
        metadata={"base_entity": "fact_orders", "metrics": {"metric_7": "x"}, "dimensions": {}},
    )
    spec = SemanticQuerySpec(metric_ids=[7], dimensions=[DimensionSelection(column_id=4)], filters=[], limit=100)
    candidate = to_compiler_candidate(
        compiled, spec=spec, dimension_names=["fact_orders.channel"], filter_names=[], resolver=resolver
    )
    canonical = candidate.canonical_query
    assert canonical.primary_entity == "order"
    assert canonical.dimensions == ("order.channel",)
    assert canonical.metrics == ("net_revenue",)
    assert 'AS "net_revenue"' in candidate.sql
    assert 'AS "channel"' in candidate.sql and "dimension_4" not in candidate.sql
