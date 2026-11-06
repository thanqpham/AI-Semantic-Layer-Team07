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
            },
            {
                "id": 2,
                "name": "order_count",
                "business_name": "Số lượng đơn hàng",
                "formula": "COUNT(id)",
                "base_entity": "orders",
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
            }
        ],
    }


def test_prompt_requires_empty_top_level_metric_ids_for_unresolved_queries(sample_catalog: dict) -> None:
    prompt = _build_parse_prompt("Xem lợi nhuận", sample_catalog, False, [])
    assert 'status "missing_metric" hoặc "needs_clarification", metric_ids cấp cao nhất phải là []' in prompt
    assert '"status": "missing_metric", "metric_name": "Tỷ lệ giữ chân khách hàng", "metric_ids": []' in prompt


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
        "user_message": "Tổng doanh thu theo khách hàng năm 2024",
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
