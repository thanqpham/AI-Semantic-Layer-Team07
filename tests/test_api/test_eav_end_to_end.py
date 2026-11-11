"""End-to-end EAV flow: declare config → approve → create metric → query."""

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
from src.models.schema_metadata import (
    ColumnMetadata,
    Identifier,
    RawSchemaMetadata,
    SchemaDialect,
    SchemaMetadata,
    TableMetadata,
)

_DIALECT = SchemaDialect.SQLITE
_ROWS = [
    (1, "revenue", None, 100.0),
    (1, "region", "Miền Bắc", None),
    (2, "revenue", None, 200.0),
    (2, "region", "Miền Nam", None),
    (3, "revenue", None, 50.0),
    (3, "region", "Miền Bắc", None),
]


def _headers() -> dict[str, str]:
    user = UserModel(
        id=1,
        email="test@company.com",
        username="tester",
        full_name="Tester",
        hashed_password="hash",
        status="active",
    )
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _seed_target_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE entity_eav (entity_id INTEGER, attr_code TEXT, value_str TEXT, value_num REAL)"
    )
    connection.executemany("INSERT INTO entity_eav VALUES (?, ?, ?, ?)", _ROWS)
    connection.commit()
    connection.close()


def _schema_metadata() -> dict:
    def table(name: str, columns: list[str]) -> TableMetadata:
        return TableMetadata(
            schema_name=Identifier.from_raw("main", _DIALECT),
            table_name=Identifier.from_raw(name, _DIALECT),
            columns=tuple(
                ColumnMetadata(
                    column_name=Identifier.from_raw(column, _DIALECT),
                    ordinal_position=index + 1,
                    raw_data_type="text",
                    data_type="TEXT",
                    nullable=True,
                )
                for index, column in enumerate(columns)
            ),
        )

    return RawSchemaMetadata(
        dialect=_DIALECT,
        schemas=(SchemaMetadata(schema_name=Identifier.from_raw("main", _DIALECT)),),
        tables=(table("entity_eav", ["entity_id", "attr_code", "value_str", "value_num"]),),
    ).model_dump(mode="json")


async def _seed_semantic_store(db: AsyncSession) -> int:
    """Seed database, live target, and the entity table in semantic metadata."""
    database = SemanticDatabaseModel(
        created_by=1,
        display_name="EAV Live DB",
        db_type="sqlite",
        conn_url_enc="encrypted-url",
        status="approved",
    )
    db.add(database)
    await db.flush()
    db.add(
        LiveTargetDbModel(
            created_by=1,
            display_name="EAV Live DB",
            dialect="sqlite",
            conn_url_enc="encrypted-url",
            schema_metadata=_schema_metadata(),
            semantic_db_id=database.id,
        )
    )
    table = SemanticTableModel(
        db_id=database.id, table_name="entity_eav", business_name="Bảng EAV", created_by=1
    )
    db.add(table)
    await db.flush()
    db.add(
        SemanticColumnModel(
            table_id=table.id,
            column_name="entity_id",
            data_type="INTEGER",
            business_name="Mã thực thể",
            is_primary_key=True,
        )
    )
    await db.commit()
    return database.id


_CONFIG_PAYLOAD = {
    "name": "EAV chính",
    "entity_table": "entity_eav",
    "entity_id_column": "entity_id",
    "attribute_mode": "direct",
    "attribute_column": "attr_code",
    "value_columns": {"string": "value_str", "number": "value_num"},
    "attributes": [
        {"attribute_key": "revenue", "label": "Doanh thu", "data_type": "number", "multi_value_rule": "reject"},
        {"attribute_key": "region", "label": "Khu vực", "data_type": "string", "multi_value_rule": "reject"},
    ],
}


@pytest.mark.asyncio
async def test_eav_declare_approve_metric_query_flow(client: Any, async_session: AsyncSession, tmp_path: Any):
    db_id = await _seed_semantic_store(async_session)
    headers = _headers()
    target = tmp_path / "eav.db"
    _seed_target_db(target)

    created = await client.post(f"/api/v1/semantic/{db_id}/eav-configs", headers=headers, json=_CONFIG_PAYLOAD)
    assert created.status_code == 201, created.text
    config = created.json()
    assert config["review_status"] == "pending_review"

    approved = await client.post(
        f"/api/v1/semantic/{db_id}/eav-configs/{config['id']}/review", headers=headers, json={"action": "approve"}
    )
    assert approved.status_code == 200
    assert approved.json()["review_status"] == "approved"

    attributes = {item["attribute_key"]: item for item in config["attributes"]}
    metric_response = await client.post(
        f"/api/v1/semantic/{db_id}/eav-configs/{config['id']}/attributes/{attributes['revenue']['id']}/metric",
        headers=headers,
        json={"aggregation": "SUM", "name": "Tổng doanh thu"},
    )
    assert metric_response.status_code == 201, metric_response.text
    metric_id = metric_response.json()["metric_id"]
    definition = metric_response.json()["definition"]
    assert definition["schema_version"] == 2
    assert definition["metric"]["grain"]["column_ids"], "resolver phải điền grain entity cho metric EAV"

    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric is not None
    metric.status = "approved"
    await async_session.commit()

    with patch("src.api.routes.decrypt_conn_url", return_value=f"sqlite:///{target}"):
        query = await client.post(
            f"/api/v1/semantic/{db_id}/query",
            headers=headers,
            json={
                "metric_ids": [metric_id],
                "eav_dimensions": [{"attribute_id": attributes["region"]["id"]}],
                "limit": 100,
            },
        )
    assert query.status_code == 200, query.text
    body = query.json()
    assert sorted(body["rows"], key=lambda row: str(row[0])) == [["Miền Bắc", 150.0], ["Miền Nam", 200.0]]
