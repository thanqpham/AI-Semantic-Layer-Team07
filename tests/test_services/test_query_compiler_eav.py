"""EAV query compilation: spec extension, SQL builder, and orchestration routing."""

from datetime import datetime

import pytest
import sqlglot

from src.models.db_eav import EavAttributeModel, EavSourceConfigModel
from src.models.metric_definition import MetricDefinition
from src.models.schemas import (
    DimensionSelection,
    EavDimensionSelection,
    EavQueryFilter,
    SemanticQueryRequest,
    SemanticQuerySpec,
)
from src.services.query_compiler_eav import build_eav_sql
from src.services.query_compiler_types import CompiledQuery
from src.services.semantic_compile_error import SemanticCompileError


def test_eav_spec_fields_roundtrip():
    request = SemanticQueryRequest(
        metric_ids=[7],
        eav_dimensions=[{"attribute_id": 11}],
        eav_filters=[{"attribute_id": 12, "operator": "eq", "value": "Miền Bắc"}],
        as_of="2026-01-15T00:00:00",
    )
    spec = request.to_spec()
    assert isinstance(spec, SemanticQuerySpec)
    assert [item.attribute_id for item in spec.eav_dimensions] == [11]
    assert spec.eav_filters[0].attribute_id == 12
    assert spec.eav_filters[0].operator == "eq"
    assert spec.as_of == datetime(2026, 1, 15)


def test_compiled_query_prechecks_default_empty():
    compiled = CompiledQuery(sql="SELECT 1")
    assert compiled.prechecks == []


# ---------------------------------------------------------------------------
# SQL builder fixtures (plain ORM instances, no database)


def _config(**overrides) -> EavSourceConfigModel:
    payload = {
        "id": 5,
        "semantic_db_id": 1,
        "name": "EAV chÃ­nh",
        "entity_table": "entity_eav",
        "entity_id_column": "entity_id",
        "attribute_mode": "direct",
        "attribute_column": "attr_code",
        "value_columns": {"string": "value_str", "number": "value_num"},
    }
    payload.update(overrides)
    return EavSourceConfigModel(**payload)


def _attr(
    key: str,
    data_type: str,
    rule: str = "reject",
    history: bool = False,
    attr_id: int = 11,
    value_column: str | None = None,
) -> EavAttributeModel:
    return EavAttributeModel(
        id=attr_id,
        config_id=5,
        attribute_key=key,
        label=key,
        data_type=data_type,
        multi_value_rule=rule,
        history_enabled=history,
        value_column=value_column,
    )


def _definition(
    attribute: EavAttributeModel, config: EavSourceConfigModel, function: str = "SUM", metric_id: int = 7
) -> tuple[int, MetricDefinition]:
    definition = MetricDefinition.model_validate(
        {
            "metric": {
                "name": f"Metric {attribute.attribute_key}",
                "formula": {"function": function, "expression": attribute.attribute_key},
                "base_entity": config.entity_table,
                "eav": {
                    "config_id": config.id,
                    "attribute_id": attribute.id,
                    "attribute_key": attribute.attribute_key,
                    "data_type": attribute.data_type,
                    "multi_value_rule": attribute.multi_value_rule,
                    "history_enabled": attribute.history_enabled,
                },
            }
        }
    )
    return metric_id, definition


def _spec(**overrides) -> SemanticQuerySpec:
    payload = {
        "metric_ids": [7],
        "dimensions": [],
        "filters": [],
        "eav_dimensions": [],
        "eav_filters": [],
        "limit": 100,
    }
    payload.update(overrides)
    return SemanticQuerySpec(**payload)


