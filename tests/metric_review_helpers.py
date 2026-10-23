"""Small metadata and durable-proof fixtures for metric review tests."""

from typing import Any
from unittest.mock import AsyncMock

from sqlalchemy import select

from src.models.db import SemanticColumnModel, SemanticTableModel
from src.models.metric_definition import MetricDefinition
from src.models.metric_review import MetricScopeSelection
from src.services.metric_context import load_review_schema
from src.services.metric_proposal_generation import prepare_proposal_context
from src.services.metric_proposals import persist_proposal


def definition(expression: str = "amount", name: str = "Doanh thu trước thuế") -> dict[str, Any]:
    return MetricDefinition.model_validate(
        {
            "metric": {
                "name": name,
                "base_entity": "orders",
                "formula": {"function": "SUM", "expression": expression},
                "filters": [],
                "status": "pending_approval",
                "confidence": "high",
                "excluded_notes": "",
            }
        }
    ).model_dump(mode="json")


def reviewer_mock(status: str = "pass", summary: str = "Matches the confirmed request", issues=None) -> AsyncMock:
    """Return correlated judgments while exercising the real coordinator and validators."""
    async def review(_context, _task_id, items):
        return [{"candidate_id": item["candidate_id"], "status": status, "summary": summary,
                 "issues": issues or [], "clarification": summary if status == "needs_clarification" else None} for item in items]
    return AsyncMock(side_effect=review)


def scope_mock(payload: dict) -> AsyncMock:
    """Mock the managed schema agent contract, never a real model endpoint."""
    return AsyncMock(return_value=MetricScopeSelection.model_validate(payload))


def schema() -> dict[str, Any]:
    return {
        "tables": [
            {
                "table_name": "orders",
                "columns": [
                    {"column_name": "id", "data_type": "INTEGER", "is_primary_key": True, "is_nullable": False},
                    {"column_name": "amount", "data_type": "NUMERIC", "is_nullable": False},
                    {"column_name": "status", "data_type": "TEXT", "allowed_values": ["completed", "cancelled"]},
                    {"column_name": "is_test_order", "data_type": "BOOLEAN"},
                ],
            }
        ],
        "relationships": [],
    }


def context() -> dict[str, Any]:
    return prepare_proposal_context(
        {
            "user_message": "Doanh thu trước thuế của đơn hoàn tất",
            "enriched_schema": schema(),
            "user_message_id": "current-message",
            "chat_history": [
                {"id": "original-message", "role": "user", "content": "Tính doanh thu trước thuế"},
                {"id": "clarification", "role": "assistant", "content": "Lấy đơn nào?"},
            ],
        }
    )


async def seed_proposal(db, db_id: int, user_id: int, raw: dict[str, Any] | None = None):
    raw = raw or definition()
    table = await db.scalar(select(SemanticTableModel).where(SemanticTableModel.db_id == db_id))
    if table is None:
        table = SemanticTableModel(db_id=db_id, table_name="orders", business_name="Đơn hàng", review_status="approved")
        db.add(table)
        await db.flush()
        db.add_all(
            [
                SemanticColumnModel(
                    table_id=table.id, column_name="id", business_name="ID", data_type="INTEGER", is_primary_key=True
                ),
                SemanticColumnModel(
                    table_id=table.id, column_name="amount", business_name="Amount", data_type="NUMERIC"
                ),
            ]
        )
        await db.flush()
    evidence_context = {**context(), "schema": await load_review_schema(db, db_id)}
    return await persist_proposal(
        db,
        db_id,
        user_id,
        {
            "context": evidence_context,
            "original_definition": raw,
            "final_definition": raw,
            "review": {"status": "pass", "summary": "Định nghĩa khớp yêu cầu và metadata."},
        },
    )
