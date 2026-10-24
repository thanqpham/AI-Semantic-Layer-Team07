"""Metric Reviewer Agent: evaluate a batch of technically valid definitions."""

from __future__ import annotations

import json
from typing import Any

from src.agents.roles.metric_prompt_rules import CONTEXT_RULES
from src.models.metric_review import MetricReviewBatch
from src.observability import trace_action
from src.services.metric_runtime import MetricCallError, execution_failure, invoke_metric_json

_REVIEW_PROMPT = (
    CONTEXT_RULES
    + """
Bạn là Metric Reviewer Agent. Thẩm định riêng từng definition đã qua kiểm tra kỹ thuật.
Đọc câu hỏi gốc, lịch sử xác nhận, schema, nguồn KPI và catalog trong context.
Đối chiếu grain, aggregation, đơn vị, population, thuế, hoàn tiền và điều kiện thời gian.
Không tự sửa definition, không ghi audit hoặc tự phê duyệt. Chỉ trả judgment.
Giữ chính xác task_id và candidate_id được giao, không thêm KPI, không bỏ sót KPI.
pass chỉ khi đầy đủ yêu cầu và không còn vấn đề. needs_revision phải có issues gồm
code, message, evidence cụ thể, action; chỉ dùng khi context đủ để sửa.
Thiếu quyết định nghiệp vụ dùng needs_clarification và clarification là câu hỏi cụ thể.
Nếu yêu cầu chung có nhiều biến thể được schema chứng minh, đánh giá riêng từng biến thể; không yêu cầu chọn một biến thể trước.
Kiểm tra tên và công thức thể hiện đúng criteria và variant_id, không gán nguồn của biến thể khác.
Không yêu cầu bộ lọc trạng thái, đơn thử, hủy hay hoàn tiền nếu yêu cầu/biến thể không nêu chúng; không áp dụng quy ước phổ biến như chính sách doanh nghiệp.
Grain được backend chuẩn hóa từ khóa chính của bảng; không yêu cầu Builder điền column_ids.
Nếu các cách hiểu thuế/giảm giá có thể biểu diễn riêng, đánh giá từng biến thể; chỉ yêu cầu làm rõ người dùng khi schema không ánh xạ được bất kỳ biến thể nào.
FORMAT DUY NHẤT:
{"task_id":"đúng task_id đã nhận", "decisions":[{"candidate_id":"đúng ID được giao",
"status":"pass", "summary":"Lý do dựa trên yêu cầu và metadata", "issues":[], "clarification":null}]}
Các status khác: needs_revision, needs_clarification, rejected, unsupported.
"""
)



async def review_metric_batch(
    context: dict[str, Any], task_id: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Make one model call for all ready definitions, excluding the audit ledger."""
    payload = {"task_id": task_id, "context": context, "items": items}
    batch = await trace_action(
        "metric_review_decision",
        {},
        invoke_metric_json(
            MetricReviewBatch,
            [("system", _REVIEW_PROMPT), ("user", json.dumps(payload, ensure_ascii=False))],
            "reviewer",
        ),
    )
    if batch.task_id != task_id:
        raise MetricCallError(execution_failure("INVALID_AGENT_OUTPUT", "reviewer"))
    return batch.decisions


