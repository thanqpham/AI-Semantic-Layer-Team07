"""Tests for metrics module — _format_columns and build_metric_system_prompt value sampling."""

from __future__ import annotations

from src.services.metrics import _format_columns, build_metric_system_prompt

# ---------------------------------------------------------------------------
# _format_columns — sample_values
# ---------------------------------------------------------------------------


def test_format_columns_with_sample_values() -> None:
    """Unreviewed samples must not be sent to the metric model."""
    columns = [
        {
            "column_name": "status",
            "data_type": "VARCHAR",
            "business_name": "Trạng thái",
            "sample_values": ["active", "inactive"],
        }
    ]
    result = _format_columns(columns)
    assert len(result) == 1
    assert "values:" not in result[0]
    assert "status" in result[0]


def test_format_columns_without_sample_values() -> None:
    """Columns without sample_values should not show values."""
    columns = [
        {
            "column_name": "name",
            "data_type": "VARCHAR",
            "business_name": "Tên",
        }
    ]
    result = _format_columns(columns)
    assert len(result) == 1
    assert "values:" not in result[0]


def test_format_columns_with_empty_sample_values() -> None:
    """Columns with empty sample_values list should not show values."""
    columns = [
        {
            "column_name": "status",
            "data_type": "VARCHAR",
            "business_name": "Trạng thái",
            "sample_values": [],
        }
    ]
    result = _format_columns(columns)
    assert len(result) == 1
    assert "values:" not in result[0]


def test_format_columns_with_default_value() -> None:
    """Raw defaults are not needed in the prompt and may contain PII."""
    columns = [
        {
            "column_name": "created_at",
            "data_type": "TIMESTAMP",
            "business_name": "Ngày tạo",
            "default_value": "CURRENT_TIMESTAMP",
        }
    ]
    result = _format_columns(columns)
    assert len(result) == 1
    assert "default:" not in result[0]


def test_format_columns_with_default_and_sample_values() -> None:
    """Neither raw defaults nor samples may reach the prompt."""
    columns = [
        {
            "column_name": "status",
            "data_type": "VARCHAR",
            "business_name": "Trạng thái",
            "default_value": "active",
            "sample_values": ["active", "inactive", "pending"],
        }
    ]
    result = _format_columns(columns)
    assert len(result) == 1
    assert "default:" not in result[0]
    assert "values:" not in result[0]


def test_format_columns_with_none_default_value() -> None:
    """Columns with default_value=None should not show default."""
    columns = [
        {
            "column_name": "name",
            "data_type": "VARCHAR",
            "business_name": "Tên",
            "default_value": None,
        }
    ]
    result = _format_columns(columns)
    assert len(result) == 1
    assert "default:" not in result[0]


def test_format_columns_multiple_columns_mixed() -> None:
    """Multiple columns with mixed sample_values presence."""
    columns = [
        {
            "column_name": "status",
            "data_type": "VARCHAR",
            "business_name": "Trạng thái",
            "sample_values": ["active", "inactive"],
        },
        {
            "column_name": "name",
            "data_type": "VARCHAR",
            "business_name": "Tên",
        },
        {
            "column_name": "category",
            "data_type": "VARCHAR",
            "business_name": "Danh mục",
            "sample_values": ["electronics", "clothing"],
        },
    ]
    result = _format_columns(columns)
    assert len(result) == 3
    assert "values:" not in result[0]
    assert "values:" not in result[1]
    assert "values:" not in result[2]


def test_format_columns_only_includes_approved_allowed_values() -> None:
    """Do not disclose pending values to the model."""
    pending = {"column_name": "status", "allowed_values": ["pending-secret"], "review_status": "pending_review"}
    approved = {"column_name": "status", "allowed_values": ["completed"], "review_status": "approved"}
    assert "pending-secret" not in _format_columns([pending])[0]
    assert "completed" in _format_columns([approved])[0]
    approved["allowed_values"] = ["private@example.test"]
    assert "private@example.test" not in _format_columns([approved])[0]


