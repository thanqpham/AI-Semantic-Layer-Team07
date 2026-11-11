"""Deterministic SQL rendering for approved EAV metrics and attributes.

Every attribute becomes one per-entity subquery (aggregate-before-join) so
multi-valued attributes never fan out the outer aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from src.models.db_eav import EavAttributeModel, EavSourceConfigModel
from src.models.metric_definition import MetricDefinition
from src.models.schemas import EavQueryFilter, SemanticQuerySpec
from src.services.query_compiler_parameters import (
    bind_coerced_parameter,
    bind_coerced_sequence,
    validate_null_filter_value,
)
from src.services.semantic_compile_error import SemanticCompileError

_AGG_RULES = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}
_AGG_ONLY_RULES = {"sum", "avg"}
_EAV_FILTER_TYPES = {
    "number": "NUMERIC",
    "string": "VARCHAR",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP",
}


@dataclass(frozen=True)
class BuiltEavQuery:
    """Rendered EAV statement with its bound parameters and prechecks."""

    sql: str
    parameters: dict[str, Any]
    prechecks: list[tuple[str, dict[str, Any]]]
    metadata: dict[str, Any]


@dataclass
class _Usage:
    """One attribute occurrence in the query (metric, dimension, or filter)."""

    role: str
    identifier: int
    attribute: EavAttributeModel
    alias: str
    agg: str | None
    subquery: str


def _quoted(name: str, dialect: str) -> str:
    """Render one identifier quoted for the target dialect."""
    return exp.to_identifier(name, quoted=True).sql(dialect=dialect)


async def load_eav_context(
    db: AsyncSession, connection_id: int, attribute_ids: list[int]
) -> tuple[EavSourceConfigModel, dict[int, EavAttributeModel]]:
    """Load the attributes and their single approved configuration."""
    result = await db.execute(
        select(EavAttributeModel, EavSourceConfigModel)
        .join(EavSourceConfigModel, EavAttributeModel.config_id == EavSourceConfigModel.id)
        .where(EavAttributeModel.id.in_(attribute_ids))
    )
    rows = list(result.all())
    attributes = {attribute.id: attribute for attribute, _ in rows}
    if missing := set(attribute_ids) - attributes.keys():
        raise SemanticCompileError("UNKNOWN_REFERENCE", "EAV attributes not found", {"attribute_ids": sorted(missing)})
    config = _require_single_config(rows, connection_id)
    return config, attributes


def _require_single_config(
    rows: list[tuple[EavAttributeModel, EavSourceConfigModel]], connection_id: int
) -> EavSourceConfigModel:
    """Ensure every attribute belongs to one approved configuration of this database."""
    configs = {config.id: config for _, config in rows}
    if len(configs) != 1:
        raise SemanticCompileError("INCOMPATIBLE_BASE_ENTITY", "Các thuộc tính EAV phải thuộc cùng một cấu hình nguồn")
    config = next(iter(configs.values()))
    if config.semantic_db_id != connection_id:
        raise SemanticCompileError("UNKNOWN_REFERENCE", "EAV configuration not found", {"config_id": config.id})
    if config.review_status != "approved":
        raise SemanticCompileError(
            "EAV_CONFIG_NOT_APPROVED",
            f"Cấu hình EAV '{config.name}' chưa được phê duyệt",
            {"config_id": config.id},
        )
    return config


def _value_column(config: EavSourceConfigModel, attribute: EavAttributeModel) -> str:
    column = attribute.value_column or (config.value_columns or {}).get(attribute.data_type)
    if not column:
        raise SemanticCompileError(
            "EAV_VALUE_COLUMN_MISSING",
            f"Cấu hình EAV thiếu cột value cho kiểu {attribute.data_type}",
            {"attribute_key": attribute.attribute_key},
        )
    return column


def _rule_agg(attribute: EavAttributeModel, *, metric_role: bool) -> str | None:
    """Map the multi-value rule to a per-entity aggregate; None means reject."""
    rule = attribute.multi_value_rule
    if rule == "reject":
        return None
    if rule in _AGG_ONLY_RULES and (attribute.data_type != "number" or not metric_role):
        target = "thuộc tính kiểu number" if attribute.data_type != "number" else "metric"
        raise SemanticCompileError(
            "EAV_RULE_UNSUPPORTED",
            f"Quy tắc {rule.upper()} chỉ áp dụng cho {target} (thuộc tính {attribute.attribute_key})",
            {"attribute_key": attribute.attribute_key},
        )
    if rule in _AGG_RULES:
        return _AGG_RULES[rule]
    raise SemanticCompileError(
        "EAV_RULE_UNSUPPORTED",
        f"Quy tắc {rule} chưa được hỗ trợ vì không xác định được thứ tự dòng (thuộc tính {attribute.attribute_key})",
        {"attribute_key": attribute.attribute_key},
    )


def _attr_predicate(config: EavSourceConfigModel, key_param: str, dialect: str) -> str:
    """Predicate selecting the rows of one attribute, in either mode."""
    if config.attribute_mode == "dictionary":
        key_column = _quoted(config.dict_key_column or "", dialect)
        label_column = _quoted(config.dict_label_column or "", dialect)
        dict_table = _quoted(config.dict_table or "", dialect)
        fk_column = _quoted(config.attribute_column or "", dialect)
        return (
            f"{fk_column} IN (SELECT {key_column} FROM {dict_table}"  # noqa: S608 - builder, ids quoted, values bound
            f" WHERE {label_column} = :{key_param})"
        )
    code_column = _quoted(config.attribute_column or "", dialect)
    return f"{code_column} = :{key_param}"


def _history_predicates(
    config: EavSourceConfigModel, attribute: EavAttributeModel, dialect: str, as_of: Any, parameters: dict[str, Any]
) -> list[str]:
    """Time predicates for historical attributes; empty for plain attributes."""
    if not attribute.history_enabled:
        return []
    history = config.history or {}
    if not history.get("effective_column"):
        raise SemanticCompileError(
            "EAV_HISTORY_CONFIG_MISSING",
            f"Thuộc tính {attribute.attribute_key} bật history nhưng cấu hình thiếu quy tắc thời gian",
            {"attribute_key": attribute.attribute_key},
        )
    effective = _quoted(history["effective_column"], dialect)
    if as_of is not None:
        parameters["eav_asof"] = as_of
        predicates = [f"{effective} <= :eav_asof"]
        if history.get("end_column"):
            end = _quoted(history["end_column"], dialect)
            predicates.append(f"({end} IS NULL OR {end} > :eav_asof)")
        return predicates
    end_column = history.get("end_column")
    if not end_column:
        raise SemanticCompileError(
            "EAV_AS_OF_REQUIRED",
            "Cấu hình history thiếu end_column — phải chọn thời điểm truy vấn (as_of)"
            f" cho thuộc tính {attribute.attribute_key}",
            {"attribute_key": attribute.attribute_key},
        )
    return [f"{_quoted(end_column, dialect)} IS NULL"]


def _usages(
    config: EavSourceConfigModel,
    attributes: dict[int, EavAttributeModel],
    metrics: list[tuple[int, MetricDefinition]],
    spec: SemanticQuerySpec,
    dialect: str,
    parameters: dict[str, Any],
) -> tuple[list[_Usage], list[tuple[str, dict[str, Any]]]]:
    """Resolve every attribute occurrence into a rendered subquery usage."""
    usages: list[_Usage] = []
    prechecks: list[tuple[str, dict[str, Any]]] = []
    requested = _requested_attributes(metrics, spec)
    for index, (role, identifier, attribute_id) in enumerate(requested, start=1):
        attribute = attributes.get(attribute_id)
        if attribute is None:
            raise SemanticCompileError(
                "UNKNOWN_REFERENCE", f"EAV attribute for {role} not found", {"attribute_id": attribute_id}
            )
        usages.append(
            _build_usage(config, attribute, role, identifier, index, dialect, spec.as_of, parameters, prechecks)
        )
    return usages, prechecks


def _requested_attributes(
    metrics: list[tuple[int, MetricDefinition]], spec: SemanticQuerySpec
) -> list[tuple[str, int, int]]:
    requested = [
        ("metric", metric_id, definition.metric.eav.attribute_id)
        for metric_id, definition in metrics
        if definition.metric.eav is not None
    ]
    requested.extend(("dimension", item.attribute_id, item.attribute_id) for item in spec.eav_dimensions)
    requested.extend(("filter", item.attribute_id, item.attribute_id) for item in spec.eav_filters)
    return requested


def _build_usage(
    config: EavSourceConfigModel,
    attribute: EavAttributeModel,
    role: str,
    identifier: int,
    index: int,
    dialect: str,
    as_of: Any,
    parameters: dict[str, Any],
    prechecks: list[tuple[str, dict[str, Any]]],
) -> _Usage:
    """Render one attribute's per-entity subquery, collecting its precheck."""
    key_param = f"eav_key_{index}"
    parameters[key_param] = attribute.attribute_key
    value_column = _quoted(_value_column(config, attribute), dialect)
    agg = _rule_agg(attribute, metric_role=role == "metric")
    predicates = [_attr_predicate(config, key_param, dialect)]
    predicates.extend(_history_predicates(config, attribute, dialect, as_of, parameters))
    where = " AND ".join(predicates)
    table, entity_column = _quoted(config.entity_table, dialect), _quoted(config.entity_id_column, dialect)
    subquery = _attribute_subquery(table, entity_column, value_column, agg, where)
    if agg is None:
        _append_reject_precheck(prechecks, table, entity_column, where, key_param, parameters)
    return _Usage(
        role=role,
        identifier=identifier,
        attribute=attribute,
        alias=f"eav_{index}",
        agg=agg,
        subquery=subquery,
    )


