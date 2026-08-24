"""Stage 2: run the real enrichment pipeline and read back semantic state."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from eval.agent_runner.adapters import to_enrichment_candidate
from eval.agent_runner.bootstrap import AgentRunContext
from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.evaluator.schemas import CandidateEnrichmentOutput
from src.models.db import CanonicalRelationshipModel, SemanticTableModel
from src.models.schema_metadata import RawSchemaMetadata
from src.services.semantic_service import (
    enrich_and_save_canonical_schema,
    ensure_semantic_database,
)

SOURCE_TYPE = "live_target_db"
SOURCE_ID = 1
DISPLAY_NAME = "eval-agent-runner"


@dataclass(frozen=True)
class EnrichmentState:
    """Semantic tables and relationships persisted by the pipeline."""

    tables: list[SemanticTableModel]
    relationships: list[CanonicalRelationshipModel]


async def run_enrichment_pipeline(
    ctx: AgentRunContext,
    raw: RawSchemaMetadata,
    enrichment: dict | None = None,
) -> int:
    """Ensure semantic db then enrich (LLM) or replay via enrichment dict."""
    async with ctx.session_maker() as db:
        conn_id = await ensure_semantic_database(
            db,
            SOURCE_TYPE,
            SOURCE_ID,
            ctx.user_id,
            DISPLAY_NAME,
            "sqlite",
        )
        await enrich_and_save_canonical_schema(db, ctx.user_id, conn_id, raw, "sqlite", enrichment=enrichment)
    return conn_id


async def load_enrichment_state(db: AsyncSession, conn_id: int) -> EnrichmentState:
    """Load one connection's semantic tables (columns eager) and relationships."""
    tables_stmt = (
        select(SemanticTableModel)
        .where(SemanticTableModel.db_id == conn_id)
        .options(selectinload(SemanticTableModel.columns))
    )
    tables = list((await db.execute(tables_stmt)).scalars().all())
    rels_stmt = select(CanonicalRelationshipModel).where(CanonicalRelationshipModel.connection_id == conn_id)
    relationships = list((await db.execute(rels_stmt)).scalars().all())
    return EnrichmentState(tables=tables, relationships=relationships)


async def collect_enrichment(
    ctx: AgentRunContext,
    conn_id: int,
    case_ids: list[str],
    resolver: CanonicalResolver,
) -> dict[str, CandidateEnrichmentOutput]:
    """Build one shared candidate from the persisted semantic state."""
    async with ctx.session_maker() as db:
        state = await load_enrichment_state(db, conn_id)
        candidate = to_enrichment_candidate(state, resolver=resolver)
    return {case_id: candidate for case_id in case_ids}
