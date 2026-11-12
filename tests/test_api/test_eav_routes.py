"""CRUD and review flow for manually declared EAV source configs."""

import pytest

from src.api.auth import create_access_token
from src.models.db import (
    LiveTargetDbModel,
    OrganizationMemberModel,
    OrganizationModel,
    SemanticDatabaseModel,
    UserModel,
)
from src.models.db_eav import EavAttributeModel, EavSourceConfigModel
from src.models.schema_metadata import (
    ColumnMetadata,
    Identifier,
    RawSchemaMetadata,
    SchemaDialect,
    SchemaMetadata,
    TableMetadata,
)

_DIALECT = SchemaDialect.POSTGRESQL


def _identifier(name: str) -> Identifier:
    return Identifier.from_raw(name, _DIALECT)


def _table(name: str, columns: list[str]) -> TableMetadata:
    return TableMetadata(
        schema_name=_identifier("public"),
        table_name=_identifier(name),
        columns=tuple(
            ColumnMetadata(
                column_name=_identifier(column),
                ordinal_position=index + 1,
                raw_data_type="text",
                data_type="TEXT",
                nullable=True,
            )
            for index, column in enumerate(columns)
        ),
    )


def _schema_metadata() -> dict:
    return RawSchemaMetadata(
        dialect=_DIALECT,
        schemas=(SchemaMetadata(schema_name=_identifier("public")),),
        tables=(
            _table("entity_eav", ["entity_id", "attr_code", "value_str", "value_num"]),
            _table("attr_dict", ["dict_code", "dict_label"]),
        ),
    ).model_dump(mode="json")


def _config_payload(**overrides) -> dict:
    payload = {
        "name": "EAV chính",
        "entity_table": "entity_eav",
        "entity_id_column": "entity_id",
        "attribute_mode": "direct",
        "attribute_column": "attr_code",
        "value_columns": {"string": "value_str", "number": "value_num"},
        "attributes": [
            {
                "attribute_key": "revenue",
                "label": "Doanh thu",
                "data_type": "number",
                "multi_value_rule": "reject",
            }
        ],
    }
    payload.update(overrides)
    return payload


async def _seed_database(session, org_role: str | None = None) -> SemanticDatabaseModel:
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="postgresql", conn_url_enc="enc")
    if org_role is not None:
        org = OrganizationModel(name="Org", slug="org-eav", created_by=1)
        session.add(org)
        await session.flush()
        session.add(OrganizationMemberModel(org_id=org.id, user_id=1, role=org_role))
        database.org_id = org.id
    session.add(database)
    await session.flush()
    session.add(
        LiveTargetDbModel(
            created_by=1,
            display_name="Live DB",
            dialect="postgresql",
            conn_url_enc="enc",
            schema_metadata=_schema_metadata(),
            semantic_db_id=database.id,
        )
    )
    await session.commit()
    return database


def _headers(user: UserModel, org_id: int | None = None) -> dict:
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    if org_id is not None:
        headers["X-Organization-ID"] = str(org_id)
    return headers


@pytest.mark.asyncio
async def test_create_config_stores_pending_review(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session)
    response = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs", headers=_headers(user), json=_config_payload()
    )
    assert response.status_code == 201
    body = response.json()
    assert body["review_status"] == "pending_review"
    assert body["attributes"][0]["attribute_key"] == "revenue"
    stored = await async_session.get(EavSourceConfigModel, body["id"])
    assert stored is not None and stored.review_status == "pending_review"
    stored_attribute = await async_session.get(EavAttributeModel, body["attributes"][0]["id"])
    assert stored_attribute is not None and stored_attribute.label == "Doanh thu"


@pytest.mark.asyncio
async def test_create_config_requires_live_source(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="Dump", db_type="postgresql", conn_url_enc="enc")
    async_session.add(database)
    await async_session.commit()
    response = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs", headers=_headers(user), json=_config_payload()
    )
    assert response.status_code == 409
    assert "Live DB" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_config_reports_validation_errors(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session)
    response = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs",
        headers=_headers(user),
        json=_config_payload(entity_id_column="ghost_id"),
    )
    assert response.status_code == 422
    assert any("ghost_id" in error for error in response.json()["detail"])


