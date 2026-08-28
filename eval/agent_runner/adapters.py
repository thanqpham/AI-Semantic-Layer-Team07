"""Pure adapters from product contracts to evaluation candidate contracts."""

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, cast

from sqlglot import exp

from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.dataset.models import Dialect
from eval.evaluator.schemas import (
    CandidateCanonicalQuery,
    CandidateCompilerOutput,
    CandidateDimension,
    CandidateEnrichmentOutput,
    CandidateEntity,
    CandidateGuardrailOutput,
    CandidateMetricDefinition,
    CandidateMetricFilter,
    CandidateMetricOutput,
    CandidateRelationship,
    CandidateTimeFilter,
    CandidateWhereCondition,
    EvaluationConfig,
)
from eval.evaluator.sql_normalization import (
    SqlValidationError,
    effective_limit,
    normalize_sql,
    parse_single_statement,
)
from src.models.db import CanonicalRelationshipModel, SemanticColumnModel, SemanticTableModel
from src.models.metric_definition import MetricDefinition, MetricFilter
from src.models.schema_metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    Identifier,
    RawSchemaMetadata,
    TableMetadata,
)
from src.models.schemas import SemanticQuerySpec
from src.services.dimension_recommender import is_valid_dimension_column
from src.services.query_compiler import CompiledQuery, validate_read_only

if TYPE_CHECKING:
    from eval.agent_runner.enrichment import EnrichmentState


def to_eval_raw_schema(raw: RawSchemaMetadata) -> dict[str, Any]:
    """Convert product RawSchemaMetadata into the eval RawSchema dict shape."""
    tables = [_convert_table(table) for table in raw.tables]
    relationships = [rel for table in raw.tables for rel in _table_relationships(table)]
    return {"tables": tables, "relationships": relationships}


def _convert_table(table: TableMetadata) -> dict[str, Any]:
    name = _identifier_name(table.table_name)
    foreign_columns = _foreign_key_columns(table)
    columns = [_convert_column(column, foreign_columns) for column in table.columns]
    return {
        "table_name": name,
        "columns": columns,
        "primary_keys": _primary_keys(table),
        "foreign_keys": _foreign_keys(table),
    }


def _identifier_name(identifier: Identifier) -> str:
    """Return the normalized name of an Identifier, falling back to raw."""
    return identifier.normalized_name or identifier.raw_name


def _convert_column(column: ColumnMetadata, foreign_columns: set[str]) -> dict[str, Any]:
    name = _identifier_name(column.column_name)
    return {
        "column_name": name,
        "data_type": column.data_type,
        "is_nullable": column.nullable,
        "is_primary_key": column.primary_key,
        "is_foreign_key": name in foreign_columns,
    }


def _foreign_key_columns(table: TableMetadata) -> set[str]:
    """Return normalized names of all columns participating in any foreign key."""
    return {
        _identifier_name(column) for foreign_key in table.foreign_keys for column in foreign_key.constrained_columns
    }


def _primary_keys(table: TableMetadata) -> list[str]:
    if table.primary_key is None:
        return []
    return [_identifier_name(column) for column in table.primary_key.constrained_columns]


def _foreign_keys(table: TableMetadata) -> list[dict[str, Any]]:
    return [_convert_foreign_key(foreign_key) for foreign_key in table.foreign_keys]


def _convert_foreign_key(foreign_key: ForeignKeyMetadata) -> dict[str, Any]:
    constraint_name = foreign_key.constraint_name
    return {
        "constraint_name": None if constraint_name is None else _identifier_name(constraint_name),
        "constrained_columns": [_identifier_name(c) for c in foreign_key.constrained_columns],
        "referred_schema": _identifier_name(foreign_key.referred_schema),
        "referred_table": _identifier_name(foreign_key.referred_table),
        "referred_columns": [_identifier_name(c) for c in foreign_key.referred_columns],
    }


def _table_relationships(table: TableMetadata) -> list[dict[str, Any]]:
    from_table = _identifier_name(table.table_name)
    return [
        relationship
        for foreign_key in table.foreign_keys
        for relationship in _fk_relationships(from_table, foreign_key)
    ]


