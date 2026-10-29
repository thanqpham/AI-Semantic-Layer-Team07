"""Exercise generic child-to-parent metric plans against an in-memory database."""

import sqlite3
import unittest
from types import SimpleNamespace

from src.models.metric_definition import MetricQueryPlan
from src.services.query_compiler_plan import compile_plan_sql
from src.services.query_compiler_sql import validate_read_only


class MetricPlanSQLExecution(unittest.TestCase):
    def test_ratio_counts_parent_once_and_retains_denominator_without_children(self):
        plan = MetricQueryPlan.model_validate({
            "stages": [
                {"name": "numerator", "base_entity": "events", "joins": ["entities"],
                 "filters": [{"field": "entities.status", "operator": "eq", "value": "active"}],
                 "aggregates": [{"name": "count", "function": "COUNT_DISTINCT", "expression": "entities.id"}]},
                {"name": "denominator", "base_entity": "entities",
                 "filters": [{"field": "entities.status", "operator": "eq", "value": "active"}],
                 "aggregates": [{"name": "count", "function": "COUNT_DISTINCT", "expression": "entities.id"}]},
            ],
            "output_expression": "numerator.count / denominator.count * 100",
        })
        tables = {name: SimpleNamespace(table_name=name, physical_schema=None) for name in ("entities", "events")}
        columns = {"entities": {"id": ("id", 1, "INTEGER"), "status": ("status", 2, "TEXT")},
                   "events": {"entity_id": ("entity_id", 3, "INTEGER")}}
        paths = {("events", "entities"): [{"table_name": "entities", "physical_schema": None,
                                            "condition": "events.entity_id = entities.id"}]}
        parameters = {}
        sql = compile_plan_sql(plan, 1, "sqlite", tables, columns, paths, [], {}, [], 100, parameters)
        validate_read_only(sql)
        db = sqlite3.connect(":memory:")
        try:
            db.executescript("CREATE TABLE entities (id INTEGER, status TEXT);"
                             "CREATE TABLE events (entity_id INTEGER);"
                             "INSERT INTO entities VALUES (1, 'active'), (2, 'active'), (3, 'inactive');"
                             "INSERT INTO events VALUES (1), (1), (3);")
            self.assertEqual(db.execute(sql, parameters).fetchone()[0], 50)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
