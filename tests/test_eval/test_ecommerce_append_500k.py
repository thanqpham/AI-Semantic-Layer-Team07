"""Opt-in PostgreSQL integration check for the rollback-only append rehearsal."""

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
    "target_orders=100010",
]


@pytest.mark.skipif(os.getenv("ISSUE51_TEST_APPEND") != "1", reason="requires the synthetic DB 3")
def test_append_rehearsal_validates_and_preserves_database() -> None:
    """Adding ten orders in a dry run must leave the original database unchanged."""
    query = COMMAND[:-2] + [
        "-At",
        "-c",
        "SELECT count(*) || ':' || md5(string_agg(row_to_json(o)::text, ',' ORDER BY id)) FROM orders o",
    ]
    before = subprocess.check_output(query, text=True)  # noqa: S603
    sql = Path("scripts/ecommerce_append_500k.sql").read_text(encoding="utf-8")
    result = subprocess.run(COMMAND, input=sql, text=True, capture_output=True, check=True, timeout=180)  # noqa: S603
    assert "DRY_RUN_OK" in result.stdout
    assert before == subprocess.check_output(query, text=True)  # noqa: S603
    assert before.startswith("100000:")
    refused = subprocess.run(  # noqa: S603
        COMMAND + ["-v", "apply=true"], input=sql, text=True, capture_output=True, timeout=180
    )
    assert refused.returncode != 0
    assert "Commit is supported only for the full 500000-order target" in refused.stderr
    assert before == subprocess.check_output(query, text=True)  # noqa: S603