def _fk_relationships(from_table: str, foreign_key: ForeignKeyMetadata) -> list[dict[str, Any]]:
    to_table = _identifier_name(foreign_key.referred_table)
    return [
        {
            "from_table": from_table,
            "from_column": _identifier_name(from_column),
            "to_table": to_table,
            "to_column": _identifier_name(to_column),
            "relationship_type": "many_to_one",
        }
        for from_column, to_column in zip(foreign_key.constrained_columns, foreign_key.referred_columns, strict=True)
    ]


_ERROR_CODE_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("Invalid SQL", "SQL_PARSE_ERROR"),
    ("Multi-statement", "MULTI_STATEMENT"),
    ("Only SELECT statements", "NON_SELECT_STATEMENT"),
    ("SELECT INTO", "SELECT_INTO_FORBIDDEN"),
    ("CTE containing DML", "NESTED_DML"),
    ("DDL is not allowed", "DDL_FORBIDDEN"),
)


def _map_error_code(message: str) -> str:
    """Map a product validate_read_only message to a stable error code."""
    for fragment, code in _ERROR_CODE_FRAGMENTS:
        if fragment.lower() in message.lower():
            return code
    return "UNSAFE_SQL"


def _reject_code(sql: str, dialect: str, message: str) -> str:
    """Translate one product rejection into the golden error-code vocabulary.

    The golden vocabulary reports a write inside a rejected multi-statement
    batch as NON_SELECT_STATEMENT (writes outrank statement count), while the
    product validator reports MULTI_STATEMENT first; only that label is
    refined, and only upwards to NON_SELECT_STATEMENT.
    """
    code = _map_error_code(message)
    if code != "MULTI_STATEMENT":
        return code
    try:
        parse_single_statement(sql, cast(Dialect, dialect))
    except SqlValidationError as exc:
        # The engine parser reports writes inside a batch as NON_SELECT_STATEMENT.
        return "NON_SELECT_STATEMENT" if str(exc) == "NON_SELECT_STATEMENT" else code
    return code


class ProductionGuardrailAdapter:
    """GuardrailAdapter backed by the product's real read-only validator.

    The check is layered: the product validator first, then the framework's
    own fail-closed sqlglot validation on top — the same check that guards
    dataset validation and the execution lane. Under evaluation a statement
    must pass both: classes the product validator currently misses (e.g.
    locking reads ``FOR UPDATE``) still fail closed here.

    Satisfies the GuardrailAdapter protocol from eval.evaluator.compiler_eval.
    """

    def __init__(self, config: EvaluationConfig) -> None:
        self._config = config

    async def validate(self, sql: str, dialect: str) -> CandidateGuardrailOutput:
        """Validate SQL with the layered guardrail without ever executing it."""
        try:
            validate_read_only(sql)
        except ValueError as exc:
            return CandidateGuardrailOutput(accepted=False, error_code=_reject_code(sql, dialect, str(exc)))
        try:
            normalize_sql(sql, cast(Dialect, dialect))
        except SqlValidationError as exc:
            return CandidateGuardrailOutput(accepted=False, error_code=str(exc))
        try:
            effective = self._effective_limit(sql, dialect)
        except SqlValidationError as exc:
            return CandidateGuardrailOutput(accepted=False, error_code=str(exc))
        return CandidateGuardrailOutput(
            accepted=True,
            sql=sql,
            effective_limit=effective,
            effective_timeout_seconds=self._config.statement_timeout_seconds,
        )

    def _effective_limit(self, sql: str, dialect: str) -> int:
        """Bound the requested limit, defaulting when absent or zero."""
        requested = effective_limit(sql, cast(Dialect, dialect))
        return min(requested or self._config.default_limit, self._config.maximum_limit)


def to_enrichment_candidate(state: "EnrichmentState", *, resolver: CanonicalResolver) -> CandidateEnrichmentOutput:
    """Convert persisted semantic state into the eval enrichment candidate.

    Entity/dimension/relationship identifiers are resolved to golden canonical
    names via ``resolver`` (exact registry mapping, raw on miss).
    """
    tables_by_id = {table.id: table for table in state.tables}
    relationships = _entity_relationships(state.relationships, tables_by_id, resolver)
    entities = tuple(_candidate_entity(table, relationships.get(table.id, ()), resolver) for table in state.tables)
    return CandidateEnrichmentOutput(entities=entities)


