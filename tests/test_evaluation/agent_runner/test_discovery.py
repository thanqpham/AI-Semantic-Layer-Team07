"""Discovery collector introspects the run target and shares one candidate."""

from pathlib import Path

from eval.agent_runner.adapters import to_eval_raw_schema
from eval.agent_runner.bootstrap import prepare_run
from eval.agent_runner.discovery import collect_discovery, introspect_target


async def test_collect_discovery_same_candidate_for_all_cases(tmp_path):
    ctx = await prepare_run(Path("eval/golden_dataset"), "ecommerce", tmp_path / "run")
    raw = await introspect_target(ctx)
    assert raw.tables  # non-empty RawSchemaMetadata

    candidates = await collect_discovery(ctx, ["d1", "d2"])
    assert set(candidates) == {"d1", "d2"}
    schema = candidates["d1"].raw_schema
    assert schema == to_eval_raw_schema(raw)
    assert any(t["table_name"] == "fact_orders" for t in schema["tables"])
