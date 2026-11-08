"""Semantic parser contract at the LLM and catalog boundary."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from eval.run_semantic_parser_eval import evaluate_case, run_for_user
from eval.semantic_parser_cases import _six_month_range
from src.agents.nodes.chat.semantic_query_parser_node import semantic_query_parser_node
from src.agents.roles.semantic_query_parser_integration import _build_parse_prompt, _legacy_prompt_builder
from src.models.schemas import SemanticQueryInterpretation
from src.services.natural_language_query import normalize_interpretation
from tests.test_agents.test_semantic_query_parser_business_filters import SYNTHETIC_CATALOG


def test_prompt_explains_history_and_relative_time() -> None:
    prompt = _build_parse_prompt(
        "theo tháng",
        SYNTHETIC_CATALOG,
        False,
        [
            {"role": "user", "content": "Số đơn hàng trong 6 tháng gần nhất"},
        ],
    )
    assert "Số đơn hàng trong 6 tháng gần nhất" in prompt
    assert "ngày hiện tại lùi N tháng lịch" in prompt
    assert "không mang điều kiện cũ" in prompt.lower()


def test_prompt_screens_nested_formula_literals_and_private_fields() -> None:
    catalog = deepcopy(SYNTHETIC_CATALOG)
    catalog["metrics"][0]["formula_definition"] = {
        "function": "COUNT",
        "expression": "id",
        "_private": "private secret",
        "ratio": {
            "numerator": {
                "function": "COUNT",
                "expression": "secret-expression@x.com",
                "filters": [
                    {"field": "status", "operator": "eq", "value": "returned"},
                    {"field": "email", "operator": "eq", "value": "person@example.com"},
                    {"field": "private-field@x.com", "operator": "private-operator@x.com", "value": "unknown"},
                ],
                "expression_ast": {"value": "secret-ast@x.com"},
            },
            "denominator": {"function": "COUNT", "expression": "id", "filters": []},
            "scale": 100,
        },
    }
    prompt = _build_parse_prompt("Số đơn", catalog, False, [])
    assert "returned" in prompt
    assert "person@example.com" not in prompt
    assert "private secret" not in prompt
    assert "secret-expression@x.com" not in prompt
    assert "secret-ast@x.com" not in prompt
    assert "private-field@x.com" not in prompt
    assert "private-operator@x.com" not in prompt
    direct_prompt = _legacy_prompt_builder("Số đơn", catalog, False, [])
    assert "person@example.com" not in direct_prompt
    assert "private secret" not in direct_prompt


@pytest.mark.asyncio
async def test_clarification_option_normalizes_mapping_and_time_range() -> None:
    payload = {
        "status": "needs_clarification",
        "clarification": {
            "prompt": "Theo tháng?",
            "options": [
                {
                    "id": "monthly",
                    "label": "Theo tháng",
                    "spec": {
                        "metric_ids": [1],
                        "dimensions": [{"column_id": 11, "time_grain": "month"}],
                        "filters": [{"column_id": 12, "operator": "eq", "value": "hoàn tất"}],
                        "time_ranges": [
                            {"column_id": 11, "start_date": "2026-05-08", "end_date": "2026-11-09", "label": "6 tháng"}
                        ],
                    },
                }
            ],
        },
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": "theo tháng", "parser_catalog": SYNTHETIC_CATALOG})
    filters = result["clarification"]["options"][0]["spec"]["filters"]
    assert filters == [
        {"column_id": 12, "operator": "eq", "value": "hoàn tất"},
        {"column_id": 11, "operator": "gte", "value": "2026-05-08"},
        {"column_id": 11, "operator": "lt", "value": "2026-11-09"},
    ]


@pytest.mark.asyncio
async def test_revalidation_preserves_original_label_when_mappings_overlap() -> None:
    catalog = deepcopy(SYNTHETIC_CATALOG)
    column = catalog["filter_columns"][1]
    column["allowed_values"] = []
    column["_approved_mappings"] = [
        {"db_value": "gold", "business_value": "VIP", "status": "approved"},
        {"db_value": "other", "business_value": "gold", "status": "approved"},
    ]
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [
            {"column_id": 12, "operator": "eq", "value": "VIP"},
        ],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": "VIP", "parser_catalog": catalog})
    original = SemanticQueryInterpretation.model_validate(result["interpretation"])
    assert original.spec.filters[0].value == "VIP"
    checked = normalize_interpretation(original, catalog)
    assert checked.status == "resolved"
    assert checked.spec.filters[0].value == "gold"


@pytest.mark.asyncio
async def test_clarification_option_keeps_original_label_for_revalidation() -> None:
    catalog = deepcopy(SYNTHETIC_CATALOG)
    column = catalog["filter_columns"][1]
    column["allowed_values"] = []
    column["_approved_mappings"] = [
        {"db_value": "gold", "business_value": "VIP", "status": "approved"},
        {"db_value": "other", "business_value": "gold", "status": "approved"},
    ]
    spec = {"metric_ids": [1], "filters": [{"column_id": 12, "operator": "eq", "value": "VIP"}]}
    payload = {
        "status": "needs_clarification",
        "clarification": {
            "prompt": "VIP?",
            "options": [
                {"id": "vip", "label": "VIP", "spec": spec},
            ],
        },
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": "VIP", "parser_catalog": catalog})
    option = result["clarification"]["options"][0]["spec"]
    assert option["filters"][0]["value"] == "VIP"
    checked = normalize_interpretation(SemanticQueryInterpretation(status="resolved", spec=option), catalog)
    assert checked.status == "resolved"
    assert checked.spec.filters[0].value == "gold"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"status": "resolved", "metric_ids": [999]},
        {"status": "resolved", "metric_ids": [1], "filter": [{"column_id": 12}]},
    ],
)
async def test_invalid_resolved_output_is_parser_error(payload: dict) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": "Xem số đơn", "parser_catalog": SYNTHETIC_CATALOG})
    assert result["semantic_parse_status"] == "error"
    assert result["run_status"] == "error"
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_oversized_prompt_is_rejected_before_invoking_llm() -> None:
    catalog = deepcopy(SYNTHETIC_CATALOG)
    catalog["metrics"][0]["name"] = "x" * 100_001
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock()) as llm:
        result = await semantic_query_parser_node({"user_message": "x", "parser_catalog": catalog})
    assert result["interpretation"]["status"] == "needs_clarification"
    assert llm.await_count == 0


@pytest.mark.asyncio
async def test_large_private_formula_metadata_does_not_exhaust_prompt_capacity() -> None:
    catalog = deepcopy(SYNTHETIC_CATALOG)
    catalog["metrics"][0]["formula_definition"] = {"function": "COUNT", "_private": "x" * 100_001}
    payload = {"status": "resolved", "metric_ids": [1], "filters": []}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)) as llm:
        result = await semantic_query_parser_node({"user_message": "Số đơn hàng", "parser_catalog": catalog})
    assert result["interpretation"]["status"] == "resolved"
    assert llm.await_count == 1


@pytest.mark.asyncio
async def test_parser_logs_only_safe_summary(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="src.agents.roles.semantic_query_parser_agent")
    secret = "private user text 998877"
    payload = {"status": "resolved", "metric_ids": [1], "filters": [], "rationale": secret}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        await semantic_query_parser_node({"user_message": secret, "parser_catalog": SYNTHETIC_CATALOG})
    assert "Semantic parse summary" in caplog.text
    assert secret not in caplog.text


def test_semantic_evaluation_detects_omitted_and_added_filters() -> None:
    expected = {
        "status": "resolved",
        "metric_ids": [1],
        "dimensions": [],
        "filters": [
            {"column_id": 13, "operator": "eq", "value": "North"},
        ],
    }
    assert not evaluate_case(
        {"expected": expected},
        {
            "status": "resolved",
            "spec": {
                "metric_ids": [1],
                "dimensions": [],
                "filters": [],
            },
        },
    )


def test_semantic_evaluation_six_month_calendar_range() -> None:
    from datetime import date

    assert _six_month_range(date(2026, 8, 31)) == ("2026-02-28", "2026-09-01")
    assert _six_month_range(date(2024, 8, 31)) == ("2024-02-29", "2024-09-01")


def test_semantic_evaluation_rejects_incorrect_ranking() -> None:
    expected = {
        "status": "resolved",
        "metric_ids": [2],
        "dimensions": [],
        "filters": [],
        "limit": 5,
        "order_by": "metric_desc",
        "order_metric_id": 2,
    }
    actual = {"status": "resolved", "spec": {**expected, "order_by": None}}
    assert not evaluate_case({"expected": expected}, actual)


def test_semantic_evaluation_accepts_filter_order_variation() -> None:
    filters = [
        {"column_id": 12, "operator": "eq", "value": "completed"},
        {"column_id": 13, "operator": "in", "value": ["North", "South"]},
    ]
    expected = {"status": "resolved", "metric_ids": [1], "dimensions": [], "filters": filters}
    actual = {
        "status": "resolved",
        "spec": {
            "metric_ids": [1],
            "dimensions": [],
            "filters": [{"column_id": 13, "operator": "in", "value": ["South", "North"]}, filters[0]],
        },
    }
    assert evaluate_case({"expected": expected}, actual)


def test_semantic_evaluation_rejects_provider_error_or_generic_clarification() -> None:
    case = {"expected": {"status": "needs_clarification"}}
    error = {
        "interpretation": {
            "status": "needs_clarification",
            "clarification": {"prompt": "Không thể phân tích yêu cầu. Vui lòng thử lại.", "options": []},
        },
        "semantic_parse_status": "error",
    }
    generic = {
        "interpretation": {
            "status": "needs_clarification",
            "clarification": {"prompt": "Vui lòng làm rõ điều kiện lọc hoặc thời gian của bạn.", "options": []},
        },
        "semantic_parse_status": "needs_clarification",
    }
    assert not evaluate_case(case, error["interpretation"], error["semantic_parse_status"])
    assert not evaluate_case(case, generic["interpretation"], generic["semantic_parse_status"])


@pytest.mark.asyncio
async def test_evaluation_uses_and_restores_account_configuration() -> None:
    from types import SimpleNamespace

    from src.services.llm import account_llm_config

    config = SimpleNamespace(provider="test-provider", model="test-model")
    session = AsyncMock()
    session.__aenter__.return_value = object()
    engine = SimpleNamespace(dispose=AsyncMock())

    async def run_cases() -> int:
        assert account_llm_config.get() is config
        return 0

    with (
        patch("eval.run_semantic_parser_eval.get_session_factory", return_value=lambda: session),
        patch("eval.run_semantic_parser_eval.load_account_llm_config", new=AsyncMock(return_value=config)),
        patch("eval.run_semantic_parser_eval.get_async_engine", return_value=engine),
        patch("eval.run_semantic_parser_eval.main", new=run_cases),
    ):
        assert await run_for_user(7) == 0
    assert account_llm_config.get() is None
    engine.dispose.assert_awaited_once()