def _candidate_entity(
    table: SemanticTableModel,
    relationships: tuple[CandidateRelationship, ...],
    resolver: CanonicalResolver,
) -> CandidateEntity:
    """Build one candidate entity with canonical names and filtered dimensions."""
    dimensions = tuple(
        CandidateDimension(
            name=resolver.resolve_column(table.table_name, column.column_name),
            business_name=column.business_name,
        )
        for column in table.columns
        if is_valid_dimension_column(column)
    )
    return CandidateEntity(
        entity=resolver.resolve_entity(table.table_name),
        business_name=table.business_name,
        dimensions=dimensions,
        relationships=relationships,
    )


def _entity_relationships(
    relationships: list[CanonicalRelationshipModel],
    tables_by_id: dict[int, SemanticTableModel],
    resolver: CanonicalResolver,
) -> dict[int, tuple[CandidateRelationship, ...]]:
    """Group declared BELONGS_TO candidate relationships by source table id."""
    columns_by_id = _columns_by_id(tables_by_id)
    grouped: dict[int, list[CandidateRelationship]] = {}
    for relationship in relationships:
        pairs = _pair_relationships(relationship, columns_by_id, resolver)
        grouped.setdefault(relationship.from_entity_id, []).extend(pairs)
    return {key: tuple(value) for key, value in grouped.items()}


def _columns_by_id(
    tables_by_id: dict[int, SemanticTableModel],
) -> dict[int, tuple[SemanticTableModel, SemanticColumnModel]]:
    """Index every semantic column by id together with its owning table."""
    return {column.id: (table, column) for table in tables_by_id.values() for column in table.columns}


def _pair_relationships(
    relationship: CanonicalRelationshipModel,
    columns_by_id: dict[int, tuple[SemanticTableModel, SemanticColumnModel]],
    resolver: CanonicalResolver,
) -> list[CandidateRelationship]:
    """Resolve one relationship's column pairs into candidate relationships."""
    results = []
    for pair in relationship.column_pairs or []:
        source = columns_by_id.get(pair.get("from_column_id"))
        target = columns_by_id.get(pair.get("to_column_id"))
        if source is None or target is None:
            continue
        results.append(
            CandidateRelationship(
                source_entity=resolver.resolve_entity(source[0].table_name),
                source_field=source[1].column_name,
                target_entity=resolver.resolve_entity(target[0].table_name),
                target_field=target[1].column_name,
                relation_type="BELONGS_TO",
                inferred=False,
            )
        )
    return results


_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ARITHMETIC_OPERATOR = re.compile(r"[+\-*/]")
_FILTER_SQL_OPERATORS = {
    "eq": "=",
    "neq": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "in": "IN",
    "not_in": "NOT IN",
    "is_null": "IS NULL",
    "is_not_null": "IS NOT NULL",
}


def to_metric_candidate(
    definition: MetricDefinition,
    *,
    allowed_dimensions: list[str],
    source_table: str | None,
    resolver: CanonicalResolver,
) -> CandidateMetricOutput:
    """Map one product metric definition onto the eval candidate contract.

    ``target_entity``/``allowed_dimensions`` are resolved to canonical names;
    ``sql_expression`` is the bare expression because ``aggregation`` already
    carries the function. Golden MIXES conventions (most expressions wrap the
    declared aggregation — ``SUM(quantity)`` — while ``net_revenue`` is bare);
    comparison-side ``unwrap_declared_aggregation`` reconciles both shapes.
    """
    spec = definition.metric
    expression = spec.formula.expression
    metric = CandidateMetricDefinition(
        name=spec.name,
        business_name=spec.name,
        description=spec.excluded_notes or "",
        metric_type=_metric_type(expression),
        target_entity=resolver.resolve_entity(spec.base_entity),
        source_table=source_table or spec.base_entity,
        aggregation=spec.formula.function.lower(),
        field=expression if _BARE_IDENTIFIER.match(expression) else None,
        business_formula="",
        sql_expression=expression,
        default_filters=tuple(CandidateMetricFilter(condition=_render_filter(item)) for item in spec.filters),
        allowed_dimensions=tuple(resolver.resolve_dimension(item) for item in allowed_dimensions),
        # TimeGrain Literal has no empty value — "day" is schema-forced (contract gap, per D6).
        default_time_grain="day",
        status="approved" if spec.status == "approved" else "draft",
    )
    return CandidateMetricOutput(metric=metric)


