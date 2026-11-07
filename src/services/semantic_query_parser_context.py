"""Private prompt preparation for the semantic query parser."""

from __future__ import annotations

from typing import Any

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
    safe["metrics"] = [_public_fields(item) for item in metrics]
    safe["dimensions"] = [_prompt_dimension(item, dim_metrics) for item in catalog.get("dimensions", [])]
    safe["filter_columns"] = [_prompt_filter_column(item, filter_metrics) for item in catalog.get("filter_columns", [])]
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
    return None
