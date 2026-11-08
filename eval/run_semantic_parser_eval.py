"""Run synthetic semantic parser evaluation using the configured LLM; opt in via CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from eval.semantic_parser_cases import case_catalog, semantic_parser_cases
from src.agents.roles.semantic_query_parser_integration import parse_semantic_query
from src.models.schemas import SemanticQueryInterpretation
from src.services.database import get_async_engine, get_session_factory
from src.services.llm import account_llm_config
from src.services.llm_settings_service import load_account_llm_config
from src.services.natural_language_query import normalize_interpretation


def evaluate_case(case: dict[str, Any], interpretation: dict[str, Any], parse_status: str = "resolved") -> bool:
    """Compare interpretation against the expected status and normalized selection."""
    expected = case["expected"]
    if parse_status == "error" or interpretation.get("status") != expected["status"]:
        return False
    if expected["status"] != "resolved":
        prompt = (interpretation.get("clarification") or {}).get("prompt", "").strip()
        return bool(prompt) and prompt not in {
            "Vui lòng làm rõ điều kiện lọc hoặc thời gian của bạn.",
            "Tôi cần thêm thông tin để chạy truy vấn chính xác. Bạn vui lòng chọn một trong các gợi ý dưới đây:",
        }
    checked = normalize_interpretation(SemanticQueryInterpretation.model_validate(interpretation), case_catalog(case))
    if checked.status != "resolved" or checked.spec is None:
        return False
    spec = checked.spec.model_dump()
    fields = ("metric_ids", "dimensions", "limit", "order_by", "order_metric_id")
    return all(spec.get(field) == expected[field] for field in fields if field in expected) and (
        "filters" not in expected
        or _canonical_filters(spec.get("filters", [])) == _canonical_filters(expected["filters"])
    )


def _canonical_filters(filters: list[dict[str, Any]]) -> list[str]:
    """Compare conjunctions and IN values independent of their original ordering."""
    normalized = []
    for item in filters:
        item = dict(item)
        if item.get("operator") in {"in", "not_in"} and isinstance(item.get("value"), list):
            item["value"] = sorted(item["value"], key=lambda value: json.dumps(value, sort_keys=True))
        normalized.append(json.dumps(item, sort_keys=True, ensure_ascii=False))
    return sorted(normalized)


async def main() -> int:
    """Run all synthetic cases and print each result; return nonzero on any mismatch."""
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    cases = semantic_parser_cases(today)
    failures = 0
    for case in cases:
        result = await parse_semantic_query(case["question"], case_catalog(case), chat_history=case.get("history", []))
        passed = evaluate_case(case, result["interpretation"], result["semantic_parse_status"]) and (
            not case.get("expected_parse_status")
            or result.get("semantic_parse_status") == case["expected_parse_status"]
        )
        failures += not passed
        print(f"{'PASS' if passed else 'FAIL'} | {case['question']}", flush=True)
    print(f"{len(cases) - failures}/{len(cases)} passed", flush=True)
    return int(bool(failures))


async def run_for_user(user_id: int) -> int:
    """Evaluate using the same saved LLM configuration as a specified account."""
    try:
        async with get_session_factory()() as db:
            config = await load_account_llm_config(db, user_id)
        if config is None:
            print("No saved LLM configuration for this account.", flush=True)
            return 2
        print(f"provider={config.provider} model={config.model}", flush=True)
        token = account_llm_config.set(config)
        try:
            return await main()
        finally:
            account_llm_config.reset(token)
    finally:
        await get_async_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, required=True, help="Account whose saved LLM configuration is used")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_for_user(args.user_id)))
