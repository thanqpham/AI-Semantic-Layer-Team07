"""Validate declared EAV configs against stored schema metadata only.

Never opens a connection to the target database and never reads row data:
the input ``schema_metadata`` is the JSON dump of ``RawSchemaMetadata``
already persisted by Flow 1. Names are matched case-insensitively through
each identifier's ``normalized_name`` (the system identifier policy).
"""

from pydantic import ValidationError

from src.models.eav_config import EavAttributePayload, EavSourceConfigPayload
from src.models.schema_metadata import RawSchemaMetadata

TableIndex = dict[str, set[str]]

_NUMERIC_AGGREGATIONS = {"SUM", "AVG"}
_UNIVERSAL_AGGREGATIONS = {"COUNT", "MIN", "MAX"}


def eav_allowed_aggregations(data_type: str) -> set[str]:
    """Aggregations permitted for one EAV attribute of the given data type."""
    if data_type == "number":
        return _UNIVERSAL_AGGREGATIONS | _NUMERIC_AGGREGATIONS
    return set(_UNIVERSAL_AGGREGATIONS)


def validate_eav_source_config(payload: EavSourceConfigPayload, schema_metadata: dict) -> list[str]:
    """Return Vietnamese error messages for every problem found; empty means valid."""
    tables = _table_index(schema_metadata)
    if tables is None:
        return ["Metadata schema đã lưu không đọc được."]
    errors = _validate_entity_mapping(payload, tables)
    entity_columns = tables.get(_norm(payload.entity_table), set())
    if entity_columns:
        errors.extend(_validate_value_columns(payload, entity_columns))
        errors.extend(_validate_attributes(payload, entity_columns))
    return errors


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


def _table_index(schema_metadata: dict) -> TableIndex | None:
    """Index stored tables by normalized name; None when the payload is invalid."""
    try:
        raw_schema = RawSchemaMetadata.model_validate(schema_metadata)
    except ValidationError:
        return None
    return {
        table.table_name.normalized_name: {column.column_name.normalized_name for column in table.columns}
        for table in raw_schema.tables
    }


def _missing(columns: set[str], name: str | None, description: str) -> list[str]:
    if not (name or "").strip():
        return [f"{description} chưa được khai báo."]
    if _norm(name) not in columns:
        return [f"{description} '{name}' không tồn tại."]
    return []


def _validate_entity_mapping(payload: EavSourceConfigPayload, tables: TableIndex) -> list[str]:
    if _norm(payload.entity_table) not in tables:
        return [f"Bảng thực thể '{payload.entity_table}' không tồn tại."]
    entity_columns = tables[_norm(payload.entity_table)]
    errors = _missing(entity_columns, payload.entity_id_column, "Cột định danh thực thể")
    if payload.attribute_mode == "direct":
        errors += _missing(entity_columns, payload.attribute_column, "Cột mã thuộc tính")
        return errors
    return errors + _validate_dictionary_mapping(payload, tables, entity_columns)


def _validate_dictionary_mapping(
    payload: EavSourceConfigPayload, tables: TableIndex, entity_columns: set[str]
) -> list[str]:
    errors = _missing(entity_columns, payload.attribute_fk_column, "Cột liên kết bảng từ điển")
    if not (payload.dict_table or "").strip() or _norm(payload.dict_table) not in tables:
        return errors + [f"Bảng từ điển '{payload.dict_table}' không tồn tại."]
    dict_columns = tables[_norm(payload.dict_table)]
    errors += _missing(dict_columns, payload.dict_key_column, "Cột mã từ điển")
    errors += _missing(dict_columns, payload.dict_label_column, "Cột nhãn từ điển")
    return errors


def _validate_value_columns(payload: EavSourceConfigPayload, entity_columns: set[str]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for data_type, column in payload.value_columns.items():
        if _norm(column) in seen:
            errors.append(f"Cột giá trị '{column}' được dùng cho cả kiểu '{seen[_norm(column)]}' và '{data_type}'.")
            continue
        seen[_norm(column)] = data_type
        errors += _missing(entity_columns, column, f"Cột giá trị kiểu '{data_type}'")
    return errors


def _validate_attributes(payload: EavSourceConfigPayload, entity_columns: set[str]) -> list[str]:
    if not payload.attributes:
        return ["Phải khai báo ít nhất một thuộc tính."]
    errors: list[str] = []
    seen_keys: set[str] = set()
    for attribute in payload.attributes:
        key = attribute.attribute_key.strip()
        if not key:
            errors.append("Mã thuộc tính không được để trống.")
            continue
        if key in seen_keys:
            errors.append(f"Thuộc tính '{key}' bị khai báo trùng.")
            continue
        seen_keys.add(key)
        errors += _validate_attribute_value_column(payload, attribute, entity_columns)
        if attribute.history_enabled:
            errors += _validate_history(payload, entity_columns, key)
    return errors


def _validate_attribute_value_column(
    payload: EavSourceConfigPayload, attribute: EavAttributePayload, entity_columns: set[str]
) -> list[str]:
    if attribute.value_column is not None:
        return _missing(
            entity_columns, attribute.value_column, f"Cột giá trị của thuộc tính '{attribute.attribute_key}'"
        )
    if attribute.data_type not in payload.value_columns:
        return [f"Thuộc tính '{attribute.attribute_key}' không có cột giá trị cho kiểu '{attribute.data_type}'."]
    return []


def _validate_history(payload: EavSourceConfigPayload, entity_columns: set[str], key: str) -> list[str]:
    if payload.history is None:
        return [f"Thuộc tính '{key}' bật lịch sử nhưng cấu hình chưa khai báo cột thời gian."]
    errors = _missing(entity_columns, payload.history.effective_column, "Cột hiệu lực từ")
    if payload.history.end_column is not None:
        errors += _missing(entity_columns, payload.history.end_column, "Cột hiệu lực đến")
    return errors
