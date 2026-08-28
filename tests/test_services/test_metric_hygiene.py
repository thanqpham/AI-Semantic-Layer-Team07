"""Tests for the deterministic test/bot data-hygiene filter helper."""

from src.models.metric_definition import MetricFilter
from src.services.metric_hygiene import hygiene_flag_filters


def test_attaches_eq_false_per_matching_flag() -> None:
    """Each unmatched test/bot boolean column yields one eq-False filter."""
    columns = [("id", "INTEGER"), ("is_test_order", "BOOLEAN"), ("is_bot_traffic", "BOOLEAN")]
    filters = hygiene_flag_filters(columns, existing_fields=set())
    assert [(f.field, f.operator, f.value) for f in filters] == [
        ("is_test_order", "eq", False),
        ("is_bot_traffic", "eq", False),
    ]
    assert all(isinstance(f, MetricFilter) for f in filters)


def test_clean_table_yields_no_filters() -> None:
    """Tables without hygiene flags are left alone."""
    assert hygiene_flag_filters([("id", "INTEGER"), ("amount", "NUMERIC")], set()) == []


def test_business_flag_and_non_boolean_column_ignored() -> None:
    """checkout_completed is a business flag; INTEGER test-named columns are not boolean."""
    columns = [("checkout_completed", "BOOLEAN"), ("is_test_review", "INTEGER")]
    assert hygiene_flag_filters(columns, set()) == []


def test_existing_field_reference_is_idempotent_case_insensitive() -> None:
    """A filter already declared on the flag (any case) blocks re-attachment."""
    columns = [("is_test_order", "BOOLEAN")]
    assert hygiene_flag_filters(columns, existing_fields={"IS_TEST_ORDER"}) == []
