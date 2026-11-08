"""Natural-language semantic query service for Chat Studio."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db import (
    CanonicalRelationshipModel,
    LiveTargetDbModel,
    SemanticColumnModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.schemas import (
    ChatClarificationOption,
    ChatClarificationPayload,
    ChatSemanticQueryResult,
    DimensionSelection,
    SemanticQueryFilter,
    SemanticQueryInterpretation,
    SemanticQuerySpec,
    SemanticTimeRange,
)
from src.services.categorical_discovery_policy import safe_observed_values
from src.services.chat_execution import execution_step
from src.services.database import decrypt_conn_url
from src.services.dimension_recommender import (
    JUNK_KEYWORDS,
    _make_dimension_item,
    get_dimensions_for_metric,
    get_filter_columns_for_metric,
)
from src.services.query_compiler import SemanticQueryCompiler
from src.services.query_execution import execute_compiled_query
from src.services.relationship_runtime import (
    active_relationship_filters,
    safe_join_path,
    unique_filter_targets,
    valid_pairs,
)
from src.services.semantic_compile_error import SemanticCompileError
from src.services.semantic_query_values import _normalize_filter_values
from src.services.semantic_value_mappings import mapping_metadata_fingerprint, read_approved_business_mappings


async def build_parser_catalog(db: AsyncSession, db_id: int) -> dict[str, Any]:
    """Build a bounded, deduplicated catalog of approved metrics, dimensions, and filter columns."""
    stmt = select(SemanticMetricModel).where(
        SemanticMetricModel.db_id == db_id,
        SemanticMetricModel.status == "approved",
        SemanticMetricModel.definition.is_not(None),
        SemanticMetricModel.is_deleted.is_(False),
    )
    approved_metrics = list((await db.execute(stmt)).scalars().all())
    relationship_fingerprint = await _relationship_fingerprint(db, db_id)
    mapping_fingerprint = await _mapping_fingerprint(db, db_id)
    if not approved_metrics:
        return {
            "metrics": [],
            "dimensions": [],
            "filter_columns": [],
            "_relationship_fingerprint": relationship_fingerprint,
            "_mapping_fingerprint": mapping_fingerprint,
        }

    metric_items = [_format_metric_item(m) for m in approved_metrics]
    capabilities = await _dimension_capabilities(db, db_id, approved_metrics)
    dim_items, filter_items = await _collect_dims_and_filters(db, db_id, approved_metrics, metric_items, capabilities)
    await _add_filter_values(db, filter_items)
    return {
        "metrics": metric_items,
        "dimensions": dim_items,
        "filter_columns": filter_items,
        "_relationship_fingerprint": relationship_fingerprint,
        "_mapping_fingerprint": mapping_fingerprint,
    }


async def _mapping_fingerprint(db: AsyncSession, db_id: int) -> str:
    """Fingerprint approved column mappings without exposing their values."""
    rows = (
        await db.scalars(
            select(SemanticColumnModel)
            .join(SemanticTableModel, SemanticColumnModel.table_id == SemanticTableModel.id)
            .where(SemanticTableModel.db_id == db_id)
            .order_by(SemanticColumnModel.id)
        )
    ).all()
    payload = [
        (
            row.id,
            mapping_metadata_fingerprint(
                row.allowed_value_mappings, row.review_status, getattr(row, "allowed_values_complete", True)
            ),
        )
        for row in rows
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


async def _relationship_fingerprint(db: AsyncSession, db_id: int) -> str:
    """Fingerprint the approved relationship graph without exposing its details."""
    stmt = (
        select(CanonicalRelationshipModel)
        .where(CanonicalRelationshipModel.connection_id == db_id, *active_relationship_filters())
        .order_by(CanonicalRelationshipModel.id)
    )
    rows = (await db.scalars(stmt)).all()
    data = [(r.id, r.from_entity_id, r.to_entity_id, r.relationship_type, r.column_pairs) for r in rows]
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _format_metric_item(metric: SemanticMetricModel) -> dict[str, Any]:
    """Format an approved metric for the parser catalog."""
    definition = metric.definition or {}
    metric_body = definition.get("metric", {})
    formula_obj = metric_body.get("formula", {})
    func = formula_obj.get("function", "")
    expr = formula_obj.get("expression", "")
    formula_str = f"{func}({expr})" if func and expr else expr or func or "N/A"
    return {
        "id": metric.id,
        "name": metric.name,
        "version": metric.version,
        "_definition_fingerprint": hashlib.sha256(
            json.dumps(definition, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "business_name": metric_body.get("business_name") or metric.name,
        "formula": formula_str,
        "base_entity": metric_body.get("base_entity") or metric.base_entity,
        "filters": metric_body.get("filters", []),
    }


async def _collect_dims_and_filters(
    db: AsyncSession,
    db_id: int,
    metrics: list[SemanticMetricModel],
    metric_items: list[dict[str, Any]],
    capabilities: dict[int, list[Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect deduplicated dimensions and filter columns across approved metrics."""
    dim_items: dict[int, dict[str, Any]] = {}
    filter_items: dict[int, dict[str, Any]] = {}

    for metric, item in zip(metrics, metric_items, strict=True):
        dims = (
            capabilities.get(metric.base_entity_id, [])
            if capabilities is not None
            else await get_dimensions_for_metric(db, db_id, metric.id, limit=None)
        )
        item["dimension_ids"] = [d.column_id for d in dims]
        for d in dims:
            dim_items.setdefault(d.column_id, d.model_dump())

        filters = await get_filter_columns_for_metric(db, db_id, metric.id)
        item["filter_column_ids"] = [f.column_id for f in filters]
        for f in filters:
            filter_items.setdefault(f.column_id, f.model_dump())

    return list(dim_items.values()), list(filter_items.values())