def test_build_direct_mode_metric_and_dimension_sql():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum", attr_id=11)
    region = _attr("region", "string", rule="reject", attr_id=12)
    metric = _definition(revenue, config)
    built = build_eav_sql(
        config,
        {11: revenue, 12: region},
        [metric],
        _spec(eav_dimensions=[EavDimensionSelection(attribute_id=12)]),
        "postgres",
    )
    sqlglot.parse_one(built.sql, dialect="postgres")
    assert 'AS "metric_7"' in built.sql
    assert 'AS "dimension_12"' in built.sql
    assert "GROUP BY" in built.sql
    assert built.sql.rstrip().endswith("LIMIT 100")
    assert built.parameters["eav_key_1"] == "revenue"
    assert built.parameters["eav_key_2"] == "region"
    assert built.metadata["eav"] is True


def test_build_dictionary_mode_predicate():
    config = _config(
        attribute_mode="dictionary",
        attribute_column="attr_fk",
        dict_table="attr_dict",
        dict_key_column="dict_code",
        dict_label_column="dict_label",
    )
    revenue = _attr("revenue", "number", rule="sum")
    metric = _definition(revenue, config)
    built = build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert "IN (SELECT" in built.sql
    assert '"attr_dict"' in built.sql and '"dict_label"' in built.sql


def test_build_multivalue_sum_aggregates_in_subquery():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum")
    metric = _definition(revenue, config)
    built = build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert "SUM(" in built.sql
    assert "GROUP BY" in built.sql
    assert built.prechecks == []


def test_build_reject_rule_emits_precheck():
    config = _config()
    revenue = _attr("revenue", "number", rule="reject")
    metric = _definition(revenue, config)
    built = build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert len(built.prechecks) == 1
    precheck_sql, precheck_params = built.prechecks[0]
    assert "HAVING COUNT(*) > 1" in precheck_sql
    assert precheck_params["eav_key_1"] == "revenue"


@pytest.mark.parametrize("rule", ["first", "last"])
def test_build_first_last_rule_refused(rule):
    config = _config()
    revenue = _attr("revenue", "number", rule=rule)
    metric = _definition(revenue, config)
    with pytest.raises(SemanticCompileError) as exc:
        build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert exc.value.code == "EAV_RULE_UNSUPPORTED"


def test_build_string_sum_rule_refused():
    config = _config()
    region = _attr("region", "string", rule="sum")
    metric = _definition(region, config)
    with pytest.raises(SemanticCompileError, match="SUM"):
        build_eav_sql(config, {11: region}, [metric], _spec(), "postgres")


def test_build_dimension_sum_rule_refused():
    config = _config()
    region = _attr("region", "string", rule="sum")
    with pytest.raises(SemanticCompileError):
        build_eav_sql(
            config,
            {11: region},
            [],
            _spec(eav_dimensions=[EavDimensionSelection(attribute_id=11)]),
            "postgres",
        )


def test_build_history_as_of_predicate():
    config = _config(history={"effective_column": "eff_at", "end_column": "end_at"})
    revenue = _attr("revenue", "number", rule="reject", history=True)
    metric = _definition(revenue, config)
    spec = _spec(as_of=datetime(2026, 1, 15))
    built = build_eav_sql(config, {11: revenue}, [metric], spec, "postgres")
    assert "<= :eav_asof" in built.sql
    assert "IS NULL OR" in built.sql
    assert built.parameters["eav_asof"] == datetime(2026, 1, 15)


def test_build_history_current_requires_end_column():
    config = _config(history={"effective_column": "eff_at", "end_column": "end_at"})
    revenue = _attr("revenue", "number", rule="reject", history=True)
    metric = _definition(revenue, config)
    built = build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert '"end_at" IS NULL' in built.sql
    assert ":eav_asof" not in built.sql

    no_end = _config(history={"effective_column": "eff_at"})
    with pytest.raises(SemanticCompileError) as exc:
        build_eav_sql(config=no_end, attributes={11: revenue}, metrics=[metric], spec=_spec(), dialect="postgres")
    assert exc.value.code == "EAV_AS_OF_REQUIRED"


def test_build_history_attribute_requires_history_config():
    config = _config()
    revenue = _attr("revenue", "number", rule="reject", history=True)
    metric = _definition(revenue, config)
    with pytest.raises(SemanticCompileError) as exc:
        build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert exc.value.code == "EAV_HISTORY_CONFIG_MISSING"


