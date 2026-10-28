"""Discovery must scope large inventories before loading full KPI evidence."""

from unittest.mock import AsyncMock, patch

from src.services.metric_context import _token_estimate, build_discovery_context
from src.services.metric_proposal_context import prepare_proposal_context
from src.services.metric_proposals import review_schema_fingerprint
from tests.metric_review_helpers import scope_mock


def _large_schema() -> dict:
    return {
        "tables": [
            {
                "table_name": f"orders_{index}",
                "business_name": "Đơn hàng",
                "description": "Order facts",
                "review_status": "approved",
                "columns": [
                    {
                        "column_name": f"field_{column}",
                        "data_type": "INTEGER",
                        "description": "business context " * 75,
                        "is_primary_key": column == 0,
                        "is_nullable": False,
                        "allowed_values": [0, 1] if column == 7 else None,
                    }
                    for column in range(8)
                ],
            }
            for index in range(3)
        ],
        "relationships": [],
    }


def _loader(schema: dict) -> AsyncMock:
    async def load(_db, _db_id, table_names=None):
        return {
            **schema,
            "tables": [t for t in schema["tables"] if table_names is None or t["table_name"] in table_names],
        }

    return AsyncMock(side_effect=load)


async def test_large_discovery_reaches_generation_with_complete_selected_metadata():
    schema = _large_schema()
    assert _token_estimate(schema) > 8000
    selector = scope_mock({"table_names": ["orders_2"], "needs_clarification": False})
    with (
        patch("src.services.metric_context.load_review_schema", _loader(schema)),
        patch("src.services.metric_context.get_llm"),
        patch("src.services.metric_context.invoke_metric_json", selector),
    ):
        result = await build_discovery_context(None, 1, 8000, question="Doanh thu trước thuế, chỉ đơn hoàn tất")
    assert result.diagnostic["status"] == "ready", result.diagnostic
    assert result.schema["tables"] == [schema["tables"][2]]
    assert result.schema["discovery_scope"] == {"inventory_table_count": 3, "selected_table_count": 1}
    assert "trước thuế, chỉ đơn hoàn tất" in selector.call_args.args[1]
    assert review_schema_fingerprint(result.schema) == review_schema_fingerprint(
        {
            "tables": [schema["tables"][2]],
            "relationships": [],
        }
    )
    assert all(t["table_name"] in selector.call_args.args[1] for t in schema["tables"])
    with patch("src.services.metric_proposal_context.get_settings") as settings:
        settings.return_value.metric_context_token_budget = 8000
        context = prepare_proposal_context(
            {"enriched_schema": result.schema, "proposal_mode": "discovery", "user_message": "Khám phá KPI"}
        )
    assert context["schema"]["tables"][0]["columns"][-1]["allowed_values"] == [0, 1]


async def test_small_discovery_needs_no_scope_llm_call():
    schema = {
        "tables": [{"table_name": "orders", "columns": [{"column_name": "id", "is_primary_key": True}]}],
        "relationships": [],
    }
    with (
        patch("src.services.metric_context.load_review_schema", _loader(schema)),
        patch("src.services.metric_context.invoke_metric_json", new_callable=AsyncMock) as selector,
    ):
        result = await build_discovery_context(None, 1, 8000)
    assert result.diagnostic["status"] == "ready"
    selector.assert_not_awaited()


async def test_explicit_oversized_targets_are_not_silently_replaced():
    schema = _large_schema()
    with (
        patch("src.services.metric_context.load_review_schema", _loader(schema)),
        patch("src.services.metric_context.invoke_metric_json", new_callable=AsyncMock) as selector,
    ):
        result = await build_discovery_context(None, 1, 8000, [t["table_name"] for t in schema["tables"]])
    assert result.diagnostic["status"] == "needs_clarification"
    selector.assert_not_awaited()


async def test_oversized_model_selection_still_respects_context_budget():
    schema = _large_schema()
    selected = {"table_names": [t["table_name"] for t in schema["tables"]], "needs_clarification": False}
    with (
        patch("src.services.metric_context.load_review_schema", _loader(schema)),
        patch("src.services.metric_context.get_llm"),
        patch("src.services.metric_context.invoke_metric_json", scope_mock(selected)),
    ):
        result = await build_discovery_context(None, 1, 8000)
    assert result.diagnostic["status"] == "needs_clarification"


async def test_oversized_inventory_is_not_truncated_or_sent_to_llm():
    schema = _large_schema()
    for table in schema["tables"]:
        for column in table["columns"]:
            column["column_name"] = "long_identifier" * 500
    with (
        patch("src.services.metric_context.load_review_schema", _loader(schema)),
        patch("src.services.metric_context.invoke_metric_json", new_callable=AsyncMock) as selector,
    ):
        result = await build_discovery_context(None, 1, 8000)
    assert result.diagnostic["status"] == "needs_clarification"
    assert "Inventory" in result.diagnostic["message"]
    selector.assert_not_awaited()


async def test_unknown_table_selection_never_reaches_generation():
    with (
        patch("src.services.metric_context.load_review_schema", _loader(_large_schema())),
        patch("src.services.metric_context.get_llm"),
        patch("src.services.metric_context.invoke_metric_json", scope_mock({"table_names": ["invented"]})),
    ):
        result = await build_discovery_context(None, 1, 8000)
    assert result.diagnostic["status"] == "needs_clarification"
