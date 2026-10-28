"""Validate draft metrics using metadata only, including the compiler's actual AST."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import sqlglot
from sqlglot import exp

from src.models.metric_definition import (
    MetricAggregate,
    MetricDefinition,
    MetricFilter,
    MetricFormula,
    MetricGrain,
    MetricPlanFilter,
)
from src.models.metric_review import MetricReview, ReviewIssue
from src.services.metric_definition_resolver import _resolve_filters, _resolve_ratio, expression_tree_for_columns
from src.services.metric_definitions import _validate_expression_columns, _validate_filter_columns
from src.services.metric_hygiene import hygiene_flag_filters


def schema_tables(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept existing map and list metadata envelopes."""
    tables = schema.get("tables", schema)
    if isinstance(tables, list):
        return tables
    return [
        {**table, "table_name": table.get("table_name", name)}
        for name, table in tables.items()
        if isinstance(table, dict)
    ]


def technical_review(
    raw: dict[str, Any], context: dict[str, Any]
) -> tuple[MetricDefinition | None, MetricReview | None]:
    """Canonicalize hygiene and reject drafts the existing compiler cannot represent."""
    try:
        definition = _parse_definition(raw)
        _validate_schema(definition, context["schema"])
        definition.metric.status = "pending_approval"
        definition.diagnostics = []
        return definition, None
    except (ValueError, KeyError, TypeError, sqlglot.errors.SqlglotError) as exc:
        message = str(exc)
        unsupported = (
            "Unsupported expression" in message
            or "UNSUPPORTED_RATIO" in message
            or "DIVISION" in message
            or "Metric plan" in message
            or "metric plan" in message
        )
        issue = ReviewIssue(
            code="UNSUPPORTED" if unsupported else "INVALID_DEFINITION",
            message="Định nghĩa chưa hợp lệ.",
            evidence=message,
            action="Dùng công thức compiler hỗ trợ và đúng metadata; không đổi mục tiêu KPI.",
        )
        return None, MetricReview(
            status="unsupported" if unsupported else "needs_revision",
            summary="Kiểm tra kỹ thuật chưa đạt.",
            issues=[issue],
        )


def _parse_definition(raw: dict[str, Any]) -> MetricDefinition:
    spec = raw.get("metric", raw)
    if not isinstance(spec, dict):
        raise ValueError("metric phải là object.")
    raw_filters = spec.get("filters", [])
    if not isinstance(raw_filters, list):
        raise ValueError("filters phải là danh sách, không được bỏ qua điều kiện sai contract.")
    raw_filters = _named_filters(raw_filters)
    for item in raw_filters:
        MetricFilter.model_validate(item)
    spec = {key: value for key, value in spec.items() if key not in {"grain", "base_entity_id"}}
    spec.update(filters=raw_filters, formula=_unresolved_formula(spec.get("formula")))
    if isinstance(spec.get("query_plan"), dict):
        spec["query_plan"] = _unresolved_query_plan(spec["query_plan"])
    if "ratio" in spec:
        spec["ratio"] = _unresolved_formula({"ratio": spec["ratio"]})["ratio"]
    return MetricDefinition.model_validate({**raw, "metric": spec} if "metric" in raw else spec)


def _unresolved_query_plan(plan: dict[str, Any]) -> dict[str, Any]:
    stages = []
    for stage in plan.get("stages", []):
        clean = {key: value for key, value in stage.items() if key != "column_id"}
        clean["group_by"] = [
            {key: value for key, value in field.items() if key != "column_id"} for field in stage.get("group_by", [])
        ]
        clean["filters"] = _named_filters(stage.get("filters", []))
        clean["aggregates"] = []
        for aggregate in stage.get("aggregates", []):
            clean_aggregate = dict(aggregate)
            clean_aggregate["filters"] = _named_filters(aggregate.get("filters", []))
            clean["aggregates"].append(clean_aggregate)
        stages.append(clean)
    return {**plan, "stages": stages}


def _named_filters(filters: Any) -> Any:
    if not isinstance(filters, list):
        return filters
    return [
        {key: value for key, value in item.items() if key != "column_id"} if isinstance(item, dict) else item
        for item in filters
    ]


def _unresolved_formula(formula: Any) -> Any:
    if not isinstance(formula, dict):
        return formula
    clean = {key: value for key, value in formula.items() if key != "expression_ast"}
    if "filters" in clean:
        clean["filters"] = _named_filters(clean["filters"])
    if isinstance(clean.get("ratio"), dict):
        ratio = dict(clean["ratio"])
        for side in ("numerator", "denominator"):
            ratio[side] = _unresolved_formula(ratio.get(side))
        clean["ratio"] = ratio
    return clean


