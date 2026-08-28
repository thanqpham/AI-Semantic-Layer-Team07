"""Selection-only resolver: pick approved metrics/dimensions for a question."""

from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db import CanonicalRelationshipModel, SemanticMetricModel, SemanticTableModel
from src.services.dimension_recommender import is_valid_dimension_column
from src.services.llm import get_llm
from src.services.llm_caller import parse_llm_json

MAX_ATTEMPTS = 3
MAX_TRACE_OUTPUT = 4000
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
ALLOWED_OPERATORS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "is_not_null"})
TIME_GRAINS = frozenset({"day", "week", "month", "quarter", "year"})

#: Relationship types whose direction the compiler can join along (child -> parent).
_MANY_TO_ONE_TYPES = frozenset({"many_to_one", "belongs_to", "n:1", "one_to_one", "1:1", "has_one"})

SYSTEM_PROMPT = (
    "Bạn là bước resolver của semantic layer. Nhiệm vụ duy nhất: CHỌN từ danh mục "
    "đã duyệt. Chỉ chọn tên trong danh mục đã duyệt; trả đúng JSON; không sinh tên mới. "
    'Trả về JSON: {"metrics": [tên metric], "dimensions": ["entity.column"], '
    '"filters": [{"dimension": "entity.column", "operator": op, "value": v}], "limit": n, '
    '"time_dimension": "entity.column", "time_grain": "day|week|month|quarter|year"}. '
    "operator chỉ thuộc: eq, neq, gt, gte, lt, lte, in, not_in, is_null, is_not_null. "
    "time_dimension/time_grain chỉ đặt khi câu hỏi phân nhóm theo thời gian "
    "(ví dụ 'doanh thu theo tháng'); khi không dùng thì bỏ hai khóa này. "
    "Chỉ chọn dimension khi câu hỏi YÊU CẦU phân nhóm theo dimension đó "
    "(ví dụ: 'doanh thu theo kênh', 'số đơn theo tháng'); câu hỏi chỉ hỏi "
    "tổng số thì PHẢI trả về dimensions là danh sách rỗng. "
    "Dimension đã chọn phải thuộc entity (bảng) của metric đã chọn, hoặc thuộc entity "
    "nối được với metric qua các relationship đã duyệt (xem phần RELATIONSHIPS). "
    "Nếu câu hỏi mơ hồ không thể chọn duy nhất metric hoặc dimension, trả về "
    '{"clarify": true, "question": "<câu hỏi làm rõ cho người dùng>"}. '
    'Nếu không metric nào trong danh mục thực sự trả lời câu hỏi, trả về {"metrics": [], "abstain": true}.'
)

#: Destructive verbs (ASCII after diacritics stripping) that start an unsafe question.
_UNSAFE_INTENT_PREFIXES = (
    "xoa ",
    "huy ",
    "drop ",
    "delete ",
    "truncate ",
    "alter ",
    "insert ",
    "update ",
)


def _strip_diacritics(text: str) -> str:
    """Lower-case and remove Vietnamese diacritics ('Xóa' -> 'xoa')."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _is_unsafe_intent(question: str) -> bool:
    """Detect a data-modifying request by its leading verb; deterministic heuristic."""
    normalized = _strip_diacritics(question).strip()
    return normalized.startswith(_UNSAFE_INTENT_PREFIXES)


class ResolverError(Exception):
    """Fail-closed resolver failure carrying a stable machine code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CatalogMetric:
    """One approved metric offered to the resolver."""

    name: str
    description: str | None
    base_entity: str
    aggregation: str


@dataclass(frozen=True)
class CatalogDimension:
    """One valid group-by dimension offered to the resolver."""

    entity: str
    column: str
    business_name: str | None
    entity_business_name: str | None = None


@dataclass(frozen=True)
class CatalogRelationship:
    """One approved join edge between two catalog entities."""

    source_entity: str
    target_entity: str
    relation_type: str


@dataclass(frozen=True)
class ResolverCatalog:
    """The approved catalog one resolver invocation may select from."""

    metrics: tuple[CatalogMetric, ...]
    dimensions: tuple[CatalogDimension, ...]
    relationships: tuple[CatalogRelationship, ...] = ()


@dataclass(frozen=True)
class ResolverFilter:
    """One validated predicate over a catalog dimension."""

    dimension: str  # "entity.column"
    operator: str  # eq|neq|gt|gte|lt|lte|in|not_in|is_null|is_not_null
    value: object


@dataclass(frozen=True)
class ResolverSelection:
    """The validated selection consumed by the query stage."""

    metric_names: tuple[str, ...]
    dimensions: tuple[str, ...]
    filters: tuple[ResolverFilter, ...]
    limit: int
    time_dimension: str | None = None  # "entity.column" of a selected time dimension
    time_grain: str | None = None  # day|week|month|quarter|year


