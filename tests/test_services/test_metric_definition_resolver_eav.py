"""Resolver behavior for metric definitions that reference EAV attributes."""

import pytest
from sqlalchemy import select

from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel
from src.models.db_eav import EavAttributeModel, EavSourceConfigModel
from src.models.metric_definition import MetricDefinition
from src.services.metric_definition_resolver import MetricDefinitionResolver


def _eav_draft(
    attribute: EavAttributeModel, config: EavSourceConfigModel, aggregation: str = "SUM"
) -> MetricDefinition:
    return MetricDefinition.model_validate(
        {
            "metric": {
                "name": "Tổng doanh thu",
                "formula": {"function": aggregation, "expression": attribute.attribute_key},
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


async def _seed(session, review_status: str = "approved") -> tuple[EavSourceConfigModel, EavAttributeModel]:
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="postgresql", conn_url_enc="enc")
    session.add(database)
    await session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="entity_eav", business_name="Bảng EAV")
    session.add(table)
    await session.flush()
    session.add(
        SemanticColumnModel(
            table_id=table.id, column_name="entity_id", business_name="Mã thực thể", data_type="INTEGER"
        )
    )
    config = EavSourceConfigModel(
        semantic_db_id=database.id,
        name="EAV chính",
        entity_table="entity_eav",
        entity_id_column="entity_id",
        attribute_mode="direct",
        attribute_column="attr_code",
        value_columns={"number": "value_num"},
        review_status=review_status,
    )
    session.add(config)
    await session.flush()
    attribute = EavAttributeModel(config_id=config.id, attribute_key="revenue", label="Doanh thu", data_type="number")
    session.add(attribute)
    await session.commit()
    return config, attribute


@pytest.mark.asyncio
async def test_resolve_eav_metric_fills_reference_and_base_entity(async_session):
    config, attribute = await _seed(async_session)
    resolved = await MetricDefinitionResolver(async_session).resolve(
        config.semantic_db_id, _eav_draft(attribute, config)
    )
    assert resolved.metric.eav is not None
    assert resolved.metric.eav.attribute_id == attribute.id
    assert resolved.metric.eav.multi_value_rule == "reject"
    assert resolved.metric.base_entity == "entity_eav"
    assert resolved.metric.base_entity_id is not None


@pytest.mark.asyncio
async def test_resolve_eav_metric_sets_grain_from_entity_id_column(async_session):
    config, attribute = await _seed(async_session)
    resolved = await MetricDefinitionResolver(async_session).resolve(
        config.semantic_db_id, _eav_draft(attribute, config)
    )
    assert resolved.schema_version == 2
    assert resolved.diagnostics == []
    result = await async_session.execute(
        select(SemanticColumnModel).where(SemanticColumnModel.table_id == resolved.metric.base_entity_id)
    )
    entity_column = result.scalars().one()
    assert resolved.metric.grain.column_ids == [entity_column.id]


@pytest.mark.asyncio
async def test_resolve_rejects_unapproved_config(async_session):
    config, attribute = await _seed(async_session, review_status="pending_review")
    with pytest.raises(ValueError, match="chưa được phê duyệt"):
        await MetricDefinitionResolver(async_session).resolve(config.semantic_db_id, _eav_draft(attribute, config))


@pytest.mark.asyncio
async def test_resolve_rejects_attribute_from_other_database(async_session):
    config, attribute = await _seed(async_session)
    other = SemanticDatabaseModel(created_by=1, display_name="Khác", db_type="postgresql", conn_url_enc="enc")
    async_session.add(other)
    await async_session.commit()
    with pytest.raises(ValueError, match="không tồn tại"):
        await MetricDefinitionResolver(async_session).resolve(other.id, _eav_draft(attribute, config))


@pytest.mark.asyncio
async def test_resolve_rejects_numeric_aggregation_on_string_attribute(async_session):
    config, attribute = await _seed(async_session)
    attribute.data_type = "string"
    async_session.add(attribute)
    await async_session.commit()
    with pytest.raises(ValueError, match="SUM"):
        await MetricDefinitionResolver(async_session).resolve(config.semantic_db_id, _eav_draft(attribute, config))


@pytest.mark.asyncio
async def test_regular_metric_still_resolves(async_session):
    config, _ = await _seed(async_session)
    draft = MetricDefinition.model_validate(
        {
            "metric": {
                "name": "Số dòng",
                "formula": {"function": "COUNT", "expression": "entity_id"},
                "base_entity": "entity_eav",
            }
        }
    )
    resolved = await MetricDefinitionResolver(async_session).resolve(config.semantic_db_id, draft)
    assert resolved.metric.eav is None
    assert resolved.metric.formula.expression_ast is not None
