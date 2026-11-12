"""POST /semantic/{db_id}/query with EAV metrics — Flow 2 for EAV sources."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import create_access_token
from src.models.db import (
    LiveTargetDbModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
    UserModel,
)
from src.models.db_eav import EavAttributeModel, EavSourceConfigModel

QUERY_ENDPOINT = "/api/v1/semantic/{db_id}/query"

_ROWS = [
    (1, "revenue", None, 100.0),
    (1, "region", "Miền Bắc", None),
    (2, "revenue", None, 200.0),
    (2, "region", "Miền Nam", None),
    (3, "revenue", None, 50.0),
    (3, "region", "Miền Bắc", None),
]


def _token_headers() -> dict[str, str]:
    user = UserModel(
        id=1,
        email="test@company.com",
        username="tester",
        full_name="Tester",
        hashed_password="hash",
        status="active",
    )
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _seed_target_db(path: Path, duplicate_revenue: bool = False) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE entity_eav (entity_id INTEGER, attr_code TEXT, value_str TEXT, value_num REAL)")
    rows = list(_ROWS)
    if duplicate_revenue:
        rows.append((2, "revenue", None, 300.0))
    connection.executemany("INSERT INTO entity_eav VALUES (?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


async def _seed_eav_semantic_db(db: AsyncSession, with_live_target: bool = True) -> dict[str, int]:
    """Seed an approved EAV config, one approved metric, and optional live target."""
    sem_db = SemanticDatabaseModel(
        created_by=1,
        display_name="EAV Live DB",
        db_type="sqlite",
        conn_url_enc="encrypted-url",
        status="approved",
    )
    db.add(sem_db)
    await db.flush()
    if with_live_target:
        db.add(
            LiveTargetDbModel(
                created_by=1,
                display_name="EAV Live DB",
                dialect="sqlite",
                conn_url_enc="encrypted-url",
                schema_metadata={},
                semantic_db_id=sem_db.id,
            )
        )
        await db.flush()
    table = SemanticTableModel(db_id=sem_db.id, table_name="entity_eav", business_name="Bảng EAV", created_by=1)
    db.add(table)
    await db.flush()
    entity_column = SemanticColumnModel(
        table_id=table.id, column_name="entity_id", data_type="INTEGER", business_name="Mã thực thể"
    )
    db.add(entity_column)
    await db.flush()
    config = EavSourceConfigModel(
        semantic_db_id=sem_db.id,
        name="EAV chính",
        entity_table="entity_eav",
        entity_id_column="entity_id",
        attribute_mode="direct",
        attribute_column="attr_code",
        value_columns={"string": "value_str", "number": "value_num"},
        review_status="approved",
    )
    db.add(config)
    await db.flush()
    revenue = EavAttributeModel(
        config_id=config.id,
        attribute_key="revenue",
        label="Doanh thu",
        data_type="number",
        multi_value_rule="reject",
    )
    region = EavAttributeModel(
        config_id=config.id,
        attribute_key="region",
        label="Khu vực",
        data_type="string",
        multi_value_rule="reject",
    )
    db.add_all([revenue, region])
    await db.flush()
    metric = SemanticMetricModel(
        db_id=sem_db.id,
        created_by=1,
        name="Tổng doanh thu",
        description="",
        sql_template="",
        source="manual",
        status="approved",
        aggregation_type="SUM",
        base_entity_id=table.id,
        definition={
            "schema_version": 2,
            "metric": {
                "name": "Tổng doanh thu",
                "formula": {"function": "SUM", "expression": "revenue"},
                "base_entity": "entity_eav",
                "base_entity_id": table.id,
                "grain": {"column_ids": [entity_column.id]},
                "eav": {
                    "config_id": config.id,
                    "attribute_id": revenue.id,
                    "attribute_key": "revenue",
                    "data_type": "number",
                    "multi_value_rule": "reject",
                    "history_enabled": False,
                },
            },
        },
    )
    db.add(metric)
    await db.commit()
    return {
        "sem_db_id": sem_db.id,
        "metric_id": metric.id,
        "region_attribute_id": region.id,
    }


async def _post_query(client: Any, data: dict[str, int]) -> Any:
    return await client.post(
        QUERY_ENDPOINT.format(db_id=data["sem_db_id"]),
        json={
            "metric_ids": [data["metric_id"]],
            "eav_dimensions": [{"attribute_id": data["region_attribute_id"]}],
            "limit": 100,
        },
        headers=_token_headers(),
    )


@pytest.mark.asyncio
async def test_query_eav_metric_returns_rows(client: Any, async_session: AsyncSession, tmp_path: Any):
    data = await _seed_eav_semantic_db(async_session)
    target = tmp_path / "eav.db"
    _seed_target_db(target, duplicate_revenue=False)
    with patch("src.api.routes.decrypt_conn_url", return_value=f"sqlite:///{target}"):
        response = await _post_query(client, data)
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["dimension_12", "metric_7"] or len(body["columns"]) == 2
    assert sorted(body["rows"], key=lambda row: str(row[0])) == [["Miền Bắc", 150.0], ["Miền Nam", 200.0]]


@pytest.mark.asyncio
async def test_query_eav_multi_value_returns_400(client: Any, async_session: AsyncSession, tmp_path: Any):
    data = await _seed_eav_semantic_db(async_session)
    target = tmp_path / "eav.db"
    _seed_target_db(target, duplicate_revenue=True)
    with patch("src.api.routes.decrypt_conn_url", return_value=f"sqlite:///{target}"):
        response = await _post_query(client, data)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "EAV_MULTI_VALUE"


@pytest.mark.asyncio
async def test_query_eav_rejects_sql_dump_source(client: Any, async_session: AsyncSession):
    data = await _seed_eav_semantic_db(async_session, with_live_target=False)
    response = await _post_query(client, data)
    assert response.status_code == 400
    assert "Live DB" in response.json()["detail"]
