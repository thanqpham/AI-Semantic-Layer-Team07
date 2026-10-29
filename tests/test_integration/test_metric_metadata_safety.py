"""Regression checks for metadata-only metric context and plan instructions."""

import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import Enum, Text

from src.agents.roles.metric_prompt_rules import MULTI_TABLE_RULES
from src.models.db import SemanticColumnModel, SemanticTableModel
from src.services.introspection import _column
from src.services.metric_context import load_review_schema
from src.services.metric_review_validation import technical_review


class MetricMetadataSafety(unittest.IsolatedAsyncioTestCase):
    async def test_review_schema_does_not_read_live_database_rows(self):
        column = SemanticColumnModel(id=1, column_name="status", data_type="TEXT", allowed_values=None)
        table = SemanticTableModel(id=1, table_name="orders", columns=[column])
        with patch("src.services.metric_context._load_metadata", AsyncMock(return_value=([table], []))):
            result = await load_review_schema(AsyncMock(), 1)
        self.assertIsNone(result["tables"][0]["columns"][0]["allowed_values"])

    def test_reflected_enum_is_metadata_and_text_has_no_values(self):
        for data_type, expected in [(Enum("completed", "cancelled"), ["completed", "cancelled"]), (Text(), None)]:
            result = _column({"name": "status", "type": data_type}, set(), {})
            self.assertEqual(result["sample_values"], expected)

    def test_agent_is_told_how_to_handle_related_rows_safely(self):
        self.assertIn("COUNT_DISTINCT", MULTI_TABLE_RULES)
        self.assertIn("nhiều-một", MULTI_TABLE_RULES)
        self.assertIn("bảng con", MULTI_TABLE_RULES)

    def test_child_rows_can_count_distinct_parent_without_fanout(self):
        schema = {
            "tables": [
                {"id": 1, "table_name": "orders", "columns": [
                    {"id": 1, "column_name": "id", "data_type": "INTEGER", "is_primary_key": True},
                ]},
                {"id": 2, "table_name": "order_items", "columns": [
                    {"id": 2, "column_name": "id", "data_type": "INTEGER", "is_primary_key": True},
                    {"id": 3, "column_name": "order_id", "data_type": "INTEGER"},
                ]},
            ],
            "relationships": [{"from_table": "order_items", "to_table": "orders",
                               "relationship_type": "many_to_one", "join_condition": "order_items.order_id = orders.id"}],
        }
        raw = {"metric": {"name": "Số đơn có dòng hàng", "base_entity": "order_items", "query_plan": {
            "stages": [{"name": "counts", "base_entity": "order_items", "joins": ["orders"],
                        "aggregates": [{"name": "orders", "function": "COUNT_DISTINCT", "expression": "orders.id"}]}],
            "output_expression": "counts.orders",
        }}}
        definition, issue = technical_review(raw, {"schema": schema})
        self.assertIsNone(issue, str(issue))
        self.assertEqual(definition.schema_version, 3)


if __name__ == "__main__":
    unittest.main()
