"""Stage 3: generate metrics per golden case via the real product path."""

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from eval.agent_runner.adapters import to_metric_candidate
from eval.agent_runner.bootstrap import AgentRunContext
from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.agent_runner.golden_view import MetricCaseView
from eval.evaluator.schemas import CandidateMetricOutput
from src.models.db import SemanticMetricModel, SemanticTableModel
from src.models.schemas import MetricSuggestionItem
from src.services.dimension_recommender import get_dimensions_for_metric
from src.services.metrics import generate_metrics_from_prompt
from src.services.semantic_service import approve_metric, create_metric

logger = logging.getLogger(__name__)
AGENT_SOURCE = "eval-agent-runner"


@dataclass
class MetricCollectResult:
    """Candidates plus the ids of created metrics for later stages."""

    candidates: dict[str, CandidateMetricOutput] = field(default_factory=dict)
    metric_ids: dict[str, int] = field(default_factory=dict)


async def collect_metrics(
    ctx: AgentRunContext,
    conn_id: int,
    cases: list[MetricCaseView],
    resolver: CanonicalResolver,
) -> MetricCollectResult:
    """Generate, persist, approve, and map one candidate per golden case."""
    result = MetricCollectResult()
    async with ctx.session_maker() as db:
        schema_context = await _build_schema_context(db, conn_id)
        existing: list[dict[str, Any]] = []
        for case in cases:
            candidate, metric_id, item = await _process_case(
                db, ctx.user_id, conn_id, case, schema_context, existing, resolver
            )
            result.candidates[case.case_id] = candidate
            if metric_id is not None:
                result.metric_ids[case.case_id] = metric_id
            if item is not None:
                existing.append(item)
    return result


async def _process_case(
    db: AsyncSession,
    user_id: int,
    conn_id: int,
    case: MetricCaseView,
    schema_context: dict[str, Any],
    existing: list[dict[str, Any]],
    resolver: CanonicalResolver,
) -> tuple[CandidateMetricOutput, int | None, dict[str, Any] | None]:
    """Run one case end-to-end; map any failure to a stable error code."""
    try:
        try:
            suggestions, _notices = await generate_metrics_from_prompt(
                case.request, "sqlite", schema_dict=schema_context, existing_metrics=existing
            )
        except ValueError as exc:
            logger.warning("generation failed for case %s: %s", case.case_id, exc)
            return _failure("AGENT_GENERATION_FAILED"), None, None
        if not suggestions:
            return _failure("AGENT_GENERATION_FAILED"), None, None
        return await _persist_first(db, user_id, conn_id, suggestions[0], resolver)
    except Exception:
        logger.warning("case %s crashed unexpectedly", case.case_id, exc_info=True)
        await _safe_rollback(db)
        return _failure("AGENT_UNEXPECTED_ERROR"), None, None


def _failure(code: str) -> CandidateMetricOutput:
    """Build the error-only candidate output for one code."""
    return CandidateMetricOutput(error_code=code)


async def _persist_first(
    db: AsyncSession,
    user_id: int,
    conn_id: int,
    suggestion: MetricSuggestionItem,
    resolver: CanonicalResolver,
) -> tuple[CandidateMetricOutput, int, dict[str, Any]]:
    """Create, approve, and map the first suggestion via real services."""
    metric = await create_metric(
        db,
        conn_id,
        {"definition": suggestion.definition.model_dump(mode="json"), "source": AGENT_SOURCE},
        user_id,
    )
    await _approve(db, metric.id, user_id)
    allowed = [
        f"{item.table_name}.{item.column_name}" for item in await get_dimensions_for_metric(db, conn_id, metric.id)
    ]
    candidate = to_metric_candidate(
        suggestion.definition,
        allowed_dimensions=allowed,
        source_table=suggestion.definition.metric.base_entity,
        resolver=resolver,
    )
    await db.commit()
    return candidate, metric.id, _existing_item(metric)


async def _approve(db: AsyncSession, metric_id: int, user_id: int) -> None:
    """Approve best-effort; review-gated failures only downgrade the metric."""
    try:
        await approve_metric(db, metric_id, user_id)
    except Exception:
        logger.warning("approval failed for metric %s", metric_id, exc_info=True)


def _existing_item(metric: SemanticMetricModel) -> dict[str, Any]:
    """Summarize one created metric for the generator's dedupe context."""
    spec = (metric.definition or {}).get("metric", {})
    formula = spec.get("formula", {})
    return {
        "id": metric.id,
        "name": metric.name,
        "status": metric.status,
        "function": formula.get("function", ""),
        "expression": formula.get("expression", ""),
        "base_entity": spec.get("base_entity", ""),
        "filters": spec.get("filters", []),
    }


async def _safe_rollback(db: AsyncSession) -> None:
    """Best-effort rollback so later cases keep a usable session."""
    try:
        await db.rollback()
    except Exception:
        logger.warning("rollback failed after case crash", exc_info=True)


async def _build_schema_context(db: AsyncSession, conn_id: int) -> dict[str, Any]:
    """Read one connection's semantic tables into the generator's schema dict."""
    stmt = (
        select(SemanticTableModel)
        .where(SemanticTableModel.db_id == conn_id)
        .options(selectinload(SemanticTableModel.columns))
    )
    tables = (await db.execute(stmt)).scalars().all()
    return {table.table_name: _table_context(table) for table in tables}


def _table_context(table: SemanticTableModel) -> dict[str, Any]:
    """Render one semantic table with its enriched columns."""
    return {
        "business_name": table.business_name,
        "description": table.description,
        "columns": [
            {
                "column_name": column.column_name,
                "data_type": column.data_type,
                "business_name": column.business_name,
            }
            for column in table.columns
        ],
    }