def _attribute_subquery(table: str, entity_column: str, value_column: str, agg: str | None, where: str) -> str:
    if agg is None:
        return (
            f"(SELECT {entity_column} AS eid, {value_column} AS val"  # noqa: S608 - builder, ids quoted, values bound
            f" FROM {table} WHERE {where})"
        )
    return (
        f"(SELECT {entity_column} AS eid, {agg}({value_column}) AS val"  # noqa: S608 - builder, ids quoted, values bound
        f" FROM {table} WHERE {where} GROUP BY {entity_column})"
    )


def _append_reject_precheck(
    prechecks: list[tuple[str, dict[str, Any]]],
    table: str,
    entity_column: str,
    where: str,
    key_param: str,
    parameters: dict[str, Any],
) -> None:
    precheck_sql = (
        f"SELECT COUNT(*) FROM (SELECT {entity_column} FROM {table} WHERE {where}"  # noqa: S608 - builder, ids quoted
        f" GROUP BY {entity_column} HAVING COUNT(*) > 1) AS dups"
    )
    params = {key: value for key, value in parameters.items() if key == key_param or key == "eav_asof"}
    prechecks.append((precheck_sql, params))


def build_eav_sql(
    config: EavSourceConfigModel,
    attributes: dict[int, EavAttributeModel],
    metrics: list[tuple[int, MetricDefinition]],
    spec: SemanticQuerySpec,
    dialect: str,
) -> BuiltEavQuery:
    """Render one deterministic EAV SELECT with parameters and prechecks."""
    parameters: dict[str, Any] = {}
    usages, prechecks = _usages(config, attributes, metrics, spec, dialect, parameters)
    sql = _assemble(usages, metrics, spec, dialect, parameters)
    return BuiltEavQuery(
        sql=sql,
        parameters=parameters,
        prechecks=prechecks,
        metadata=_metadata(config, attributes, metrics, spec),
    )