@dataclass(frozen=True)
class ResolverAttempt:
    """One resolver LLM attempt: its raw output and why it was rejected."""

    raw_output: str
    error_code: str | None  # None when the attempt was accepted
    error_message: str


@dataclass
class ResolverTrace:
    """Per-invocation resolver evidence, collected only when a trace is passed."""

    question: str
    catalog_size: dict[str, int] = field(default_factory=dict)
    attempts: list[ResolverAttempt] = field(default_factory=list)
    outcome: str = ""  # "passed" | final error code, set by the query stage


async def build_catalog(db: AsyncSession, conn_id: int) -> ResolverCatalog:
    """Load approved metrics and valid dimensions for one connection."""
    tables_stmt = (
        select(SemanticTableModel)
        .where(SemanticTableModel.db_id == conn_id)
        .options(selectinload(SemanticTableModel.columns))
    )
    tables = list((await db.execute(tables_stmt)).scalars().all())
    metrics_stmt = select(SemanticMetricModel).where(
        SemanticMetricModel.db_id == conn_id,
        SemanticMetricModel.status == "approved",
    )
    metrics = (await db.execute(metrics_stmt)).scalars().all()
    names_by_id = {table.id: table.table_name for table in tables}
    return ResolverCatalog(
        metrics=tuple(_catalog_metric(row, names_by_id) for row in metrics),
        dimensions=_catalog_dimensions(tables),
        relationships=await _catalog_relationships(db, conn_id),
    )


async def _catalog_relationships(db: AsyncSession, conn_id: int) -> tuple[CatalogRelationship, ...]:
    """Load approved join edges for one connection as entity-name pairs."""
    stmt = (
        select(CanonicalRelationshipModel)
        .where(CanonicalRelationshipModel.connection_id == conn_id)
        .options(
            selectinload(CanonicalRelationshipModel.from_entity),
            selectinload(CanonicalRelationshipModel.to_entity),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return tuple(
        CatalogRelationship(
            source_entity=row.from_entity.table_name,
            target_entity=row.to_entity.table_name,
            relation_type=row.relationship_type,
        )
        for row in rows
        if row.from_entity is not None and row.to_entity is not None
    )


def _catalog_metric(row: SemanticMetricModel, names_by_id: dict[int, str]) -> CatalogMetric:
    """Project one approved metric row into a catalog entry."""
    spec = (row.definition or {}).get("metric", {})
    formula = spec.get("formula", {})
    description = spec.get("excluded_notes") or row.description or None
    return CatalogMetric(
        name=row.name or spec.get("name", ""),
        description=description,
        base_entity=spec.get("base_entity") or names_by_id.get(row.base_entity_id or -1, ""),
        aggregation=formula.get("function", "") or (row.aggregation_type or ""),
    )


def _catalog_dimensions(tables: list[SemanticTableModel]) -> tuple[CatalogDimension, ...]:
    """Flatten selectable dimension columns (time included) across the connection's tables.

    The product rule (``is_valid_dimension_column``) excludes time columns —
    it governs generic dimension recommendation. The resolver needs them back:
    questions like "doanh thu theo tháng" must be able to select the time
    dimension and its grain, so the eval catalog re-adds columns flagged
    ``is_time_dimension`` on top of the product rule.
    """
    return tuple(
        CatalogDimension(
            entity=table.table_name,
            column=column.column_name,
            business_name=column.business_name or None,
            entity_business_name=table.business_name or None,
        )
        for table in tables
        for column in table.columns
        if is_valid_dimension_column(column) or column.is_time_dimension
    )


async def resolve_question(
    question: str,
    catalog: ResolverCatalog,
    llm: BaseChatModel | None = None,
    *,
    trace: ResolverTrace | None = None,
) -> ResolverSelection:
    """Resolve a natural-language question to a catalog-only selection."""
    if _is_unsafe_intent(question):
        raise ResolverError("UNSAFE_INTENT", "question requests a data-modifying action")
    model = llm or get_llm()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=_user_prompt(question, catalog)),
    ]
    error = ResolverError("RESOLVER_INVALID_OUTPUT")
    for _attempt in range(MAX_ATTEMPTS):
        content = await _invoke_model(model, messages, trace)
        try:
            payload = parse_llm_json(content)
        except ValueError as exc:
            error = ResolverError("RESOLVER_INVALID_OUTPUT", f"JSON parse failed: {exc}")
            _record_attempt(trace, content, error)
            continue
        try:
            selection = _validate_selection(payload, catalog)
        except ResolverError as exc:
            _record_attempt(trace, content, exc)
            if exc.code != "RESOLVER_SCOPE_VIOLATION":
                raise
            error = exc
            messages = [*messages, HumanMessage(content=_scope_feedback(exc))]
            continue
        _record_attempt(trace, content, None)
        return selection
    raise error