async def _dimension_capabilities(
    db: AsyncSession, db_id: int, metrics: list[SemanticMetricModel]
) -> dict[int, list[Any]]:
    """Build safe dimension capabilities once per distinct metric base table."""
    tables = (
        await db.scalars(
            select(SemanticTableModel)
            .where(SemanticTableModel.db_id == db_id)
            .options(selectinload(SemanticTableModel.columns))
        )
    ).all()
    relationships = (
        await db.scalars(
            select(CanonicalRelationshipModel).where(
                CanonicalRelationshipModel.connection_id == db_id, *active_relationship_filters()
            )
        )
    ).all()
    return {
        base: _dimensions_for_base(base, tables, relationships) for base in {m.base_entity_id for m in metrics} if base
    }


def _dimensions_for_base(base: int, tables: list[Any], relationships: list[Any]) -> list[Any]:
    result = []
    unique, reachable = _safe_reachability(base, relationships)
    for table in tables:
        if table.id not in reachable:
            continue
        if table.id != base and table.id not in unique:
            try:
                safe_join_path(relationships, base, table.id)
            except SemanticCompileError:
                continue
        for col in table.columns:
            if _eligible_query_dimension(col):
                result.append(_make_dimension_item(col, table, "A" if table.id == base else "C", True, False))
    return result


def _safe_reachability(base: int, relationships: list[Any]) -> tuple[set[int], set[int]]:
    """Identify directed safe paths, using bridges for unambiguous paths."""
    edges: dict[int, set[int]] = {}
    for rel in relationships:
        if not valid_pairs(rel.column_pairs):
            continue
        kind = rel.relationship_type.replace("-", "_").lower()
        if kind in {"many_to_one", "n:1", "one_to_one", "1:1"}:
            edges.setdefault(rel.from_entity_id, set()).add(rel.to_entity_id)
        if kind in {"one_to_many", "1:n", "one_to_one", "1:1"}:
            edges.setdefault(rel.to_entity_id, set()).add(rel.from_entity_id)
    reachable = {base}
    pending = deque([base])
    while pending:
        for target in edges.get(pending.popleft(), set()) - reachable:
            reachable.add(target)
            pending.append(target)
    return unique_filter_targets(relationships, base), reachable


def _eligible_query_dimension(col: SemanticColumnModel) -> bool:
    """Keep existing sensitive-column rules without the recommendation cardinality cap."""
    name = col.column_name.lower()
    if (
        col.review_status != "approved"
        or col.is_primary_key
        or col.is_foreign_key
        or any(x in name for x in JUNK_KEYWORDS)
    ):
        return False
    if name.endswith("_id"):
        return any(x in name for x in ("store", "product", "channel", "category", "device"))
    return True