def _metric_type(expression: str) -> str:
    """Classify a formula expression as derived when it contains arithmetic."""
    return "derived" if _ARITHMETIC_OPERATOR.search(expression) else "simple"


def _render_filter(item: MetricFilter) -> str:
    """Render one fixed metric filter as a readable ``field OP value`` string."""
    operator = _FILTER_SQL_OPERATORS.get(item.operator, item.operator.upper())
    if item.value is None or item.operator in {"is_null", "is_not_null"}:
        return f"{item.field} {operator}"
    if isinstance(item.value, list):
        joined = ", ".join(f"'{entry}'" if isinstance(entry, str) else str(entry) for entry in item.value)
        return f"{item.field} {operator} ({joined})"
    if isinstance(item.value, bool):
        val_str = "TRUE" if item.value else "FALSE"
        return f"{item.field} {operator} {val_str}"
    if isinstance(item.value, str):
        val_str = (
            item.value if (item.value.startswith("'") or item.value.upper() in {"TRUE", "FALSE"}) else f"'{item.value}'"
        )
        return f"{item.field} {operator} {val_str}"
    return f"{item.field} {operator} {item.value}"


_CANONICAL_WHERE_OPERATORS: dict[str, str] = {
    "eq": "=",
    "neq": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "in": "in",
    "not_in": "not_in",
}


def to_compiler_candidate(
    compiled: CompiledQuery,
    *,
    spec: SemanticQuerySpec,
    dimension_names: list[str],
    filter_names: list[str],
    relationship_entities: tuple[str, ...] = (),
    resolver: CanonicalResolver,
    domain: str = "",
    time_grains: tuple[str | None, ...] = (),
) -> CandidateCompilerOutput:
    """Map one compiled semantic query onto the eval compiler candidate contract.

    ``intent`` is fixed to ``metric_query`` (the only pipeline intent) and
    ``domain`` comes from the dataset manifest. Metric names resolve through
    case provenance, entity/dimension names through the golden registry, and
    output column aliases are renamed from ``metric_<id>``/``dimension_<column_id>``
    to the canonical names the golden result columns use — this fixes
    ``result_schema_accuracy``/``sql_execution_accuracy`` (executed column
    names); AST equivalence is already alias-insensitive because
    ``_canonicalize_aliases`` strips all aliases.
    """
    metadata = compiled.metadata or {}
    canonical_names = tuple(resolver.resolve_metric_id(metric_id) for metric_id in spec.metric_ids)
    alias_map = {
        **dict(zip((f"metric_{mid}" for mid in spec.metric_ids), canonical_names, strict=True)),
        **_dimension_alias_map(spec, dimension_names, resolver),
    }
    resolved_dimensions = [resolver.resolve_dimension(name) for name in dimension_names]
    canonical = CandidateCanonicalQuery(
        intent="metric_query",
        domain=domain,
        primary_entity=resolver.resolve_entity(str(metadata.get("base_entity", ""))),
        metrics=canonical_names,
        dimensions=tuple(resolved_dimensions),
        time_filters=_candidate_time_filters(dimension_names, time_grains, resolver),
        where_conditions=_compiled_where_conditions(spec, [resolver.resolve_dimension(f) for f in filter_names]),
        entities_in_path=tuple(resolver.resolve_entity(name) for name in relationship_entities),
    )
    sql = _re_alias_output_columns(
        _inline_parameters(_strip_namespace_placeholder(compiled.sql), compiled.parameters),
        alias_map,
    )
    return CandidateCompilerOutput(canonical_query=canonical, sql=sql)