def _validate_schema(definition: MetricDefinition, schema: dict[str, Any]) -> None:
    if definition.metric.query_plan is not None:
        _validate_query_plan(definition, schema)
        return
    table = next(
        (t for t in schema_tables(schema) if t["table_name"].casefold() == definition.metric.base_entity.casefold()),
        None,
    )
    if table is None:
        raise ValueError("Bảng gốc không tồn tại trong schema.")
    definition.metric.base_entity = table["table_name"]
    columns = _columns(table)
    _validate_expression_columns(definition, columns)
    _validate_filter_columns(definition, columns)
    _validate_grain(definition, columns)
    _validate_compiler_expression(definition, columns)
    definition.metric.filters.extend(
        hygiene_flag_filters(
            [(c.column_name, c.data_type) for c in columns.values()], {f.field for f in definition.metric.filters}
        )
    )
    _validate_filters(definition, columns)
    _resolve_metadata(definition, table, columns)


def _validate_query_plan(definition: MetricDefinition, schema: dict[str, Any]) -> None:
    """Resolve every physical stage against the supplied schema and approved edges."""
    tables = {table["table_name"].casefold(): table for table in schema_tables(schema)}
    relationships = schema.get("relationships", [])
    seen_outputs: dict[str, set[str]] = {}
    physical_table_sets: list[set[str]] = []
    first_source: dict[str, Any] | None = None
    for stage in definition.metric.query_plan.stages:
        if stage.source_stage:
            source_outputs = seen_outputs.get(stage.source_stage)
            if source_outputs is None:
                raise ValueError("Metric plan references a stage that has not been resolved")
            columns = source_outputs
            available_tables: set[str] = set()
        else:
            base = tables.get((stage.base_entity or "").casefold())
            if base is None:
                raise ValueError(f"Metric plan base table does not exist: {stage.base_entity}")
            stage.base_entity = base["table_name"]
            first_source = first_source or base
            available_tables = {stage.base_entity.casefold()}
            for target_name in stage.joins:
                target = tables.get(target_name.casefold())
                if target is None:
                    raise ValueError(f"Metric plan join table does not exist: {target_name}")
                target_name = target["table_name"]
                path = _review_join_path(relationships, stage.base_entity, target_name)
                available_tables.update(name.casefold() for name in path)
                available_tables.add(target_name.casefold())
            physical_table_sets.append(available_tables)
            columns = set()
        if stage.source_stage:
            for field in stage.group_by:
                field.expression = _prior_stage_output(field.expression, stage.source_stage, columns)
                if field.expression not in columns:
                    raise ValueError(f"Unknown prior-stage grouping field: {field.expression}")
            for aggregate in stage.aggregates:
                if aggregate.expression != "*":
                    for reference in sqlglot.parse_one(aggregate.expression).find_all(exp.Column):
                        _prior_stage_output(reference.sql(), stage.source_stage, columns)
                for item in aggregate.filters:
                    item.field = _prior_stage_output(item.field, stage.source_stage, columns)
                    if item.field not in columns:
                        raise ValueError(f"Unknown prior-stage filter field: {item.field}")
            for item in stage.filters:
                item.field = _prior_stage_output(item.field, stage.source_stage, columns)
                if item.field not in columns:
                    raise ValueError("Unknown prior-stage row filter")
        else:
            for field in stage.group_by:
                _validate_plan_column(field.expression, available_tables, tables)
                column = _plan_column(field.expression, available_tables, tables)
                field.column_id = column.get("id")
            for aggregate in stage.aggregates:
                if aggregate.expression != "*":
                    for node in sqlglot.parse_one(aggregate.expression).find_all(exp.Column):
                        _validate_plan_column(node.sql(), available_tables, tables)
                for item in aggregate.filters:
                    _validate_plan_filter(item, available_tables, tables)
                    item.column_id = _plan_column(item.field, available_tables, tables).get("id")
            for item in stage.filters:
                _validate_plan_filter(item, available_tables, tables)
                item.column_id = _plan_column(item.field, available_tables, tables).get("id")
            for table_name in available_tables:
                table = tables[table_name]
                existing_names = {
                    item.field.split(".", 1)[1].casefold()
                    for item in stage.filters
                    if "." in item.field and item.field.split(".", 1)[0].casefold() == table_name
                }
                for generated in hygiene_flag_filters(
                    [(column["column_name"], column.get("data_type", "")) for column in table.get("columns", [])],
                    existing_names,
                ):
                    column = next(
                        column for column in table.get("columns", [])
                        if column["column_name"].casefold() == generated.field.casefold()
                    )
                    stage.filters.append(
                        MetricPlanFilter(
                            field=f"{table['table_name']}.{column['column_name']}",
                            column_id=column.get("id"),
                            operator=generated.operator,
                            value=generated.value,
                        )
                    )
                    existing_names.add(column["column_name"].casefold())
        seen_outputs[stage.name] = {field.name for field in stage.group_by} | {item.name for item in stage.aggregates}
    if definition.metric.filters:
        shared_tables = set.intersection(*physical_table_sets) if physical_table_sets else set()
        for item in definition.metric.filters:
            matches = [
                (table_name, column)
                for table_name in shared_tables
                for column in tables[table_name].get("columns", [])
                if column["column_name"].casefold() == item.field.casefold()
            ]
            if len(matches) != 1:
                raise ValueError(f"Metric plan scope filter must map to one common source column: {item.field}")
            table_name, column = matches[0]
            _validate_plan_filter(item.model_copy(update={"field": f"{table_name}.{column['column_name']}"}), shared_tables, tables)
            item.column_id = column.get("id")
    if first_source is None:
        raise ValueError("Metric plan must include a source table")
    definition.metric.base_entity = first_source["table_name"]
    definition.metric.base_entity_id = first_source.get("id")
    _validate_grain(definition, _columns(first_source))
    definition.schema_version = 3


