"""Shared fixtures: bootstrapped ctx + enriched run without LLM."""

import re
from pathlib import Path

import pytest

from eval.agent_runner.bootstrap import prepare_run
from eval.agent_runner.discovery import introspect_target
from eval.agent_runner.enrichment import run_enrichment_pipeline
from src.models.schema_metadata import RawSchemaMetadata

GOLDEN_ROOT = Path("eval/golden_dataset")


def _fake_enrichment(raw: RawSchemaMetadata) -> dict:
    """Synthetic pass1+pass2 replay dict — no golden answers, no LLM."""
    tables = []
    for table in raw.tables:
        name = table.table_name.raw_name
        tables.append(
            {
                "table_name": name,
                "business_name": name.replace("_", " ").title(),
                "description": f"bang {name}",
                "columns": [
                    {
                        "column_name": column.column_name.raw_name,
                        "business_name": column.column_name.raw_name.replace("_", " ").title(),
                        "description": "",
                    }
                    for column in table.columns
                ],
            }
        )
    return {"tables": tables}


def slugify(text: str) -> str:
    """Normalize free text into a bounded identifier fragment."""
    return re.sub(r"\W+", "_", text).strip("_")[:40] or "metric"


@pytest.fixture
async def ctx(tmp_path):
    return await prepare_run(GOLDEN_ROOT, "ecommerce", tmp_path / "run")


@pytest.fixture
async def enriched(ctx):
    """Bootstrap + real enrichment services with synthetic replay (no LLM)."""
    raw = await introspect_target(ctx)
    conn_id = await run_enrichment_pipeline(ctx, raw, enrichment=_fake_enrichment(raw))
    return ctx, conn_id, raw
