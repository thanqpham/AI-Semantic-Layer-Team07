"""Prepare complete evidence for metric proposals."""

from __future__ import annotations

import json
from typing import Any

from src.config import get_settings
from src.services.metric_knowledge import metric_knowledge


def prepare_proposal_context(state: dict[str, Any]) -> dict[str, Any]:
    """Keep complete request evidence or ask for a narrower/new conversation."""
    message = state.get("user_message") or "Đề xuất các KPI phù hợp với schema."
    history = state.get("chat_history") or []
    requirement = "\n".join(
        [f"[{m.get('id', 'history')}] {m['content']}" for m in history if m.get("role") == "user"]
        + [f"[{state.get('user_message_id', 'current')}] {message}"]
    )
    mode = state.get("proposal_mode", "requested")
    context = {
        "question": message,
        "requirement": requirement,
        "history": history,
        "message_id": state.get("user_message_id"),
        "session_id": state.get("session_id"),
        "schema": state.get("enriched_schema") or {},
        "existing_metrics": state.get("existing_metrics") or [],
        "assumptions": state.get("metric_decision", {}).get("assumptions", []),
        "proposal_mode": mode,
        "knowledge": metric_knowledge(requirement, mode == "discovery"),
    }
    check_context_budget(context)
    return context


def check_context_budget(context: dict[str, Any]) -> None:
    """Never silently truncate business constraints to fit a prompt."""
    if (len(json.dumps(context, ensure_ascii=False)) + 3) // 4 > get_settings().metric_context_token_budget:
        raise ValueError(
            "Context quá lớn. Hãy thu hẹp bảng/domain hoặc bắt đầu cuộc trò chuyện mới với đầy đủ điều kiện."
        )
