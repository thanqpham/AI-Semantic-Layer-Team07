"""Synthetic language cases for the opt-in semantic parser evaluation."""

from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from tests.test_agents.test_semantic_query_parser_business_filters import PARSER_CASES, SYNTHETIC_CATALOG


def _six_month_range(today: date) -> tuple[str, str]:
    month_index = today.year * 12 + today.month - 1 - 6
    year, month = divmod(month_index, 12)
    month += 1
    start = date(year, month, min(today.day, calendar.monthrange(year, month)[1]))
    return start.isoformat(), (today + timedelta(days=1)).isoformat()


def semantic_parser_cases(today: date) -> list[dict[str, Any]]:
    """Return expected normalized selections without querying a target database."""
    start, end = _six_month_range(today)
    cases = [{**case, "history": []} for case in PARSER_CASES]
    cases.extend(
        [
            {
                "question": "Thực hiện truy vấn chỉ số số lượng đơn hàng",
                "expected": {"status": "resolved", "metric_ids": [1], "dimensions": [], "filters": []},
            },
            {
                "question": "Số đơn hàng đã hoàn tất ở miền Bắc",
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [],
                    "filters": [
                        {"column_id": 12, "operator": "eq", "value": "completed"},
                        {"column_id": 13, "operator": "eq", "value": "North"},
                    ],
                },
            },
            {
                "question": "Theo tháng",
                "history": [
                    {"role": "user", "content": "Số đơn hàng trong 6 tháng gần nhất"},
                    {"role": "assistant", "content": "Bạn muốn xem theo ngày hay theo tháng?"},
                ],
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [{"column_id": 11, "time_grain": "month"}],
                    "filters": [
                        {"column_id": 11, "operator": "gte", "value": start},
                        {"column_id": 11, "operator": "lt", "value": end},
                    ],
                },
            },
            {
                "question": "Đổi sang miền Nam",
                "history": [{"role": "user", "content": "Số đơn hàng miền Bắc"}],
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [],
                    "filters": [{"column_id": 13, "operator": "eq", "value": "South"}],
                },
            },
            {
                "question": "Số lượng đơn hàng",
                "history": [{"role": "user", "content": "Doanh thu miền Bắc"}],
                "expected": {"status": "resolved", "metric_ids": [1], "dimensions": [], "filters": []},
            },
            {"question": "Số đơn hàng ở Đông Bắc Bộ", "expected": {"status": "needs_clarification"}},
            {
                "question": "Số đơn hàng năm 2024",
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [],
                    "filters": [
                        {"column_id": 11, "operator": "gte", "value": "2024-01-01"},
                        {"column_id": 11, "operator": "lt", "value": "2025-01-01"},
                    ],
                },
            },
            {
                "question": "Số đơn hàng không có số lượng sản phẩm",
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [],
                    "filters": [{"column_id": 15, "operator": "is_null", "value": None}],
                },
            },
            {
                "question": "Tổng doanh thu",
                "history": [{"role": "user", "content": "Số đơn hàng ở miền Bắc"}],
                "expected": {"status": "resolved", "metric_ids": [2], "dimensions": [], "filters": []},
            },
            {
                "question": "Bỏ lọc khu vực",
                "history": [{"role": "user", "content": "Số đơn hàng miền Bắc"}],
                "expected": {"status": "resolved", "metric_ids": [1], "dimensions": [], "filters": []},
            },
            {
                "question": "Cho tôi xem kết quả chỉ số tỉ lệ đơn hàng bị hoàn lại so với tổng số đơn hàng",
                "catalog_mutation": "refund_ratio",
                "expected": {"status": "resolved", "metric_ids": [3], "dimensions": [], "filters": []},
            },
            {
                "question": "Tỷ lệ giữ chân khách hàng",
                "expected": {"status": "needs_clarification"},
                "expected_parse_status": "missing_metric",
            },
            {
                "question": "Top 5 khu vực có doanh thu cao nhất",
                "expected": {
                    "status": "resolved",
                    "metric_ids": [2],
                    "dimensions": [{"column_id": 13, "time_grain": None}],
                    "filters": [],
                    "limit": 5,
                    "order_by": "metric_desc",
                    "order_metric_id": 2,
                },
            },
            {
                "question": "Doanh thu không phải miền Bắc",
                "expected": {
                    "status": "resolved",
                    "metric_ids": [2],
                    "dimensions": [],
                    "filters": [{"column_id": 13, "operator": "neq", "value": "North"}],
                },
            },
            {
                "question": "Doanh thu Mien Bac hoac Mien Nam",
                "expected": {
                    "status": "resolved",
                    "metric_ids": [2],
                    "dimensions": [],
                    "filters": [{"column_id": 13, "operator": "in", "value": ["North", "South"]}],
                },
            },
            {
                "question": "Số đơn hàng có số lượng sản phẩm không quá 10",
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [],
                    "filters": [{"column_id": 15, "operator": "lte", "value": 10}],
                },
            },
            {
                "question": "Số đơn hàng theo khu vực và trạng thái",
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [{"column_id": 13, "time_grain": None}, {"column_id": 12, "time_grain": None}],
                    "filters": [],
                },
            },
            {
                "question": "Theo khu vực",
                "history": [{"role": "user", "content": "Số đơn hàng năm 2024"}],
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [{"column_id": 13, "time_grain": None}],
                    "filters": [
                        {"column_id": 11, "operator": "gte", "value": "2024-01-01"},
                        {"column_id": 11, "operator": "lt", "value": "2025-01-01"},
                    ],
                },
            },
            {
                "question": "Chỉ năm 2024",
                "history": [{"role": "user", "content": "Số đơn hàng miền Bắc"}],
                "expected": {
                    "status": "resolved",
                    "metric_ids": [1],
                    "dimensions": [],
                    "filters": [
                        {"column_id": 13, "operator": "eq", "value": "North"},
                        {"column_id": 11, "operator": "gte", "value": "2024-01-01"},
                        {"column_id": 11, "operator": "lt", "value": "2025-01-01"},
                    ],
                },
            },
        ]
    )
    return cases


def case_catalog(case: dict[str, Any]) -> dict[str, Any]:
    """Select the synthetic catalog appropriate to a case."""
    from tests.test_agents.test_semantic_query_parser_business_filters import (
        _ambiguous_region_catalog,
        _approved_label_catalog,
        _t2_multi_filter_catalog,
    )

    factories = {
        "ambiguous_region_column": _ambiguous_region_catalog,
        "approved_non_sample_mapping": _approved_label_catalog,
        "t2_multi_filter_catalog": _t2_multi_filter_catalog,
    }
    factory = factories.get(case.get("catalog_mutation"))
    catalog = factory() if factory else deepcopy(SYNTHETIC_CATALOG)
    if case.get("catalog_mutation") == "refund_ratio":
        catalog["metrics"].append(
            {
                "id": 3,
                "name": "refund_order_rate",
                "business_name": "Tỷ lệ đơn hàng đã trả hàng (%)",
                "base_entity": "orders",
                "dimension_ids": [11],
                "filter_column_ids": [11, 12],
                "formula_definition": {
                    "ratio": {
                        "numerator": {
                            "function": "COUNT_DISTINCT",
                            "expression": "id",
                            "filters": [{"field": "status", "operator": "eq", "value": "returned"}],
                        },
                        "denominator": {"function": "COUNT_DISTINCT", "expression": "id", "filters": []},
                        "scale": 100,
                    }
                },
            }
        )
    return catalog