async def _invoke_model(
    model: BaseChatModel,
    messages: list,
    trace: ResolverTrace | None,
) -> str:
    """Invoke the model once; record transport failures into the trace."""
    try:
        return (await model.ainvoke(messages)).content
    except Exception as exc:
        _record_attempt(trace, "", ResolverError("RESOLVER_LLM_ERROR", f"{type(exc).__name__}: {exc}"))
        raise


def _record_attempt(trace: ResolverTrace | None, content: str, error: ResolverError | None) -> None:
    """Append one attempt to the trace when one is being collected."""
    if trace is None:
        return
    trace.attempts.append(
        ResolverAttempt(
            raw_output=content[:MAX_TRACE_OUTPUT],
            error_code=None if error is None else error.code,
            error_message="" if error is None else error.message,
        )
    )


def _user_prompt(question: str, catalog: ResolverCatalog) -> str:
    """Render the question plus the approved catalog for the LLM."""
    lines = [f"Câu hỏi: {question}", "", "METRICS (tên — mô tả):"]
    for metric in catalog.metrics:
        lines.append(f"- {metric.name} — {metric.description or ''}")
    lines.append("DIMENSIONS (entity.column — tên nghiệp vụ):")
    for dimension in catalog.dimensions:
        lines.append(
            f"- {dimension.entity}.{dimension.column} — {dimension.business_name or ''} "
            f"(bảng: {dimension.entity_business_name or dimension.entity})"
        )
    if catalog.relationships:
        lines.append("RELATIONSHIPS (entity -> entity):")
        for relationship in catalog.relationships:
            lines.append(f"- {relationship.source_entity} -> {relationship.target_entity}")
    lines.append(
        "Chỉ trả JSON đúng schema đã nêu, không giải thích. Chỉ chọn dimension khi câu hỏi "
        "yêu cầu phân nhóm theo dimension đó; ngược lại để dimensions rỗng."
    )
    return "\n".join(lines)


def _validate_selection(payload: Any, catalog: ResolverCatalog) -> ResolverSelection:
    """Validate one parsed payload against the catalog; raise ResolverError when invalid."""
    if not isinstance(payload, dict):
        raise ResolverError("RESOLVER_INVALID_OUTPUT", "payload is not a JSON object")
    metric_names = _string_list(payload, "metrics")
    if not metric_names:
        if payload.get("clarify") is True:
            raise _clarify_error(payload)
        if payload.get("abstain") is True:
            raise ResolverError("UNKNOWN_METRIC", "no catalog metric answers the question")
        raise ResolverError("RESOLVER_INVALID_OUTPUT", "metrics must be a non-empty list")
    dimension_names = tuple(f"{d.entity}.{d.column}" for d in catalog.dimensions)
    metrics = tuple(_match_name(name, [m.name for m in catalog.metrics], "METRIC") for name in metric_names)
    time_dimension, time_grain = _validate_time_selection(payload, dimension_names)
    dimensions = _merge_time_dimension(
        tuple(_match_name(name, dimension_names, "DIMENSION") for name in _string_list(payload, "dimensions")),
        time_dimension,
    )
    _scope_check(dimensions, metrics, catalog)
    filters = _validate_filters(payload.get("filters"), dimension_names)
    return ResolverSelection(
        metric_names=metrics,
        dimensions=dimensions,
        filters=filters,
        limit=_clamp_limit(payload.get("limit")),
        time_dimension=time_dimension,
        time_grain=time_grain,
    )


def _clarify_error(payload: dict[str, Any]) -> ResolverError:
    """Build the NEEDS_CLARIFICATION error from one clarify payload."""
    question = str(payload.get("question") or "").strip()
    if not question:
        return ResolverError("RESOLVER_INVALID_OUTPUT", "clarify requires a non-empty question")
    return ResolverError("NEEDS_CLARIFICATION", question)


def _validate_time_selection(
    payload: dict[str, Any],
    dimension_names: tuple[str, ...],
) -> tuple[str | None, str | None]:
    """Validate the optional time_dimension/time_grain pair against the catalog."""
    grain = payload.get("time_grain")
    if grain is None and payload.get("time_dimension") is None:
        return None, None
    if grain not in TIME_GRAINS:
        raise ResolverError("RESOLVER_INVALID_OUTPUT", f"time_grain must be one of {sorted(TIME_GRAINS)}")
    dimension = _match_name(str(payload.get("time_dimension") or ""), dimension_names, "DIMENSION")
    return dimension, str(grain)


