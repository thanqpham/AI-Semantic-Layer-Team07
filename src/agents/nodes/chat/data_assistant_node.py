"""Adapt the Data Assistant Agent response to the chat graph state."""

from src.agents.roles.data_assistant_agent import answer_data_question
from src.agents.state import AgentState
from src.observability import trace_node


@trace_node("data_assistant")
async def data_assistant_node(state: AgentState) -> dict[str, str]:
    context = {
        key: state.get(key, default)
        for key, default in (
            ("enriched_schema", {}),
            ("approved_metrics", []),
            ("metric_decision", {}),
            ("error", None),
            ("chat_history", []),
        )
    }
    response = await answer_data_question(state.get("user_message", ""), context)
    return {"intent": "data_question", "chat_response": response}
