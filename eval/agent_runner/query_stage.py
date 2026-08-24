"""Stage 4: compile per-query candidates from resolver or oracle selections."""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eval.agent_runner.adapters import to_compiler_candidate
from eval.agent_runner.bootstrap import AgentRunContext
from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.agent_runner.golden_view import QueryCaseView
from eval.agent_runner.resolver import (
    ALLOWED_OPERATORS,
    ResolverError,
    ResolverFilter,
    ResolverSelection,
    build_catalog,
    resolve_question,
)
from eval.evaluator.schemas import CandidateCompilerOutput
from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.services.query_compiler import CompiledQuery, SemanticQueryCompiler
from src.services.semantic_compile_error import SemanticCompileError

logger = logging.getLogger(__name__)

MIN_LIMIT = 1
MAX_LIMIT = 1000


@dataclass(frozen=True)
class OracleInput:
    """Caller-provided ground-truth selection for one query case."""

    metric_ids: tuple[int, ...]
    dimensions: tuple[str, ...]  # "entity.column"
    filters: tuple[ResolverFilter, ...]
    limit: int = 100


@dataclass(frozen=True)
class _Selection:
    """Mode-neutral selection consumed by the spec builder."""

    metric_ids: tuple[int, ...]
    dimensions: tuple[str, ...]
    filters: tuple[ResolverFilter, ...]
    limit: int


async def collect_queries(
    ctx: AgentRunContext,
    conn_id: int,
    cases: list[QueryCaseView],
    *,
    mode: str = "resolver",
    metric_map: dict[str, int] | None = None,
    oracle_inputs: dict[str, OracleInput] | None = None,
    resolver: CanonicalResolver,
) -> dict[str, CandidateCompilerOutput]:
    """Compile one candidate per query case; a crashing case never kills the run.

    ``metric_map`` is accepted for orchestrator interface symmetry only:
    metric-name-to-id resolution always reads the run's own metadata store.
    """
    if mode not in {"resolver", "oracle"}:
        raise ValueError(f"unknown mode: {mode!r}")
    outputs: dict[str, CandidateCompilerOutput] = {}
    oracles = oracle_inputs or {}
    async with ctx.session_maker() as db:
        for case in cases:
            outputs[case.case_id] = await _collect_one(db, conn_id, case, mode, oracles, resolver)
    return outputs


async def _collect_one(
    db: AsyncSession,
    conn_id: int,
    case: QueryCaseView,
    mode: str,
    oracles: dict[str, OracleInput],
    resolver: CanonicalResolver,
) -> CandidateCompilerOutput:
    """Run one case; map every failure to a stable error code."""
    try:
        return await _run_case(db, conn_id, case, mode, oracles, resolver)
    except ResolverError as exc:
        return _failure(exc.code)
    except SemanticCompileError as exc:
        return _failure(exc.code)
    except Exception:
        logger.warning("query case %s crashed unexpectedly", case.case_id, exc_info=True)
        await _safe_rollback(db)
        return _failure("AGENT_UNEXPECTED_ERROR")


async def _run_case(
    db: AsyncSession,
    conn_id: int,
    case: QueryCaseView,
    mode: str,
    oracles: dict[str, OracleInput],
    resolver: CanonicalResolver,
) -> CandidateCompilerOutput:
    """Get the selection, build the spec, compile with the real compiler, adapt."""
    if mode == "oracle":
        oracle = oracles.get(case.case_id)
        if oracle is None:
            return _failure("ORACLE_INPUT_MISSING")
        selection = _oracle_selection(oracle)
    else:
        selection = await _resolver_selection(db, conn_id, case)
    spec = await _build_spec(db, conn_id, selection)
    compiled = await SemanticQueryCompiler(db).compile(conn_id, spec)
    entities = await _path_entities(db, conn_id, compiled)
    return to_compiler_candidate(
        compiled,
        spec=spec,
        dimension_names=list(selection.dimensions),
        filter_names=[item.dimension for item in selection.filters],
        relationship_entities=entities,
        resolver=resolver,
    )


def _oracle_selection(oracle: OracleInput) -> _Selection:
    """Validate one caller-provided oracle input and clamp its limit."""
    for item in oracle.filters:
        if item.operator not in ALLOWED_OPERATORS:
            raise ResolverError("UNKNOWN_OPERATOR", f"{item.operator!r} is not an allowed operator")
    limit = min(max(oracle.limit, MIN_LIMIT), MAX_LIMIT)
    return _Selection(oracle.metric_ids, oracle.dimensions, oracle.filters, limit)


