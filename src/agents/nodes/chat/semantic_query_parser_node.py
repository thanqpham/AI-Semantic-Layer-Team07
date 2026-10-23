"""Adapt the Semantic Query Parser Agent to the chat graph state."""

from typing import Any

from src.agents.roles.semantic_query_parser_agent import parse_semantic_query
from src.agents.state import AgentState
from src.observability import trace_node


@trace_node("semantic_parse")
async def semantic_query_parser_node(state: AgentState) -> dict[str, Any]:
    return await parse_semantic_query(
        user_message=state.get("user_message", ""),
        parser_catalog=state.get("parser_catalog") or {},
        can_generate_metrics=state.get("can_generate_metrics", False),
        chat_history=state.get("chat_history", []),
    )