def _prior_stage_output(reference: str, source_stage: str, outputs: set[str]) -> str:
    """Resolve a bare output alias or source_stage.output alias without allowing cross-stage access."""
    parsed = sqlglot.parse_one(reference)
    if not isinstance(parsed, exp.Column):
        raise ValueError(f"Prior-stage reference must be an output column: {reference}")
    if parsed.table and parsed.table.casefold() != source_stage.casefold():
        raise ValueError(f"Prior-stage reference must use its direct source stage: {reference}")
    if parsed.name not in outputs:
        raise ValueError(f"Unknown prior-stage output: {reference}")
    return parsed.name


def _review_join_path(relationships: list[dict[str, Any]], source: str, target: str) -> list[str]:
    graph: dict[str, list[str]] = {}
    for relation in relationships:
        if relation.get("relationship_type", "").replace("-", "_") == "many_to_one":
            graph.setdefault(relation["from_table"].casefold(), []).append(relation["to_table"])
    queue = [(source.casefold(), [])]
    shortest: int | None = None
    paths: list[list[str]] = []
    while queue:
        current, path = queue.pop(0)
        if shortest is not None and len(path) >= shortest:
            continue
        for neighbor in graph.get(current, []):
            if neighbor.casefold() in {name.casefold() for name in path}:
                continue
            next_path = [*path, neighbor]
            if neighbor.casefold() == target.casefold():
                shortest = len(next_path)
                paths.append(next_path)
            else:
                queue.append((neighbor.casefold(), next_path))
    if len(paths) != 1:
        raise ValueError(f"Metric plan requires one unambiguous many-to-one path: {source} -> {target}")
    return paths[0]


def _validate_plan_column(expression: str, allowed_tables: set[str], tables: dict[str, Any]) -> None:
    for node in sqlglot.parse_one(expression).find_all(exp.Column):
        table_name = node.table.casefold() if node.table else next(iter(allowed_tables))
        if table_name not in allowed_tables:
            raise ValueError(f"Metric plan column table is not declared as a safe join: {node.sql()}")
        _plan_column(node.sql(), allowed_tables, tables)


def _plan_column(reference: str, allowed_tables: set[str], tables: dict[str, Any]) -> dict[str, Any]:
    parsed = sqlglot.parse_one(reference)
    if not isinstance(parsed, exp.Column):
        raise ValueError(f"Metric plan field must be a column reference: {reference}")
    if not parsed.table and len(allowed_tables) > 1:
        raise ValueError(f"Metric plan column must name its table: {reference}")
    table_name = parsed.table.casefold() if parsed.table else next(iter(allowed_tables))
    table = tables.get(table_name)
    column = next((item for item in table.get("columns", []) if item["column_name"].casefold() == parsed.name.casefold()), None) if table else None
    if column is None:
        raise ValueError(f"Metric plan column does not exist: {reference}")
    return column


def _validate_plan_filter(item: Any, allowed_tables: set[str], tables: dict[str, Any]) -> None:
    column = _plan_column(item.field, allowed_tables, tables)
    if item.operator in {"is_null", "is_not_null"}:
        return
    values = item.value if item.operator in {"in", "not_in"} else [item.value]
    for value in values:
        _validate_filter_value(SimpleNamespace(**{
            "column_name": column["column_name"], "data_type": column.get("data_type", ""),
            "allowed_values": column.get("allowed_values"), "allowed_values_complete": column.get("allowed_values_complete", True), "is_nullable": column.get("is_nullable", True),
        }), value)


