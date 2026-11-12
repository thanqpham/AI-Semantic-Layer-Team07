"""Validation of manually declared EAV source configs against stored metadata."""

import pytest
from pydantic import ValidationError

from src.models.eav_config import EavAttributePayload, EavHistoryRule, EavSourceConfigPayload
from src.models.schema_metadata import (
    ColumnMetadata,
    Identifier,
    RawSchemaMetadata,
    SchemaDialect,
    SchemaMetadata,
    TableMetadata,
)
from src.services.eav_config_validation import validate_eav_source_config

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


@pytest.fixture
def schema_metadata() -> dict:
    return RawSchemaMetadata(
        dialect=_DIALECT,
        schemas=(SchemaMetadata(schema_name=_identifier("public")),),
        tables=(
            _table(
                "entity_eav",
                [
                    "entity_id",
                    "attr_code",
                    "attr_name_id",
                    "value_str",
                    "value_num",
                    "value_ts",
                    "effective_from",
                    "effective_to",
                ],
            ),
            _table("attr_dict", ["dict_code", "dict_label"]),
        ),
    ).model_dump(mode="json")


def _attribute(**overrides) -> EavAttributePayload:
    defaults = {"attribute_key": "revenue", "label": "Doanh thu", "data_type": "number"}
    defaults.update(overrides)
    return EavAttributePayload(**defaults)


def _direct_config(**overrides) -> EavSourceConfigPayload:
    defaults = {
        "name": "EAV chính",
        "entity_table": "entity_eav",
        "entity_id_column": "entity_id",
        "attribute_mode": "direct",
        "attribute_column": "attr_code",
        "value_columns": {"string": "value_str", "number": "value_num"},
        "attributes": [_attribute()],
    }
    defaults.update(overrides)
    return EavSourceConfigPayload(**defaults)


def _dict_config(**overrides) -> EavSourceConfigPayload:
    defaults = {
        "attribute_mode": "dictionary",
        "attribute_column": None,
        "attribute_fk_column": "attr_name_id",
        "dict_table": "attr_dict",
        "dict_key_column": "dict_code",
        "dict_label_column": "dict_label",
    }
    defaults.update(overrides)
    return _direct_config(**defaults)


def test_valid_direct_config_passes(schema_metadata):
    assert validate_eav_source_config(_direct_config(), schema_metadata) == []


def test_valid_dictionary_config_passes(schema_metadata):
    assert validate_eav_source_config(_dict_config(), schema_metadata) == []


def test_missing_entity_table_or_column_reports_names(schema_metadata):
    errors = validate_eav_source_config(_direct_config(entity_table="missing_table"), schema_metadata)
    assert any("missing_table" in error for error in errors)
    errors = validate_eav_source_config(_direct_config(entity_id_column="ghost_id"), schema_metadata)
    assert any("ghost_id" in error for error in errors)


def test_missing_attribute_or_dict_columns_reported(schema_metadata):
    errors = validate_eav_source_config(_direct_config(attribute_column="attr_x"), schema_metadata)
    assert any("attr_x" in error for error in errors)
    errors = validate_eav_source_config(_dict_config(), schema_metadata)
    assert errors == []
    errors = validate_eav_source_config(_dict_config(dict_table="ghost_dict"), schema_metadata)
    assert any("ghost_dict" in error for error in errors)
    errors = validate_eav_source_config(_dict_config(dict_label_column="ghost_label"), schema_metadata)
    assert any("ghost_label" in error for error in errors)
    errors = validate_eav_source_config(_dict_config(attribute_fk_column="ghost_fk"), schema_metadata)
    assert any("ghost_fk" in error for error in errors)


def test_missing_value_column_reported(schema_metadata):
    errors = validate_eav_source_config(
        _direct_config(value_columns={"string": "value_str", "number": "ghost_val"}), schema_metadata
    )
    assert any("ghost_val" in error for error in errors)


def test_duplicate_value_column_across_types_rejected(schema_metadata):
    errors = validate_eav_source_config(
        _direct_config(value_columns={"string": "value_str", "number": "value_str"}), schema_metadata
    )
    assert errors


def test_attribute_without_resolvable_value_column_rejected(schema_metadata):
    errors = validate_eav_source_config(_direct_config(attributes=[_attribute(data_type="boolean")]), schema_metadata)
    assert any("revenue" in error for error in errors)


def test_attribute_value_column_override_must_exist(schema_metadata):
    errors = validate_eav_source_config(
        _direct_config(attributes=[_attribute(value_column="ghost_override")]), schema_metadata
    )
    assert any("ghost_override" in error for error in errors)


def test_duplicate_or_blank_attribute_key_rejected(schema_metadata):
    errors = validate_eav_source_config(
        _direct_config(attributes=[_attribute(), _attribute(label="Doanh thu 2")]), schema_metadata
    )
    assert any("revenue" in error for error in errors)
    errors = validate_eav_source_config(_direct_config(attributes=[_attribute(attribute_key="   ")]), schema_metadata)
    assert errors


def test_invalid_data_type_or_multi_value_rule_rejected():
    with pytest.raises(ValidationError):
        _attribute(data_type="array")
    with pytest.raises(ValidationError):
        _attribute(multi_value_rule="concat")


def test_history_enabled_without_config_history_rejected(schema_metadata):
    errors = validate_eav_source_config(_direct_config(attributes=[_attribute(history_enabled=True)]), schema_metadata)
    assert errors
    errors = validate_eav_source_config(
        _direct_config(
            history=EavHistoryRule(effective_column="ghost_from"),
            attributes=[_attribute(history_enabled=True)],
        ),
        schema_metadata,
    )
    assert any("ghost_from" in error for error in errors)
    errors = validate_eav_source_config(
        _direct_config(
            history=EavHistoryRule(effective_column="effective_from", end_column="ghost_to"),
            attributes=[_attribute(history_enabled=True)],
        ),
        schema_metadata,
    )
    assert any("ghost_to" in error for error in errors)
    errors = validate_eav_source_config(
        _direct_config(
            history=EavHistoryRule(effective_column="effective_from"),
            attributes=[_attribute(history_enabled=True)],
        ),
        schema_metadata,
    )
    assert errors == []


def test_empty_attributes_rejected(schema_metadata):
    assert validate_eav_source_config(_direct_config(attributes=[]), schema_metadata)
