"""Unit tests for natural_language_query service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    CanonicalRelationshipModel,
    LiveTargetDbModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
    UserModel,
)
from src.models.schemas import (
    DimensionSelection,
    SemanticQueryFilter,
    SemanticQueryInterpretation,
    SemanticQuerySpec,
    SemanticTimeRange,
)
from src.services.natural_language_query import (
    _add_filter_values,
    _collect_dims_and_filters,
    _format_metric_item,
    build_parser_catalog,
    execute_natural_language_query,
    format_deterministic_explanation,
    normalize_interpretation,
)
from src.services.query_compiler import CompiledQuery
from src.services.query_execution import QueryResult


@pytest.fixture
def catalog_fixture() -> dict:
    return {
        "metrics": [
            {
                "id": 1,
                "name": "revenue",
                "business_name": "Doanh thu",
                "formula": "SUM(amount)",
                "base_entity": "orders",
                "dimension_ids": [10, 11],
                "filter_column_ids": [11, 12],
            },
            {
                "id": 2,
                "name": "order_count",
                "business_name": "Số đơn hàng",
                "formula": "COUNT(order_id)",
                "base_entity": "orders",
                "dimension_ids": [10, 11],
                "filter_column_ids": [11, 12],
            },
            {
                "id": 3,
                "name": "inventory_count",
                "business_name": "Tồn kho",
                "formula": "SUM(stock)",
                "base_entity": "warehouse_stock",
                "dimension_ids": [],
                "filter_column_ids": [],
            },
        ],
        "dimensions": [
            {
                "column_id": 10,
                "column_name": "customer_id",
                "business_name": "Khách hàng",
                "table_name": "orders",
                "data_type": "INTEGER",
                "is_time_dimension": False,
            },
            {
                "column_id": 11,
                "column_name": "order_date",
                "business_name": "Ngày đặt",
                "table_name": "orders",
                "data_type": "DATE",
                "is_time_dimension": True,
            },
        ],
        "filter_columns": [
            {
                "column_id": 12,
                "column_name": "status",
                "business_name": "Trạng thái",
                "table_name": "orders",
                "data_type": "VARCHAR",
                "allowed_values": ["completed"],
            },
            {"column_id": 11, "column_name": "order_date", "data_type": "DATE"},
        ],
    }


def test_catalog_metric_carries_private_definition_fingerprint() -> None:
    metric = SimpleNamespace(
        id=1, name="Revenue", base_entity=None, version=3, definition={"metric": {"formula": {"expression": "a"}}}
    )
    first = _format_metric_item(metric)
    metric.definition = {"metric": {"formula": {"expression": "b"}}}
    second = _format_metric_item(metric)
    assert first["version"] == 3
    assert first["_definition_fingerprint"] != second["_definition_fingerprint"]


@pytest.mark.asyncio
async def test_filter_catalog_includes_all_approved_mappings_without_sample_eligibility() -> None:
    mappings = [
        {"db_value": str(index), "business_value": f"Region Name, Tier {index}!", "status": "approved"}
        for index in range(25)
    ]
    column = SimpleNamespace(
        id=12,
        column_name="customer_name",
        data_type="TEXT",
        is_primary_key=False,
        is_foreign_key=False,
        review_status="approved",
        allowed_values=["x" * 81],
        allowed_values_complete=False,
        allowed_value_mappings=mappings,
    )
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [column]))
    items = [{"column_id": 12, "column_name": "customer_name", "data_type": "TEXT"}]

    await _add_filter_values(db, items)

    assert len(items[0]["_approved_mappings"]) == 25
    assert items[0]["_approved_mappings"][7]["db_value"] == "7"
    assert items[0]["allowed_values"] == []
    assert items[0]["allowed_values_complete"] is False


@pytest.mark.parametrize(
    "filter_value,expected",
    [(" Account Manager! ", "001"), ("vip", "vip"), (2, 2), (True, True)],
)
def test_filter_normalization_preserves_approved_mapping_scalar_types(
    catalog_fixture: dict, filter_value: object, expected: object
) -> None:
    catalog_fixture["metrics"][0]["filter_column_ids"] = [12, 20, 21]
    catalog_fixture["filter_columns"][0].update(
        review_status="approved",
        allowed_values=[],
        _approved_mappings=[
            {"db_value": "001", "business_value": "Account Manager!", "status": "approved"},
            {"db_value": "vip", "business_value": "VIP", "status": "approved"},
        ],
    )
    catalog_fixture["filter_columns"].extend(
        [
            {"column_id": 20, "data_type": "INTEGER", "allowed_values": [2]},
            {"column_id": 21, "data_type": "BOOLEAN", "allowed_values": [True]},
        ]
    )
    catalog_fixture["metrics"][0]["filter_column_ids"] = [12, 20, 21]
    if isinstance(filter_value, int) and not isinstance(filter_value, bool):
        column_id = 20
    elif isinstance(filter_value, bool):
        column_id = 21
    else:
        column_id = 12
    spec = SemanticQuerySpec(
        metric_ids=[1], filters=[SemanticQueryFilter(column_id=column_id, operator="eq", value=filter_value)]
    )

    normalized = normalize_interpretation(SemanticQueryInterpretation(status="resolved", spec=spec), catalog_fixture)

    assert normalized.status == "resolved"
    assert normalized.spec.filters[0].value == expected
    assert type(normalized.spec.filters[0].value) is type(expected)


def test_normalization_rejects_ambiguous_business_mapping(catalog_fixture: dict) -> None:
    catalog_fixture["filter_columns"][0].update(
        review_status="approved",
        allowed_values=[],
        _approved_mappings=[
            {"db_value": "north-1", "business_value": "North!", "status": "approved"},
            {"db_value": "north-2", "business_value": "NORTH", "status": "approved"},
        ],
    )
    spec = SemanticQuerySpec(metric_ids=[1], filters=[SemanticQueryFilter(column_id=12, operator="eq", value="north")])

    normalized = normalize_interpretation(SemanticQueryInterpretation(status="resolved", spec=spec), catalog_fixture)

    assert normalized.status == "needs_clarification"
    assert "nhiều cách hiểu" in normalized.clarification.prompt


def test_normalization_reports_incompatible_filter_column(catalog_fixture: dict) -> None:
    spec = SemanticQuerySpec(
        metric_ids=[3], filters=[SemanticQueryFilter(column_id=12, operator="eq", value="completed")]
    )

    normalized = normalize_interpretation(SemanticQueryInterpretation(status="resolved", spec=spec), catalog_fixture)

    assert normalized.status == "needs_clarification"
    assert "không tương thích" in normalized.clarification.prompt


def test_normalize_interpretation_merges_time_range(catalog_fixture: dict) -> None:
    """Time ranges are merged into gte and lt runtime filters."""
    interp = SemanticQueryInterpretation(
        status="resolved",
        spec=SemanticQuerySpec(
            metric_ids=[1],
            dimensions=[DimensionSelection(column_id=10)],
            filters=[SemanticQueryFilter(column_id=12, operator="eq", value="completed")],
            limit=100,
        ),
        time_ranges=[
            SemanticTimeRange(
                column_id=11,
                start_date="2024-01-01",
                end_date="2025-01-01",
                label="Năm 2024",
            )
        ],
    )
    normalized = normalize_interpretation(interp, catalog_fixture)
    assert normalized.status == "resolved"
    assert normalized.spec is not None
    assert len(normalized.spec.filters) == 3
    assert normalized.spec.filters[1].operator == "gte"
    assert normalized.spec.filters[1].value == "2024-01-01"
    assert normalized.spec.filters[2].operator == "lt"
    assert normalized.spec.filters[2].value == "2025-01-01"


def test_normalize_interpretation_rejects_incompatible_base_entities(catalog_fixture: dict) -> None:
    """Multi-metrics with different base entities are converted to clarification with options."""
    interp = SemanticQueryInterpretation(
        status="resolved",
        spec=SemanticQuerySpec(
            metric_ids=[1, 3],  # orders vs warehouse_stock
            dimensions=[],
            filters=[],
            limit=100,
        ),
    )
    normalized = normalize_interpretation(interp, catalog_fixture)
    assert normalized.status == "needs_clarification"
    assert normalized.clarification is not None
    assert len(normalized.clarification.options) == 2
    assert "Doanh thu" in normalized.clarification.options[0].label
    assert "Tồn kho" in normalized.clarification.options[1].label


def test_normalize_rejects_dimension_owned_by_another_metric(catalog_fixture: dict) -> None:
    catalog_fixture["metrics"][0].update(dimension_ids=[], filter_column_ids=[11, 12])
    interp = SemanticQueryInterpretation(
        status="resolved", spec=SemanticQuerySpec(metric_ids=[1], dimensions=[DimensionSelection(column_id=10)])
    )
    assert normalize_interpretation(interp, catalog_fixture).status == "needs_clarification"


def test_normalize_maps_only_approved_unambiguous_categorical_values(catalog_fixture: dict) -> None:
    catalog_fixture["metrics"][0].update(dimension_ids=[], filter_column_ids=[12, 20, 21])
    catalog_fixture["filter_columns"][0].update(
        allowed_values=["North"],
        allowed_value_mappings=[{"db_value": "North", "business_value": "Miền Bắc", "status": "approved"}],
        review_status="approved",
    )
    interp = SemanticQueryInterpretation(
        status="resolved",
        spec=SemanticQuerySpec(
            metric_ids=[1], filters=[SemanticQueryFilter(column_id=12, operator="eq", value="Miền Bắc")]
        ),
    )
    result = normalize_interpretation(interp, catalog_fixture)
    assert result.status == "resolved"
    assert result.spec.filters[0].value == "North"
    interp.spec.filters[0].value = "Unknown"
    assert normalize_interpretation(interp, catalog_fixture).status == "needs_clarification"


def test_normalize_rejects_ambiguous_label(catalog_fixture: dict) -> None:
    catalog_fixture["metrics"][0].update(dimension_ids=[], filter_column_ids=[12, 20, 21])
    catalog_fixture["filter_columns"][0]["review_status"] = "approved"
    catalog_fixture["filter_columns"][0].update(
        allowed_values=[],
        allowed_value_mappings=[
            {"db_value": "North", "business_value": "Miền Bắc", "status": "approved"},
            {"db_value": "West", "business_value": "Miền Bắc", "status": "approved"},
        ],
    )
    interp = SemanticQueryInterpretation(
        status="resolved",
        spec=SemanticQuerySpec(
            metric_ids=[1], filters=[SemanticQueryFilter(column_id=12, operator="eq", value="Miền Bắc")]
        ),
    )
    assert normalize_interpretation(interp, catalog_fixture).status == "needs_clarification"


@pytest.mark.parametrize(
    "column,start,end", [(999, "2024-01-01", "2025-01-01"), (11, "bad", "2025-01-01"), (11, "2025-01-01", "2024-01-01")]
)
def test_normalize_rejects_invalid_time_ranges(catalog_fixture: dict, column: int, start: str, end: str) -> None:
    interp = SemanticQueryInterpretation(
        status="resolved",
        spec=SemanticQuerySpec(metric_ids=[1]),
        time_ranges=[SemanticTimeRange(column_id=column, start_date=start, end_date=end, label="year")],
    )
    assert normalize_interpretation(interp, catalog_fixture).status == "needs_clarification"


def test_multi_metric_requires_dimension_compatible_with_both(catalog_fixture: dict) -> None:
    catalog_fixture["metrics"][1]["dimension_ids"] = []
    interp = SemanticQueryInterpretation(
        status="resolved", spec=SemanticQuerySpec(metric_ids=[1, 2], dimensions=[DimensionSelection(column_id=10)])
    )
    assert normalize_interpretation(interp, catalog_fixture).status == "needs_clarification"


def test_multi_base_does_not_offer_options_that_discard_filters(catalog_fixture: dict) -> None:
    interp = SemanticQueryInterpretation(
        status="resolved",
        spec=SemanticQuerySpec(
            metric_ids=[1, 3], filters=[SemanticQueryFilter(column_id=12, operator="eq", value="completed")]
        ),
    )
    result = normalize_interpretation(interp, catalog_fixture)
    assert result.status == "needs_clarification"
    assert result.clarification.options == []


@pytest.mark.asyncio
async def test_catalog_memberships_include_all_recommended_dimensions_without_twenty_limit() -> None:
    dims = [SimpleNamespace(column_id=i, model_dump=lambda i=i: {"column_id": i}) for i in range(1, 26)]
    metrics = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    items = [{"id": 1}, {"id": 2}]
    with (
        patch(
            "src.services.natural_language_query.get_dimensions_for_metric",
            new_callable=AsyncMock,
            side_effect=[dims, dims[:1]],
        ) as get_dims,
        patch(
            "src.services.natural_language_query.get_filter_columns_for_metric",
            new_callable=AsyncMock,
            side_effect=[[], []],
        ),
    ):
        dim_items, _ = await _collect_dims_and_filters(AsyncMock(), 1, metrics, items)
    assert len(dim_items) == 25
    assert items[0]["dimension_ids"] == list(range(1, 26))
    assert items[1]["dimension_ids"] == [1]
    assert get_dims.call_args.kwargs["limit"] is None


@pytest.mark.asyncio
async def test_catalog_includes_safe_three_hop_and_large_category_but_not_sensitive(
    async_session: AsyncSession,
) -> None:
    user = UserModel(email="capability@example.com", hashed_password="pw", full_name="Test", username="capability")
    async_session.add(user)
    await async_session.flush()
    database = SemanticDatabaseModel(display_name="Catalog", db_type="sqlite", conn_url_enc="enc", created_by=user.id)
    async_session.add(database)
    await async_session.flush()
    tables = [
        SemanticTableModel(db_id=database.id, table_name=f"t{i}", business_name=f"Table {i}", review_status="approved")
        for i in range(4)
    ]
    async_session.add_all(tables)
    await async_session.flush()
    keys = [
        SemanticColumnModel(
            table_id=table.id, column_name="key", business_name="Key", data_type="INTEGER", review_status="approved"
        )
        for table in tables
    ]
    category = SemanticColumnModel(
        table_id=tables[3].id,
        column_name="category",
        business_name="Category",
        data_type="TEXT",
        review_status="approved",
        allowed_values=[f"item{i}" for i in range(31)],
    )
    quantity = SemanticColumnModel(
        table_id=tables[3].id,
        column_name="quantity",
        business_name="Quantity",
        data_type="INTEGER",
        review_status="approved",
    )
    secret = SemanticColumnModel(
        table_id=tables[3].id, column_name="email", business_name="Email", data_type="TEXT", review_status="approved"
    )
    async_session.add_all([*keys, category, quantity, secret])
    await async_session.flush()
    for i in range(3):
        async_session.add(
            CanonicalRelationshipModel(
                connection_id=database.id,
                from_entity_id=tables[i].id,
                to_entity_id=tables[i + 1].id,
                relationship_type="many_to_one",
                join_condition="key=key",
                column_pairs=[{"from_column_id": keys[i].id, "to_column_id": keys[i + 1].id}],
                review_status="approved",
                validation_status="valid",
            )
        )
    metric = SemanticMetricModel(
        db_id=database.id,
        name="Count",
        description="",
        sql_template="",
        status="approved",
        base_entity_id=tables[0].id,
        definition={"metric": {"base_entity": "t0"}},
    )
    async_session.add(metric)
    await async_session.flush()
    catalog = await build_parser_catalog(async_session, database.id)
    old_relationship_fingerprint = catalog["_relationship_fingerprint"]
    ids = catalog["metrics"][0]["dimension_ids"]
    assert category.id in ids
    assert quantity.id in ids
    assert secret.id not in ids
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=database.id,
            from_entity_id=tables[3].id,
            to_entity_id=tables[0].id,
            relationship_type="many_to_one",
            join_condition="key=key",
            column_pairs=[{"from_column_id": keys[3].id, "to_column_id": keys[0].id}],
            review_status="approved",
            validation_status="valid",
        )
    )
    await async_session.flush()
    catalog = await build_parser_catalog(async_session, database.id)
    assert category.id in catalog["metrics"][0]["dimension_ids"]
    assert catalog["_relationship_fingerprint"] != old_relationship_fingerprint


@pytest.mark.asyncio
async def test_approved_unscreened_mapping_is_server_only_and_pending_is_not_used() -> None:
    column = SimpleNamespace(
        id=12,
        column_name="region",
        data_type="TEXT",
        is_primary_key=False,
        is_foreign_key=False,
        review_status="approved",
        allowed_values=["North"],
        allowed_value_mappings=[
            {"db_value": "North", "business_value": "Miền Bắc", "status": "approved"},
            {"db_value": "South", "business_value": "Miền Nam", "status": "pending"},
        ],
    )
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [column]))
    items = [{"column_id": 12, "data_type": "TEXT"}]
    await _add_filter_values(db, items)
    assert items[0]["allowed_value_mappings"] == [
        {"db_value": "North", "business_value": "Miền Bắc", "status": "approved"}
    ]
    assert items[0]["_approved_mappings"] == items[0]["allowed_value_mappings"]


@pytest.mark.asyncio
async def test_private_mapping_rejects_sensitive_database_value() -> None:
    column = SimpleNamespace(
        id=12,
        column_name="customer_region",
        data_type="TEXT",
        is_primary_key=False,
        is_foreign_key=False,
        review_status="approved",
        allowed_values=[],
        allowed_value_mappings=[
            {"db_value": "alice@example.com", "business_value": "Khách hàng", "status": "approved"}
        ],
    )
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [column]))
    items = [{"column_id": 12, "data_type": "TEXT"}]
    await _add_filter_values(db, items)
    assert items[0]["_approved_mappings"] == [
        {"db_value": "alice@example.com", "business_value": "Khách hàng", "status": "approved"}
    ]


@pytest.mark.asyncio
async def test_sensitive_column_sample_values_stay_excluded_but_approved_mapping_is_preserved() -> None:
    column = SimpleNamespace(
        id=12,
        column_name="customer_name",
        data_type="TEXT",
        is_primary_key=False,
        is_foreign_key=False,
        review_status="approved",
        allowed_values=["Alice"],
        allowed_value_mappings=[{"db_value": "Alice", "business_value": "Khách", "status": "approved"}],
    )
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [column]))
    items = [{"column_id": 12, "data_type": "TEXT"}]
    await _add_filter_values(db, items)
    assert items[0]["allowed_values"] == []
    assert items[0]["_approved_mappings"] == [{"db_value": "Alice", "business_value": "Khách", "status": "approved"}]


def test_format_deterministic_explanation(catalog_fixture: dict) -> None:
    """Deterministic explanation formats metric name, formula, dimensions, time range."""
    text = format_deterministic_explanation(
        metric_ids=[1],
        dimensions=[DimensionSelection(column_id=11, time_grain="month")],
        filters=[SemanticQueryFilter(column_id=12, operator="eq", value="completed")],
        time_ranges=[
            SemanticTimeRange(
                column_id=11,
                start_date="2024-01-01",
                end_date="2025-01-01",
                label="Năm 2024",
            )
        ],
        catalog=catalog_fixture,
    )
    assert "**Doanh thu**" in text
    assert "`SUM(amount)`" in text
    assert "gom nhóm theo **Ngày đặt** (theo tháng)" in text
    assert "lọc theo **Năm 2024**, **Trạng thái** eq `completed`" in text


@pytest.mark.asyncio
async def test_execute_natural_language_query(catalog_fixture: dict) -> None:
    """Execution calls compiler, executes on live DB, and returns structured result."""
    db_mock = AsyncMock(spec=AsyncSession)
    live_db = LiveTargetDbModel(
        id=1,
        created_by=1,
        display_name="Test DB",
        dialect="sqlite",
        conn_url_enc="enc_url",
    )
    spec = SemanticQuerySpec(metric_ids=[1], dimensions=[DimensionSelection(column_id=10)], filters=[], limit=100)

    compiled = CompiledQuery(
        sql="SELECT customer_id, SUM(amount) AS revenue FROM orders GROUP BY customer_id LIMIT 100",
        parameters={},
        metadata={"base_table": "orders"},
    )
    query_res = QueryResult(columns=["customer_id", "revenue"], rows=[[1, 500000], [2, 300000]], row_count=2)

    with (
        patch("src.services.natural_language_query.SemanticQueryCompiler") as mock_compiler_cls,
        patch("src.services.natural_language_query.decrypt_conn_url", return_value="sqlite:///test.db"),
        patch("src.services.natural_language_query.execute_compiled_query", new_callable=AsyncMock) as mock_exec,
    ):
        mock_compiler = AsyncMock()
        mock_compiler.compile.return_value = compiled
        mock_compiler_cls.return_value = mock_compiler
        mock_exec.return_value = query_res

        result = await execute_natural_language_query(
            db=db_mock,
            db_id=10,
            live_db=live_db,
            spec=spec,
            catalog=catalog_fixture,
        )

    assert result.row_count == 2
    assert result.columns == ["customer_id", "revenue"]
    assert result.rows == [[1, 500000], [2, 300000]]
    assert "**Doanh thu**" in result.explanation
    assert result.sql == compiled.sql
