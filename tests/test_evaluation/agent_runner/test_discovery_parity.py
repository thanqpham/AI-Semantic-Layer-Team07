"""Parity: converted live introspection must match golden sqlite_live.json."""

import json
import sqlite3
from pathlib import Path

from eval.agent_runner.adapters import to_eval_raw_schema
from src.services.live_db_service import introspect_live_database

GOLDEN = Path("eval/golden_dataset/ecommerce")


def _build_target(tmp_path: Path) -> Path:
    target = tmp_path / "target.sqlite"
    conn = sqlite3.connect(target)
    conn.executescript((GOLDEN / "sources/sqlite/schema.sql").read_text(encoding="utf-8"))
    conn.executescript((GOLDEN / "sources/sqlite/seed_data.sql").read_text(encoding="utf-8"))
    conn.close()
    return target


def _fixture() -> dict:
    return json.loads((GOLDEN / "raw_schema/sqlite_live.json").read_text(encoding="utf-8"))


def test_converted_schema_table_and_column_parity(tmp_path):
    target = _build_target(tmp_path)
    raw = introspect_live_database(f"sqlite:///{target.as_posix()}", "sqlite")
    converted = to_eval_raw_schema(raw)
    fixture = _fixture()

    conv_tables = {t["table_name"]: t for t in converted["tables"]}
    fix_tables = {t["table_name"]: t for t in fixture["tables"]}
    assert set(conv_tables) == set(fix_tables)

    for name, table in fix_tables.items():
        conv_cols = {c["column_name"] for c in conv_tables[name]["columns"]}
        fix_cols = {c["column_name"] for c in table["columns"]}
        assert conv_cols == fix_cols, name


def test_converted_schema_primary_key_and_relationship_parity(tmp_path):
    target = _build_target(tmp_path)
    raw = introspect_live_database(f"sqlite:///{target.as_posix()}", "sqlite")
    converted = to_eval_raw_schema(raw)
    fixture = _fixture()

    def pk_map(tables):
        return {t["table_name"]: set(t.get("primary_keys") or []) for t in tables}

    def rel_set(schema):
        return {(r["from_table"], r["from_column"], r["to_table"], r["to_column"]) for r in schema["relationships"]}

    assert pk_map(converted["tables"]) == pk_map(fixture["tables"])
    assert rel_set(converted) == rel_set(fixture)
