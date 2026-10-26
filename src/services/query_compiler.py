"""Expose the semantic compiler API and delegate metadata orchestration."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.observability import trace_action
from src.services.query_compiler_orchestration import QueryCompileOrchestrator
from src.services.query_compiler_sql import validate_read_only
from src.services.query_compiler_trace import CompileTraceBuilder
from src.services.query_compiler_types import CompiledQuery
from src.services.semantic_compile_error import SemanticCompileError

__all__ = ["CompiledQuery", "SemanticQueryCompiler", "validate_read_only"]


def _query_spec(
    query: SemanticQuerySpec | list[int] | None,
    metric_ids: list[int] | None,
    dimension_ids: list[int] | None,
    filters: list[SemanticQueryFilter] | None,
    limit: int,
) -> SemanticQuerySpec:
    """Normalize legacy compiler arguments into the canonical input."""
    if isinstance(query, SemanticQuerySpec):
        return query
    selected_metrics = query if isinstance(query, list) else metric_ids
    dimensions = [DimensionSelection(column_id=item) for item in dimension_ids or []]
    return SemanticQuerySpec(
        metric_ids=selected_metrics or [],
        dimensions=dimensions,
        filters=filters or [],
        limit=min(limit, 1000),
    )


def _reject_duplicate_selections(spec: SemanticQuerySpec) -> None:
    metric_ids = spec.metric_ids
    dimension_ids = [item.column_id for item in spec.dimensions]
    if len(metric_ids) != len(set(metric_ids)) or len(dimension_ids) != len(set(dimension_ids)):
        raise SemanticCompileError("DUPLICATE_SELECTION", "Semantic selections must be unique")


class SemanticQueryCompiler:
    """Compile approved metrics through metadata orchestration and SQL renderers."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._orchestrator = QueryCompileOrchestrator(db)

    async def compile(
        self,
        connection_id: int,
        query: SemanticQuerySpec | list[int] | None = None,
        dimension_ids: list[int] | None = None,
        filters: list[SemanticQueryFilter] | None = None,
        limit: int = 100,
        *,
        metric_ids: list[int] | None = None,
    ) -> CompiledQuery:
        """Compile semantic selections without accepting SQL from the caller."""
        spec = _query_spec(query, metric_ids, dimension_ids, filters, limit)
        _reject_duplicate_selections(spec)
        trace = CompileTraceBuilder()
        try:
            return await trace_action(
                "query_compile",
                {"connection_id": connection_id, "metric_count": len(spec.metric_ids)},
                self._orchestrator.compile(connection_id, spec, trace),
            )
        except SemanticCompileError as exc:
            if trace.completed_steps:
                exc.context.setdefault("partial_trace", trace.snapshot())
            raise
