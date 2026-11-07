"""Unit tests for semantic_query_parser_node."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.nodes.chat.semantic_query_parser_node import semantic_query_parser_node
from src.agents.roles.semantic_query_parser_agent import _build_parse_prompt


@pytest.fixture
def sample_catalog() -> dict:
    return {
        "metrics": [
            {
                "id": 1,
                "name": "total_revenue",
                "business_name": "Tổng doanh thu",
                "formula": "SUM(amount)",
                "base_entity": "orders",
                "dimension_ids": [10, 11],
                "filter_column_ids": [11, 12],
            },
            {
                "id": 2,
                "name": "order_count",
                "business_name": "Số lượng đơn hàng",
                "formula": "COUNT(id)",
                "base_entity": "orders",
                "dimension_ids": [10, 11],
                "filter_column_ids": [11, 12],
            },
        ],
        "dimensions": [
            {
                "column_id": 10,
                "column_name": "customer_id",
                "business_name": "Mã khách hàng",
                "table_name": "orders",
                "data_type": "INTEGER",
                "is_time_dimension": False,
            },
            {
                "column_id": 11,
                "column_name": "created_at",
                "business_name": "Ngày tạo đơn",
                "table_name": "orders",
                "data_type": "TIMESTAMP",
                "is_time_dimension": True,
            },
        ],
        "filter_columns": [
            {
                "column_id": 12,
                "column_name": "status",
                "business_name": "Trạng thái đơn",
                "table_name": "orders",
                "data_type": "VARCHAR",
                "allowed_values": ["completed"],
                "allowed_value_mappings": [{"db_value": "completed", "business_value": "hoàn tất"}],
            },
            {"column_id": 11, "column_name": "created_at", "data_type": "TIMESTAMP", "is_time_dimension": True},
        ],
    }


def test_prompt_requires_empty_top_level_metric_ids_for_unresolved_queries(sample_catalog: dict) -> None:
    prompt = _build_parse_prompt("Xem lợi nhuận", sample_catalog, False, [])
    assert 'status "missing_metric" hoặc "needs_clarification", metric_ids cấp cao nhất phải là []' in prompt
    assert '"status": "missing_metric", "metric_name": "Tỷ lệ giữ chân khách hàng", "metric_ids": []' in prompt


def test_private_approved_mappings_do_not_enter_llm_prompt(sample_catalog: dict) -> None:
    sample_catalog["_relationship_fingerprint"] = "private_relationship_digest"
    sample_catalog["metrics"][0]["_definition_fingerprint"] = "private_digest"
    sample_catalog["filter_columns"][0]["_approved_mappings"] = [
        {"db_value": "private_code", "business_value": "Private Name"}
    ]
    prompt = _build_parse_prompt("Xem doanh thu", sample_catalog, False, [])
    assert "Private Name" not in prompt
    assert "private_code" not in prompt
    assert "private_digest" not in prompt
    assert "private_relationship_digest" not in prompt


@pytest.mark.asyncio
async def test_parser_rejects_unknown_resolved_field(sample_catalog: dict) -> None:
    payload = {"status": "resolved", "metric_ids": [1], "filter": [{"column_id": 12, "value": "hoàn tất"}]}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu hoàn tất", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_year_in_metric_name_is_not_invented_as_filter(sample_catalog: dict) -> None:
    sample_catalog["metrics"][0]["business_name"] = "Doanh thu năm 2024"
    payload = {"status": "resolved", "metric_ids": [1]}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Xem Doanh thu năm 2024", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_metric_name_year_is_not_treated_as_historical_filter(sample_catalog: dict) -> None:
    sample_catalog["metrics"][0]["business_name"] = "Doanh thu năm 2024"
    payload = {"status": "resolved", "metric_ids": [1], "dimensions": [{"column_id": 10}]}
    state = {
        "user_message": "Theo khách hàng",
        "chat_history": [{"role": "user", "content": "Xem Doanh thu năm 2024"}],
        "parser_catalog": sample_catalog,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(state)
    assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_parser_rejects_unknown_nested_filter_field(sample_catalog: dict) -> None:
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "eq", "value": "completed", "condition": "not"}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu hoàn tất", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize("filters,ranges", [([], []), ([{"column_id": 12, "operator": "eq", "value": "hoàn tất"}], [])])
async def test_parser_does_not_drop_explicit_year(sample_catalog: dict, filters: list, ranges: list) -> None:
    payload = {"status": "resolved", "metric_ids": [1], "filters": filters, "time_ranges": ranges}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu hoàn tất năm 2024", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_parser_does_not_drop_known_business_value(sample_catalog: dict) -> None:
    payload = {"status": "resolved", "metric_ids": [1], "filters": []}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu hoàn tất", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_parser_does_not_replace_requested_year(sample_catalog: dict) -> None:
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "time_ranges": [{"column_id": 11, "start_date": "2023-01-01", "end_date": "2024-01-01", "label": "2023"}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu năm 2024", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end", [("2024-01-01", None), ("2023-01-01", "2026-01-01")])
async def test_parser_requires_exact_full_year_bounds(sample_catalog: dict, start: str, end: str | None) -> None:
    filters = [{"column_id": 11, "operator": "gte", "value": start}]
    if end:
        filters.append({"column_id": 11, "operator": "lt", "value": end})
    payload = {"status": "resolved", "metric_ids": [1], "filters": filters}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu năm 2024", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["tháng trước", "tháng này", "tuần trước", "hôm nay", "quý 2"])
async def test_parser_does_not_drop_relative_time(sample_catalog: dict, period: str) -> None:
    payload = {"status": "resolved", "metric_ids": [1], "filters": []}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": f"Doanh thu {period}", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,start,end",
    [
        ("Doanh thu tháng 1 năm 2024", "2024-01-01", "2024-02-01"),
        ("Doanh thu từ năm 2023 đến năm 2024", "2023-01-01", "2025-01-01"),
    ],
)
async def test_parser_accepts_explicit_time_interval(sample_catalog: dict, question: str, start: str, end: str) -> None:
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "time_ranges": [{"column_id": 11, "start_date": start, "end_date": end, "label": question}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": question, "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_parser_accepts_exact_today_range(sample_catalog: dict) -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "time_ranges": [
            {
                "column_id": 11,
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=1)).isoformat(),
                "label": "Hôm nay",
            }
        ],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu hôm nay", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
@pytest.mark.parametrize("operator,question", [("neq", "Doanh thu miền Bắc"), ("eq", "Doanh thu không phải miền Bắc")])
async def test_parser_requires_matching_negation(sample_catalog: dict, operator: str, question: str) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North"], _approved_mappings=[{"db_value": "North", "business_value": "miền Bắc"}]
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": operator, "value": "North"}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": question, "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_parser_allows_explicit_matching_negation(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North"], _approved_mappings=[{"db_value": "North", "business_value": "miền Bắc"}]
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "neq", "value": "North"}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu không phải miền Bắc", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_followup_keeps_previous_filter_with_new_year(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North"], _approved_mappings=[{"db_value": "North", "business_value": "miền Bắc"}]
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "time_ranges": [{"column_id": 11, "start_date": "2024-01-01", "end_date": "2025-01-01", "label": "2024"}],
    }
    state = {
        "user_message": "Chỉ năm 2024",
        "chat_history": [{"role": "user", "content": "Doanh thu miền Bắc"}],
        "parser_catalog": sample_catalog,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(state)
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_followup_keeps_previous_year_when_adding_dimension(sample_catalog: dict) -> None:
    payload = {"status": "resolved", "metric_ids": [1], "dimensions": [{"column_id": 10}]}
    state = {
        "user_message": "Theo khách hàng",
        "chat_history": [{"role": "user", "content": "Doanh thu năm 2024"}],
        "parser_catalog": sample_catalog,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(state)
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_followup_change_of_region_does_not_require_old_region(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North", "South"],
        _approved_mappings=[
            {"db_value": "North", "business_value": "miền Bắc"},
            {"db_value": "South", "business_value": "miền Nam"},
        ],
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "eq", "value": "South"}],
    }
    state = {
        "user_message": "Bây giờ xem miền Nam",
        "chat_history": [{"role": "user", "content": "Doanh thu miền Bắc"}],
        "parser_catalog": sample_catalog,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(state)
    assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_followup_replacing_region_does_not_keep_old_value(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North", "South"],
        _approved_mappings=[
            {"db_value": "North", "business_value": "miền Bắc"},
            {"db_value": "South", "business_value": "miền Nam"},
        ],
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "in", "value": ["North", "South"]}],
    }
    state = {
        "user_message": "Bây giờ xem miền Nam",
        "chat_history": [{"role": "user", "content": "Doanh thu miền Bắc"}],
        "parser_catalog": sample_catalog,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(state)
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_ambiguous_same_label_from_different_columns_requires_clarification(sample_catalog: dict) -> None:
    sample_catalog["metrics"][0]["filter_column_ids"].append(13)
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North"], _approved_mappings=[{"db_value": "North", "business_value": "miền Bắc"}]
    )
    sample_catalog["filter_columns"].append(
        {
            "column_id": 13,
            "column_name": "region",
            "table_name": "customers",
            "data_type": "TEXT",
            "allowed_values": ["North"],
            "_approved_mappings": [{"db_value": "North", "business_value": "miền Bắc"}],
        }
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "eq", "value": "North"}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu miền Bắc", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_or_request_does_not_execute_two_and_filters(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North", "South"],
        _approved_mappings=[
            {"db_value": "North", "business_value": "miền Bắc"},
            {"db_value": "South", "business_value": "miền Nam"},
        ],
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [
            {"column_id": 12, "operator": "eq", "value": "North"},
            {"column_id": 12, "operator": "eq", "value": "South"},
        ],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu miền Bắc hoặc miền Nam", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,filters",
    [
        (
            "Doanh thu Mien Bac hoac Mien Nam",
            [
                {"column_id": 12, "operator": "eq", "value": "Mien Bac"},
                {"column_id": 12, "operator": "eq", "value": "Mien Nam"},
            ],
        ),
        ("Doanh thu ngoai Mien Bac", [{"column_id": 12, "operator": "eq", "value": "Mien Bac"}]),
    ],
)
async def test_ascii_conditions_keep_or_negation(sample_catalog: dict, question: str, filters: list[dict]) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North", "South"],
        _approved_mappings=[
            {"db_value": "North", "business_value": "Miền Bắc"},
            {"db_value": "South", "business_value": "Miền Nam"},
        ],
    )
    payload = {"status": "resolved", "metric_ids": [1], "filters": filters}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": question, "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_unrequested_extra_time_filter_requires_clarification(sample_catalog: dict) -> None:
    sample_catalog["metrics"][0]["filter_column_ids"].append(13)
    sample_catalog["filter_columns"].append({"column_id": 13, "column_name": "shipped_at", "data_type": "TIMESTAMP"})
    bounds = [
        {"column_id": col, "operator": op, "value": val}
        for col in [11, 13]
        for op, val in [("gte", "2024-01-01"), ("lt", "2025-01-01")]
    ]
    payload = {"status": "resolved", "metric_ids": [1], "filters": bounds}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu năm 2024", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_excluding_region_cannot_become_inclusion(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North"], _approved_mappings=[{"db_value": "North", "business_value": "miền Bắc"}]
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "eq", "value": "North"}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu ngoài miền Bắc", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_unrequested_grouping_requires_clarification(sample_catalog: dict) -> None:
    payload = {"status": "resolved", "metric_ids": [1], "dimensions": [{"column_id": 10}]}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": "Tổng doanh thu", "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["Doanh thu theo khu vực", "Top 5 sản phẩm doanh thu cao nhất"])
async def test_requested_grouping_cannot_be_omitted(sample_catalog: dict, question: str) -> None:
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "dimensions": [],
        "filters": [],
        "limit": 5,
        "order_by": "metric_desc",
        "order_metric_id": 1,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": question, "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_filter",
    [
        {"column_id": 11, "operator": "gte", "value": "2024-01-01"},
        {"column_id": 13, "operator": "gt", "value": 1000},
    ],
)
async def test_unrequested_filter_cannot_be_added(sample_catalog: dict, extra_filter: dict) -> None:
    sample_catalog["metrics"][0]["filter_column_ids"].append(13)
    sample_catalog["filter_columns"].append({"column_id": 13, "column_name": "amount", "data_type": "NUMERIC"})
    payload = {"status": "resolved", "metric_ids": [1], "filters": [extra_filter]}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": "Tổng doanh thu", "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,extra_filter",
    [
        ("Doanh thu đơn trên 100", {"column_id": 13, "operator": "lt", "value": 100}),
        ("Tổng doanh thu", {"column_id": 12, "operator": "is_null", "value": None}),
    ],
)
async def test_filter_operator_must_match_request(sample_catalog: dict, question: str, extra_filter: dict) -> None:
    sample_catalog["metrics"][0]["filter_column_ids"].append(13)
    sample_catalog["filter_columns"].append({"column_id": 13, "column_name": "amount", "data_type": "NUMERIC"})
    payload = {"status": "resolved", "metric_ids": [1], "filters": [extra_filter]}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": question, "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_year_is_not_evidence_for_an_unrequested_numeric_filter(sample_catalog: dict) -> None:
    sample_catalog["metrics"][0]["filter_column_ids"].append(13)
    sample_catalog["filter_columns"].append({"column_id": 13, "column_name": "amount", "data_type": "NUMERIC"})
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 13, "operator": "eq", "value": 2024}],
        "time_ranges": [{"column_id": 11, "start_date": "2024-01-01", "end_date": "2025-01-01", "label": "Năm 2024"}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu năm 2024", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_null_condition_cannot_be_inverted(sample_catalog: dict) -> None:
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "is_not_null", "value": None}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu không có trạng thái đơn", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,dimensions",
    [
        ("Doanh thu theo tháng", []),
        ("Doanh thu theo ngày tạo đơn", [{"column_id": 10}]),
    ],
)
async def test_grouping_must_match_request(sample_catalog: dict, question: str, dimensions: list) -> None:
    payload = {"status": "resolved", "metric_ids": [1], "dimensions": dimensions}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": question, "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,filters",
    [
        ("Doanh thu số lượng trên 100", []),
        ("Doanh thu số lượng trên 100", [{"column_id": 13, "operator": "eq", "value": 100}]),
        ("Doanh thu không có số lượng", [{"column_id": 13, "operator": "is_not_null", "value": None}]),
    ],
)
async def test_numeric_conditions_cannot_be_lost_or_inverted(
    sample_catalog: dict, question: str, filters: list
) -> None:
    sample_catalog["metrics"][0]["filter_column_ids"].append(13)
    sample_catalog["filter_columns"].append(
        {"column_id": 13, "column_name": "quantity", "business_name": "Số lượng", "data_type": "INTEGER"}
    )
    payload = {"status": "resolved", "metric_ids": [1], "filters": filters}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": question, "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_all_requested_grouping_dimensions_are_required(sample_catalog: dict) -> None:
    sample_catalog["metrics"][0]["dimension_ids"].append(13)
    sample_catalog["dimensions"].append(
        {"column_id": 13, "column_name": "region", "business_name": "Khu vực", "data_type": "TEXT"}
    )
    payload = {"status": "resolved", "metric_ids": [1], "dimensions": [{"column_id": 13}]}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu theo khu vực và khách hàng", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_grouping_ignores_columns_only_compatible_with_another_metric(sample_catalog: dict) -> None:
    sample_catalog["dimensions"].append(
        {"column_id": 13, "column_name": "customer_id", "business_name": "Mã khách hàng", "data_type": "INTEGER"}
    )
    sample_catalog["metrics"][1]["dimension_ids"].append(13)
    payload = {"status": "resolved", "metric_ids": [1], "dimensions": [{"column_id": 10}]}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu theo khách hàng", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_polite_followup_does_not_drop_prior_filter(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North"], _approved_mappings=[{"db_value": "North", "business_value": "Miền Bắc"}]
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "time_ranges": [{"column_id": 11, "start_date": "2024-01-01", "end_date": "2025-01-01", "label": "2024"}],
    }
    state = {
        "user_message": "Xin cho toi nam 2024",
        "chat_history": [{"role": "user", "content": "Doanh thu Mien Bac"}],
        "parser_catalog": sample_catalog,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(state)
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_or_request_accepts_single_in_filter(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North", "South"],
        _approved_mappings=[
            {"db_value": "North", "business_value": "miền Bắc"},
            {"db_value": "South", "business_value": "miền Nam"},
        ],
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "in", "value": ["North", "South"]}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu miền Bắc hoặc miền Nam", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_unmapped_region_cannot_be_silently_dropped(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(allowed_values=["North", "South"], allowed_value_mappings=[])
    payload = {"status": "resolved", "metric_ids": [1], "filters": []}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu miền Bắc", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
@pytest.mark.parametrize("order,limit", [(None, 5), ("metric_desc", 100)])
async def test_top_five_requires_order_and_requested_limit(sample_catalog: dict, order: str | None, limit: int) -> None:
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "dimensions": [{"column_id": 10}],
        "order_by": order,
        "order_metric_id": 1,
        "limit": limit,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Top 5 khách hàng doanh thu cao nhất", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_latest_categorical_value_cannot_be_overridden_by_history(sample_catalog: dict) -> None:
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North", "South"],
        _approved_mappings=[
            {"db_value": "North", "business_value": "miền Bắc"},
            {"db_value": "South", "business_value": "miền Nam"},
        ],
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "eq", "value": "North"}],
    }
    state = {
        "user_message": "Bây giờ xem miền Nam",
        "chat_history": [{"role": "user", "content": "Xem miền Bắc"}],
        "parser_catalog": sample_catalog,
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(state)
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_parser_rejects_malformed_filter_instead_of_silently_omitting(sample_catalog: dict) -> None:
    payload = {"status": "resolved", "metric_ids": [1], "filters": [{"operator": "eq", "value": "x"}]}
    with patch(
        "src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock, return_value=payload
    ):
        result = await semantic_query_parser_node({"user_message": "Doanh thu", "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_parser_rejects_incompatible_dimension_for_one_metric(sample_catalog: dict) -> None:
    sample_catalog["metrics"][0]["dimension_ids"] = []
    payload = {"status": "resolved", "metric_ids": [1], "dimensions": [{"column_id": 10}]}
    with patch(
        "src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock, return_value=payload
    ):
        result = await semantic_query_parser_node({"user_message": "Doanh thu", "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_parser_requires_approved_mapping_to_connect_north_with_mien_bac(sample_catalog: dict) -> None:
    column = sample_catalog["filter_columns"][0]
    column.update(allowed_values=["North"], allowed_value_mappings=[])
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "eq", "value": "North"}],
    }
    state = {"user_message": "Doanh thu miền Bắc", "parser_catalog": sample_catalog}
    with patch(
        "src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock, return_value=payload
    ):
        result = await semantic_query_parser_node(state)
        assert result["interpretation"]["status"] == "needs_clarification"
        column["_approved_mappings"] = [{"db_value": "North", "business_value": "miền Bắc"}]
        result = await semantic_query_parser_node(state)
        assert result["interpretation"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_evidence_preserves_vietnamese_accents(sample_catalog: dict) -> None:
    column = sample_catalog["filter_columns"][0]
    column.update(allowed_values=["Nam"], allowed_value_mappings=[])
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "filters": [{"column_id": 12, "operator": "eq", "value": "Nam"}],
    }
    with patch(
        "src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock, return_value=payload
    ):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu năm 2024", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_member_query_keeps_approved_region_filter_and_time_range(sample_catalog: dict) -> None:
    from src.models.schemas import SemanticQueryInterpretation
    from src.services.natural_language_query import normalize_interpretation

    sample_catalog["metrics"][0].update(name="total_orders", business_name="Tổng số đơn hàng")
    sample_catalog["filter_columns"][0].update(
        allowed_values=["North"], _approved_mappings=[{"db_value": "North", "business_value": "Miền Bắc"}]
    )
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "dimensions": [],
        "filters": [{"column_id": 12, "operator": "eq", "value": "Miền Bắc"}],
        "time_ranges": [{"column_id": 11, "start_date": "2024-01-01", "end_date": "2025-01-01", "label": "2024"}],
    }
    state = {"user_message": "Trong năm 2024, miền Bắc có bao nhiêu đơn hàng?", "parser_catalog": sample_catalog}
    with patch(
        "src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock, return_value=payload
    ):
        result = await semantic_query_parser_node(state)
    checked = normalize_interpretation(SemanticQueryInterpretation(**result["interpretation"]), sample_catalog)
    assert checked.status == "resolved"
    assert checked.spec.dimensions == []
    assert [(f.column_id, f.operator, f.value) for f in checked.spec.filters] == [
        (12, "eq", "North"),
        (11, "gte", "2024-01-01"),
        (11, "lt", "2025-01-01"),
    ]


@pytest.mark.asyncio
async def test_parser_drops_incompatible_clarification_option(sample_catalog: dict) -> None:
    sample_catalog["metrics"][0]["dimension_ids"] = []
    payload = {
        "status": "needs_clarification",
        "clarification": {
            "prompt": "Chọn",
            "options": [
                {"id": "bad", "label": "Theo khách", "spec": {"metric_ids": [1], "dimensions": [{"column_id": 10}]}}
            ],
        },
    }
    with patch(
        "src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock, return_value=payload
    ):
        result = await semantic_query_parser_node({"user_message": "Doanh thu", "parser_catalog": sample_catalog})
    assert result["interpretation"]["clarification"]["options"] == []


@pytest.mark.asyncio
async def test_clarification_option_preserves_time_range_as_filters(sample_catalog: dict) -> None:
    payload = {
        "status": "needs_clarification",
        "clarification": {
            "prompt": "Chọn",
            "options": [
                {
                    "id": "one",
                    "label": "Năm 2024",
                    "spec": {
                        "metric_ids": [1],
                        "time_ranges": [
                            {"column_id": 11, "start_date": "2024-01-01", "end_date": "2025-01-01", "label": "2024"}
                        ],
                    },
                }
            ],
        },
    }
    with patch(
        "src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock, return_value=payload
    ):
        result = await semantic_query_parser_node({"user_message": "Doanh thu 2024", "parser_catalog": sample_catalog})
    filters = result["interpretation"]["clarification"]["options"][0]["spec"]["filters"]
    assert [(item["operator"], item["value"]) for item in filters] == [("gte", "2024-01-01"), ("lt", "2025-01-01")]


@pytest.mark.asyncio
async def test_empty_catalog_returns_needs_clarification() -> None:
    """An ambiguous request remains a clarification even with an empty catalog."""
    state = {
        "user_message": "Tổng doanh thu 2024",
        "parser_catalog": {"metrics": []},
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = {"status": "needs_clarification", "clarification": {"prompt": "Chỉ số nào?"}}
        result = await semantic_query_parser_node(state)

    assert result["intent"] == "semantic_query"
    assert result["interpretation"]["status"] == "needs_clarification"
    assert result["semantic_parse_status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_resolved_query_mapping(sample_catalog: dict) -> None:
    """Valid LLM JSON is mapped to resolved SemanticQueryInterpretation with spec and time range."""
    llm_payload = {
        "status": "resolved",
        "metric_ids": [1],
        "dimensions": [{"column_id": 10, "time_grain": None}],
        "filters": [{"column_id": 12, "operator": "eq", "value": "completed"}],
        "time_ranges": [
            {
                "column_id": 11,
                "start_date": "2024-01-01",
                "end_date": "2025-01-01",
                "label": "Năm 2024",
            }
        ],
        "limit": 100,
        "rationale": "Tính doanh thu theo khách hàng cho đơn hàng hoàn tất trong năm 2024.",
    }

    state = {
        "user_message": "Tổng doanh thu các đơn hoàn tất theo khách hàng năm 2024",
        "parser_catalog": sample_catalog,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = llm_payload
        result = await semantic_query_parser_node(state)

    interp = result["interpretation"]
    assert interp["status"] == "resolved"
    assert interp["spec"]["metric_ids"] == [1]
    assert interp["spec"]["dimensions"][0]["column_id"] == 10
    assert interp["spec"]["filters"][0]["column_id"] == 12
    assert len(interp["time_ranges"]) == 1
    assert interp["time_ranges"][0]["start_date"] == "2024-01-01"


@pytest.mark.asyncio
async def test_unknown_metric_id_falls_back_to_clarification(sample_catalog: dict) -> None:
    """If LLM hallucinates an unknown metric_id not in catalog, node falls back to clarification."""
    llm_payload = {
        "status": "resolved",
        "metric_ids": [9999],  # unknown ID
        "dimensions": [],
        "filters": [],
        "time_ranges": [],
    }

    state = {
        "user_message": "Tổng chi phí",
        "parser_catalog": sample_catalog,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = llm_payload
        result = await semantic_query_parser_node(state)

    interp = result["interpretation"]
    assert interp["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_needs_clarification_with_options(sample_catalog: dict) -> None:
    """When LLM returns ambiguous clarification, options with specs are preserved."""
    llm_payload = {
        "status": "needs_clarification",
        "clarification": {
            "prompt": "Bạn muốn xem doanh thu theo tiêu chí nào?",
            "options": [
                {
                    "id": "opt_cust",
                    "label": "Doanh thu theo khách hàng",
                    "description": "Nhóm theo mã khách hàng",
                    "spec": {"metric_ids": [1], "dimensions": [{"column_id": 10}], "filters": [], "limit": 100},
                },
                {
                    "id": "opt_date",
                    "label": "Doanh thu theo ngày",
                    "description": "Nhóm theo ngày tạo",
                    "spec": {
                        "metric_ids": [1],
                        "dimensions": [{"column_id": 11, "time_grain": "day"}],
                        "filters": [],
                        "limit": 100,
                    },
                },
            ],
        },
        "rationale": "Câu hỏi chưa rõ chiều phân tích",
    }

    state = {
        "user_message": "Cho tôi xem doanh thu",
        "parser_catalog": sample_catalog,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = llm_payload
        result = await semantic_query_parser_node(state)

    interp = result["interpretation"]
    assert interp["status"] == "needs_clarification"
    assert result["clarification"] is not None
    assert len(result["clarification"]["options"]) == 2
    assert result["clarification"]["options"][0]["id"] == "opt_cust"


@pytest.mark.asyncio
async def test_llm_exception_falls_back_gracefully(sample_catalog: dict) -> None:
    """When ainvoke_json raises an exception, node gracefully returns needs_clarification."""
    state = {
        "user_message": "Doanh thu",
        "parser_catalog": sample_catalog,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.side_effect = RuntimeError("LLM connection timeout")
        result = await semantic_query_parser_node(state)

    assert result["interpretation"]["status"] == "needs_clarification"
    assert "chưa hiểu rõ" in result["chat_response"]


@pytest.mark.asyncio
async def test_missing_metric_returns_create_metric_option_for_lead(sample_catalog: dict) -> None:
    """When requested metric is missing and user is Lead/Admin, returns clean prompt and Tạo Business Metric option."""
    llm_payload = {
        "status": "missing_metric",
        "metric_name": "Tỷ lệ giữ chân khách hàng (Retention Rate)",
        "clarification": {
            "prompt": "Hệ thống hiện chưa có chỉ số 'Tỷ lệ giữ chân khách hàng (Retention Rate)'. Các chỉ số liên quan hiện có gồm ID 8. Bạn có muốn tạo mới không?",
            "options": [],
        },
        "rationale": "Chưa có chỉ số trong catalog",
    }

    state = {
        "user_message": "Xem tỷ lệ giữ chân khách hàng (Retention Rate) tháng này",
        "parser_catalog": sample_catalog,
        "can_generate_metrics": True,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = llm_payload
        result = await semantic_query_parser_node(state)

    interp = result["interpretation"]
    assert interp["status"] == "needs_clarification"
    assert result["clarification"] is not None
    # Verify prompt is clean without unrelated metrics listing
    assert "ID 8" not in result["chat_response"]
    assert "Bạn có muốn tôi đề xuất tạo Business Metric mới này không?" in result["chat_response"]
    assert len(result["clarification"]["options"]) == 1
    assert result["clarification"]["options"][0]["id"] == "create_metric"
    assert "Tạo Business Metric" in result["clarification"]["options"][0]["label"]
    assert "Tỷ lệ giữ chân khách hàng" in result["clarification"]["options"][0]["label"]


@pytest.mark.asyncio
async def test_missing_metric_returns_submit_request_option_for_member(sample_catalog: dict) -> None:
    """When requested metric is missing and user is Member, returns prompt for Data Lead proposal."""
    llm_payload = {
        "status": "missing_metric",
        "metric_name": "Tỷ lệ giữ chân khách hàng",
        "clarification": {
            "prompt": "Hệ thống hiện chưa có chỉ số 'Tỷ lệ giữ chân khách hàng'. Bạn có muốn tạo không?",
            "options": [],
        },
        "rationale": "Chưa có chỉ số trong catalog",
    }

    state = {
        "user_message": "Xem tỷ lệ giữ chân khách hàng",
        "parser_catalog": sample_catalog,
        "can_generate_metrics": False,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = llm_payload
        result = await semantic_query_parser_node(state)

    interp = result["interpretation"]
    assert interp["status"] == "needs_clarification"
    assert result["clarification"] is not None
    assert "Bạn có muốn gửi Data Lead đề xuất chỉ số này không?" in result["chat_response"]
    assert len(result["clarification"]["options"]) == 1
    assert result["clarification"]["options"][0]["id"] == "create_metric"
    assert "Gửi Data Lead đề xuất chỉ số" in result["clarification"]["options"][0]["label"]


@pytest.mark.asyncio
async def test_forced_mismatch_intercepted_and_converted_to_clarification(sample_catalog: dict) -> None:
    """If LLM hallucinates resolved for a different metric (e.g. retention mapped to order count), safety net converts to clarification."""
    llm_payload = {
        "status": "resolved",
        "metric_ids": [2],  # order_count / Số lượng đơn hàng
        "dimensions": [],
        "filters": [],
        "time_ranges": [],
    }

    state = {
        "user_message": "Xem tỷ lệ giữ chân khách hàng",
        "parser_catalog": sample_catalog,
        "can_generate_metrics": True,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = llm_payload
        result = await semantic_query_parser_node(state)

    interp = result["interpretation"]
    assert interp["status"] == "needs_clarification"
    assert result["clarification"] is not None
    assert "tỷ lệ giữ chân khách hàng" in result["chat_response"].lower()
    assert result["semantic_parse_status"] == "needs_clarification"
    assert result["clarification"]["options"] == []


@pytest.mark.asyncio
async def test_invalid_option_spec_is_skipped(sample_catalog: dict) -> None:
    """An option whose spec fails Pydantic validation is dropped, not executed as semantic query."""
    llm_payload = {
        "status": "needs_clarification",
        "clarification": {
            "prompt": "Bạn muốn xem doanh thu theo tiêu chí nào?",
            "options": [
                {
                    "id": "opt_bad",
                    "label": "Spec không hợp lệ",
                    "spec": {"metric_ids": "not-a-list"},
                }
            ],
        },
        "rationale": "Cần làm rõ",
    }

    state = {
        "user_message": "Cho tôi xem doanh thu",
        "parser_catalog": sample_catalog,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = llm_payload
        result = await semantic_query_parser_node(state)

    interp = result["interpretation"]
    assert interp["status"] == "needs_clarification"
    assert result["clarification"] is not None
    assert result["clarification"]["options"] == []


@pytest.mark.asyncio
async def test_stale_catalog_metric_id_dropped_from_options(sample_catalog: dict) -> None:
    """Clarification options referencing metric IDs absent from the approved catalog are dropped."""
    llm_payload = {
        "status": "needs_clarification",
        "clarification": {
            "prompt": "Bạn muốn xem chỉ số nào?",
            "options": [
                {
                    "id": "opt_stale",
                    "label": "Chỉ số không tồn tại",
                    "spec": {"metric_ids": [9999], "dimensions": [], "filters": [], "limit": 100},
                },
                {
                    "id": "opt_ok",
                    "label": "Doanh thu theo khách hàng",
                    "spec": {"metric_ids": [1], "dimensions": [{"column_id": 10}], "filters": [], "limit": 100},
                },
            ],
        },
        "rationale": "Cần làm rõ",
    }

    state = {
        "user_message": "Cho tôi xem số liệu",
        "parser_catalog": sample_catalog,
    }

    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = llm_payload
        result = await semantic_query_parser_node(state)

    interp = result["interpretation"]
    assert interp["status"] == "needs_clarification"
    assert result["clarification"] is not None
    kept = result["clarification"]["options"]
    assert [o["id"] for o in kept] == ["opt_ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog", [{"metrics": []}, {"metrics": [{"id": 1, "name": "orders"}]}])
async def test_explicit_missing_metric_has_structured_signal(catalog: dict) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.return_value = {"status": "missing_metric", "metric_name": "Tổng số khách hàng"}
        result = await semantic_query_parser_node({"user_message": "Xem tổng số khách hàng", "parser_catalog": catalog})
    assert result["semantic_parse_status"] == "missing_metric"
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_empty_catalog_ambiguous_request_does_not_signal_missing() -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.return_value = {"status": "needs_clarification", "clarification": {"prompt": "Chỉ số nào?", "options": []}}
        result = await semantic_query_parser_node({"user_message": "Xem số liệu", "parser_catalog": {"metrics": []}})
    assert result["semantic_parse_status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_parser_error_does_not_signal_missing(sample_catalog: dict) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.side_effect = RuntimeError("unavailable")
        result = await semantic_query_parser_node({"user_message": "Xem doanh thu", "parser_catalog": sample_catalog})
    assert result["semantic_parse_status"] == "error"


@pytest.mark.asyncio
async def test_parser_error_does_not_log_provider_secrets(
    sample_catalog: dict, caplog: pytest.LogCaptureFixture
) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.side_effect = RuntimeError("provider-token-secret")
        result = await semantic_query_parser_node({"user_message": "Xem doanh thu", "parser_catalog": sample_catalog})
    assert result["semantic_parse_status"] == "error"
    assert "provider-token-secret" not in caplog.text


@pytest.mark.asyncio
async def test_clarification_text_alone_does_not_signal_missing(sample_catalog: dict) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.return_value = {
            "status": "needs_clarification",
            "clarification": {"prompt": "Chưa có chỉ số rõ ràng, bạn muốn xem chỉ số nào?", "options": []},
        }
        result = await semantic_query_parser_node({"user_message": "Xem số liệu", "parser_catalog": sample_catalog})
    assert result["semantic_parse_status"] == "needs_clarification"
    assert result["clarification"]["options"] == []


@pytest.mark.asyncio
async def test_missing_metric_without_name_is_error(sample_catalog: dict) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.return_value = {"status": "missing_metric", "metric_name": ""}
        result = await semantic_query_parser_node({"user_message": "Xem số liệu", "parser_catalog": sample_catalog})
    assert result["semantic_parse_status"] == "error"
    assert result["clarification"]["options"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["  TỔNG   DOANH THU ", "total_revenue"])
async def test_missing_metric_matching_catalog_requires_clarification(sample_catalog: dict, name: str) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.return_value = {"status": "missing_metric", "metric_name": name}
        result = await semantic_query_parser_node({"user_message": "Xem doanh thu", "parser_catalog": sample_catalog})
    assert result["semantic_parse_status"] == "needs_clarification"
    assert result["clarification"]["options"] == []


@pytest.mark.asyncio
async def test_missing_metric_without_name_never_offers_create_action(sample_catalog: dict) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.return_value = {
            "status": "missing_metric",
            "metric_name": "",
            "clarification": {"prompt": "Chỉ số nào?", "options": []},
        }
        result = await semantic_query_parser_node({"user_message": "Xem số liệu", "parser_catalog": sample_catalog})
    assert result["semantic_parse_status"] == "error"
    assert result["clarification"]["options"] == []


@pytest.mark.asyncio
async def test_missing_metric_with_selected_ids_does_not_offer_creation(sample_catalog: dict) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.return_value = {"status": "missing_metric", "metric_name": "Lợi nhuận", "metric_ids": [1]}
        result = await semantic_query_parser_node({"user_message": "Xem lợi nhuận", "parser_catalog": sample_catalog})
    assert result["semantic_parse_status"] == "error"
    assert result["clarification"]["options"] == []


@pytest.mark.asyncio
async def test_resolved_total_without_dimensions(sample_catalog: dict) -> None:
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new_callable=AsyncMock) as llm:
        llm.return_value = {"status": "resolved", "metric_ids": [1], "dimensions": [], "filters": []}
        result = await semantic_query_parser_node(
            {"user_message": "Xem tổng doanh thu", "parser_catalog": sample_catalog}
        )
    assert result["semantic_parse_status"] == "resolved"
    assert result["interpretation"]["spec"]["dimensions"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Doanh thu số lượng ít nhất 5",
        "Doanh thu số lượng tối đa 10",
        "Doanh thu số lượng bằng 3",
        "Doanh thu số lượng từ 100",
        "Doanh thu số lượng >= 100",
        "Doanh thu số lượng < 100",
    ],
)
async def test_more_numeric_conditions_cannot_be_omitted(sample_catalog: dict, question: str) -> None:
    sample_catalog["metrics"][0]["filter_column_ids"].append(13)
    sample_catalog["filter_columns"].append(
        {"column_id": 13, "column_name": "quantity", "business_name": "Số lượng", "data_type": "INTEGER"}
    )
    payload = {"status": "resolved", "metric_ids": [1], "filters": []}
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node({"user_message": question, "parser_catalog": sample_catalog})
    assert result["interpretation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_monthly_grouping_cannot_be_changed_to_yearly(sample_catalog: dict) -> None:
    payload = {
        "status": "resolved",
        "metric_ids": [1],
        "dimensions": [{"column_id": 11, "time_grain": "year"}],
        "time_ranges": [{"column_id": 11, "start_date": "2024-01-01", "end_date": "2025-01-01", "label": "2024"}],
    }
    with patch("src.agents.roles.semantic_query_parser_agent.ainvoke_json", new=AsyncMock(return_value=payload)):
        result = await semantic_query_parser_node(
            {"user_message": "Doanh thu theo tháng năm 2024", "parser_catalog": sample_catalog}
        )
    assert result["interpretation"]["status"] == "needs_clarification"


def test_dimension_check_rejects_wrong_time_grain(sample_catalog: dict) -> None:
    from src.agents.roles.semantic_query_requirements import _dimensions_match
    from src.models.schemas import DimensionSelection, SemanticQuerySpec

    spec = SemanticQuerySpec(metric_ids=[1], dimensions=[DimensionSelection(column_id=11, time_grain="year")])
    assert not _dimensions_match(spec, sample_catalog, "Doanh thu theo tháng năm 2024")
