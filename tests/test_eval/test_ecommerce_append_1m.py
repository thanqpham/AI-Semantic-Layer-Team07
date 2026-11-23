"""Opt-in PostgreSQL rehearsal for incremental 500k to 1m loading."""

import os
import subprocess
from pathlib import Path

import pytest

COMMAND = [
    "docker",
    "exec",
    "-i",
    "infra-postgres-1",
    "psql",
    "-X",
    "-U",
    "dev",
    "-d",
    "ecommerce_dashboard_demo",
    "-v",
    "ON_ERROR_STOP=1",
    "-v",
    "target_orders=500010",
]


@pytest.mark.skipif(os.getenv("ISSUE51_TEST_APPEND_1M") != "1", reason="requires synthetic 500k DB 3")
def test_small_increment_rolls_back_and_preserves_existing_orders() -> None:
    """A rehearsal crosses the inventory ID boundary without changing existing rows."""
    query = COMMAND[:-2] + [
        "-At",
        "-c",
        "SELECT count(*) || ':' || md5(string_agg(row_to_json(o)::text, ',' ORDER BY id)) FROM orders o",
    ]
    before = subprocess.check_output(query, text=True)  # noqa: S603
    sql = Path("scripts/ecommerce_append_500k.sql").read_text(encoding="utf-8")
    result = subprocess.run(COMMAND, input=sql, text=True, capture_output=True, timeout=240)  # noqa: S603
    assert result.returncode == 0, result.stderr
    assert "DRY_RUN_OK" in result.stdout
    assert before == subprocess.check_output(query, text=True)  # noqa: S603
    assert before.startswith("500000:")
    refused = subprocess.run(COMMAND + ["-v", "apply=true"], input=sql, text=True, capture_output=True, timeout=120)  # noqa: S603
    assert refused.returncode != 0
    assert "Commit requires an exact supported target" in refused.stderr