def _resolve_metadata(definition: MetricDefinition, table: dict[str, Any], columns: dict[str, Any]) -> None:
    by_name = {name.lower(): column for name, column in columns.items()}
    formula = definition.metric.formula
    formula.expression_ast = expression_tree_for_columns(
        formula.expression, {name: c.id for name, c in by_name.items()}
    )
    formula.ratio = _resolve_ratio(formula.ratio, by_name)
    definition.metric.filters = _resolve_filters(definition.metric.filters, by_name)
    definition.metric.base_entity_id = table.get("id")
    if table.get("id"):
        definition.schema_version = 2


def _columns(table: dict[str, Any]) -> dict[str, Any]:
    return {
        c.get("column_name", c.get("name")): SimpleNamespace(
            **{
                **c,
                "column_name": c.get("column_name", c.get("name")),
                "id": c.get("id", i),
                "data_type": c.get("data_type", ""),
                "is_primary_key": c.get("is_primary_key", False),
                "is_nullable": c.get("is_nullable", True),
                "allowed_values": c.get("allowed_values"),
                "allowed_values_complete": c.get("allowed_values_complete", True),
            }
        )
        for i, c in enumerate(table.get("columns", []), 1)
    }


def _validate_grain(definition: MetricDefinition, columns: dict[str, Any]) -> None:
    primary_keys = [column.id for column in columns.values() if column.is_primary_key]
    if not primary_keys:
        raise ValueError("MISSING_GRAIN: chưa xác định khóa chính của bảng gốc.")
    definition.metric.grain = MetricGrain(column_ids=primary_keys)


def _validate_compiler_expression(definition: MetricDefinition, columns: dict[str, Any]) -> None:
    formula = definition.metric.formula
    if formula.ratio is None and sqlglot.parse_one(formula.expression).find(exp.Div):
        raise ValueError("UNSUPPORTED_RATIO: phép chia giữa aggregates phải dùng formula.ratio.")
    _validate_aggregate_expression(formula, columns)
    if formula.ratio is not None:
        for aggregate in (formula.ratio.numerator, formula.ratio.denominator):
            _validate_aggregate_expression(aggregate, columns)


def _validate_aggregate_expression(formula: MetricFormula | MetricAggregate, columns: dict[str, Any]) -> None:
    if formula.expression == "*":
        return
    parsed = sqlglot.parse_one(formula.expression)
    by_name = {name.casefold(): column for name, column in columns.items()}
    expression_tree_for_columns(formula.expression, {name: column.id for name, column in by_name.items()})
    for column in parsed.find_all(exp.Column):
        data_type = by_name[column.name.casefold()].data_type.upper()
        if formula.function in {"SUM", "AVG"} and any(t in data_type for t in ("BOOL", "BIT")):
            raise ValueError("SUM/AVG không hỗ trợ cột boolean hoặc bit.")
    for division in parsed.find_all(exp.Div):
        denominator = division.expression
        if any(
            by_name[c.name.casefold()].is_primary_key or c.name.casefold().endswith("_id")
            for c in division.find_all(exp.Column)
        ):
            raise ValueError("UNSUPPORTED_RATIO: không được chia khóa/ID để tạo KPI tỷ lệ.")
        if not isinstance(denominator, exp.Literal) or not denominator.is_number or float(denominator.this) == 0:
            raise ValueError("UNSAFE_DIVISION: mẫu số có thể bằng không; compiler chưa có primitive chia an toàn.")


def _validate_filters(definition: MetricDefinition, columns: dict[str, Any]) -> None:
    by_name = {name.casefold(): c for name, c in columns.items()}
    filters = list(definition.metric.filters)
    ratio = definition.metric.formula.ratio
    if ratio is not None:
        filters.extend([*ratio.numerator.filters, *ratio.denominator.filters])
    for item in filters:
        column = by_name[item.field.casefold()]
        item.field = column.column_name
        if item.operator in {"is_null", "is_not_null"}:
            continue
        values = item.value if item.operator in {"in", "not_in"} else [item.value]
        if not isinstance(values, list) or not values:
            raise ValueError("Filter IN cần danh sách giá trị không rỗng.")
        for value in values:
            _validate_filter_value(column, value)


def _validate_filter_value(column: Any, value: Any) -> None:
    dtype = column.data_type.upper()
    if value is None or isinstance(value, (dict, list)):
        raise ValueError(f"Filter {column.column_name} cần literal khác NULL.")
    if column.allowed_values and getattr(column, "allowed_values_complete", True) and value not in column.allowed_values:
        raise ValueError(f"Giá trị filter {column.column_name} không có trong metadata khai báo.")
    if "BOOL" in dtype and not isinstance(value, bool):
        raise ValueError(f"Filter {column.column_name} cần true/false.")
    if any(t in dtype for t in ("INT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL", "BIT")):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Filter {column.column_name} cần giá trị số.")
    if any(t in dtype for t in ("CHAR", "TEXT", "DATE", "TIME")) and not isinstance(value, str):
        raise ValueError(f"Filter {column.column_name} cần giá trị chuỗi.")
