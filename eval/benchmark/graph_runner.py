"""Run production LangGraph workflows inside an isolated benchmark sandbox."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from eval.agent_runner.bootstrap import AgentRunContext
from src.agents.graph import build_graph
from src.services.database import encrypt_conn_url


class FlowGraph(Protocol):
    """Represent the minimal compiled-graph interface used by the benchmark adapter."""

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the production graph until its configured interrupt or terminal state."""


async def run_flow1_graph(
    context: AgentRunContext,
    graph: FlowGraph | None = None,
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute Flow 1 production nodes against one throwaway SQLite target."""
    workflow = graph or build_graph()
    return await workflow.ainvoke(_flow1_state(context, request))


def _flow1_state(context: AgentRunContext, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the minimum encrypted input state required by the Flow 1 graph."""
    return {
        "db_id": 1,
        "user_id": context.user_id,
        "conn_url_enc": encrypt_conn_url(context.target_url),
        "db_type": "sqlite",
        "existing_metrics": [],
        "hitl_approved": False,
        "user_message": _metric_request(request),
    }


def _metric_request(request: Mapping[str, Any] | None) -> str:
    """Return a bounded benchmark request suitable for metric generation."""
    message = request.get("user_message") if request else None
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "Hãy đề xuất một metric đếm số đơn hàng từ cột order_id của bảng fact_orders."