def _metadata(
    config: EavSourceConfigModel,
    attributes: dict[int, EavAttributeModel],
    metrics: list[tuple[int, MetricDefinition]],
    spec: SemanticQuerySpec,
) -> dict[str, Any]:
    return {
        "eav": True,
        "config_id": config.id,
        "metrics": {f"metric_{metric_id}": definition.metric.name for metric_id, definition in metrics},
        "dimensions": {
            f"dimension_{item.attribute_id}": attributes[item.attribute_id].label for item in spec.eav_dimensions
        },
    }


def _assemble(
    usages: list[_Usage],
    metrics: list[tuple[int, MetricDefinition]],
    spec: SemanticQuerySpec,
    dialect: str,
    parameters: dict[str, Any],
) -> str:
    """Compose selections, joins, predicates, grouping, ordering, and limit."""
    selections = _selections(usages, metrics)
    parts = ["SELECT\n  " + ",\n  ".join(selections)]
    parts.extend(_from_and_joins(usages))
    where = _where_clause(usages, spec, dialect, parameters)
    if where:
        parts.append(f"WHERE {where}")
    dimension_count = sum(1 for usage in usages if usage.role == "dimension")
    if dimension_count:
        positions = ", ".join(str(index + 1) for index in range(dimension_count))
        parts.append(f"GROUP BY {positions}")
    order = _order_clause(usages, metrics, spec)
    if order:
        parts.append(order)
    parts.append(f"LIMIT {spec.limit}")
    return "\n".join(parts)


