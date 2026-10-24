"""Conversational orchestrator graph for data guidance and metric proposals."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.agents.nodes.chat.conversation_node import conversation_node
from src.agents.nodes.chat.data_assistant_node import data_assistant_node
from src.agents.nodes.chat.orchestrator_node import orchestrator_node
from src.agents.nodes.chat.semantic_query_parser_node import semantic_query_parser_node
from src.agents.nodes.metric.coordinator_node import coordinator_node
from src.agents.state import AgentState
from src.observability import trace_transition


def _route_by_intent(state: AgentState) -> str:
    """Route the server-classified intent without a metric-decision gate."""
    if state.get("chat_response"):
        trace_transition("orchestrator", "chitchat_done")
        return "chitchat_done"
    intent = state.get("intent", "chitchat")
    if intent == "out_of_scope":
        trace_transition("orchestrator", "out_of_scope")
        return "chitchat_done"
    trace_transition("orchestrator", intent)
    return intent


def build_chat_graph() -> StateGraph:
    """Build the direct chitchat, data-assistant, metric-proposal, and semantic-query flows."""
    graph = StateGraph(AgentState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("chitchat", conversation_node)
    graph.add_node("data_assistant", data_assistant_node)
    graph.add_node("metric_coordinator", coordinator_node)
    graph.add_node("semantic_parse", semantic_query_parser_node)
    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        _route_by_intent,
        {
            "chitchat": "chitchat",
            "data_question": "data_assistant",
            "metric_query": "metric_coordinator",
            "semantic_query": "semantic_parse",
            "out_of_scope": END,
            "chitchat_done": END,
        },
    )
    graph.add_edge("chitchat", END)
    graph.add_edge("data_assistant", END)
    graph.add_edge("metric_coordinator", END)
    graph.add_edge("semantic_parse", END)
    return graph.compile()


chat_agent = build_chat_graph()