def test_build_value_column_missing():
    config = _config(value_columns={"string": "value_str"})
    revenue = _attr("revenue", "number", rule="sum")
    metric = _definition(revenue, config)
    with pytest.raises(SemanticCompileError) as exc:
        build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert exc.value.code == "EAV_VALUE_COLUMN_MISSING"


def test_build_two_metrics_left_join_and_order():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum", attr_id=11)
    clicks = _attr("clicks", "number", rule="sum", attr_id=13)
    first = _definition(revenue, config, metric_id=7)
    second = _definition(clicks, config, metric_id=8)
    spec = _spec(metric_ids=[7, 8], order_by="metric_desc", order_metric_id=7)
    built = build_eav_sql(config, {11: revenue, 13: clicks}, [first, second], spec, "postgres")
    assert "LEFT JOIN" in built.sql
    assert "ORDER BY" in built.sql
    sqlglot.parse_one(built.sql, dialect="postgres")


def test_build_eav_filter_predicate():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum")
    region = _attr("region", "string", rule="reject", attr_id=12)
    metric = _definition(revenue, config)
    spec = _spec(eav_filters=[EavQueryFilter(attribute_id=12, operator="eq", value="Miền Bắc")])
    built = build_eav_sql(config, {11: revenue, 12: region}, [metric], spec, "postgres")
    assert "JOIN" in built.sql
    assert "Miền Bắc" in built.parameters.values()
    sqlglot.parse_one(built.sql, dialect="postgres")


def test_build_value_column_override_wins():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum", value_column="amount_col")
    metric = _definition(revenue, config)
    built = build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert '"amount_col"' in built.sql
    assert "value_num" not in built.sql
    sqlglot.parse_one(built.sql, dialect="postgres")


def test_build_value_columns_quoted():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum")
    metric = _definition(revenue, config)
    built = build_eav_sql(config, {11: revenue}, [metric], _spec(), "postgres")
    assert '"value_num"' in built.sql
    assert " value_num" not in built.sql


def test_build_eav_filter_empty_in_refused():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum")
    region = _attr("region", "string", rule="reject", attr_id=12)
    metric = _definition(revenue, config)
    spec = _spec(eav_filters=[EavQueryFilter(attribute_id=12, operator="in", value=[])])
    with pytest.raises(SemanticCompileError) as exc:
        build_eav_sql(config, {11: revenue, 12: region}, [metric], spec, "postgres")
    assert exc.value.code == "INVALID_FILTER_VALUE"


def test_build_eav_filter_eq_null_refused():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum")
    region = _attr("region", "string", rule="reject", attr_id=12)
    metric = _definition(revenue, config)
    spec = _spec(eav_filters=[EavQueryFilter(attribute_id=12, operator="eq", value=None)])
    with pytest.raises(SemanticCompileError) as exc:
        build_eav_sql(config, {11: revenue, 12: region}, [metric], spec, "postgres")
    assert exc.value.code == "INVALID_FILTER_VALUE"


def test_build_eav_filter_number_coerced():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum")
    clicks = _attr("clicks", "number", rule="reject", attr_id=13)
    metric = _definition(revenue, config)
    spec = _spec(eav_filters=[EavQueryFilter(attribute_id=13, operator="eq", value="not-a-number")])
    with pytest.raises(SemanticCompileError) as exc:
        build_eav_sql(config, {11: revenue, 13: clicks}, [metric], spec, "postgres")
    assert exc.value.code == "INVALID_FILTER_VALUE"

    numeric = _spec(eav_filters=[EavQueryFilter(attribute_id=13, operator="eq", value="150")])
    built = build_eav_sql(config, {11: revenue, 13: clicks}, [metric], numeric, "postgres")
    assert 150 in [float(value) for value in built.parameters.values() if hasattr(value, "__float__")]


