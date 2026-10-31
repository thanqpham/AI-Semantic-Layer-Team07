"""Evaluate real relationship suggestions against an independent synthetic fixture."""

import argparse
import asyncio
import json
from pathlib import Path

from fastapi import HTTPException

from eval.evaluator.scoring import match_sets

FIXTURE = Path(__file__).parent / "golden_dataset" / "relationship_suggestions.json"


def relationship_key(item: dict) -> tuple:
    """Normalize direction and retain all pairs of a composite relationship."""
    left, right = item["from_entity_id"], item["to_entity_id"]
    return tuple(
        sorted(
            tuple(sorted(((left, pair["from_column_id"]), (right, pair["to_column_id"]))))
            for pair in item["column_pairs"]
        )
    )


def score_relationships(expected: list[dict], actual: list[dict]) -> dict:
    """Score exact joins and expose missing and unexpected pairs."""
    wanted = {relationship_key(item) for item in expected}
    received = [relationship_key(item) for item in actual]
    match = match_sets(wanted, received)
    return {
        **match.counts.model_dump(),
        **match.metrics.model_dump(),
        "missing": sorted(wanted - set(received)),
        "unexpected": sorted(set(received) - wanted),
        "duplicates": list(match.duplicates),
    }


async def run(baseline: str) -> dict:
    """Run the production suggestion pipeline against synthetic metadata only."""
    from src.config import get_settings
    from src.services.llm import _resolve_llm_config
    from src.services.relationship_suggestions import request_all_suggestions

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    config = _resolve_llm_config(get_settings())
    result = {
        "dataset_version": fixture["version"],
        "baseline": baseline,
        "evaluation_scope": "raw_llm_output",
        "cardinality_scored": False,
        "provider": config.provider,
        "model": config.model,
        "temperature": config.temperature,
        "tables": len(fixture["metadata"]),
        "expected": len(fixture["expected"]),
    }
    try:
        metadata = [{**table, "existing_relationships": []} for table in fixture["metadata"]]
        suggestions = await request_all_suggestions(metadata)
    except HTTPException as exc:
        errors = exc.detail.get("errors", []) if isinstance(exc.detail, dict) else []
        safe = ("code", "unscanned_table_ids", "unscanned_batches")
        return {
            **result,
            "status": "error",
            "failed_runs": 1,
            "errors": [{key: error[key] for key in safe if key in error} for error in errors],
        }
    except Exception as exc:
        return {**result, "status": "error", "error_type": type(exc).__name__, "failed_runs": 1}
    actual = [item.model_dump() for item in suggestions]
    return {
        **result,
        "status": "complete",
        "failed_runs": 0,
        "predicted": len(actual),
        **score_relationships(fixture["expected"], actual),
    }


def main() -> None:
    """Print a reproducible JSON report; this command makes real LLM calls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Identifier of the run used as baseline, or 'none'")
    args = parser.parse_args()
    result = asyncio.run(run(args.baseline))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
