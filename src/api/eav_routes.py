"""Manual EAV source configuration endpoints with metadata-only validation."""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.auth import get_current_user
from src.api.routes import _require_resource_permission
from src.models.db import LiveTargetDbModel, SemanticDatabaseModel, SemanticMetricModel, UserModel
from src.models.db_base import utc_now
from src.models.db_eav import EavAttributeModel, EavSourceConfigModel
from src.models.eav_config import EavAttributePayload, EavConfigResponse, EavSourceConfigPayload
from src.models.metric_definition import MetricDefinition
from src.services.database import get_db_session
from src.services.eav_config_validation import eav_allowed_aggregations, validate_eav_source_config
from src.services.metric_service import DuplicateMetricError, create_metric
from src.services.review_notifications import sync_metrics_pending_notifications

eav_router = APIRouter(tags=["eav"])


class EavConfigReviewRequest(BaseModel):
    """Approve or reject one pending EAV source configuration."""

    action: Literal["approve", "reject"]


class EavMetricCreateRequest(BaseModel):
    """Create one metric from an approved EAV attribute."""

    aggregation: Literal["SUM", "AVG", "MIN", "MAX", "COUNT"]
    name: str | None = None
    description: str = ""


@eav_router.post("/semantic/{db_id}/eav-configs", status_code=201)
async def create_eav_config(
    db_id: int,
    payload: EavSourceConfigPayload,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EavConfigResponse:
    """Declare one EAV source after validating it against stored metadata."""
    semantic_db = await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    _, schema_metadata = await _load_live_metadata(db, semantic_db)
    errors = validate_eav_source_config(payload, schema_metadata)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    await _reject_duplicate_entity_table(db, db_id, payload.entity_table)
    config = _build_config(payload, db_id, user.id)
    db.add(config)
    await db.flush()
    response = EavConfigResponse.model_validate(config)
    await db.commit()
    return response


@eav_router.get("/semantic/{db_id}/eav-configs")
async def list_eav_configs(
    db_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """List EAV source configurations declared for one semantic database."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    result = await db.execute(
        select(EavSourceConfigModel)
        .where(EavSourceConfigModel.semantic_db_id == db_id)
        .options(selectinload(EavSourceConfigModel.attributes))
        .order_by(EavSourceConfigModel.id)
    )
    return {"items": [EavConfigResponse.model_validate(config) for config in result.scalars()]}


@eav_router.get("/semantic/{db_id}/eav-configs/{config_id}")
async def get_eav_config(
    db_id: int,
    config_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EavConfigResponse:
    """Return one EAV source configuration."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    return EavConfigResponse.model_validate(await _owned_config(db, db_id, config_id))


@eav_router.put("/semantic/{db_id}/eav-configs/{config_id}")
async def update_eav_config(
    db_id: int,
    config_id: int,
    payload: EavSourceConfigPayload,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EavConfigResponse:
    """Replace one EAV configuration; it returns to pending review."""
    semantic_db = await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    config = await _owned_config(db, db_id, config_id)
    _, schema_metadata = await _load_live_metadata(db, semantic_db)
    errors = validate_eav_source_config(payload, schema_metadata)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    if payload.entity_table != config.entity_table:
        await _reject_duplicate_entity_table(db, db_id, payload.entity_table)
    await _reject_removed_attributes_in_use(db, db_id, config, payload)
    _apply_payload(config, payload)
    await db.flush()
    response = EavConfigResponse.model_validate(config)
    await db.commit()
    return response


@eav_router.delete("/semantic/{db_id}/eav-configs/{config_id}", status_code=204)
async def delete_eav_config(
    db_id: int,
    config_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Remove one EAV configuration and its attributes."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    config = await _owned_config(db, db_id, config_id)
    await _reject_config_delete_in_use(db, db_id, config)
    await db.delete(config)
    await db.commit()


@eav_router.post("/semantic/{db_id}/eav-configs/{config_id}/review")
async def review_eav_config(
    db_id: int,
    config_id: int,
    body: EavConfigReviewRequest,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EavConfigResponse:
    """Approve or reject one pending EAV configuration (data lead)."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_approve_metrics")
    config = await _owned_config(db, db_id, config_id)
    if config.review_status != "pending_review":
        raise HTTPException(status_code=409, detail="Chỉ cấu hình đang chờ duyệt mới được xử lý.")
    config.review_status = "approved" if body.action == "approve" else "rejected"
    config.reviewed_by = user.id
    config.reviewed_at = utc_now()
    response = EavConfigResponse.model_validate(config)
    await db.commit()
    return response


@eav_router.get("/semantic/{db_id}/eav-configs/{config_id}/attributes")
async def list_eav_attributes(
    db_id: int,
    config_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """List declared attributes with their usable-as roles."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    config = await _owned_config(db, db_id, config_id)
    return {"items": [_attribute_item(attribute) for attribute in config.attributes]}


@eav_router.post("/semantic/{db_id}/eav-configs/{config_id}/attributes/{attribute_id}/metric", status_code=201)
async def create_metric_from_eav_attribute(
    db_id: int,
    config_id: int,
    attribute_id: int,
    body: EavMetricCreateRequest,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Create one metric referencing an approved EAV attribute."""
    semantic_db = await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    config = await _owned_config(db, db_id, config_id)
    attribute = await _owned_attribute(db, config.id, attribute_id)
    if config.review_status != "approved":
        raise HTTPException(status_code=409, detail="Cấu hình EAV chưa được phê duyệt.")
    if body.aggregation not in eav_allowed_aggregations(attribute.data_type):
        raise HTTPException(
            status_code=422, detail=f"Phép {body.aggregation} không áp dụng cho thuộc tính kiểu {attribute.data_type}."
        )
    metric = await _create_eav_metric(db, db_id, user.id, _eav_metric_draft(config, attribute, body))
    semantic_db.status = "draft"
    await db.commit()
    await sync_metrics_pending_notifications(db, db_id)
    return {
        "metric_id": metric.id,
        "name": metric.name,
        "status": metric.status,
        "definition": metric.definition,
    }


async def _create_eav_metric(
    db: AsyncSession, db_id: int, user_id: int, draft: MetricDefinition
) -> SemanticMetricModel:
    """Persist the metric draft, mapping service errors to HTTP responses."""
    try:
        return await create_metric(
            db=db,
            connection_id=db_id,
            metric_data={"definition": draft.model_dump(mode="json"), "source": "manual"},
            user_id=user_id,
        )
    except DuplicateMetricError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _attribute_item(attribute: EavAttributeModel) -> dict:
    """Serialize one attribute with the metric/dimension roles it can take."""
    return {
        "id": attribute.id,
        "attribute_key": attribute.attribute_key,
        "label": attribute.label,
        "description": attribute.description,
        "data_type": attribute.data_type,
        "multi_value_rule": attribute.multi_value_rule,
        "history_enabled": attribute.history_enabled,
        "usable_as": ["metric", "dimension"] if attribute.data_type == "number" else ["dimension"],
    }


async def _owned_attribute(db: AsyncSession, config_id: int, attribute_id: int) -> EavAttributeModel:
    """Load one attribute belonging to the given configuration."""
    result = await db.execute(
        select(EavAttributeModel).where(EavAttributeModel.id == attribute_id, EavAttributeModel.config_id == config_id)
    )
    attribute = result.scalar_one_or_none()
    if attribute is None:
        raise HTTPException(status_code=404, detail="EAV attribute not found")
    return attribute


def _eav_metric_draft(
    config: EavSourceConfigModel, attribute: EavAttributeModel, body: EavMetricCreateRequest
) -> MetricDefinition:
    """Build the metric definition draft referencing the EAV attribute."""
    return MetricDefinition.model_validate(
        {
            "metric": {
                "name": body.name or f"{attribute.label} ({body.aggregation})",
                "formula": {"function": body.aggregation, "expression": attribute.attribute_key},
                "base_entity": config.entity_table,
                "excluded_notes": body.description,
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


async def _load_live_metadata(db: AsyncSession, semantic_db: SemanticDatabaseModel) -> tuple[LiveTargetDbModel, dict]:
    """Return the live target and its stored schema metadata for this source."""
    result = await db.execute(select(LiveTargetDbModel).where(LiveTargetDbModel.semantic_db_id == semantic_db.id))
    live = result.scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=409, detail="EAV chỉ hỗ trợ nguồn Live DB, không hỗ trợ SQL Dump.")
    return live, live.schema_metadata


async def _reject_duplicate_entity_table(db: AsyncSession, semantic_db_id: int, entity_table: str) -> None:
    """Ensure only one configuration exists per entity table."""
    result = await db.execute(
        select(EavSourceConfigModel).where(
            EavSourceConfigModel.semantic_db_id == semantic_db_id,
            EavSourceConfigModel.entity_table == entity_table,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Đã có cấu hình EAV cho bảng '{entity_table}'.")


async def _owned_config(db: AsyncSession, db_id: int, config_id: int) -> EavSourceConfigModel:
    """Load one configuration belonging to the given semantic database."""
    result = await db.execute(
        select(EavSourceConfigModel)
        .where(EavSourceConfigModel.id == config_id, EavSourceConfigModel.semantic_db_id == db_id)
        .options(selectinload(EavSourceConfigModel.attributes))
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="EAV configuration not found")
    return config


def _build_config(payload: EavSourceConfigPayload, semantic_db_id: int, user_id: int) -> EavSourceConfigModel:
    """Build a pending-review ORM configuration from the request payload."""
    config = EavSourceConfigModel(
        semantic_db_id=semantic_db_id,
        created_by=user_id,
        name=payload.name,
        entity_table=payload.entity_table,
        entity_id_column=payload.entity_id_column,
        attribute_mode=payload.attribute_mode,
        attribute_column=payload.attribute_column,
        attribute_fk_column=payload.attribute_fk_column,
        dict_table=payload.dict_table,
        dict_key_column=payload.dict_key_column,
        dict_label_column=payload.dict_label_column,
        value_columns=payload.value_columns,
        history=payload.history.model_dump() if payload.history else None,
    )
    config.attributes = _build_attributes(payload)
    return config


def _build_attributes(payload: EavSourceConfigPayload) -> list[EavAttributeModel]:
    """Build attribute rows for one payload."""
    return [
        EavAttributeModel(
            attribute_key=item.attribute_key,
            label=item.label,
            description=item.description,
            data_type=item.data_type,
            value_column=item.value_column,
            multi_value_rule=item.multi_value_rule,
            history_enabled=item.history_enabled,
        )
        for item in payload.attributes
    ]


def _apply_payload(config: EavSourceConfigModel, payload: EavSourceConfigPayload) -> None:
    """Overwrite mutable fields and reset the review state after an edit."""
    config.name = payload.name
    config.entity_table = payload.entity_table
    config.entity_id_column = payload.entity_id_column
    config.attribute_mode = payload.attribute_mode
    config.attribute_column = payload.attribute_column
    config.attribute_fk_column = payload.attribute_fk_column
    config.dict_table = payload.dict_table
    config.dict_key_column = payload.dict_key_column
    config.dict_label_column = payload.dict_label_column
    config.value_columns = payload.value_columns
    config.history = payload.history.model_dump() if payload.history else None
    _merge_attributes(config, payload.attributes)
    config.review_status = "pending_review"
    config.reviewed_by = None
    config.reviewed_at = None


def _merge_attributes(config: EavSourceConfigModel, items: list[EavAttributePayload]) -> None:
    """Update attributes in place by attribute_key so metric references keep their ids."""
    existing = {attribute.attribute_key: attribute for attribute in config.attributes}
    for item in items:
        row = existing.get(item.attribute_key)
        if row is None:
            config.attributes.append(
                EavAttributeModel(
                    attribute_key=item.attribute_key,
                    label=item.label,
                    description=item.description,
                    data_type=item.data_type,
                    value_column=item.value_column,
                    multi_value_rule=item.multi_value_rule,
                    history_enabled=item.history_enabled,
                )
            )
            continue
        row.label = item.label
        row.description = item.description
        row.data_type = item.data_type
        row.value_column = item.value_column
        row.multi_value_rule = item.multi_value_rule
        row.history_enabled = item.history_enabled
    kept_keys = {item.attribute_key for item in items}
    for key, row in existing.items():
        if key not in kept_keys:
            config.attributes.remove(row)


async def _referenced_attribute_ids(db: AsyncSession, db_id: int) -> set[int]:
    """Attribute ids referenced by live metrics of this semantic database."""
    result = await db.execute(
        select(SemanticMetricModel).where(
            SemanticMetricModel.db_id == db_id,
            SemanticMetricModel.is_deleted.is_(False),
        )
    )
    referenced: set[int] = set()
    for metric in result.scalars():
        eav = (metric.definition or {}).get("metric", {}).get("eav")
        if eav is not None and eav.get("attribute_id") is not None:
            referenced.add(eav["attribute_id"])
    return referenced


async def _reject_removed_attributes_in_use(
    db: AsyncSession, db_id: int, config: EavSourceConfigModel, payload: EavSourceConfigPayload
) -> None:
    """Block edits that would drop attributes still referenced by metrics."""
    kept = {item.attribute_key for item in payload.attributes}
    removed = [attribute for attribute in config.attributes if attribute.attribute_key not in kept]
    referenced = await _referenced_attribute_ids(db, db_id)
    in_use = [attribute.attribute_key for attribute in removed if attribute.id in referenced]
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=f"Thuộc tính EAV đang được metric sử dụng: {', '.join(sorted(in_use))}. Hãy xóa metric trước.",
        )


async def _reject_config_delete_in_use(db: AsyncSession, db_id: int, config: EavSourceConfigModel) -> None:
    """Block deleting a configuration whose attributes are referenced by metrics."""
    referenced = await _referenced_attribute_ids(db, db_id)
    in_use = [attribute.attribute_key for attribute in config.attributes if attribute.id in referenced]
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=f"Cấu hình EAV đang được metric sử dụng (thuộc tính: {', '.join(sorted(in_use))}). Hãy xóa metric trước.",
        )