def _selections(usages: list[_Usage], metrics: list[tuple[int, MetricDefinition]]) -> list[str]:
    selections = []
    for usage in usages:
        if usage.role == "dimension":
            selections.append(f'{usage.alias}.val AS "dimension_{usage.identifier}"')
    for metric_id, definition in metrics:
        usage = next(item for item in usages if item.role == "metric" and item.identifier == metric_id)
        selections.append(f'{_outer_aggregate(usage, definition)} AS "metric_{metric_id}"')
    return selections


def _outer_aggregate(usage: _Usage, definition: MetricDefinition) -> str:
    function = definition.metric.formula.function.upper()
    if function == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {usage.alias}.val)"
    return f"{function}({usage.alias}.val)"


def _from_and_joins(usages: list[_Usage]) -> list[str]:
    if not usages:
        return []
    clauses = [f"FROM {usages[0].subquery} AS {usages[0].alias}"]
    for usage in usages[1:]:
        join = "LEFT JOIN" if usage.role in {"metric", "dimension"} else "JOIN"
        clauses.append(f"{join} {usage.subquery} AS {usage.alias} ON {usage.alias}.eid = {usages[0].alias}.eid")
    return clauses


def _where_clause(
    usages: list[_Usage], spec: SemanticQuerySpec, dialect: str, parameters: dict[str, Any]
) -> str:
    predicates: list[str] = []
    for index, item in enumerate(spec.eav_filters, start=1):
        usage = next(
            candidate
            for candidate in usages
            if candidate.role == "filter" and candidate.identifier == item.attribute_id
        )
        predicates.extend(_filter_predicate(usage, item, index, dialect, parameters))
    return " AND ".join(predicates)


def _filter_predicate(
    usage: _Usage, item: EavQueryFilter, index: int, dialect: str, parameters: dict[str, Any]
) -> list[str]:
    """Render one EAV filter through the shared coercion and binding rules."""
    column = f"{usage.alias}.val"
    prefix = f"eav_filter_{index}"
    column_type = _EAV_FILTER_TYPES.get(usage.attribute.data_type, "")
    operator, value = item.operator, item.value
    if operator in {"is_null", "is_not_null"}:
        validate_null_filter_value(value, column_type, dialect)
        keyword = "IS NULL" if operator == "is_null" else "IS NOT NULL"
        return [f"{column} {keyword}"]
    if operator in {"in", "not_in"}:
        names = bind_coerced_sequence(value, column_type, dialect, parameters, prefix)
        keyword = "IN" if operator == "in" else "NOT IN"
        return [f"{column} {keyword} ({', '.join(names)})"]
    symbols = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    if operator not in symbols:
        raise SemanticCompileError("UNKNOWN_REFERENCE", f"Unsupported filter operator {operator}")
    placeholder = bind_coerced_parameter(value, column_type, dialect, parameters, prefix)
    return [f"{column} {symbols[operator]} {placeholder}"]


def _order_clause(usages: list[_Usage], metrics: list[tuple[int, MetricDefinition]], spec: SemanticQuerySpec) -> str:
    dimensions = [usage for usage in usages if usage.role == "dimension"]
    if spec.order_by == "metric_desc" and metrics:
        target_id = spec.order_metric_id or metrics[0][0]
        usage = next(item for item in usages if item.role == "metric" and item.identifier == target_id)
        position = (
            len(dimensions) + next(index for index, (metric_id, _) in enumerate(metrics) if metric_id == target_id) + 1
        )
        return f"ORDER BY ({usage.alias}.val) IS NULL, {position} DESC, 1 ASC"
    if spec.order_by == "dimension_desc" and dimensions:
        return f"ORDER BY ({dimensions[0].alias}.val) IS NULL, 1 DESC"
    return ""