def _candidate_time_filters(
    dimension_names: list[str],
    time_grains: tuple[str | None, ...],
    resolver: CanonicalResolver,
) -> tuple[CandidateTimeFilter, ...]:
    """Pair each grain-carrying dimension with an unbounded ``all`` range.

    The deterministic pipeline filters no time range: a grain only changes the
    projection (e.g. ``%Y-%m``), so the candidate declares the widest range.
    """
    return tuple(
        CandidateTimeFilter(dimension=resolver.resolve_dimension(name), granularity=grain, range="all")
        for name, grain in zip(dimension_names, time_grains, strict=False)
        if grain is not None
    )


def _dimension_alias_map(
    spec: SemanticQuerySpec,
    dimension_names: list[str],
    resolver: CanonicalResolver,
) -> dict[str, str]:
    """Map compiler ``dimension_<column_id>`` aliases to expected column names.

    Golden result columns are bare canonical names (``channel``); time-grain
    projections alias by grain (``month``). Pairing is positional and safe: the
    query stage derives ``spec.dimensions`` ids from this same ordered list.
    """
    aliases: dict[str, str] = {}
    for selection, name in zip(spec.dimensions, dimension_names, strict=True):
        table, _, field = name.partition(".")
        aliases[f"dimension_{selection.column_id}"] = selection.time_grain or resolver.resolve_column(table, field)
    return aliases


def _re_alias_output_columns(sql: str, alias_map: Mapping[str, str]) -> str:
    """Rename compiler output aliases; fail-open (untouched SQL scores honestly)."""
    if not alias_map:
        return sql
    try:
        expression = parse_single_statement(sql, "sqlite")
    except SqlValidationError:
        return sql
    _rename_aliases(expression, alias_map)
    return expression.sql(dialect="sqlite")


def _rename_aliases(expression: exp.Expression, alias_map: Mapping[str, str]) -> None:
    """Rewrite projection aliases in place where they appear in the map."""
    for projection in expression.expressions:
        if isinstance(projection, exp.Alias) and projection.alias in alias_map:
            projection.set("alias", exp.to_identifier(alias_map[projection.alias], quoted=True))


_DEFAULT_NAMESPACE_TOKEN = re.compile(r'"__default__"\.')


def _strip_namespace_placeholder(sql: str) -> str:
    """Drop the product's namespace-less placeholder qualifier from SQL text.

    The compiler qualifies tables with the ``__default__`` schema when the
    target DB has none (SQLite); the engine's SQLite fixtures are schema-less,
    so the qualifier must go for the execution lane to resolve the tables.
    """
    return _DEFAULT_NAMESPACE_TOKEN.sub("", sql)


def _sql_literal(value: Any) -> str:
    """Render one bound value as a SQL literal (the engine executes raw text)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, datetime):  # datetime is a date subclass — check it first
        return f"'{value.isoformat(sep=' ')}'"
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    if isinstance(value, list | tuple):
        return "(" + ", ".join(_sql_literal(item) for item in value) + ")"
    return "'" + str(value).replace("'", "''") + "'"


def _inline_parameters(sql: str, parameters: dict[str, Any]) -> str:
    """Inline the compiler's named bind values as literals, preserving semantics.

    Values come from ``CompiledQuery.parameters`` — the compiler's own bind
    map — so the rendered statement is exactly what the product would execute
    with those values bound; nothing is inferred or fabricated here.
    """
    for name, value in parameters.items():
        pattern = re.compile(rf":{re.escape(name)}(?![A-Za-z0-9_])")
        sql = pattern.sub(lambda _match, literal=_sql_literal(value): literal, sql)
    return sql


def _compiled_where_conditions(
    spec: SemanticQuerySpec,
    filter_names: list[str],
) -> tuple[CandidateWhereCondition, ...]:
    """Translate semantic runtime filters into canonical where conditions.

    ``is_null``/``is_not_null`` have no operator in the frozen candidate
    contract and are omitted (disclosed v1 limitation).
    """
    conditions: list[CandidateWhereCondition] = []
    for name, item in zip(filter_names, spec.filters, strict=True):
        operator = _CANONICAL_WHERE_OPERATORS.get(item.operator)
        if operator is None:
            continue
        conditions.append(CandidateWhereCondition(dimension=name, operator=operator, value=item.value))
    return tuple(conditions)