async def _add_filter_values(db: AsyncSession, filter_items: list[dict[str, Any]]) -> None:
    """Attach approved mappings and independently screened sample values."""
    ids = [item["column_id"] for item in filter_items]
    if not ids:
        return
    rows = (await db.scalars(select(SemanticColumnModel).where(SemanticColumnModel.id.in_(ids)))).all()
    by_id = {column.id: column for column in rows}
    for item in filter_items:
        column = by_id.get(item["column_id"])
        if not column or column.review_status != "approved":
            continue
        _attach_filter_value_metadata(item, column)


def _eligible_query_column(column: SemanticColumnModel) -> bool:
    """Preserve existing sensitive/identifier exclusions for both samples and mappings."""
    name = column.column_name.casefold()
    blocked = ("name", "email", "phone", "address", "secret", "token", "password", "comment", "description")
    return not column.is_primary_key and not column.is_foreign_key and not any(term in name for term in blocked)


def _attach_filter_value_metadata(item: dict[str, Any], column: SemanticColumnModel) -> None:
    """Keep approved mapping metadata separate from screened sample values."""
    mappings = read_approved_business_mappings(column.allowed_value_mappings, column.review_status)
    item["review_status"] = column.review_status
    item["allowed_values"] = (
        safe_observed_values(column.allowed_values or []) or [] if _eligible_query_column(column) else []
    )
    item["allowed_values_complete"] = getattr(column, "allowed_values_complete", True)
    item["allowed_value_mappings"] = mappings
    item["_approved_mappings"] = mappings
    item["_mapping_fingerprint"] = mapping_metadata_fingerprint(
        column.allowed_value_mappings, column.review_status, item["allowed_values_complete"]
    )
    item["_mapping_count"] = len(item["_approved_mappings"])
    item["_mapping_overflow"] = len(item["_approved_mappings"]) > 100


def _ensure_catalog_mapping_capacity(catalog: dict[str, Any]) -> str | None:
    """Reject oversized prompt catalogs instead of silently omitting approved mappings."""
    if any(column.get("_mapping_overflow") for column in catalog.get("filter_columns", [])):
        return "Một cột có hơn 100 ánh xạ đã duyệt; hãy yêu cầu quản lý ánh xạ chia phạm vi trước khi truy vấn."
    serialized = json.dumps(catalog, ensure_ascii=False, default=str)
    if len(serialized) > 100_000:
        return "Danh mục ánh xạ nghiệp vụ quá lớn để xử lý đầy đủ. Hãy thu hẹp metric hoặc phạm vi bảng."
    return None


