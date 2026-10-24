"""Metric Designer Agent: draft and repair schema-grounded metric definitions."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from src.agents.roles.metric_prompt_rules import CONTEXT_RULES
from src.models.metric_review import MetricBuildBatch
from src.observability import trace_action
from src.services.metric_runtime import MetricCallError, execution_failure, invoke_metric_json
from src.services.metrics import _BASE_RULES


async def generate_metric_drafts(context: dict[str, Any], task_id: str | None = None) -> list[dict[str, Any]]:
    """Generate candidates without discarding invalid definitions before review."""
    discovery = context["proposal_mode"] == "discovery"
    prompt = "Bạn là Metric Designer Agent. Schema và yêu cầu đầy đủ nằm trong context JSON đính kèm.\n" + _BASE_RULES
    prompt += "\n" + CONTEXT_RULES + "\n" + _draft_instructions(discovery)
    task_id = task_id or str(uuid4())
    payload = {"task_id": task_id, "context": context}
    batch = await trace_action(
        "metric_generation",
        {"mode": context["proposal_mode"]},
        invoke_metric_json(
            MetricBuildBatch, [("system", prompt), ("user", json.dumps(payload, ensure_ascii=False))], "builder"
        ),
    )
    if batch.task_id != task_id:
        raise MetricCallError(execution_failure("INVALID_AGENT_OUTPUT", "builder"))
    ready = [item for item in batch.candidates if item.get("status", "ready") in {"ready", "candidate"}][:5]
    blocked = [item for item in batch.candidates if item.get("status") not in {"ready", "candidate", None}][:5]
    candidates = ready + blocked
    if not candidates:
        raise MetricCallError(execution_failure("INVALID_AGENT_OUTPUT", "builder"))
    return candidates


def _draft_instructions(discovery: bool) -> str:
    """Override the legacy output envelope with an explicit feasibility contract."""
    count = (
        "Tối đa 5 candidate khả thi và 5 mục chưa khả thi từ 10 nhóm KPI; không ép đủ số lượng."
        if discovery
        else "Tối đa 5 biến thể khả thi của KPI được hỏi và 5 mục chưa khả thi. Nếu yêu cầu đã chọn tiêu chí thì chỉ trả biến thể phù hợp."
    )
    return f"""FORMAT DUY NHẤT cho Builder; task_id phải sao chép chính xác từ yêu cầu:
{{"task_id":"task_id đã nhận", "candidates":[{{"name":"Tổng số đơn hàng", "status":"ready",
"definition":{{"metric":{{"name":"Tổng số đơn hàng", "base_entity":"orders",
"formula":{{"function":"COUNT_DISTINCT","expression":"id"}}, "filters":[],
"status":"pending_approval", "excluded_notes":""}}}}, "knowledge_id":null,
"variant_id":null, "criteria":{{}}, "reason":"Đếm khóa đơn hàng"}}]}}
orders/id chỉ là ví dụ, phải thay bằng bảng/cột thật. ready BẮT BUỘC có definition đầy đủ.
Bạn chỉ tạo/sửa định nghĩa. Không tự kết luận trùng lặp, thay yêu cầu bằng metric khác, phê duyệt hay viết phản hồi cuối.
Không đoán column_id, base_entity_id, grain hoặc expression_ast; code sẽ ánh xạ từ metadata.
TUYỆT ĐỐI KHÔNG chỉ viết công thức trong reason hoặc trả definition=null cho ready.
Khi chưa thể xây dựng: trả {{"name":"KPI", "status":"needs_clarification|unsupported|rejected",
"reason":"Bằng chứng thiếu và hành động cần làm", "knowledge_id":null}}, không giả định nghĩa.
Nếu metric khớp một mục knowledge, knowledge_id, variant_id và toàn bộ criteria của biến thể là bắt buộc.
Không trả AOV mơ hồ thiếu variant_id/criteria; dùng đúng order_average_pre_tax, order_average_after_tax,
hoặc order_average_after_tax_discount khi tên, công thức và schema cùng chứng minh biến thể.
AOV ở grain đơn hàng chỉ dùng AVG trên cột số không NULL, một dòng mỗi đơn; không dùng SUM/SUM hoặc chia ID.
Trả mỗi biến thể khả thi thành candidate riêng, tên nêu thuế/giảm giá; loại biến thể không có cột chứng minh.
Tên metric phải ghi các tiêu chí ảnh hưởng kết quả. Không gắn nguồn hoặc tiêu chí không có trong biến thể được chọn.
Khi yêu cầu chưa chọn thuế, hoàn tiền, trạng thái hay mốc thời gian, có thể tạo nhiều biến thể riêng nếu mỗi biến thể được schema chứng minh.
Chỉ hỏi lại nếu không thể ánh xạ dữ liệu một cách đáng tin cậy. Mỗi KPI cần nêu ánh xạ dữ liệu và lý do phù hợp.
{count} Ưu tiên căn cứ schema rõ ràng và KPI chưa có trong catalog.
"""


async def repair_metric_drafts(
    context: dict[str, Any], items: list[dict[str, Any]], task_id: str
) -> list[dict[str, Any]]:
    """Repair only failed items once, preserving server-owned task and candidate IDs."""
    payload = {"task_id": task_id, "context": context, "items": items}
    prompt = (
        _BASE_RULES
        + CONTEXT_RULES
        + "\nSửa các KPI được giao, giữ nguyên candidate_id và mục tiêu; không sinh lại KPI khác.\n"
    )
    prompt += _repair_instructions()
    result = await trace_action(
        "metric_repair",
        {"attempt": 1},
        invoke_metric_json(
            MetricBuildBatch, [("system", prompt), ("user", json.dumps(payload, ensure_ascii=False))], "repair"
        ),
    )
    if result.task_id != task_id:
        raise MetricCallError(execution_failure("INVALID_AGENT_OUTPUT", "repair"))
    return result.candidates


def _repair_instructions() -> str:
    """Make repair IDs and complete artifacts explicit in the only repair round."""
    return """Chỉ trả JSON theo format:
{"task_id":"giữ nguyên task_id","candidates":[{"candidate_id":"ID hiện có",
"name":"tên metric có tiêu chí","status":"ready","definition":{"metric":{
"name":"cùng tên","base_entity":"bảng thật","formula":{"function":"AVG","expression":"cột thật"},
"filters":[],"grain":{"column_ids":[]},"status":"pending_approval"}},
"knowledge_id":"đúng id hoặc null","variant_id":"đúng id hoặc null","criteria":{},"reason":""}]}
Trả đúng một phần tử cho mỗi candidate_id đã giao, không thêm hoặc bỏ candidate.
Bản sửa phải có definition đầy đủ; giữ hoặc sửa variant_id và criteria đúng feedback.
Chỉ sửa phần có bằng chứng sai; không đổi KPI, không tự chọn metric có sẵn để thay thế.
Backend tự thay grain bằng khóa chính đã xác thực. Không bịa filter nghiệp vụ chưa được xác nhận.
Nếu vẫn không thể tạo một định nghĩa hợp lệ, trả status unsupported hoặc needs_clarification với reason cụ thể.
"""
