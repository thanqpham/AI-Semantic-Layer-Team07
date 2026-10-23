"""Adapt the Conversation Agent response to the chat graph state."""

from src.agents.roles.conversation_agent import respond
from src.agents.state import AgentState
from src.observability import trace_node


@trace_node("chitchat")
async def conversation_node(state: AgentState) -> dict[str, str]:
    return {
        "chat_response": await respond(
            user_message=state.get("user_message", ""), chat_history=state.get("chat_history", [])
        )
    }
