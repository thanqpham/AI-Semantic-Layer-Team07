"""Payload contracts for manually declared EAV source configurations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EavAttributeMode = Literal["direct", "dictionary"]
EavDataType = Literal["string", "number", "boolean", "date", "datetime"]
EavMultiValueRule = Literal["reject", "first", "last", "sum", "avg", "min", "max"]

EAV_DATA_TYPES: tuple[str, ...] = ("string", "number", "boolean", "date", "datetime")
EAV_MULTI_VALUE_RULES: tuple[str, ...] = ("reject", "first", "last", "sum", "avg", "min", "max")


class EavHistoryRule(BaseModel):
    """Time columns that make EAV values resolvable at a chosen point in time."""

    effective_column: str
    end_column: str | None = None


class EavAttributePayload(BaseModel):
    """One declared EAV attribute with its handling rules."""

    attribute_key: str
    label: str
    data_type: EavDataType
    value_column: str | None = None
    multi_value_rule: EavMultiValueRule = "reject"
    history_enabled: bool = False
    description: str = ""


class EavSourceConfigPayload(BaseModel):
    """Manual declaration of one EAV table and the attributes built on it."""

    name: str
    entity_table: str
    entity_id_column: str
    attribute_mode: EavAttributeMode
    attribute_column: str | None = None
    attribute_fk_column: str | None = None
    dict_table: str | None = None
    dict_key_column: str | None = None
    dict_label_column: str | None = None
    value_columns: dict[EavDataType, str] = Field(default_factory=dict)
    history: EavHistoryRule | None = None
    attributes: list[EavAttributePayload]


class EavAttributeResponse(BaseModel):
    """Stored representation of one EAV attribute."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    attribute_key: str
    label: str
    description: str
    data_type: str
    value_column: str | None
    multi_value_rule: str
    history_enabled: bool


class EavConfigResponse(BaseModel):
    """Stored EAV source configuration with its declared attributes."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    entity_table: str
    entity_id_column: str
    attribute_mode: str
    attribute_column: str | None
    attribute_fk_column: str | None
    dict_table: str | None
    dict_key_column: str | None
    dict_label_column: str | None
    value_columns: dict[str, str]
    history: dict | None
    review_status: str
    reviewed_by: int | None
    reviewed_at: datetime | None
    created_at: datetime
    attributes: list[EavAttributeResponse]
