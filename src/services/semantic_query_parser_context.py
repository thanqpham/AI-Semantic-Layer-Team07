"""Private prompt preparation for the semantic query parser."""

from __future__ import annotations

import json
import math
import re
from types import SimpleNamespace
from typing import Any

from src.services.categorical_discovery_policy import eligible_column, safe_observed_values
from src.services.semantic_value_mappings import read_approved_business_mappings


def prompt_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Expose only public catalog fields and structurally valid approved mappings."""
    metrics = catalog.get("metrics", [])
    dim_metrics: dict[int, list[int]] = {}
    filter_metrics: dict[int, list[int]] = {}
    for metric in metrics:
        mid = metric.get("id")
        if not isinstance(mid, int):
            continue
        for cid in metric.get("dimension_ids", []):
            dim_metrics.setdefault(cid, []).append(mid)
        for cid in metric.get("filter_column_ids", []):
            filter_metrics.setdefault(cid, []).append(mid)
    safe = {key: value for key, value in catalog.items() if not key.startswith("_")}
    safe["metrics"] = [_prompt_metric(item) for item in metrics]
    safe["dimensions"] = [_prompt_dimension(item, dim_metrics) for item in catalog.get("dimensions", [])]
    safe["filter_columns"] = [_prompt_filter_column(item, filter_metrics) for item in catalog.get("filter_columns", [])]
    return safe


def _prompt_metric(metric: dict[str, Any]) -> dict[str, Any]:
    safe = _public_fields(metric)
    if "formula_definition" in safe:
        safe["formula_definition"] = _prompt_formula(safe["formula_definition"])
    return safe


def _prompt_formula(formula: Any) -> dict[str, Any]:
    if not isinstance(formula, dict):
        return {}
    safe: dict[str, Any] = {}
    if isinstance(formula.get("function"), str) and formula["function"] in {
        "SUM",
        "COUNT",
        "COUNT_DISTINCT",
        "AVG",
        "MIN",
        "MAX",
    }:
        safe["function"] = formula["function"]
    for key in ("scale", "offset"):
        value = formula.get(key)
        if type(value) in (int, float) and math.isfinite(value):
            safe[key] = value
    expression = formula.get("expression")
    if isinstance(expression, str) and re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_$]*|\*)", expression):
        safe["expression"] = expression
    if isinstance(formula.get("filters"), list):
        safe["filters"] = [_prompt_formula_filter(item) for item in formula["filters"] if isinstance(item, dict)]
    for key in ("ratio", "numerator", "denominator"):
        if key in formula:
            safe[key] = _prompt_formula(formula[key])
    return safe


def _prompt_formula_filter(item: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    field = item.get("field")
    if isinstance(field, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,199}", field):
        safe["field"] = field
    column_id = item.get("column_id")
    if type(column_id) is int and column_id > 0:
        safe["column_id"] = column_id
    operator = item.get("operator")
    if isinstance(operator, str) and operator in {
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "is_null",
        "is_not_null",
    }:
        safe["operator"] = operator
    if "value" in item:
        column = SimpleNamespace(
            column_name=safe.get("field", ""), data_type="TEXT", is_primary_key=False, is_foreign_key=False
        )
        value = item["value"]
        values = value if isinstance(value, list) else [value]
        safe["value"] = value if eligible_column(column) and safe_observed_values(values) else "[REDACTED]"
    return safe


def _prompt_dimension(dimension: dict[str, Any], dim_metrics: dict[int, list[int]]) -> dict[str, Any]:
    safe = _public_fields(dimension)
    cid = safe.get("column_id")
    if isinstance(cid, int) and cid in dim_metrics:
        safe["compatible_metric_ids"] = dim_metrics[cid]
    return safe


def _prompt_filter_column(column: dict[str, Any], filter_metrics: dict[int, list[int]]) -> dict[str, Any]:
    """Preserve approved mapping scalars in a JSON-only prompt structure."""
    safe = _public_fields(column)
    cid = safe.get("column_id")
    if isinstance(cid, int) and cid in filter_metrics:
        safe["compatible_metric_ids"] = filter_metrics[cid]
    safe["allowed_value_mappings"] = read_approved_business_mappings(
        column.get("_approved_mappings", column.get("allowed_value_mappings", [])),
        column.get("review_status", "approved"),
    )
    return safe


def _public_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def catalog_capacity_error(catalog: dict[str, Any]) -> str | None:
    """Reject mapping catalogs beyond the supported management size."""
    if any(item.get("_mapping_overflow") for item in catalog.get("filter_columns", [])):
        return "A compatible column has more than 100 approved mappings; narrow the metric or filter scope before querying."
    if sum(len(item.get("_approved_mappings", [])) for item in catalog.get("filter_columns", [])) > 1000:
        return "The catalog has more than 1,000 approved mappings; narrow the metric or table scope before querying."
    if len(json.dumps(prompt_catalog(catalog), ensure_ascii=False, default=str)) > 100_000:
        return "Danh mục truy vấn quá lớn để xử lý đầy đủ. Hãy thu hẹp metric hoặc phạm vi bảng."
    return None
