"""Adapt the Orchestrator Agent to the chat graph state."""

from typing import Any

from src.agents.roles.orchestrator_agent import classify_request
from src.agents.state import AgentState
from src.observability import trace_node


@trace_node("orchestrator")
async def orchestrator_node(state: AgentState) -> dict[str, Any]:
    return await classify_request(
        user_message=state.get("user_message", ""),
        chat_history=state.get("chat_history", []),
        existing_intent=state.get("intent"),
        existing_response=state.get("chat_response"),
    )