def test_build_metric_desc_orders_null_metric_last():
    config = _config()
    revenue = _attr("revenue", "number", rule="sum", attr_id=11)
    clicks = _attr("clicks", "number", rule="sum", attr_id=13)
    first = _definition(revenue, config, metric_id=7)
    second = _definition(clicks, config, metric_id=8)
    spec = _spec(metric_ids=[7, 8], order_by="metric_desc", order_metric_id=7)
    built = build_eav_sql(config, {11: revenue, 13: clicks}, [first, second], spec, "postgres")
    assert "(eav_1.val) IS NULL" in built.sql
    sqlglot.parse_one(built.sql, dialect="postgres")


# ---------------------------------------------------------------------------
# Orchestration routing (async, metadata store in SQLite memory)

from src.models.db import SemanticDatabaseModel, SemanticMetricModel  # noqa: E402
from src.services.query_compiler import SemanticQueryCompiler  # noqa: E402


async def _seed_eav_metric(
    session,
    review_status: str = "approved",
    metric_status: str = "approved",
    rule: str = "sum",
    with_dimension: bool = True,
) -> tuple[SemanticDatabaseModel, int, int]:
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="postgresql", conn_url_enc="enc")
    session.add(database)
    await session.flush()
    config = EavSourceConfigModel(
        semantic_db_id=database.id,
        name="EAV chính",
        entity_table="entity_eav",
        entity_id_column="entity_id",
        attribute_mode="direct",
        attribute_column="attr_code",
        value_columns={"string": "value_str", "number": "value_num"},
        review_status=review_status,
    )
    session.add(config)
    await session.flush()
    revenue = EavAttributeModel(
        config_id=config.id, attribute_key="revenue", label="Doanh thu", data_type="number", multi_value_rule=rule
    )
    session.add(revenue)
    region = None
    if with_dimension:
        region = EavAttributeModel(config_id=config.id, attribute_key="region", label="Khu vực", data_type="string")
        session.add(region)
    await session.flush()
    metric = SemanticMetricModel(
        db_id=database.id,
        created_by=1,
        name="Tổng doanh thu",
        description="",
        sql_template="",
        source="manual",
        status=metric_status,
        aggregation_type="SUM",
        definition={
            "schema_version": 2,
            "metric": {
                "name": "Tổng doanh thu",
                "formula": {"function": "SUM", "expression": "revenue"},
                "base_entity": "entity_eav",
                "grain": {"column_ids": [1]},
                "eav": {
                    "config_id": config.id,
                    "attribute_id": revenue.id,
                    "attribute_key": "revenue",
                    "data_type": "number",
                    "multi_value_rule": rule,
                    "history_enabled": False,
                },
            },
        },
    )
    session.add(metric)
    await session.commit()
    return database, metric.id, (region.id if region else None)


@pytest.mark.asyncio
async def test_compile_routes_eav_metric_with_dimension(async_session):
    database, metric_id, region_id = await _seed_eav_metric(async_session)
    spec = SemanticQuerySpec(metric_ids=[metric_id], eav_dimensions=[EavDimensionSelection(attribute_id=region_id)])
    compiled = await SemanticQueryCompiler(async_session).compile(database.id, spec)
    assert compiled.metadata["eav"] is True
    assert "GROUP BY" in compiled.sql
    assert "LIMIT 100" in compiled.sql


@pytest.mark.asyncio
async def test_compile_refuses_unapproved_config(async_session):
    database, metric_id, region_id = await _seed_eav_metric(async_session, review_status="pending_review")
    with pytest.raises(SemanticCompileError) as exc:
        await SemanticQueryCompiler(async_session).compile(database.id, SemanticQuerySpec(metric_ids=[metric_id]))
    assert exc.value.code == "EAV_CONFIG_NOT_APPROVED"