def _merge_time_dimension(dimensions: tuple[str, ...], time_dimension: str | None) -> tuple[str, ...]:
    """Fold the declared time dimension into the selection's dimensions.

    The prompt's "leave dimensions empty without grouping" rule makes LLMs
    omit the time dimension from ``dimensions`` while still declaring it via
    ``time_dimension``/``time_grain`` — the declared intent is unambiguous,
    so the pair is reconciled instead of rejected. The merged dimension then
    goes through the same scope check as every other selected dimension.
    """
    if time_dimension is None or time_dimension in dimensions:
        return dimensions
    return (*dimensions, time_dimension)


def _scope_check(dimensions: tuple[str, ...], metric_names: tuple[str, ...], catalog: ResolverCatalog) -> None:
    """Reject dimensions not joinable from the selected metrics' entities."""
    allowed = {m.base_entity for m in catalog.metrics if m.name in metric_names}
    if not allowed:
        return
    reachable = _reachable_entities(allowed, catalog.relationships)
    violating = tuple(d for d in dimensions if d.split(".", 1)[0] not in reachable)
    if not violating:
        return
    legal = tuple(f"{d.entity}.{d.column}" for d in catalog.dimensions if d.entity in reachable)
    raise ResolverError(
        "RESOLVER_SCOPE_VIOLATION",
        f"dimensions {violating} cannot be joined to the selected metrics' entities; legal dimensions: {legal}",
    )


def _reachable_entities(roots: set[str], relationships: tuple[CatalogRelationship, ...]) -> set[str]:
    """Close roots over many-to-one edges — the direction the compiler joins."""
    forward: dict[str, set[str]] = {}
    for relationship in relationships:
        if relationship.relation_type.lower() in _MANY_TO_ONE_TYPES:
            forward.setdefault(relationship.source_entity, set()).add(relationship.target_entity)
    seen = set(roots)
    queue = list(roots)
    while queue:
        for neighbor in forward.get(queue.pop(), ()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def _scope_feedback(error: ResolverError) -> str:
    """Render the retry message for one scope violation."""
    return (
        f"Lỗi phạm vi: {error.message}. Hãy chọn dimension thuộc entity (bảng) "
        "của metric đã chọn hoặc entity nối được qua RELATIONSHIPS, và trả lại JSON đúng schema."
    )


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    """Extract a list-of-strings field; anything else is invalid output."""
    raw = payload.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ResolverError("RESOLVER_INVALID_OUTPUT", f"{key} must be a list of strings")
    return raw


def _match_name(name: str, catalog_names: list[str] | tuple[str, ...], kind: str) -> str:
    """Return name only on an exact catalog hit; never auto-correct a miss."""
    if name in catalog_names:
        return name
    close = difflib.get_close_matches(name, catalog_names, n=2)
    if len(close) >= 2:
        raise ResolverError(f"AMBIGUOUS_{kind}", f"{name!r} closely matches {close}")
    raise ResolverError(f"UNKNOWN_{kind}", f"{name!r} is not in the approved catalog")


def _validate_filters(raw: Any, dimension_names: tuple[str, ...]) -> tuple[ResolverFilter, ...]:
    """Validate the filters field; missing means no filters."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ResolverError("RESOLVER_INVALID_OUTPUT", "filters must be a list")
    return tuple(_validate_filter(item, dimension_names) for item in raw)


def _validate_filter(item: Any, dimension_names: tuple[str, ...]) -> ResolverFilter:
    """Validate one filter entry: known dimension, allowed operator, raw value."""
    if not isinstance(item, dict):
        raise ResolverError("RESOLVER_INVALID_OUTPUT", "filter entry must be an object")
    operator = item.get("operator")
    if not isinstance(operator, str) or operator not in ALLOWED_OPERATORS:
        raise ResolverError("UNKNOWN_OPERATOR", f"{operator!r} is not an allowed operator")
    dimension = str(item.get("dimension") or "")
    return ResolverFilter(
        dimension=_match_name(dimension, dimension_names, "DIMENSION"),
        operator=operator,
        value=item.get("value"),
    )


def _clamp_limit(raw: Any) -> int:
    """Bound the requested limit: default 100, clamped into [1, 1000]."""
    try:
        value = DEFAULT_LIMIT if raw is None else int(raw)
    except (TypeError, ValueError):
        raise ResolverError("RESOLVER_INVALID_OUTPUT", "limit must be an integer") from None
    return min(max(value, 1), MAX_LIMIT)
