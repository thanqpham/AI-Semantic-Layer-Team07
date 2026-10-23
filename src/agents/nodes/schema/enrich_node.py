"""Adapt schema state to the Schema Enrichment Agent."""

import logging
from typing import Any

from src.agents.roles.schema_enrichment_agent import enrich_schema
from src.agents.state import AgentState
from src.observability import trace_node

logger = logging.getLogger(__name__)


@trace_node("enrich")
async def enrich_node(state: AgentState) -> dict[str, Any]:
    raw_schema = state.get("raw_schema", {})
    if not raw_schema or not raw_schema.get("tables"):
        return {"error": "enrich_node: raw_schema is empty"}
    try:
        return await enrich_schema(raw_schema, state.get("db_type", "postgresql"))
    except Exception as exc:
        logger.error("enrich_node error: %s", exc)
        return {"error": f"enrich_node: {exc}"}