def _approved_mapping_prompt_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Build the LLM-facing catalog with private fingerprints and sample internals removed."""
    safe = {key: value for key, value in catalog.items() if not key.startswith("_")}
    safe["metrics"] = [
        {key: value for key, value in metric.items() if not key.startswith("_")}
        for metric in catalog.get("metrics", [])
    ]
    safe["filter_columns"] = [
        {key: value for key, value in column.items() if not key.startswith("_")}
        for column in catalog.get("filter_columns", [])
    ]
    safe["dimensions"] = [
        {key: value for key, value in dimension.items() if not key.startswith("_")}
        for dimension in catalog.get("dimensions", [])
    ]
    return safe


def normalize_interpretation(
    interpretation: SemanticQueryInterpretation,
    catalog: dict[str, Any],
    now_vn: datetime | None = None,
) -> SemanticQueryInterpretation:
    """Validate IDs against catalog and merge time ranges into runtime filters."""
    if interpretation.status != "resolved" or interpretation.spec is None:
        return interpretation

    spec = interpretation.spec
    capacity_error = _ensure_catalog_mapping_capacity(catalog)
    if capacity_error:
        return _invalid_selection_clarification(capacity_error)
    error = _validate_query_selection(interpretation, catalog)
    if error is not None:
        return error
    merged_filters = _merge_time_ranges(spec.filters, interpretation.time_ranges)
    normalized_filters = _normalize_filter_values(merged_filters, catalog)
    if normalized_filters is None:
        return _invalid_selection_clarification(_filter_normalization_message(merged_filters, catalog, spec.metric_ids))
    updated_spec = spec.model_copy(update={"filters": normalized_filters, "limit": min(max(spec.limit, 1), 1000)})
    return interpretation.model_copy(update={"spec": updated_spec})


def _column_has_approved_mappings(column: dict[str, Any]) -> bool:
    """Check whether the filter column has any usable approved business mapping."""
    return bool(read_approved_business_mappings(column.get("_approved_mappings", []), column.get("review_status", "")))


def _filter_normalization_message(
    filters: list[SemanticQueryFilter], catalog: dict[str, Any], metric_ids: list[int]
) -> str:
    """Explain whether a filter is missing, ambiguous, or incompatible with approved metadata."""
    from src.services.semantic_query_values import filter_value_resolution

    metrics = {metric["id"]: metric for metric in catalog.get("metrics", [])}
    compatible = set.intersection(*(set(metrics[mid].get("filter_column_ids", [])) for mid in metric_ids))
    columns = {column["column_id"]: column for column in catalog.get("filter_columns", [])}
    for item in filters:
        column = columns.get(item.column_id)
        if column is None or item.column_id not in compatible:
            return "Cột lọc không tương thích với metric đã chọn. Hãy chọn cột lọc được hỗ trợ cho metric này."
        reason = filter_value_resolution(item, column)
        if reason == "ambiguous":
            return f"Nhãn lọc có nhiều cách hiểu trong cột '{column.get('business_name') or column.get('column_name')}'. Hãy chỉ rõ giá trị hoặc cột."
        if reason == "unmapped":
            source = "Chưa có ánh xạ đã duyệt" if _column_has_approved_mappings(column) else "Chưa có ánh xạ được duyệt"
            return f"{source} cho giá trị trong cột '{column.get('business_name') or column.get('column_name')}'. Hãy chọn nhãn đã duyệt hoặc làm rõ giá trị."
        if reason == "malformed":
            return f"Giá trị lọc không đúng kiểu dữ liệu của cột '{column.get('business_name') or column.get('column_name')}'."
    return "Giá trị bộ lọc không phù hợp với kiểu dữ liệu metadata đã duyệt."


def _validate_query_selection(
    interpretation: SemanticQueryInterpretation, catalog: dict[str, Any]
) -> SemanticQueryInterpretation | None:
    """Validate selected metrics and columns before normalizing filter values."""
    spec = interpretation.spec
    assert spec is not None
    if not spec.metric_ids and (spec.filters or spec.dimensions or interpretation.time_ranges):
        return _invalid_selection_clarification(
            "Hãy chọn metric đã được phê duyệt trước khi chỉ định dimension hoặc filter."
        )
    valid_metrics = {m["id"]: m for m in catalog.get("metrics", [])}
    if not set(spec.metric_ids).issubset(valid_metrics.keys()):
        return _invalid_selection_clarification("Chỉ số không tồn tại trong danh mục đã duyệt.")

    bases = {valid_metrics[m_id].get("base_entity") for m_id in spec.metric_ids}
    if len(bases) > 1:
        if spec.dimensions or spec.filters or interpretation.time_ranges:
            return _invalid_selection_clarification(
                "Các chỉ số có nguồn khác nhau; hãy hỏi riêng và giữ các điều kiện."
            )
        return _incompatible_bases_clarification(spec.metric_ids, valid_metrics)

    if not _selections_are_compatible(spec, interpretation.time_ranges, valid_metrics):
        return _incompatible_column_clarification(spec, interpretation, valid_metrics, catalog)
    if not _valid_time_ranges(interpretation.time_ranges, catalog):
        return _invalid_selection_clarification("Khoảng thời gian không hợp lệ với metadata đã duyệt.")
    return None


def _incompatible_column_clarification(
    spec: SemanticQuerySpec,
    interpretation: SemanticQueryInterpretation,
    metrics: dict[int, dict[str, Any]],
    catalog: dict[str, Any],
) -> SemanticQueryInterpretation:
    """Identify the exact selected column incompatible with one or more metrics."""
    dimensions = {item.column_id for item in spec.dimensions}
    filters = {item.column_id for item in spec.filters} | {item.column_id for item in interpretation.time_ranges}
    if not spec.metric_ids:
        return _invalid_selection_clarification("Hãy chọn metric đã được phê duyệt trước khi lọc.")
    for metric_id in spec.metric_ids:
        metric = metrics[metric_id]
        if not dimensions <= set(metric.get("dimension_ids", [])):
            return _invalid_selection_clarification(
                "Dimension không tương thích (không phù hợp) với metric đã chọn. Hãy chọn dimension hỗ trợ metric này."
            )
        if not filters <= set(metric.get("filter_column_ids", [])):
            return _invalid_selection_clarification(
                "Cột lọc không tương thích (không phù hợp) với metric đã chọn. Hãy chọn cột lọc hỗ trợ metric này."
            )
        catalogued = {column["column_id"] for column in catalog.get("filter_columns", [])}
        if not filters <= catalogued:
            return _invalid_selection_clarification("Cột lọc không có trong catalog đã duyệt. Hãy làm rõ cột muốn lọc.")
    return _invalid_selection_clarification("Cột truy vấn không tương thích với metric đã chọn.")


def _selections_are_compatible(
    spec: SemanticQuerySpec, ranges: list[SemanticTimeRange], metrics: dict[int, dict[str, Any]]
) -> bool:
    """Require every selected column to be valid for every selected metric."""
    dims = {item.column_id for item in spec.dimensions}
    filters = {item.column_id for item in spec.filters} | {item.column_id for item in ranges}
    return all(
        dims <= set(metrics[mid].get("dimension_ids", [])) and filters <= set(metrics[mid].get("filter_column_ids", []))
        for mid in spec.metric_ids
    )


def _valid_time_ranges(ranges: list[SemanticTimeRange], catalog: dict[str, Any]) -> bool:
    """Require valid half-open dates on permitted temporal columns."""
    columns = {item["column_id"]: item for item in catalog.get("filter_columns", [])}
    for item in ranges:
        column = columns.get(item.column_id, {})
        if not any(t in str(column.get("data_type", "")).upper() for t in ("DATE", "TIME")):
            return False
        try:
            if date.fromisoformat(item.start_date) >= date.fromisoformat(item.end_date):
                return False
        except ValueError:
            return False
    return True


def _merge_time_ranges(
    filters: list[SemanticQueryFilter], time_ranges: list[SemanticTimeRange]
) -> list[SemanticQueryFilter]:
    """Convert half-open [start_date, end_date) time ranges to gte and lt filters."""
    merged = list(filters)
    for tr in time_ranges:
        merged.append(SemanticQueryFilter(column_id=tr.column_id, operator="gte", value=tr.start_date))
        merged.append(SemanticQueryFilter(column_id=tr.column_id, operator="lt", value=tr.end_date))
    return merged


def _invalid_selection_clarification(message: str) -> SemanticQueryInterpretation:
    """Build a clarification when selection fails catalog verification."""
    return SemanticQueryInterpretation(
        status="needs_clarification",
        clarification=ChatClarificationPayload(prompt=message, options=[]),
    )


def _incompatible_bases_clarification(
    metric_ids: list[int], valid_metrics: dict[int, dict[str, Any]]
) -> SemanticQueryInterpretation:
    """Build clarification options when selected metrics belong to different base entities."""
    options = [
        ChatClarificationOption(
            id=f"opt_single_{m_id}",
            label=f"Xem {valid_metrics[m_id]['business_name']}",
            description=f"Truy vấn riêng cho bảng {valid_metrics[m_id]['base_entity']}",
            spec=SemanticQuerySpec(metric_ids=[m_id], dimensions=[], filters=[], limit=100),
        )
        for m_id in metric_ids[:3]
    ]
    prompt = (
        "Các chỉ số bạn chọn thuộc các bảng dữ liệu khác nhau nên không thể gom chung vào 1 bảng. "
        "Bạn vui lòng chọn một chỉ số để xem:"
    )
    return SemanticQueryInterpretation(
        status="needs_clarification",
        clarification=ChatClarificationPayload(prompt=prompt, options=options),
    )


async def execute_natural_language_query(
    db: AsyncSession,
    db_id: int,
    live_db: LiveTargetDbModel,
    spec: SemanticQuerySpec,
    catalog: dict[str, Any],
    time_ranges: list[SemanticTimeRange] | None = None,
) -> ChatSemanticQueryResult:
    """Compile and execute a validated query spec on the Live DB."""
    with execution_step("sql_compile"):
        compiled = await SemanticQueryCompiler(db).compile(db_id, spec)
    conn_url = decrypt_conn_url(live_db.conn_url_enc)
    with execution_step("sql_execute"):
        exec_result = await execute_compiled_query(
            conn_url=conn_url,
            dialect=live_db.dialect,
            compiled=compiled,
            timeout_seconds=15,
        )
    explanation = format_deterministic_explanation(
        metric_ids=spec.metric_ids,
        dimensions=spec.dimensions,
        filters=spec.filters,
        time_ranges=time_ranges or [],
        catalog=catalog,
    )
    return ChatSemanticQueryResult(
        spec=spec,
        columns=exec_result.columns,
        rows=exec_result.rows,
        row_count=exec_result.row_count,
        explanation=explanation,
        sql=compiled.sql,
        metadata=compiled.metadata,
    )


def format_deterministic_explanation(
    metric_ids: list[int],
    dimensions: list[DimensionSelection],
    filters: list[SemanticQueryFilter],
    time_ranges: list[SemanticTimeRange],
    catalog: dict[str, Any],
) -> str:
    """Format a deterministic Vietnamese explanation from metadata without LLM."""
    metric_map = {m["id"]: m for m in catalog.get("metrics", [])}
    dim_map = {d["column_id"]: d for d in catalog.get("dimensions", [])}
    filter_map = {f["column_id"]: f for f in catalog.get("filter_columns", [])}

    metric_parts = [
        f"**{metric_map[m_id]['business_name']}** (công thức `{metric_map[m_id]['formula']}`)"
        for m_id in metric_ids
        if m_id in metric_map
    ]
    base_text = "Số liệu được tính từ chỉ số " + ", ".join(metric_parts) if metric_parts else "Số liệu"

    dim_parts = _format_dimension_parts(dimensions, dim_map)
    dim_text = f", gom nhóm theo {', '.join(dim_parts)}" if dim_parts else ""

    filter_parts = _format_filter_parts(filters, time_ranges, filter_map, dim_map)
    filter_text = f", lọc theo {', '.join(filter_parts)}" if filter_parts else ""

    return f"{base_text}{dim_text}{filter_text}."


def _format_dimension_parts(dimensions: list[DimensionSelection], dim_map: dict[int, dict[str, Any]]) -> list[str]:
    """Format dimension labels with time grains."""
    grain_labels = {"day": "ngày", "week": "tuần", "month": "tháng", "quarter": "quý", "year": "năm"}
    parts = []
    for d in dimensions:
        info = dim_map.get(d.column_id)
        name = info.get("business_name") or info.get("column_name", str(d.column_id)) if info else str(d.column_id)
        if d.time_grain and d.time_grain in grain_labels:
            parts.append(f"**{name}** (theo {grain_labels[d.time_grain]})")
        else:
            parts.append(f"**{name}**")
    return parts


def _format_filter_parts(
    filters: list[SemanticQueryFilter],
    time_ranges: list[SemanticTimeRange],
    filter_map: dict[int, dict[str, Any]],
    dim_map: dict[int, dict[str, Any]],
) -> list[str]:
    """Format filter predicates and time ranges into readable explanation phrases."""
    parts = [f"**{tr.label}**" for tr in time_ranges if tr.label]
    cols = {**dim_map, **filter_map}
    for f in filters:
        if any(tr.column_id == f.column_id for tr in time_ranges):
            continue
        info = cols.get(f.column_id)
        col_name = info.get("business_name") or info.get("column_name", str(f.column_id)) if info else str(f.column_id)
        parts.append(f"**{col_name}** {f.operator} `{f.value}`")
    return parts
