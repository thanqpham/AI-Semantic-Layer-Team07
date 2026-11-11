"""End-to-end EAV execution: prechecks run before the main read-only SELECT."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.models.db_eav import EavAttributeModel, EavSourceConfigModel
from src.models.metric_definition import MetricDefinition
from src.models.schemas import EavDimensionSelection, SemanticQuerySpec
from src.services.query_compiler_eav import build_eav_sql
from src.services.query_compiler_types import CompiledQuery
from src.services.query_execution import execute_compiled_query
from src.services.semantic_compile_error import SemanticCompileError

_ROWS = [
    (1, "revenue", None, 100.0),
    (1, "region", "Miền Bắc", None),
    (2, "revenue", None, 200.0),
    (2, "region", "Miền Nam", None),
    (3, "revenue", None, 50.0),
    (3, "region", "Miền Bắc", None),
]


def _seed_target_db(path: Path, duplicate_revenue: bool = False) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE entity_eav (entity_id INTEGER, attr_code TEXT, value_str TEXT, value_num REAL)")
    rows = list(_ROWS)
    if duplicate_revenue:
        rows.append((2, "revenue", None, 300.0))
    connection.executemany("INSERT INTO entity_eav VALUES (?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def _compiled_revenue_by_region() -> CompiledQuery:
    config = EavSourceConfigModel(
        id=5,
        semantic_db_id=1,
        name="EAV",
        entity_table="entity_eav",
        entity_id_column="entity_id",
        attribute_mode="direct",
        attribute_column="attr_code",
        value_columns={"string": "value_str", "number": "value_num"},
    )
    revenue = EavAttributeModel(
        id=11,
        config_id=5,
        attribute_key="revenue",
        label="Doanh thu",
        data_type="number",
        multi_value_rule="reject",
    )
    region = EavAttributeModel(
        id=12,
        config_id=5,
        attribute_key="region",
        label="Khu vực",
        data_type="string",
        multi_value_rule="reject",
    )
    definition = MetricDefinition.model_validate(
        {
            "metric": {
                "name": "Tổng doanh thu",
                "formula": {"function": "SUM", "expression": "revenue"},
                "base_entity": "entity_eav",
                "eav": {
                    "config_id": 5,
                    "attribute_id": 11,
                    "attribute_key": "revenue",
                    "data_type": "number",
                    "multi_value_rule": "reject",
                    "history_enabled": False,
                },
            }
        }
    )
    spec = SemanticQuerySpec(metric_ids=[7], eav_dimensions=[EavDimensionSelection(attribute_id=12)], limit=100)
    built = build_eav_sql(config, {11: revenue, 12: region}, [(7, definition)], spec, "sqlite")
    return CompiledQuery(sql=built.sql, parameters=built.parameters, metadata=built.metadata, prechecks=built.prechecks)


def _result_rows(result: Any) -> list[list[Any]]:
    return sorted(result.rows, key=lambda row: str(row[0]))


@pytest.mark.asyncio
async def test_execute_eav_returns_correct_totals(tmp_path: Any):
    target = tmp_path / "eav.db"
    _seed_target_db(target, duplicate_revenue=False)
    result = await execute_compiled_query(f"sqlite:///{target}", "sqlite", _compiled_revenue_by_region())
    assert result.columns == ["dimension_12", "metric_7"]
    assert _result_rows(result) == [["Miền Bắc", 150.0], ["Miền Nam", 200.0]]


@pytest.mark.asyncio
async def test_execute_eav_rejects_multi_valued_attribute(tmp_path: Any):
    target = tmp_path / "eav.db"
    _seed_target_db(target, duplicate_revenue=True)
    with pytest.raises(SemanticCompileError) as exc:
        await execute_compiled_query(f"sqlite:///{target}", "sqlite", _compiled_revenue_by_region())
    assert exc.value.code == "EAV_MULTI_VALUE"