@pytest.mark.asyncio
async def test_create_config_rejects_duplicate_entity_table(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session)
    url = f"/api/v1/semantic/{database.id}/eav-configs"
    first = await client.post(url, headers=_headers(user), json=_config_payload())
    assert first.status_code == 201
    second = await client.post(url, headers=_headers(user), json=_config_payload(name="Bản sao"))
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_list_and_get_config(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session)
    created = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs", headers=_headers(user), json=_config_payload()
    )
    config_id = created.json()["id"]
    listed = await client.get(f"/api/v1/semantic/{database.id}/eav-configs", headers=_headers(user))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [config_id]
    single = await client.get(f"/api/v1/semantic/{database.id}/eav-configs/{config_id}", headers=_headers(user))
    assert single.status_code == 200 and single.json()["entity_table"] == "entity_eav"
    other_db = SemanticDatabaseModel(created_by=1, display_name="Khác", db_type="postgresql", conn_url_enc="enc")
    async_session.add(other_db)
    await async_session.commit()
    missing = await client.get(f"/api/v1/semantic/{other_db.id}/eav-configs/{config_id}", headers=_headers(user))
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_update_config_resets_pending_review(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session)
    created = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs", headers=_headers(user), json=_config_payload()
    )
    config_id = created.json()["id"]
    approve = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs/{config_id}/review",
        headers=_headers(user),
        json={"action": "approve"},
    )
    assert approve.status_code == 200
    updated = await client.put(
        f"/api/v1/semantic/{database.id}/eav-configs/{config_id}",
        headers=_headers(user),
        json=_config_payload(name="EAV sửa"),
    )
    assert updated.status_code == 200
    assert updated.json()["review_status"] == "pending_review"
    assert updated.json()["name"] == "EAV sửa"


@pytest.mark.asyncio
async def test_review_config_flow_with_roles(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session, org_role="data_lead")
    org_id = database.org_id
    created = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs", headers=_headers(user, org_id), json=_config_payload()
    )
    assert created.status_code == 201
    config_id = created.json()["id"]
    approve = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs/{config_id}/review",
        headers=_headers(user, org_id),
        json={"action": "approve"},
    )
    assert approve.status_code == 200
    assert approve.json()["review_status"] == "approved"
    assert approve.json()["reviewed_by"] == user.id
    again = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs/{config_id}/review",
        headers=_headers(user, org_id),
        json={"action": "approve"},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_member_cannot_create_or_approve(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session, org_role="member")
    org_id = database.org_id
    created = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs", headers=_headers(user, org_id), json=_config_payload()
    )
    assert created.status_code == 403
    config = EavSourceConfigModel(
        semantic_db_id=database.id,
        name="Có sẵn",
        entity_table="entity_eav",
        entity_id_column="entity_id",
        attribute_mode="direct",
        attribute_column="attr_code",
        value_columns={"string": "value_str"},
    )
    async_session.add(config)
    await async_session.flush()
    async_session.add(
        EavAttributeModel(config_id=config.id, attribute_key="revenue", label="Doanh thu", data_type="string")
    )
    await async_session.commit()
    approve = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs/{config.id}/review",
        headers=_headers(user, org_id),
        json={"action": "approve"},
    )
    assert approve.status_code == 403


@pytest.mark.asyncio
async def test_delete_config(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session)
    created = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs", headers=_headers(user), json=_config_payload()
    )
    config_id = created.json()["id"]
    deleted = await client.delete(f"/api/v1/semantic/{database.id}/eav-configs/{config_id}", headers=_headers(user))
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/semantic/{database.id}/eav-configs/{config_id}", headers=_headers(user))
    assert missing.status_code == 404


async def _seed_approved_config(session) -> tuple:
    from src.models.db_eav import EavAttributeModel, EavSourceConfigModel

    database = await _seed_database(session)
    config = EavSourceConfigModel(
        semantic_db_id=database.id,
        name="EAV chính",
        entity_table="entity_eav",
        entity_id_column="entity_id",
        attribute_mode="direct",
        attribute_column="attr_code",
        value_columns={"number": "value_num"},
        review_status="approved",
    )
    session.add(config)
    await session.flush()
    attribute = EavAttributeModel(config_id=config.id, attribute_key="revenue", label="Doanh thu", data_type="number")
    session.add(attribute)
    await session.commit()
    return database, config, attribute


