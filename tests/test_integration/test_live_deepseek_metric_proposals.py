"""Opt-in DeepSeek checks using synthetic schema only.

Run with RUN_LIVE_DEEPSEEK=1 and LIVE_LLM_USER_ID set to an account
configured with DeepSeek. These checks incur provider charges.
"""

import os
import unittest

from src.agents.workflows.metric_proposal_workflow import run_metric_workflow
from src.services.database import get_async_engine, get_session_factory
from src.services.llm import account_llm_config
from src.services.llm_settings_service import load_account_llm_config
from src.services.metric_proposal_context import prepare_proposal_context


def synthetic_schema(include_values=True):
    """Return metadata without any real customer data."""
    status = {"id": 3, "column_name": "status", "data_type": "TEXT"}
    if include_values:
        status["allowed_values"] = ["completed", "cancelled"]
    return {
        "tables": [
            {"id": 1, "table_name": "orders", "columns": [
                {"id": 1, "column_name": "id", "data_type": "INTEGER", "is_primary_key": True},
                {"id": 2, "column_name": "amount", "data_type": "NUMERIC"},
                status,
            ]},
            {"id": 2, "table_name": "refunds", "columns": [
                {"id": 4, "column_name": "id", "data_type": "INTEGER", "is_primary_key": True},
                {"id": 5, "column_name": "order_id", "data_type": "INTEGER"},
                {"id": 6, "column_name": "amount", "data_type": "NUMERIC"},
            ]},
            {"id": 3, "table_name": "order_items", "columns": [
                {"id": 7, "column_name": "id", "data_type": "INTEGER", "is_primary_key": True},
                {"id": 8, "column_name": "order_id", "data_type": "INTEGER"},
                {"id": 9, "column_name": "quantity", "data_type": "INTEGER"},
            ]},
        ],
        "relationships": [
            {"from_table": "refunds", "to_table": "orders", "relationship_type": "many_to_one",
             "join_condition": "refunds.order_id = orders.id"},
            {"from_table": "order_items", "to_table": "orders", "relationship_type": "many_to_one",
             "join_condition": "order_items.order_id = orders.id"},
        ],
    }


@unittest.skipUnless(os.environ.get("RUN_LIVE_DEEPSEEK") == "1", "Live DeepSeek test is opt-in")
class LiveDeepSeekMetricProposals(unittest.IsolatedAsyncioTestCase):
    """Exercise real builder, validator and reviewer with a saved account credential."""

    async def asyncSetUp(self):
        async with get_session_factory()() as db:
            config = await load_account_llm_config(db, int(os.environ["LIVE_LLM_USER_ID"]))
        if config is None or config.provider != "deepseek":
            self.fail("The selected account must have DeepSeek configured")
        self.token = account_llm_config.set(config)

    async def asyncTearDown(self):
        account_llm_config.reset(self.token)
        await get_async_engine().dispose()

    async def check_case(self, name, question, include_values=True, expect_ready=True):
        context = prepare_proposal_context({"user_message": question, "enriched_schema": synthetic_schema(include_values)})
        results = await run_metric_workflow(context)
        summaries = [(item["review"]["status"], item["review"].get("summary"),
                      [issue.get("evidence") for issue in item["review"].get("issues", [])]) for item in results]
        print(f"\nCASE {name}: {summaries}", flush=True)
        self.assertTrue(results, "Agent returned no candidates")
        self.assertFalse(any(item["review"]["status"] == "error" for item in results), f"Provider error: {summaries}")
        ready = [item for item in results if item["review"]["status"] == "pass"]
        if expect_ready:
            self.assertTrue(ready, f"No candidate passed review: {summaries}")
        else:
            self.assertFalse(ready, f"Missing status evidence was accepted: {summaries}")

    async def test_five_metric_cases(self):
        cases = [
            ("count_orders", "Tạo metric tổng số đơn hàng, tính tất cả trạng thái.", True, True),
            ("completed_revenue", "Tạo metric tổng amount của đơn hàng có status bằng completed.", True, True),
            ("cancellation_ratio", "Tạo metric tỷ lệ số đơn cancelled trên tổng số đơn, tính phần trăm.", True, True),
            ("missing_values", "Tạo metric số đơn hoàn tất; chưa có quy ước giá trị trạng thái.", False, False),
            ("orders_with_items", "Tạo metric số đơn hàng có ít nhất một dòng hàng; đếm mỗi đơn một lần.", True, True),
            ("orders_with_refunds", "Tạo metric số đơn hàng có ít nhất một bản ghi refunds liên quan, đếm mỗi đơn một lần.", True, True),
        ]
        for name, question, include_values, expect_ready in cases:
            with self.subTest(case=name):
                await self.check_case(name, question, include_values, expect_ready)


if __name__ == "__main__":
    unittest.main(verbosity=2)
