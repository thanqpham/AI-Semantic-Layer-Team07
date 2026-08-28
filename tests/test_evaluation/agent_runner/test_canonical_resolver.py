"""CanonicalResolver: exact registry/provenance mapping with audit logs."""

from types import SimpleNamespace

from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.dataset.models import CanonicalDimensionDefinition, CanonicalEntityDefinition


def _entity(name: str, table: str, dims: dict[str, str]) -> CanonicalEntityDefinition:
    """Build one canonical entity with name->field dimension mappings."""
    return CanonicalEntityDefinition(
        entity=name,
        table_mapping=table,
        business_name=name,
        dimensions=[
            CanonicalDimensionDefinition(name=dim, business_name=dim, type="string", field=field)
            for dim, field in dims.items()
        ],
        relationships=[],
    )


def _resolver() -> CanonicalResolver:
    """Build a resolver over a miniature registry (order + customer)."""
    return CanonicalResolver(
        entities={
            "order": _entity("order", "fact_orders", {"order_status": "order_status", "order_flag": "is_test_order"}),
            "customer": _entity("customer", "customers", {"city": "city"}),
        },
        metric_names_by_id={7: "net_revenue"},
    )


def test_resolve_entity_maps_physical_to_canonical():
    assert _resolver().resolve_entity("fact_orders") == "order"


def test_resolve_entity_unknown_stays_raw_and_logs_unresolved():
    resolver = _resolver()
    assert resolver.resolve_entity("dim_stores") == "dim_stores"
    assert {"kind": "entity", "value": "dim_stores"} in [
        {"kind": item["kind"], "value": item["value"]} for item in resolver.unresolved
    ]


def test_resolve_entity_collision_keeps_raw():
    resolver = CanonicalResolver(
        entities={"a": _entity("a", "same_table", {}), "b": _entity("b", "same_table", {})},
        metric_names_by_id={},
    )
    assert resolver.resolve_entity("same_table") == "same_table"


def test_resolve_column_maps_field_to_canonical_name():
    assert _resolver().resolve_column("fact_orders", "is_test_order") == "order_flag"


def test_resolve_dimension_maps_dotted():
    assert _resolver().resolve_dimension("fact_orders.is_test_order") == "order.order_flag"


def test_resolve_dimension_without_dot_stays_raw():
    assert _resolver().resolve_dimension("not_dotted") == "not_dotted"


def test_resolve_metric_id_uses_provenance():
    resolver = _resolver()
    assert resolver.resolve_metric_id(7) == "net_revenue"
    assert {"kind": "metric", "from": "metric_7", "to": "net_revenue"} in [dict(item) for item in resolver.resolutions]


def test_resolve_metric_id_unknown_falls_back():
    assert _resolver().resolve_metric_id(99) == "metric_99"


def test_from_dataset_builds_metric_provenance():
    dataset = SimpleNamespace(
        canonical_entities={"order": _entity("order", "fact_orders", {})},
        metric_cases=[
            SimpleNamespace(case_id="ecommerce_metric_001", expected_metric=SimpleNamespace(name="net_revenue"))
        ],
    )
    resolver = CanonicalResolver.from_dataset(dataset, {"ecommerce_metric_001": 7})
    assert resolver.resolve_metric_id(7) == "net_revenue"
    assert resolver.resolve_entity("fact_orders") == "order"
