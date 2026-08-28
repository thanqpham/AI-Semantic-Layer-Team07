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

#: Aggregates that skip NULL inputs, so ``AGG(CASE WHEN f THEN x END)`` and
#: ``AGG(x) ... WHERE f`` compute the same value.
_NULL_IGNORING_AGGREGATES = (exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Count)


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
    canonical_expression = _canonicalize_semantics(expression.copy())
    canonical = canonical_expression.sql(dialect=_sqlglot_dialect(dialect), normalize=True, pretty=False)
    return NormalizedSql(expression=expression, canonical=canonical)


def structurally_equal(left: str, right: str, dialect: Dialect = "sqlite", *, ignore_limit: bool = False) -> bool:
    """Compare SQL AST structure while ignoring formatting and removable aliases.

    With ``ignore_limit=True`` the top-level LIMIT and ORDER BY are stripped
    from both sides first: LIMIT is a product-mandated guardrail (auto-appended,
    bounded), and ORDER BY is presentation — the execution lane already
    compares row multisets (``ordered=False``), so ordering is not query
    semantics. Golden reference SQL may legitimately omit both.

    Quoted and unquoted identifiers compare equal, and redundant
    parenthesization is stripped: both are rendering choices of the producer
    (the product compiler quotes every identifier and parenthesizes binary
    chains; golden fixtures do not), not query semantics.
    """
    return canonical_sql(left, dialect, ignore_limit=ignore_limit) == canonical_sql(
        right, dialect, ignore_limit=ignore_limit
    )


def canonical_sql(sql: str, dialect: Dialect = "sqlite", *, ignore_limit: bool = False) -> str:
    """Return the exact canonical string ``structurally_equal`` compares.

    Exposed so mismatch diagnostics can show precisely what was compared on
    each side — the diagnostic and the comparison can never drift apart.
    """
    normalized = normalize_sql(sql, dialect)
    if ignore_limit:
        normalized = _without_presentation_clauses(normalized, dialect)
    return normalized.canonical


def _without_presentation_clauses(normalized: NormalizedSql, dialect: Dialect) -> NormalizedSql:
    """Return the same normalized SQL with top-level ORDER BY and LIMIT removed."""
    expression = _canonicalize_semantics(normalized.expression.copy())
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
    canonical = _canonicalize_semantics(cast(exp.Expression, parsed[0]).copy())
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
    canonical = _canonicalize_semantics(target.copy())
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
    if expression.find(exp.Lock) is not None:
        raise SqlValidationError("UNSAFE_SQL")
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


def _canonicalize_semantics(expression: exp.Expression) -> exp.Expression:
    """Apply every non-semantic rendering canonicalization in one pipeline.

    Order matters only in that alias canonicalization must see the original
    column/table qualifiers; the remaining steps are rendering-only rewrites
    (identifier quoting, boolean literal convention, parenthesization), and
    the conditional-aggregate rewrite runs last so the condition it copies
    into every CASE branch is itself already canonical.
    """
    return _canonicalize_conditional_aggregates(
        _canonicalize_parens(_canonicalize_booleans(_canonicalize_identifier_quotes(_canonicalize_aliases(expression))))
    )


def _canonicalize_conditional_aggregates(expression: exp.Expression) -> exp.Expression:
    """Rewrite ``AGG(x) ... WHERE f`` into ``AGG(CASE WHEN f THEN x END)``.

    For NULL-ignoring aggregates both spellings compute the same value, and
    the golden dataset mixes the conventions: golden SQL conditions inside
    CASE while the product compiler lifts the same metric filters into
    WHERE. Rewriting the WHERE form onto the CASE form — applied to both
    compared sides — removes that presentation difference.

    Fail-closed: set operations, projection subqueries, window functions,
    HAVING, already-conditioned aggregates, and explicit FILTER clauses all
    skip the rewrite, so such sides compare as written (honest mismatch,
    never a false equal). With GROUP BY the CASE form retains empty groups
    that WHERE drops; accepted because golden treats both spellings as one
    intent.
    """
    if not isinstance(expression, exp.Select):
        return expression
    where = expression.args.get("where")
    if where is None or expression.args.get("having") is not None:
        return expression
    if any(p.find(exp.Select, exp.Window) is not None for p in expression.expressions):
        return expression
    aggregates = tuple(a for p in expression.expressions for a in p.find_all(*_NULL_IGNORING_AGGREGATES))
    if not aggregates or any(_conditioned(a) for a in aggregates):
        return expression
    condition = where.this
    for aggregate in aggregates:
        aggregate.replace(_case_wrapped(aggregate, condition))
    expression.set("where", None)
    return expression


def _conditioned(aggregate: exp.Expression) -> bool:
    """Report whether the aggregate already carries its own condition."""
    if aggregate.args.get("filter") is not None:
        return True
    argument = aggregate.this
    if isinstance(argument, exp.Distinct):
        argument = argument.expressions[0] if argument.expressions else None
    return isinstance(argument, exp.Case)


def _case_wrapped(aggregate: exp.Expression, condition: exp.Expression) -> exp.Expression:
    """Return the same aggregate with its argument guarded by the condition."""
    if isinstance(aggregate.this, exp.Distinct):
        distinct = aggregate.this.copy()
        distinct.set("expressions", [_guarded(distinct.expressions[0], condition)])
        return aggregate.__class__(this=distinct)
    return aggregate.__class__(this=_guarded(aggregate.this, condition))


def _guarded(argument: exp.Expression, condition: exp.Expression) -> exp.Case:
    """Return ``CASE WHEN condition THEN argument END`` (``COUNT(*)`` counts 1)."""
    inner = exp.Literal.number(1) if isinstance(argument, exp.Star) else argument.copy()
    return exp.Case(ifs=[exp.If(this=condition.copy(), true=inner)])


def _canonicalize_identifier_quotes(expression: exp.Expression) -> exp.Expression:
    """Drop identifier quoting so quoted and bare names compare equal.

    SQLite resolves ``"column"`` and ``column`` identically; quoting is a
    rendering choice of the producer (the product compiler quotes every
    identifier, golden fixtures do not), not query semantics.
    """
    for identifier in expression.find_all(exp.Identifier):
        identifier.set("quoted", False)
    return expression


def _canonicalize_parens(expression: exp.Expression) -> exp.Expression:
    """Strip redundant parenthesization until none remain.

    Parenthesization encodes nothing the AST does not already encode, and
    producers differ: the product compiler parenthesizes every binary chain
    (``((a - b) - c)``) while golden fixtures write ``a - b - c``. A single
    ``transform`` pass cannot unwrap nested ``Paren`` wrappers (replaced
    subtrees are not revisited), so the pass repeats until fixpoint.
    """
    result = expression
    while any(isinstance(node, exp.Paren) for node in result.find_all(exp.Paren)):
        result = result.transform(lambda node: node.this if isinstance(node, exp.Paren) else node)
    return result


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