async def _seed_metric_referencing_attribute(session, database, config, attribute) -> None:
    from src.models.db import SemanticMetricModel

    session.add(
        SemanticMetricModel(
            db_id=database.id,
            created_by=1,
            name="Tổng doanh thu",
            description="",
            sql_template="",
            source="manual",
            status="approved",
            aggregation_type="SUM",
            definition={
                "metric": {
                    "name": "Tổng doanh thu",
                    "eav": {
                        "config_id": config.id,
                        "attribute_id": attribute.id,
                        "attribute_key": attribute.attribute_key,
                        "data_type": "number",
                        "multi_value_rule": "reject",
                        "history_enabled": False,
                    },
                }
            },
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_update_config_keeps_attribute_ids_stable(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session)
    created = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs",
        headers=_headers(user),
        json=_config_payload(
            attributes=[
                {"attribute_key": "revenue", "label": "Doanh thu", "data_type": "number"},
                {"attribute_key": "region", "label": "Khu vực", "data_type": "string"},
            ]
        ),
    )
    config_id = created.json()["id"]
    revenue_id = next(a["id"] for a in created.json()["attributes"] if a["attribute_key"] == "revenue")
    payload = _config_payload(
        attributes=[
            {"attribute_key": "region", "label": "Khu vực", "data_type": "string"},
            {"attribute_key": "revenue", "label": "Doanh thu sửa", "data_type": "number"},
        ]
    )
    updated = await client.put(
        f"/api/v1/semantic/{database.id}/eav-configs/{config_id}", headers=_headers(user), json=payload
    )
    assert updated.status_code == 200, updated.text
    items = {item["attribute_key"]: item for item in updated.json()["attributes"]}
    assert items["revenue"]["id"] == revenue_id, "attribute_id phải ổn định để metric không mồ côi"
    assert items["revenue"]["label"] == "Doanh thu sửa"


@pytest.mark.asyncio
async def test_update_config_blocked_when_attribute_in_use(client, async_session):
    user = await async_session.get(UserModel, 1)
    database, config, attribute = await _seed_approved_config(async_session)
    await _seed_metric_referencing_attribute(async_session, database, config, attribute)
    payload = _config_payload(attributes=[{"attribute_key": "region", "label": "Khu vực", "data_type": "string"}])
    updated = await client.put(
        f"/api/v1/semantic/{database.id}/eav-configs/{config.id}", headers=_headers(user), json=payload
    )
    assert updated.status_code == 409
    assert "revenue" in updated.json()["detail"]


@pytest.mark.asyncio
async def test_delete_config_blocked_when_attribute_in_use(client, async_session):
    user = await async_session.get(UserModel, 1)
    database, config, attribute = await _seed_approved_config(async_session)
    await _seed_metric_referencing_attribute(async_session, database, config, attribute)
    deleted = await client.delete(f"/api/v1/semantic/{database.id}/eav-configs/{config.id}", headers=_headers(user))
    assert deleted.status_code == 409
    assert "revenue" in deleted.json()["detail"]


@pytest.mark.asyncio
async def test_create_metric_from_eav_attribute(client, async_session):
    from src.models.db import SemanticMetricModel

    user = await async_session.get(UserModel, 1)
    database, config, attribute = await _seed_approved_config(async_session)
    response = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs/{config.id}/attributes/{attribute.id}/metric",
        headers=_headers(user),
        json={"aggregation": "SUM"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["definition"]["metric"]["eav"]["attribute_key"] == "revenue"
    attribute_id = attribute.id
    database_id = database.id
    await async_session.rollback()
    metric = await async_session.get(SemanticMetricModel, body["metric_id"])
    assert metric is not None, "metric phải được commit, không chỉ flush"
    assert metric.status == "pending_approval"
    assert metric.aggregation_type == "SUM"
    assert metric.definition["metric"]["eav"]["attribute_id"] == attribute_id
    fresh_db = await async_session.get(SemanticDatabaseModel, database_id)
    assert fresh_db.status == "draft"


@pytest.mark.asyncio
async def test_create_metric_from_pending_config_rejected(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = await _seed_database(async_session)
    config = EavSourceConfigModel(
        semantic_db_id=database.id,
        name="EAV chính",
        entity_table="entity_eav",
        entity_id_column="entity_id",
        attribute_mode="direct",
        attribute_column="attr_code",
        value_columns={"number": "value_num"},
    )
    async_session.add(config)
    await async_session.flush()
    attribute = EavAttributeModel(config_id=config.id, attribute_key="revenue", label="Doanh thu", data_type="number")
    async_session.add(attribute)
    await async_session.commit()
    response = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs/{config.id}/attributes/{attribute.id}/metric",
        headers=_headers(user),
        json={"aggregation": "SUM"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_metric_rejects_mismatched_aggregation(client, async_session):
    user = await async_session.get(UserModel, 1)
    database, config, attribute = await _seed_approved_config(async_session)
    attribute.data_type = "string"
    async_session.add(attribute)
    await async_session.commit()
    response = await client.post(
        f"/api/v1/semantic/{database.id}/eav-configs/{config.id}/attributes/{attribute.id}/metric",
        headers=_headers(user),
        json={"aggregation": "SUM"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_attributes_reports_usable_as(client, async_session):
    user = await async_session.get(UserModel, 1)
    database, config, attribute = await _seed_approved_config(async_session)
    region = EavAttributeModel(config_id=config.id, attribute_key="region", label="Khu vực", data_type="string")
    async_session.add(region)
    await async_session.commit()
    response = await client.get(
        f"/api/v1/semantic/{database.id}/eav-configs/{config.id}/attributes", headers=_headers(user)
    )
    assert response.status_code == 200
    items = {item["attribute_key"]: item["usable_as"] for item in response.json()["items"]}
    assert items["revenue"] == ["metric", "dimension"]
    assert items["region"] == ["dimension"]
