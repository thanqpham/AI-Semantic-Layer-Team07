"""Fail-closed SQL parsing and structural canonicalization with sqlglot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from eval.dataset.models import Dialect

_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Merge,
    exp.TruncateTable,
)
_FORBIDDEN_FUNCTIONS = {"load_extension", "pg_sleep", "readfile", "writefile"}


@dataclass(frozen=True)
class NormalizedSql:
    """Contain a safe parsed expression and its canonical representation."""

    expression: exp.Expression
    canonical: str


class SqlValidationError(ValueError):
    """Report a safe SQL parsing or read-only validation failure."""


def normalize_sql(sql: str, dialect: Dialect = "sqlite") -> NormalizedSql:
    """Parse one read-only query and remove non-semantic alias differences."""
    expression = parse_single_statement(sql, dialect)
    _validate_read_only(expression)
    canonical_expression = _canonicalize_booleans(_canonicalize_aliases(expression.copy()))
    canonical = canonical_expression.sql(dialect=_sqlglot_dialect(dialect), normalize=True, pretty=False)
    return NormalizedSql(expression=expression, canonical=canonical)


def structurally_equal(left: str, right: str, dialect: Dialect = "sqlite", *, ignore_limit: bool = False) -> bool:
    """Compare SQL AST structure while ignoring formatting and removable aliases.

    With ``ignore_limit=True`` the top-level LIMIT and ORDER BY are stripped
    from both sides first: LIMIT is a product-mandated guardrail (auto-appended,
    bounded), and ORDER BY is presentation — the execution lane already
    compares row multisets (``ordered=False``), so ordering is not query
    semantics. Golden reference SQL may legitimately omit both.
    """
    left_sql, right_sql = normalize_sql(left, dialect), normalize_sql(right, dialect)
    if ignore_limit:
        left_sql = _without_presentation_clauses(left_sql, dialect)
        right_sql = _without_presentation_clauses(right_sql, dialect)
    return left_sql.canonical == right_sql.canonical


def _without_presentation_clauses(normalized: NormalizedSql, dialect: Dialect) -> NormalizedSql:
    """Return the same normalized SQL with top-level ORDER BY and LIMIT removed."""
    expression = _canonicalize_booleans(_canonicalize_aliases(normalized.expression.copy()))
    expression.set("order", None)
    expression.set("limit", None)
    canonical = expression.sql(dialect=_sqlglot_dialect(dialect), normalize=True, pretty=False)
    return NormalizedSql(expression=expression, canonical=canonical)


def parse_single_statement(sql: str, dialect: Dialect = "sqlite") -> exp.Expression:
    """Parse exactly one non-empty SQL statement."""
    try:
        statements = [statement for statement in parse(sql, read=_sqlglot_dialect(dialect)) if statement is not None]
    except ParseError as exc:
        raise SqlValidationError("SQL_PARSE_ERROR") from exc
    if len(statements) != 1:
        if any(_contains_write(statement) for statement in statements):
            raise SqlValidationError("NON_SELECT_STATEMENT")
        raise SqlValidationError("MULTI_STATEMENT")
    return cast(exp.Expression, statements[0])


def effective_limit(sql: str, dialect: Dialect = "sqlite") -> int | None:
    """Read a literal top-level LIMIT from one safe query."""
    expression = normalize_sql(sql, dialect).expression
    limit = expression.args.get("limit")
    if limit is None:
        return None
    value = limit.expression
    if not isinstance(value, exp.Literal) or not value.is_int:
        raise SqlValidationError("NON_LITERAL_LIMIT")
    return int(value.this)


def normalize_expression(value: str, dialect: Dialect = "sqlite") -> str:
    """Canonicalize a SQL expression used by metric fields or filters."""
    try:
        parsed = parse(value, read=_sqlglot_dialect(dialect))
    except ParseError:
        return " ".join(value.casefold().split())
    if len(parsed) != 1 or parsed[0] is None:
        return " ".join(value.casefold().split())
    canonical = _canonicalize_booleans(cast(exp.Expression, parsed[0]).copy())
    return canonical.sql(dialect=_sqlglot_dialect(dialect), normalize=True, pretty=False)


_AggregationWrapper = tuple[type[exp.Expression], bool]

#: Declared aggregation -> (wrapper node class, expects a DISTINCT argument).
#: "ratio" is absent on purpose: a ratio is inherently arithmetic at the top level.
_AGGREGATION_WRAPPERS: dict[str, _AggregationWrapper] = {
    "sum": (exp.Sum, False),
    "count": (exp.Count, False),
    "count_distinct": (exp.Count, True),
    "avg": (exp.Avg, False),
    "min": (exp.Min, False),
    "max": (exp.Max, False),
}


def unwrap_declared_aggregation(value: str, aggregation: str | None, dialect: Dialect = "sqlite") -> str:
    """Canonicalize a metric expression, stripping one matching top-level wrapper.

    Golden metric SQL mixes conventions: most expressions wrap the declared
    aggregation (``SUM(quantity)`` with aggregation ``sum``) while others stay
    bare (``quantity`` with aggregation ``sum``). Stripping a single top-level
    aggregation call when — and only when — it matches that side's own declared
    ``aggregation`` makes both shapes comparable without loosening: a wrapper
    contradicting the declaration (e.g. ``COUNT(x)`` with ``sum``) is kept, and
    unparsable text falls back to plain canonicalization (honest mismatch).
    """
    try:
        node = parse_single_statement(value, dialect)
    except SqlValidationError:
        return normalize_expression(value, dialect)
    wrapper = _AGGREGATION_WRAPPERS.get(aggregation or "")
    inner = _wrapper_inner(node, wrapper) if wrapper is not None else None
    target = node if inner is None else inner
    canonical = _canonicalize_booleans(target.copy())
    return canonical.sql(dialect=_sqlglot_dialect(dialect), normalize=True, pretty=False)


def _wrapper_inner(node: exp.Expression, wrapper: _AggregationWrapper) -> exp.Expression | None:
    """Return the wrapped argument when node is exactly the declared call."""
    wrapper_class, expects_distinct = wrapper
    if not isinstance(node, wrapper_class) or node.this is None:
        return None
    if isinstance(node.this, exp.Distinct):
        if not expects_distinct or not node.this.expressions:
            return None
        return node.this.expressions[0]
    return None if expects_distinct else node.this


def _sqlglot_dialect(dialect: Dialect) -> str:
    return "postgres" if dialect == "postgresql" else dialect


def _validate_read_only(expression: exp.Expression) -> None:
    if isinstance(expression, _WRITE_NODES):
        raise SqlValidationError("NON_SELECT_STATEMENT")
    if _contains_write(expression):
        raise SqlValidationError("NESTED_DML")
    if expression.find(exp.Into) is not None:
        raise SqlValidationError("SELECT_INTO_FORBIDDEN")
    if not isinstance(expression, exp.Query):
        raise SqlValidationError("NON_SELECT_STATEMENT")
    for function in expression.find_all(exp.Anonymous):
        if function.name.casefold() in _FORBIDDEN_FUNCTIONS:
            raise SqlValidationError("FORBIDDEN_FUNCTION")


def _contains_write(expression: exp.Expression) -> bool:
    return expression.find(*_WRITE_NODES) is not None


def _canonicalize_booleans(expression: exp.Expression) -> exp.Expression:
    """Rewrite boolean literals as integers (SQLite semantics: FALSE=0, TRUE=1).

    The golden reference writes ``is_test_order = FALSE`` while the product
    prompt convention is ``0``/``1`` for binary flags — both are the same
    value in SQLite, so comparisons must canonicalize them.
    """
    return expression.transform(
        lambda node: exp.Literal.number(1 if node.this else 0) if isinstance(node, exp.Boolean) else node
    )


def _canonicalize_aliases(expression: exp.Expression) -> exp.Expression:
    tables = tuple(expression.find_all(exp.Table))
    table_aliases = _table_aliases(tables)
    single_table = len(tables) == 1
    for column in expression.find_all(exp.Column):
        if column.table in table_aliases:
            column.set("table", table_aliases[column.table])
        if single_table:
            column.set("table", None)
    _canonicalize_table_nodes(tables, single_table)
    for alias in tuple(expression.find_all(exp.Alias)):
        alias.replace(alias.this)
    return expression


def _table_aliases(tables: tuple[exp.Table, ...]) -> dict[str, str]:
    return {table.alias or table.name: f"_t{index}" for index, table in enumerate(tables, start=1)}


def _canonicalize_table_nodes(tables: tuple[exp.Table, ...], single_table: bool) -> None:
    for index, table in enumerate(tables, start=1):
        alias = None if single_table else exp.TableAlias(this=exp.Identifier(this=f"_t{index}"))
        table.set("alias", alias)