# ---------------------------------------------------------------------------
# build_metric_system_prompt — Rule 6
# ---------------------------------------------------------------------------


def test_metric_system_prompt_contains_rule_6() -> None:
    """System prompt must contain rule 6 about using exact values from sample."""
    prompt = build_metric_system_prompt("test schema text")
    assert "values: [...]" in prompt
    assert "PHẢI dùng đúng 1 giá trị trong danh sách values" in prompt


def test_metric_system_prompt_contains_schema_text() -> None:
    """System prompt must include the provided schema text."""
    schema = "Entity orders: ... test content ..."
    prompt = build_metric_system_prompt(schema)
    assert schema in prompt


def test_metric_system_prompt_contains_all_rules() -> None:
    """System prompt must contain rules 1 through 6."""
    prompt = build_metric_system_prompt("test")
    for rule_text in [
        "formula.function chỉ dùng",
        "formula.expression chỉ gồm",
        "base_entity và các cột phải tồn tại",
        "Ưu tiên base_entity có PK/grain",
        "Filter chỉ dùng cột base_entity",
        "PHẢI dùng đúng 1 giá trị trong danh sách values",
    ]:
        assert rule_text in prompt


# ---------------------------------------------------------------------------
# build_metric_system_prompt — V1/V2 dedupe behavior
# ---------------------------------------------------------------------------


def test_build_metric_system_prompt_v1_unchanged_without_existing() -> None:
    """Without existing metrics the prompt stays V1 (no dedupe artifacts)."""
    text = build_metric_system_prompt("Entity `orders`: ...")
    assert "CÁC METRIC ĐANG TỒN TẠI" not in text
    assert "duplicates" not in text  # V1 output format nguyên vẹn


def test_build_metric_system_prompt_v2_includes_dedupe_rules() -> None:
    """With existing metrics the prompt gains dedupe rules and V2 output format."""
    text = build_metric_system_prompt(
        "Entity `orders`: ...",
        existing_metrics_text='CÁC METRIC ĐANG TỒN TẠI TRONG HỆ THỐNG:\n- [ID 12 | approved] "Doanh thu" = SUM(x)',
    )
    assert "TỒN TẠI TỒN TẠI" not in text  # header không bị lặp 2 lần
    assert "[ID 12 | approved]" in text
    assert "duplicates" in text and "conflicts" in text
    assert "90%" in text  # ngưỡng semantics ≥90% xuất hiện trong rule


# ---------------------------------------------------------------------------
# build_metric_system_prompt — WHERE-correctness rules (spec §3)
# ---------------------------------------------------------------------------


def test_metric_system_prompt_requires_default_filters() -> None:
    """Hygiene is attached by code; completion follows the confirmed requirement."""
    prompt = build_metric_system_prompt("test")
    assert "Hệ thống tự thêm hygiene" in prompt
    assert "không thay bằng điều kiện chỉ loại đơn hủy" in prompt
    assert "Không bịa ánh xạ trạng thái" in prompt


def test_metric_system_prompt_forbids_column_reference_filter_values() -> None:
    """Rule 5(c): filter values must be literals, never column references or joins."""
    prompt = build_metric_system_prompt("test")
    assert "Không bịa ánh xạ trạng thái, điều kiện join hay coi tên cột là literal" in prompt


def test_metric_system_prompt_binary_flag_numeric_typing() -> None:
    """Unknown binary business conventions must not be inferred from column names."""
    prompt = build_metric_system_prompt("test")
    assert "Giá trị filter phải khớp kiểu và metadata" in prompt
    assert "không tự suy diễn quy ước 1/0 hoặc Y/N" in prompt


def test_metric_system_prompt_entity_counting_uses_count_distinct() -> None:
    """Rule 1 must mandate COUNT_DISTINCT for entity counting."""
    prompt = build_metric_system_prompt("test")
    assert "COUNT_DISTINCT trên khóa thực thể" in prompt
    assert "COUNT chỉ dùng" in prompt
