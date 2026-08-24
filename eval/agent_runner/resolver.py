"""Selection-only resolver: pick approved metrics/dimensions for a question."""

from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db import SemanticMetricModel, SemanticTableModel
from src.services.dimension_recommender import is_valid_dimension_column
from src.services.llm import get_llm
from src.services.llm_caller import parse_llm_json

MAX_ATTEMPTS = 3
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
ALLOWED_OPERATORS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "is_not_null"})

SYSTEM_PROMPT = (
    "Bạn là bước resolver của semantic layer. Nhiệm vụ duy nhất: CHỌN từ danh mục "
    "đã duyệt. Chỉ chọn tên trong danh mục đã duyệt; trả đúng JSON; không sinh tên mới. "
    'Trả về JSON: {"metrics": [tên metric], "dimensions": ["entity.column"], '
    '"filters": [{"dimension": "entity.column", "operator": op, "value": v}], "limit": n}. '
    "operator chỉ thuộc: eq, neq, gt, gte, lt, lte, in, not_in, is_null, is_not_null. "
    "Chỉ chọn dimension khi câu hỏi YÊU CẦU phân nhóm theo dimension đó "
    "(ví dụ: 'doanh thu theo kênh', 'số đơn theo tháng'); câu hỏi chỉ hỏi "
    "tổng số thì PHẢI trả về dimensions là danh sách rỗng. "
    "Dimension đã chọn phải thuộc entity (bảng) của metric đã chọn — không chọn dimension của bảng khác. "
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
class ResolverCatalog:
    """The approved catalog one resolver invocation may select from."""

    metrics: tuple[CatalogMetric, ...]
    dimensions: tuple[CatalogDimension, ...]


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
    """Flatten valid dimension columns across the connection's tables."""
    return tuple(
        CatalogDimension(
            entity=table.table_name,
            column=column.column_name,
            business_name=column.business_name or None,
            entity_business_name=table.business_name or None,
        )
        for table in tables
        for column in table.columns
        if is_valid_dimension_column(column)
    )


async def resolve_question(
    question: str,
    catalog: ResolverCatalog,
    llm: BaseChatModel | None = None,
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
        content = (await model.ainvoke(messages)).content
        try:
            payload = parse_llm_json(content)
        except ValueError:
            error = ResolverError("RESOLVER_INVALID_OUTPUT")
            continue
        try:
            return _validate_selection(payload, catalog)
        except ResolverError as exc:
            if exc.code != "RESOLVER_SCOPE_VIOLATION":
                raise
            error = exc
            messages = [*messages, HumanMessage(content=_scope_feedback(exc))]
    raise error


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
        if payload.get("abstain") is True:
            raise ResolverError("UNKNOWN_METRIC", "no catalog metric answers the question")
        raise ResolverError("RESOLVER_INVALID_OUTPUT", "metrics must be a non-empty list")
    dimension_names = tuple(f"{d.entity}.{d.column}" for d in catalog.dimensions)
    metrics = tuple(_match_name(name, [m.name for m in catalog.metrics], "METRIC") for name in metric_names)
    dimensions = tuple(_match_name(name, dimension_names, "DIMENSION") for name in _string_list(payload, "dimensions"))
    _scope_check(dimensions, metrics, catalog)
    filters = _validate_filters(payload.get("filters"), dimension_names)
    return ResolverSelection(
        metric_names=metrics,
        dimensions=dimensions,
        filters=filters,
        limit=_clamp_limit(payload.get("limit")),
    )


def _scope_check(dimensions: tuple[str, ...], metric_names: tuple[str, ...], catalog: ResolverCatalog) -> None:
    """Reject dimensions outside the selected metrics' entities (harness scoping)."""
    allowed = {m.base_entity for m in catalog.metrics if m.name in metric_names}
    violating = tuple(d for d in dimensions if d.split(".", 1)[0] not in allowed)
    if not violating:
        return
    legal = tuple(f"{d.entity}.{d.column}" for d in catalog.dimensions if d.entity in allowed)
    raise ResolverError(
        "RESOLVER_SCOPE_VIOLATION",
        f"dimensions {violating} belong to a different entity than the selected metrics; legal dimensions: {legal}",
    )


def _scope_feedback(error: ResolverError) -> str:
    """Render the retry message for one scope violation."""
    return (
        f"Lỗi phạm vi: {error.message}. Hãy chọn dimension thuộc entity (bảng) "
        "của metric đã chọn và trả lại JSON đúng schema."
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
