"""Re-aliasing compiled SQL output columns to canonical metric names."""

from eval.agent_runner.adapters import _re_alias_output_columns, to_compiler_candidate
from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.dataset.models import CanonicalDimensionDefinition, CanonicalEntityDefinition
from src.models.schemas import DimensionSelection, SemanticQuerySpec
from src.services.query_compiler import CompiledQuery


def test_re_alias_renames_metric_projection():
    sql = 'SELECT\n  SUM(("t"."a" - "t"."b")) AS "metric_1"\nFROM "t"\nLIMIT 100'
    result = _re_alias_output_columns(sql, {"metric_1": "net_revenue"})
    assert '"net_revenue"' in result
    assert "metric_1" not in result


def test_re_alias_leaves_other_aliases_alone():
    sql = 'SELECT COUNT(*) AS "cnt" FROM "t"'
    assert _re_alias_output_columns(sql, {"metric_1": "net_revenue"}) == sql.replace('"cnt"', '"cnt"')


def test_re_alias_unparseable_sql_returned_verbatim():
    sql = "SELECT FROM WHERE"
    assert _re_alias_output_columns(sql, {"metric_1": "net_revenue"}) == sql


def test_re_alias_empty_map_is_identity():
    sql = 'SELECT 1 AS "metric_1"'
    assert _re_alias_output_columns(sql, {}) == sql


def _registry_resolver() -> CanonicalResolver:
    """Two-entity registry: physical fact_orders/customers -> canonical order/customer."""
    return CanonicalResolver(
        entities={
            "order": CanonicalEntityDefinition(
                entity="order",
                table_mapping="fact_orders",
                business_name="order",
                dimensions=[
                    CanonicalDimensionDefinition(
                        name="channel", business_name="channel", type="string", field="channel"
                    )
                ],
                relationships=[],
            ),
            "customer": CanonicalEntityDefinition(
                entity="customer",
                table_mapping="customers",
                business_name="customer",
                dimensions=[
                    CanonicalDimensionDefinition(name="city", business_name="city", type="string", field="city")
                ],
                relationships=[],
            ),
        },
        metric_names_by_id={7: "net_revenue"},
    )


def _dimensional_compiled() -> CompiledQuery:
    return CompiledQuery(
        sql=(
            'SELECT "fact_orders"."channel" AS "dimension_4",\n'
            '  "customers"."city" AS "dimension_9",\n'
            '  SUM("fact_orders"."gross_amount") AS "metric_7"\n'
            'FROM "__default__"."fact_orders"\nLIMIT 100'
        ),
        parameters={},
        metadata={"base_entity": "fact_orders", "metrics": {"metric_7": "x"}, "dimensions": {}},
    )


def _dimensional_spec(time_grain: str | None = None) -> SemanticQuerySpec:
    return SemanticQuerySpec(
        metric_ids=[7],
        dimensions=[DimensionSelection(column_id=4, time_grain=time_grain), DimensionSelection(column_id=9)],
        filters=[],
        limit=100,
    )


def test_to_compiler_candidate_re_aliases_dimension_columns():
    """dimension_<id> projections re-alias to bare canonical names (golden columns)."""
    candidate = to_compiler_candidate(
        _dimensional_compiled(),
        spec=_dimensional_spec(),
        dimension_names=["fact_orders.channel", "customers.city"],
        filter_names=[],
        resolver=_registry_resolver(),
    )
    assert 'AS "channel"' in candidate.sql and "dimension_4" not in candidate.sql
    assert 'AS "city"' in candidate.sql and "dimension_9" not in candidate.sql
    assert candidate.canonical_query.dimensions == ("order.channel", "customer.city")


def test_to_compiler_candidate_time_grain_dimension_aliases_by_grain():
    """Time-grain projections follow the golden convention: alias equals the grain."""
    compiled = CompiledQuery(
        sql=(
            'SELECT strftime(\'%Y-%m\', "fact_orders"."order_date") AS "dimension_4",\n'
            '  SUM("fact_orders"."gross_amount") AS "metric_7"\n'
            'FROM "fact_orders"\nLIMIT 100'
        ),
        parameters={},
        metadata={"base_entity": "fact_orders"},
    )
    spec = SemanticQuerySpec(
        metric_ids=[7], dimensions=[DimensionSelection(column_id=4, time_grain="month")], filters=[], limit=100
    )
    candidate = to_compiler_candidate(
        compiled, spec=spec, dimension_names=["fact_orders.order_date"], filter_names=[], resolver=_registry_resolver()
    )
    assert 'AS "month"' in candidate.sql and "dimension_4" not in candidate.sql


def test_to_compiler_candidate_dimension_alias_falls_back_to_raw_field():
    """Unmapped physical columns keep their raw field name (fail-open-to-mismatch)."""
    candidate = to_compiler_candidate(
        _dimensional_compiled(),
        spec=_dimensional_spec(),
        dimension_names=["fact_orders.unknown_col", "customers.city"],
        filter_names=[],
        resolver=_registry_resolver(),
    )
    assert 'AS "unknown_col"' in candidate.sql