async def _resolver_selection(db: AsyncSession, conn_id: int, case: QueryCaseView) -> _Selection:
    """Resolve the question via the Task 7 LLM-only-chooses step, then map ids."""
    catalog = await build_catalog(db, conn_id)
    resolved: ResolverSelection = await resolve_question(case.question, catalog)
    metric_ids = await _approved_metric_ids(db, conn_id, resolved.metric_names)
    return _Selection(metric_ids, resolved.dimensions, resolved.filters, resolved.limit)


async def _approved_metric_ids(
    db: AsyncSession,
    conn_id: int,
    names: tuple[str, ...],
) -> tuple[int, ...]:
    """Map metric names to ids of approved metrics in the run's own store."""
    if not names:
        raise ResolverError("RESOLVER_INVALID_OUTPUT", "selection must contain at least one metric")
    stmt = (
        select(SemanticMetricModel)
        .where(
            SemanticMetricModel.db_id == conn_id,
            SemanticMetricModel.status == "approved",
            SemanticMetricModel.name.in_(names),
        )
        .order_by(SemanticMetricModel.id)
    )
    rows = (await db.execute(stmt)).scalars().all()
    by_name = {metric.name: metric.id for metric in rows}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise ResolverError("UNKNOWN_METRIC", f"{missing!r} are not approved metrics")
    return tuple(by_name[name] for name in names)


async def _build_spec(db: AsyncSession, conn_id: int, selection: _Selection) -> SemanticQuerySpec:
    """Map selection names onto canonical ids inside one SemanticQuerySpec."""
    dimension_ids = await _column_ids(db, conn_id, selection.dimensions)
    filter_ids = await _column_ids(db, conn_id, tuple(item.dimension for item in selection.filters))
    dimensions = [DimensionSelection(column_id=column_id, time_grain=None) for column_id in dimension_ids]
    filters = [
        SemanticQueryFilter(column_id=column_id, operator=item.operator, value=item.value)
        for column_id, item in zip(filter_ids, selection.filters, strict=True)
    ]
    limit = min(max(selection.limit, MIN_LIMIT), MAX_LIMIT)
    return SemanticQuerySpec(
        metric_ids=list(selection.metric_ids),
        dimensions=dimensions,
        filters=filters,
        limit=limit,
    )


async def _column_ids(db: AsyncSession, conn_id: int, names: tuple[str, ...]) -> tuple[int, ...]:
    """Resolve ``entity.column`` names against the run's semantic metadata."""
    ids: list[int] = []
    for name in names:
        ids.append(await _column_id(db, conn_id, name))
    return tuple(ids)


async def _column_id(db: AsyncSession, conn_id: int, name: str) -> int:
    """Look up one ``entity.column`` name; unknown names fail closed."""
    entity, _, column = name.partition(".")
    stmt = (
        select(SemanticColumnModel.id)
        .join(SemanticTableModel, SemanticColumnModel.table_id == SemanticTableModel.id)
        .where(
            SemanticTableModel.db_id == conn_id,
            SemanticTableModel.table_name == entity,
            SemanticColumnModel.column_name == column,
        )
    )
    column_id = (await db.execute(stmt)).scalar_one_or_none()
    if column_id is None:
        raise ResolverError("UNKNOWN_DIMENSION", f"{name!r} is not a known column")
    return column_id


async def _path_entities(db: AsyncSession, conn_id: int, compiled: CompiledQuery) -> tuple[str, ...]:
    """Resolve compiled relationship ids into the entity names they join."""
    relationship_ids = (compiled.metadata or {}).get("relationship_ids") or []
    if not relationship_ids:
        return ()
    stmt = select(CanonicalRelationshipModel).where(
        CanonicalRelationshipModel.connection_id == conn_id,
        CanonicalRelationshipModel.id.in_(relationship_ids),
    )
    relationships = (await db.execute(stmt)).scalars().all()
    tables = await _table_names(db, conn_id)
    entities: list[str] = []
    for relationship in relationships:
        for table_id in (relationship.from_entity_id, relationship.to_entity_id):
            name = tables.get(table_id)
            if name is not None and name not in entities:
                entities.append(name)
    return tuple(entities)


async def _table_names(db: AsyncSession, conn_id: int) -> dict[int, str]:
    """Index one connection's semantic tables by id."""
    stmt = select(SemanticTableModel).where(SemanticTableModel.db_id == conn_id)
    tables = (await db.execute(stmt)).scalars().all()
    return {table.id: table.table_name for table in tables}


def _failure(code: str) -> CandidateCompilerOutput:
    """Build the error-only compiler candidate for one code."""
    return CandidateCompilerOutput(error_code=code)


async def _safe_rollback(db: AsyncSession) -> None:
    """Best-effort rollback so later cases keep a usable session."""
    try:
        await db.rollback()
    except Exception:
        logger.warning("rollback failed after query case crash", exc_info=True)