@pytest.mark.asyncio
async def test_compile_refuses_mixed_eav_and_relational(async_session):
    database, metric_id, _ = await _seed_eav_metric(async_session)
    relational = SemanticMetricModel(
        db_id=database.id,
        created_by=1,
        name="Số dòng",
        description="",
        sql_template="",
        source="manual",
        status="approved",
        aggregation_type="COUNT",
        definition={
            "schema_version": 2,
            "metric": {
                "name": "Số dòng",
                "formula": {"function": "COUNT", "expression": "entity_id"},
                "base_entity": "entity_eav",
                "grain": {"column_ids": [1]},
            },
        },
    )
    async_session.add(relational)
    await async_session.commit()
    with pytest.raises(SemanticCompileError) as exc:
        await SemanticQueryCompiler(async_session).compile(
            database.id, SemanticQuerySpec(metric_ids=[metric_id, relational.id])
        )
    assert exc.value.code == "EAV_MIXED_SELECTION"


@pytest.mark.asyncio
async def test_compile_refuses_relational_dimensions_with_eav_metric(async_session):
    database, metric_id, _ = await _seed_eav_metric(async_session)
    with pytest.raises(SemanticCompileError) as exc:
        await SemanticQueryCompiler(async_session).compile(
            database.id,
            SemanticQuerySpec(metric_ids=[metric_id], dimensions=[DimensionSelection(column_id=99)]),
        )
    assert exc.value.code == "EAV_MIXED_SELECTION"


@pytest.mark.asyncio
async def test_compile_refuses_eav_selection_with_relational_metric(async_session):
    database, _, region_id = await _seed_eav_metric(async_session, with_dimension=True)
    relational = SemanticMetricModel(
        db_id=database.id,
        created_by=1,
        name="Số dòng",
        description="",
        sql_template="",
        source="manual",
        status="approved",
        aggregation_type="COUNT",
        definition={
            "schema_version": 2,
            "metric": {
                "name": "Số dòng",
                "formula": {"function": "COUNT", "expression": "entity_id"},
                "base_entity": "entity_eav",
                "grain": {"column_ids": [1]},
            },
        },
    )
    async_session.add(relational)
    await async_session.commit()
    spec = SemanticQuerySpec(metric_ids=[relational.id], eav_dimensions=[EavDimensionSelection(attribute_id=region_id)])
    with pytest.raises(SemanticCompileError) as exc:
        await SemanticQueryCompiler(async_session).compile(database.id, spec)
    assert exc.value.code == "EAV_MIXED_SELECTION"


@pytest.mark.asyncio
async def test_compile_refuses_metrics_from_different_configs(async_session):
    database, metric_id, _ = await _seed_eav_metric(async_session)
    other_config = EavSourceConfigModel(
        semantic_db_id=database.id,
        name="EAV khác",
        entity_table="other_eav",
        entity_id_column="entity_id",
        attribute_mode="direct",
        attribute_column="attr_code",
        value_columns={"number": "value_num"},
        review_status="approved",
    )
    async_session.add(other_config)
    await async_session.flush()
    other_attr = EavAttributeModel(
        config_id=other_config.id,
        attribute_key="clicks",
        label="Lượt click",
        data_type="number",
        multi_value_rule="sum",
    )
    async_session.add(other_attr)
    await async_session.flush()
    other_metric = SemanticMetricModel(
        db_id=database.id,
        created_by=1,
        name="Tổng click",
        description="",
        sql_template="",
        source="manual",
        status="approved",
        aggregation_type="SUM",
        definition={
            "schema_version": 2,
            "metric": {
                "name": "Tổng click",
                "formula": {"function": "SUM", "expression": "clicks"},
                "base_entity": "other_eav",
                "grain": {"column_ids": [1]},
                "eav": {
                    "config_id": other_config.id,
                    "attribute_id": other_attr.id,
                    "attribute_key": "clicks",
                    "data_type": "number",
                    "multi_value_rule": "sum",
                    "history_enabled": False,
                },
            },
        },
    )
    async_session.add(other_metric)
    await async_session.commit()
    with pytest.raises(SemanticCompileError) as exc:
        await SemanticQueryCompiler(async_session).compile(
            database.id, SemanticQuerySpec(metric_ids=[metric_id, other_metric.id])
        )
    assert exc.value.code == "INCOMPATIBLE_BASE_ENTITY"
