"""Stage 1: run real introspection on the run target."""

import asyncio

from eval.agent_runner.adapters import to_eval_raw_schema
from eval.agent_runner.bootstrap import AgentRunContext
from eval.evaluator.discovery_eval import CandidateDiscoveryOutput
from src.models.schema_metadata import RawSchemaMetadata
from src.services.live_db_service import introspect_live_database


async def introspect_target(ctx: AgentRunContext) -> RawSchemaMetadata:
    """Introspect the run target with the product live-DB path (plain URL)."""
    return await asyncio.to_thread(introspect_live_database, ctx.target_url, "sqlite")


async def collect_discovery(
    ctx: AgentRunContext,
    case_ids: list[str],
    raw: RawSchemaMetadata | None = None,
) -> dict[str, CandidateDiscoveryOutput]:
    """One full-schema candidate shared by every discovery case."""
    if raw is None:
        raw = await introspect_target(ctx)
    schema = to_eval_raw_schema(raw)
    return {case_id: CandidateDiscoveryOutput(raw_schema=schema) for case_id in case_ids}
