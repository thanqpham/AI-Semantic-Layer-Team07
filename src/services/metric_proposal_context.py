"""Prepare complete evidence for metric proposals."""

from __future__ import annotations

import json
from typing import Any

from src.config import get_settings
from src.services.metric_knowledge import find_variant, load_metric_knowledge, metric_knowledge


def prepare_proposal_context(state: dict[str, Any]) -> dict[str, Any]:
    """Keep complete request evidence or ask for a narrower/new conversation."""
    message = state.get("user_message") or "Đề xuất các KPI phù hợp với schema."
    history = state.get("chat_history") or []
    requirement = "\n".join(
        [f"[{m.get('id', 'history')}] {m['content']}" for m in history if m.get("role") == "user"]
        + [f"[{state.get('user_message_id', 'current')}] {message}"]
    )
    mode = state.get("proposal_mode", "requested")
    knowledge = metric_knowledge(requirement, mode == "discovery")
    selected_variant = state.get("selected_metric_variant")
    if selected_variant:
        knowledge, selected_variant = _resolve_selected_variant(knowledge, selected_variant)
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
        "knowledge": knowledge,
        "selected_metric_variant": selected_variant,
    }
    check_context_budget(context)
    return context


def _resolve_selected_variant(
    knowledge: dict[str, Any], selection: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Revalidate server-stored choices against curated families before generation."""
    catalog = load_metric_knowledge()
    family = next((item for item in catalog["metrics"] if item["id"] == selection.get("knowledge_id")), None)
    variant = find_variant(
        {"metrics": [family]} if family else {}, selection.get("knowledge_id"), selection.get("variant_id")
    )
    if variant is None or variant["criteria"] != selection.get("criteria"):
        raise ValueError("Biến thể đã chọn không còn hợp lệ. Hãy yêu cầu AI đề xuất lại.")
    if not any(item["id"] == family["id"] for item in knowledge.get("metrics", [])):
        knowledge["metrics"].append(family)
    source_ids = {source_id for option in family["variants"] for source_id in option["source_ids"]}
    knowledge["sources"] = [source for source in catalog["sources"] if source["id"] in source_ids]
    return knowledge, {"knowledge_id": family["id"], "variant_id": variant["id"], "criteria": variant["criteria"]}


def check_context_budget(context: dict[str, Any]) -> None:
    """Never silently truncate business constraints to fit a prompt."""
    if (len(json.dumps(context, ensure_ascii=False)) + 3) // 4 > get_settings().metric_context_token_budget:
        raise ValueError(
            "Context quá lớn. Hãy thu hẹp bảng/domain hoặc bắt đầu cuộc trò chuyện mới với đầy đủ điều kiện."
        )
