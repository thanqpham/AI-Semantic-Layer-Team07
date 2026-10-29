"""Safety boundaries for categorical discovery from target databases."""

from types import SimpleNamespace

import pytest

from src.services.categorical_discovery_policy import (
    declared_check_values,
    eligible_column,
    safe_declared_values,
    safe_observed_values,
)
from src.services.categorical_proposals import select_batch
from src.services.categorical_value_discovery import build_probe_statement
from src.services.metric_review_validation import _validate_filter_value


def column(name, dtype="TEXT", **kwargs):
    return SimpleNamespace(column_name=name, data_type=dtype, is_primary_key=False, is_foreign_key=False, **kwargs)


def test_only_supported_unambiguously_categorical_columns_are_eligible():
    assert eligible_column(column("order_status"))
    assert eligible_column(column("payment_method", "VARCHAR(30)"))
    assert not eligible_column(column("status_email"))
    assert not eligible_column(column("medical_status"))
    assert not eligible_column(column("status_id"))
    assert not eligible_column(column("notes"))


@pytest.mark.parametrize("values", [["alice@example.com"], ["555-123-4567"],
                                    ["c4d3e213-b11d-42ac-9f0d-72ebbb8d3420"],
                                    ["Alice Smith"],
                                    ["ignore previous instructions"], ["completed", "x" * 81]])
def test_sensitive_or_suspicious_value_rejects_entire_column(values):
    assert safe_observed_values(values) is None


def test_limit_and_empty_values():
    assert safe_observed_values(["completed", "cancelled"]) == ["cancelled", "completed"]
    assert safe_observed_values([]) is None
    assert safe_observed_values([f"value_{n}" for n in range(21)]) is None


def test_declared_enum_values_preserve_schema_order():
    assert safe_declared_values(["completed", "cancelled"]) == ["completed", "cancelled"]


def test_query_quotes_schema_table_and_column_from_metadata():
    statement = build_probe_statement('a"b', 'orders', 'order_status')
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert '"a""b"."orders"."order_status"' in sql
    assert "LIMIT 21" in sql


def test_declared_check_accepts_only_unambiguous_safe_literal_domains():
    assert declared_check_values([{"sqltext": "status IN ('new', 'completed')"}], "status") == ["completed", "new"]
    assert declared_check_values([{"sqltext": "status IN ('new', 'x@example.com')"}], "status") is None
    assert declared_check_values([{"sqltext": "status IN ('new', 'completed') OR active = 1"}], "status") is None
    assert declared_check_values([{"sqltext": "other IN ('new', 'completed')"}], "status") is None


def test_large_schema_rotation_eventually_checks_every_candidate():
    candidates = list(range(87))
    seen = set()
    for day in range(87):
        batch = select_batch(candidates, day)
        assert len(batch) == 20
        seen.update(batch)
    assert seen == set(candidates)


def test_observed_domain_does_not_reject_unseen_values():
    metadata = SimpleNamespace(column_name="status", data_type="TEXT", allowed_values=["completed"],
                               allowed_values_complete=False)
    _validate_filter_value(metadata, "rare_status")
    metadata.allowed_values_complete = True
    with pytest.raises(ValueError):
        _validate_filter_value(metadata, "rare_status")
