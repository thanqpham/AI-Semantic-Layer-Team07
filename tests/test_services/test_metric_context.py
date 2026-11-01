"""Regression tests for relationship-complete Metric AI context."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.services.metric_context import (
    _DATA_SCOPE_PROMPT,
    _SCOPE_PROMPT,
    _expand_context,
    _select_tables,
    _temporal_context,
    _token_estimate,
)
from tests.metric_review_helpers import scope_mock


@pytest.mark.asyncio
async def test_data_scope_clarification_preserves_selectable_options() -> None:
    """Data questions can still ask users to narrow an unclear domain."""
    payload = {
        "needs_clarification": True,
        "question": "Bạn muốn xem bảng nào?",
        "options": ["Bảng đơn hàng", "Bảng khách hàng"],
    }
    with (
        patch("src.services.metric_context.get_llm"),
        patch("src.services.metric_context.ainvoke_json", new=AsyncMock(return_value=payload)),
    ):
        _, diagnostic = await _select_tables(
            "Tìm thông tin", [], [_table("order_header"), _table("customer")], None, _DATA_SCOPE_PROMPT
        )
    assert [item["label"] for item in diagnostic["clarification"]["options"]] == payload["options"]
    assert all(item.get("action") is None for item in diagnostic["clarification"]["options"])


@pytest.mark.asyncio
async def test_metric_scope_uses_selected_table_without_asking_for_price_column() -> None:
    payload = {
        "table_names": ["order_header"],
        "needs_clarification": True,
        "question": "Chọn price_after_tax hay price_after_discount?",
        "options": ["price_after_tax", "price_after_discount"],
    }
    model = scope_mock(payload)
    with patch("src.services.metric_context.invoke_metric_json", new=model):
        selected, diagnostic = await _select_tables(
            "Tính giá trị trung bình mỗi đơn", [], [_table("order_header")], None
        )
    assert selected == {"order_header"}
    assert diagnostic is None
    prompt = model.call_args.args[1]
    assert "Không hỏi người dùng chọn cột giá" in prompt
    assert "Ví dụ hỏi AOV theo giá nào" not in prompt


@pytest.mark.parametrize("options", [None, "price", [None, {}, "  "]])
def test_scope_clarification_ignores_invalid_options(options) -> None:
    """Malformed model choices leave a usable free-text question without crashing."""
    from src.services.metric_context import _clarification

    result = _clarification("Chọn giá nào?", options)
    assert result.diagnostic["clarification"]["options"] == []


def _column(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        column_name=name,
        data_type="INTEGER",
        business_name=name,
        description="",
        is_primary_key=name == "id",
        is_nullable=False,
        allowed_values=None,
        review_status="approved",
        is_foreign_key=name.endswith("_id") and name != "id",
        fk_target_table=None,
        fk_target_column=None,
    )


def _table(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=1, table_name=name, business_name=name, description="", columns=[_column("id")], review_status="approved"
    )


def test_context_keeps_late_business_tables_and_relationships() -> None:
    """A context must retain order tables regardless of their original JSON position."""
    tables = [_table(f"lookup_{index}") for index in range(30)] + [_table("order_header"), _table("order_line")]
    relation = SimpleNamespace(
        from_entity=tables[-1],
        to_entity=tables[-2],
        join_condition="order_line.order_id = order_header.id",
        relationship_type="many_to_one",
    )

    context = _expand_context(tables, [relation], {"order_header", "order_line"})

    assert {table["table_name"] for table in context["tables"]} == {"order_header", "order_line"}
    assert context["relationships"][0]["join_condition"] == "order_line.order_id = order_header.id"


def test_context_does_not_expand_unrelated_direct_neighbors() -> None:
    """A table-only question keeps all its columns without adding joined tables."""
    order_header, customer = _table("order_header"), _table("customer")
    relation = SimpleNamespace(
        from_entity=order_header,
        to_entity=customer,
        join_condition="order_header.customer_id = customer.id",
        relationship_type="many_to_one",
    )

    context = _expand_context([order_header, customer], [relation], {"order_header"})

    assert [table["table_name"] for table in context["tables"]] == ["order_header"]
    assert context["relationships"] == []


def test_token_estimate_has_no_character_truncation_contract() -> None:
    """Budgeting reports a size and never mutates or slices the input payload."""
    payload = {"tables": [{"table_name": f"table_{index}"} for index in range(1000)]}

    assert _token_estimate(payload) > 2000
    assert len(payload["tables"]) == 1000


def test_scope_prompt_formats_its_json_contract() -> None:
    """The JSON example must not be interpreted as a Python format field."""
    prompt = _SCOPE_PROMPT.format(inventory="[]", question="Tính doanh thu theo ngày")

    assert '"table_names"' in prompt
    assert "Tính doanh thu theo ngày" in prompt


def test_temporal_context_lists_fields_across_schema() -> None:
    """Date/time discovery must not be rejected as a broad KPI."""
    order = _table("order_header")
    order.columns.append(SimpleNamespace(**{**_column("completed_time").__dict__, "data_type": "TIMESTAMP"}))
    customer = _table("customer")
    customer.columns.append(SimpleNamespace(**{**_column("birth_date").__dict__, "data_type": "DATE"}))

    result = _temporal_context([order, customer])

    assert result.diagnostic["status"] == "ready"
    assert {item["table_name"] for item in result.schema["tables"]} == {"order_header", "customer"}
    assert result.schema["tables"][0]["columns"][0]["column_name"] == "completed_time"


@pytest.mark.asyncio
async def test_metric_context_adds_approved_bridge_without_unrelated_tables() -> None:
    from src.services.metric_context import build_metric_context

    facts, orders, customers, unrelated = [_table(n) for n in ("facts", "orders", "customers", "unrelated")]
    for index, table in enumerate((facts, orders, customers, unrelated), 1):
        table.id = index

    def relation(source, target, number):
        return SimpleNamespace(
            id=number,
            from_entity=source,
            to_entity=target,
            from_entity_id=source.id,
            to_entity_id=target.id,
            column_pairs=[{"from_column_id": number, "to_column_id": number + 10}],
            join_condition="a = b",
            relationship_type="many_to_one",
        )

    links = [relation(facts, orders, 1), relation(orders, customers, 2)]
    with (
        patch(
            "src.services.metric_context._load_metadata",
            AsyncMock(return_value=([facts, orders, customers, unrelated], links)),
        ),
        patch("src.services.metric_context._select_tables", AsyncMock(return_value=({"facts", "customers"}, None))),
    ):
        result = await build_metric_context(None, 1, "KPI", 10000)
    assert result.diagnostic["status"] == "ready"
    assert {table["table_name"] for table in result.schema["tables"]} == {"facts", "orders", "customers"}
    assert len(result.schema["relationships"]) == 2


@pytest.mark.asyncio
async def test_ambiguous_unqualified_table_name_requests_clarification() -> None:
    tables = [_table("orders"), _table("orders")]
    tables[0].physical_schema, tables[1].physical_schema = "sales", "billing"
    with patch("src.services.metric_context.invoke_metric_json", scope_mock({"table_names": ["orders"]})):
        selected, diagnostic = await _select_tables("orders", [], tables, None)
    assert not selected
    assert diagnostic["status"] == "needs_clarification"


def test_explicit_qualified_scope_excludes_same_named_table_in_other_schema() -> None:
    sales, billing = _table("orders"), _table("orders")
    sales.physical_schema, billing.physical_schema = "sales", "billing"
    assert [t["physical_schema"] for t in _expand_context([sales, billing], [], {"sales.orders"})["tables"]] == [
        "sales"
    ]
    assert _expand_context([sales, billing], [], {"orders"})["tables"] == []


def test_context_excludes_relationship_endpoint_outside_database() -> None:
    local, target, foreign = _table("orders"), _table("customers"), _table("customers")
    local.id, target.id, foreign.id = 1, 2, 3
    link = SimpleNamespace(
        from_entity=local, to_entity=foreign, join_condition="a = b", relationship_type="many_to_one"
    )
    assert _expand_context([local, target], [link], {"orders", "customers"})["relationships"] == []


def test_bridge_reports_alternative_paths_and_ignores_unapproved_tables() -> None:
    from src.services.metric_context_graph import expand_bridges

    tables = [_table(name) for name in ("facts", "orders", "customers", "alternative")]
    for index, table in enumerate(tables, 1):
        table.id = index

    def relation(source, target, number):
        return SimpleNamespace(
            id=number,
            from_entity_id=source.id,
            to_entity_id=target.id,
            column_pairs=[{"from_column_id": number, "to_column_id": number + 10}],
            relationship_type="many_to_one",
        )

    facts, orders, customers, alternative = tables
    links = [
        relation(facts, orders, 1),
        relation(orders, customers, 2),
        relation(facts, alternative, 3),
        relation(alternative, customers, 4),
    ]
    selected, error = expand_bridges(tables, links, {"facts", "customers"})
    assert error is None
    assert selected == {"facts", "orders", "customers", "alternative"}
    alternative.review_status = "pending_review"
    selected, error = expand_bridges(tables, links, {"facts", "customers"})
    assert error is None
    assert selected == {"facts", "orders", "customers"}


def test_discovery_scope_with_unrelated_ambiguous_pair_keeps_bridge() -> None:
    from src.services.metric_context_graph import expand_bridges

    carts, orders, customers, facts = [_table(name) for name in ("carts", "orders", "customers", "order_facts")]
    for index, table in enumerate((carts, orders, customers, facts), 1):
        table.id = index

    def edge(source, target, number):
        return SimpleNamespace(
            id=number,
            from_entity_id=source.id,
            to_entity_id=target.id,
            column_pairs=[{"from_column_id": number, "to_column_id": number + 10}],
            relationship_type="many_to_one",
        )

    links = [edge(carts, customers, 1), edge(carts, orders, 2), edge(orders, customers, 3), edge(facts, orders, 4)]
    selected, error = expand_bridges([carts, orders, customers, facts], links, {"carts", "customers", "order_facts"})
    assert error is None
    assert selected == {"carts", "orders", "customers", "order_facts"}


def test_discovery_includes_common_order_bridge_for_facts_and_shipments() -> None:
    from src.services.metric_context_graph import expand_bridges

    facts, shipments, orders = [_table(name) for name in ("order_facts", "shipments", "orders")]
    for index, table in enumerate((facts, shipments, orders), 1):
        table.id = index
    links = [
        SimpleNamespace(id=i, from_entity_id=source.id, to_entity_id=orders.id,
                        column_pairs=[{"from_column_id": i, "to_column_id": i + 10}],
                        relationship_type="many_to_one")
        for i, source in enumerate((facts, shipments), 1)
    ]
    selected, error = expand_bridges([facts, shipments, orders], links, {"order_facts", "shipments"})
    assert error is None
    assert selected == {"order_facts", "shipments", "orders"}


def test_metric_review_rejects_alternative_path_of_different_length() -> None:
    from src.services.metric_review_validation import _review_join_path

    relations = [
        {"from_table": "carts", "to_table": "customers", "relationship_type": "many_to_one"},
        {"from_table": "carts", "to_table": "orders", "relationship_type": "many_to_one"},
        {"from_table": "orders", "to_table": "customers", "relationship_type": "many_to_one"},
    ]
    with pytest.raises(ValueError, match="unambiguous"):
        _review_join_path(relations, "carts", "customers")
    with pytest.raises(ValueError, match="unambiguous"):
        _review_join_path(relations, "carts", "carts")
    assert _review_join_path(relations, "orders", "customers") == ["customers"]


def test_proposal_freshness_preserves_legacy_snapshot_without_schema_name() -> None:
    from src.services.metric_proposals import _freshness_schema, review_schema_fingerprint

    original = {"tables": [{"id": 3, "table_name": "orders", "columns": []}], "relationships": []}
    current = {"tables": [{**original["tables"][0], "physical_schema": "sales"}], "relationships": []}
    assert review_schema_fingerprint(_freshness_schema(current, original)) == review_schema_fingerprint(original)


@pytest.mark.asyncio
async def test_scoped_discovery_adds_bridge_and_respects_budget() -> None:
    from src.services.metric_context import build_discovery_context

    facts, orders, customers, unrelated = [_table(name) for name in ("facts", "orders", "customers", "unrelated")]
    for index, table in enumerate((facts, orders, customers, unrelated), 1):
        table.id = index
        table.columns[0].description = "x" * (20000 if table is unrelated else 1000)

    def relation(source, target, number):
        return SimpleNamespace(
            id=number,
            from_entity=source,
            to_entity=target,
            from_entity_id=source.id,
            to_entity_id=target.id,
            column_pairs=[{"from_column_id": number, "to_column_id": number + 10}],
            join_condition="a = b",
            relationship_type="many_to_one",
        )

    tables = [facts, orders, customers, unrelated]
    links = [relation(facts, orders, 1), relation(orders, customers, 2)]

    async def load(_db, _db_id, names=None):
        return _expand_context(tables, links, set(names) if names is not None else {t.table_name for t in tables})

    with (
        patch("src.services.metric_context.load_review_schema", side_effect=load),
        patch("src.services.metric_context._load_metadata", AsyncMock(return_value=(tables, links))),
        patch(
            "src.services.metric_context._select_discovery_scope",
            AsyncMock(return_value=({"facts", "customers"}, None)),
        ),
    ):
        result = await build_discovery_context(None, 1, 8000)
        too_small = await build_discovery_context(None, 1, 2000)
    assert result.diagnostic["status"] == "ready"
    assert {t["table_name"] for t in result.schema["tables"]} == {"facts", "orders", "customers"}
    assert too_small.diagnostic["status"] == "needs_clarification"
