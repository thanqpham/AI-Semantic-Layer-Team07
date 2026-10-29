"""Deterministic comparison of canonical metrics in the metadata catalog."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import sqlglot

from src.models.metric_definition import MetricDefinition
from src.models.schemas import MetricComparisonGroup, MetricComparisonMember


def compare_catalog_metrics(metrics: list[dict[str, Any]]) -> list[MetricComparisonGroup]:
    """Group active canonical metrics by exact or filter-only identity."""
    valid = [_metric_entry(item) for item in metrics]
    valid = [item for item in valid if item is not None]
    by_core: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in valid:
        by_core[item["core_key"]].append(item)
    groups: list[MetricComparisonGroup] = []
    for entries in by_core.values():
        if len(entries) < 2:
            continue
        groups.extend(_groups_for_core(entries))
    return groups


def _groups_for_core(entries: list[dict[str, Any]]) -> list[MetricComparisonGroup]:
    by_full: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in entries:
        by_full[item["full_key"]].append(item)
    groups: list[MetricComparisonGroup] = []
    for same_filter in by_full.values():
        if len(same_filter) > 1:
            groups.append(_make_group("exact_duplicate", same_filter))
    if len(by_full) > 1:
        groups.append(_make_group("near_duplicate", entries))
    return groups


def _metric_entry(item: dict[str, Any]) -> dict[str, Any] | None:
    definition = item.get("definition")
    if isinstance(definition, MetricDefinition):
        parsed = definition
    else:
        try:
            parsed = MetricDefinition.model_validate(definition)
        except Exception:
            return None
    spec = parsed.metric
    full_key = metric_identity(parsed)
    return {
        "core_key": full_key[:-1],
        "full_key": full_key,
        "spec": spec,
        "metric": item,
        "filters": list(full_key[-1]),
    }


def metric_identity(definition: MetricDefinition) -> tuple[Any, ...]:
    """Identify a metric by its calculation, independent of its display name."""
    spec = definition.metric
    ratio = spec.formula.ratio
    ratio_key = (
        None
        if ratio is None
        else (
            ratio.numerator.function,
            _normalize_expression(ratio.numerator.expression),
            ratio.denominator.function,
            _normalize_expression(ratio.denominator.expression),
            ratio.scale,
            ratio.offset,
        )
    )
    filters = [("metric", _filter_key(item.model_dump(mode="json"))) for item in spec.filters]
    if ratio is not None:
        for scope in ("numerator", "denominator"):
            filters.extend((scope, _filter_key(item.model_dump(mode="json"))) for item in getattr(ratio, scope).filters)
    return (
        spec.formula.function,
        _normalize_expression(spec.formula.expression),
        ratio_key,
        spec.query_plan.model_dump(mode="json") if spec.query_plan else None,
        spec.base_entity_id or spec.base_entity.casefold(),
        tuple(sorted(spec.grain.column_ids)),
        tuple(sorted(filters)),
    )


def _normalize_expression(expression: str) -> str:
    try:
        return sqlglot.parse_one(expression).sql(normalize=True).casefold()
    except Exception:
        return " ".join(expression.split()).casefold()


def _filter_key(data: dict[str, Any]) -> tuple[str, str, str]:
    field = str(data.get("field") or data.get("column_id") or "").casefold()
    operator = str(data.get("operator") or "").casefold()
    value = data.get("value")
    if operator in {"in", "not_in"} and isinstance(value, list):
        value = sorted(value, key=lambda entry: json.dumps(entry, ensure_ascii=False, sort_keys=True))
    return field, operator, json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _make_group(group_type: str, entries: list[dict[str, Any]]) -> MetricComparisonGroup:
    members = [_member(entry) for entry in entries]
    unique_filters = list(dict.fromkeys(filter_item for entry in entries for filter_item in entry["filters"]))
    first = entries[0]["spec"]
    ratio = first.formula.ratio
    if ratio is None:
        core_formula = f"{first.formula.function}({first.formula.expression})"
    else:
        core_formula = (
            f"{ratio.offset} + {ratio.scale} × "
            f"({ratio.numerator.function}({ratio.numerator.expression})) / "
            f"({ratio.denominator.function}({ratio.denominator.expression}))"
        )
    return MetricComparisonGroup(
        group_type=group_type,
        core_formula=core_formula,
        base_entity=first.base_entity,
        members=members,
        differing_filters=[
            {"scope": scope, "field": fields[0], "operator": fields[1], "value": json.loads(fields[2])}
            for scope, fields in unique_filters
        ],
    )


def _member(entry: dict[str, Any]) -> MetricComparisonMember:
    spec = entry["spec"]
    metric = entry["metric"]
    return MetricComparisonMember(
        metric_id=metric["metric_id"],
        name=metric["name"],
        status=metric["status"],
        version=metric.get("version") or 1,
        function=spec.formula.function,
        expression=spec.formula.expression,
        base_entity=spec.base_entity,
        filters=[filter_item.model_dump(mode="json") for filter_item in spec.filters],
        ratio=spec.formula.ratio,
    )
