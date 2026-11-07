"""Parse natural-language questions into structured SemanticQueryInterpretation."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from src.agents.roles.semantic_query_requirements import _filter_values_have_evidence, _requirements_covered
from src.models.schemas import (
    ChatClarificationOption,
    ChatClarificationPayload,
    DimensionSelection,
    SemanticQueryFilter,
    SemanticQueryInterpretation,
    SemanticQuerySpec,
    SemanticTimeRange,
)
from src.observability import trace_action
from src.services.llm import get_llm
from src.services.llm_json import ainvoke_json
from src.services.metric_knowledge import normalized_text
from src.services.natural_language_query import normalize_interpretation

logger = logging.getLogger(__name__)

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

_PARSE_PROMPT = """Bạn là Semantic Query Parser Agent của hệ thống AI Semantic Layer.
Nhiệm vụ: Chuyển đổi câu hỏi tiếng Việt của người dùng thành cấu trúc truy vấn Semantic Query hoặc yêu cầu làm rõ (Clarification) nếu mơ hồ hoặc chưa có chỉ số.

Thời gian hiện tại tại Việt Nam (Asia/Ho_Chi_Minh): {current_time}
Vai trò người dùng: {role_description}

CATALOG CHỈ SỐ VÀ CHIỀU ĐÃ ĐƯỢC PHÊ DUYỆT:
{catalog_json}

Lịch sử hội thoại:
{history}

Câu hỏi người dùng: "{user_message}"

QUY TẮC BẮT BUỘC:
1. CHỈ ĐƯỢC DÙNG metric_id và column_id có trong CATALOG ở trên. TUYỆT ĐỐI KHÔNG TỰ NGHĨ RA ID.
   Với status "missing_metric" hoặc "needs_clarification", metric_ids cấp cao nhất phải là [].
   Riêng clarification.options[].spec.metric_ids có thể chứa ID hợp lệ trong CATALOG.
2. ĐỘ CHÍNH XÁC VỀ KHÁI NIỆM NGHIỆP VỤ (CỰC KỲ QUAN TRỌNG):
   - CHỈ ĐƯỢC CHỌN status: "resolved" khi chỉ số trong CATALOG thực sự mang đúng tên/định nghĩa hoặc là từ đồng nghĩa trực tiếp 100% của câu hỏi người dùng (ví dụ: "Doanh thu" <-> "Tổng doanh thu", "Số đơn" <-> "Số lượng đơn hàng").
   - TUYỆT ĐỐI CẤM TỰ Ý GÁN / ÉP CHỈ SỐ GẦN GIỐNG KHI KHÁC KHÁI NIỆM:
     + "Tỷ lệ giữ chân khách hàng (Retention Rate)" KHÔNG PHẢI LÀ "Tỷ lệ khách hàng quay lại mua hàng" hay "Số lượng khách hàng". Nếu catalog chỉ có "Tỷ lệ khách hàng quay lại mua hàng" mà người dùng hỏi "Tỷ lệ giữ chân khách hàng" -> trả về status: "missing_metric", TUYỆT ĐỐI KHÔNG CHỌN metric này!
     + "Doanh thu thuần (Net Revenue)" KHÔNG PHẢI LÀ "Tổng doanh thu (Gross Revenue)".
     + "Tỷ lệ chuyển đổi (Conversion Rate)" KHÔNG PHẢI LÀ "Số lượt xem" hay "Số đơn hàng".
     + "Giá trị đơn hàng trung bình (AOV)" KHÔNG PHẢI LÀ "Tổng doanh thu".
   - Khi người dùng nêu rõ chỉ số nhưng CATALOG không có đúng định nghĩa, kể cả CATALOG rỗng:
     + Trả status: "missing_metric", metric_name là tên chỉ số cụ thể; không chọn metric_ids.
     + Nếu chưa rõ chỉ số hoặc có nhiều cách hiểu, trả "needs_clarification", không kết luận thiếu metric.
3. Nếu câu hỏi rõ ràng và map được metric/dimension/filter hợp lệ:
   - Mỗi metric có dimension_ids và filter_column_ids riêng; chỉ dùng các cột hợp lệ cho tất cả metric đã chọn.
   - "miền Bắc" là giá trị bộ lọc; "theo từng khu vực" là dimension. Giữ nguyên văn giá trị người dùng trong filters, không tự dịch sang giá trị cơ sở dữ liệu.
   - status: "resolved"
   - metric_ids: danh sách ID chỉ số đã chọn (ví dụ [1])
   - dimensions: danh sách {{"column_id": int, "time_grain": "day"|"week"|"month"|"quarter"|"year"|null}}
   - filters: danh sách {{"column_id": int, "operator": "eq"|"neq"|"gt"|"gte"|"lt"|"lte"|"in"|"not_in"|"is_null"|"is_not_null", "value": any}}
   - time_ranges: danh sách {{"column_id": int, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "label": "Năm 2024"}} (khoảng thời gian nửa mở [start_date, end_date))
   - limit: số dòng tối đa (mặc định 100, tối đa 1000)
   - Với top N cao nhất, dùng limit=N, order_by="metric_desc" và order_metric_id thuộc metric_ids. Nếu không thể xác định, yêu cầu làm rõ.
4. Nếu câu hỏi rõ ràng yêu cầu giá trị tổng của metric có trong catalog nhưng không nêu chiều hoặc bộ lọc, trả "resolved" với dimensions: [] và filters: []. Không tự yêu cầu chiều hay bộ lọc.
   Nếu câu hỏi thực sự mơ hồ về metric hoặc điều kiện:
   - status: "needs_clarification"
   - clarification: {{"prompt": "Câu hỏi làm rõ tiếng Việt", "options": [
       {{"id": "opt_1", "label": "Nhãn hiển thị ngắn", "description": "Mô tả chi tiết", "spec": {{"metric_ids": [...], "dimensions": [...], "filters": [], "limit": 100}}}}
     ]}} (tối đa 3 options có spec phân tích theo các dimension/filter hợp lệ của chính metric đó).
5. rationale: Giải thích ngắn gọn lý do chọn metric/dimension hoặc lý do cần làm rõ.

VÍ DỤ MẪU BẮT BUỘC TUÂN THEO:
- Ví dụ 1 (Khớp đúng): User "Xem tổng doanh thu 2024", Catalog có "Tổng doanh thu" (id=1) -> status: "resolved", metric_ids: [1]
- Ví dụ 2: User "Xem tỷ lệ giữ chân khách hàng", Catalog chỉ có "Tỷ lệ khách hàng quay lại mua hàng" -> {{"status": "missing_metric", "metric_name": "Tỷ lệ giữ chân khách hàng", "metric_ids": [], "dimensions": [], "filters": [], "time_ranges": [], "limit": 100, "clarification": null, "rationale": "Chỉ số chưa có trong catalog."}}
- Ví dụ 3: User "Truy vấn chỉ số tổng số khách hàng", Catalog có "Tổng số khách hàng" (id=2) -> status: "resolved", metric_ids: [2], dimensions: [], filters: [].

CHỈ TRẢ VỀ DUY NHẤT 1 JSON OBJECT hợp lệ theo cấu trúc sau:
{{
  "status": "resolved" | "missing_metric" | "needs_clarification",
  "metric_name": "tên chỉ số khi missing_metric, nếu không null",
  "metric_ids": [],
  "dimensions": [],
  "filters": [],
  "time_ranges": [],
  "limit": 100,
  "clarification": null,
  "rationale": "..."
}}"""


async def parse_semantic_query(
    user_message: str,
    parser_catalog: dict[str, Any],
    can_generate_metrics: bool = False,
    chat_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Parse user query against catalog using LLM without direct DB execution."""
    catalog = parser_catalog or {}
    metrics = catalog.get("metrics") or []
    user_message = user_message.strip()
    prompt = _build_parse_prompt(user_message, catalog, can_generate_metrics, chat_history or [])
    try:
        raw_json = await trace_action(
            "semantic_parse", {"catalog_metrics": len(metrics)}, ainvoke_json(get_llm(), prompt, retries=1)
        )
        raw_json = _guard_missing_metric(raw_json, catalog)
        prior_user_messages = [
            item.get("content", "") for item in (chat_history or [])[-6:] if item.get("role") == "user"
        ]
        evidence = "\n".join([*prior_user_messages, user_message])
        interpretation = _parse_interpretation(raw_json, catalog, can_generate_metrics, user_message, evidence)
        parse_status = _semantic_parse_status(raw_json, interpretation)
    except Exception as exc:
        logger.warning("Semantic parse node failed: %s", type(exc).__name__)
        parse_status = "error"
        interpretation = _fallback_interpretation(
            "Tôi chưa hiểu rõ câu hỏi số liệu của bạn. Bạn có thể diễn đạt cụ thể hơn không?"
        )

    output = _build_node_output(interpretation)
    output["semantic_parse_status"] = parse_status
    return output


def _guard_missing_metric(raw: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Reject missing-metric claims that contradict the approved catalog."""
    if raw.get("status") != "missing_metric":
        return raw
    name = raw.get("metric_name")
    if not isinstance(name, str) or not name.strip() or raw.get("metric_ids"):
        return {"status": "error"}
    normalized = " ".join(normalized_text(name).split())
    for metric in catalog.get("metrics", []):
        for field in ("name", "business_name"):
            candidate = metric.get(field)
            if isinstance(candidate, str) and " ".join(normalized_text(candidate).split()) == normalized:
                return {
                    "status": "needs_clarification",
                    "clarification": {
                        "prompt": "Chưa xác định được chỉ số phù hợp. Vui lòng làm rõ yêu cầu.",
                        "options": [],
                    },
                }
    return raw


def _semantic_parse_status(raw: dict[str, Any], interpretation: SemanticQueryInterpretation) -> str:
    """Distinguish a specific missing metric from ambiguity or invalid output."""
    if interpretation.status == "resolved":
        return "resolved"
    name = raw.get("metric_name")
    if raw.get("status") == "missing_metric" and isinstance(name, str) and name.strip():
        return "missing_metric"
    if raw.get("status") in {"resolved", "needs_clarification"}:
        return "needs_clarification"
    return "error"


def _build_parse_prompt(
    user_message: str,
    catalog: dict[str, Any],
    can_generate_metrics: bool,
    chat_history: list[dict[str, str]],
) -> str:
    """Format catalog, history, and current Vietnam time into the prompt."""
    now_vn = datetime.now(_VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    history_str = _format_history(chat_history)
    safe_catalog = {
        **{key: value for key, value in catalog.items() if key != "_relationship_fingerprint"},
        "metrics": [
            {key: value for key, value in metric.items() if key != "_definition_fingerprint"}
            for metric in catalog.get("metrics", [])
        ],
        "filter_columns": [
            {key: value for key, value in column.items() if key != "_approved_mappings"}
            for column in catalog.get("filter_columns", [])
        ],
    }
    compact_catalog = json.dumps(safe_catalog, ensure_ascii=False, indent=2)
    if can_generate_metrics:
        role_desc = "Data Lead / Quản trị viên (có quyền tạo và phê duyệt Metric)"
        action_prompt = "đề xuất tạo Business Metric mới"
        action_label = "Tạo Business Metric"
    else:
        role_desc = "Thành viên / Người xem (không có quyền tạo trực tiếp, có quyền gửi yêu cầu đề xuất lên Data Lead)"
        action_prompt = "gửi Data Lead đề xuất Business Metric mới"
        action_label = "Gửi Data Lead đề xuất chỉ số"
    return _PARSE_PROMPT.format(
        current_time=now_vn,
        role_description=role_desc,
        action_prompt=action_prompt,
        action_label=action_label,
        catalog_json=compact_catalog,
        history=history_str,
        user_message=user_message,
    )


def _format_history(history: list[dict[str, str]]) -> str:
    """Format recent history into readable lines."""
    lines = []
    for item in history[-6:]:
        role = item.get("role")
        content = item.get("content", "").strip()[:500]
        if role in {"user", "assistant"} and content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(none)"


def _is_forced_mismatch(user_message: str, metric_ids: list[int], catalog: dict[str, Any]) -> bool:
    """Detect if distinct concepts (like retention rate) were forcefully mapped to unrelated metrics."""
    lowered = user_message.lower()
    valid_metrics = {m["id"]: m for m in catalog.get("metrics", [])}
    for m_id in metric_ids:
        m = valid_metrics.get(m_id)
        if not m:
            continue
        m_name = (m.get("business_name") or m.get("name") or "").lower()
        if ("giữ chân" in lowered or "retention" in lowered) and (
            "giữ chân" not in m_name and "retention" not in m_name
        ):
            return True
        if ("thuần" in lowered or "net" in lowered) and ("thuần" not in m_name and "net" not in m_name):
            return True
        if ("chuyển đổi" in lowered or "conversion" in lowered) and (
            "chuyển đổi" not in m_name and "conversion" not in m_name
        ):
            return True
        if ("aov" in lowered or "trung bình đơn" in lowered) and (
            "aov" not in m_name and "trung bình" not in m_name and "average" not in m_name
        ):
            return True
    return False


def _parse_interpretation(
    raw: dict[str, Any], catalog: dict[str, Any], can_generate_metrics: bool, user_message: str, evidence: str
) -> SemanticQueryInterpretation:
    """Convert raw LLM dict into validated SemanticQueryInterpretation."""
    status = raw.get("status")
    if status == "missing_metric" and isinstance(raw.get("metric_name"), str) and raw["metric_name"].strip():
        raw = {**raw, "clarification": {"prompt": f"Chưa có chỉ số '{raw['metric_name'].strip()}'.", "options": []}}
    if status == "resolved":
        spec = _build_spec(raw, catalog)
        if spec is not None:
            if _is_forced_mismatch(user_message, spec.metric_ids, catalog):
                raw = {
                    "status": "needs_clarification",
                    "clarification": {
                        "prompt": f"Chưa xác định được chỉ số phù hợp cho '{user_message.strip()}'. Vui lòng làm rõ.",
                        "options": [],
                    },
                    "rationale": "Chỉ số được hỏi chưa tồn tại chính xác trong danh mục.",
                }
            else:
                time_ranges = _build_time_ranges(raw.get("time_ranges", []))
                interpretation = SemanticQueryInterpretation(
                    status="resolved",
                    spec=spec,
                    time_ranges=time_ranges,
                    rationale=raw.get("rationale"),
                )
                checked = normalize_interpretation(interpretation, catalog)
                if checked.status != "resolved":
                    return checked
                if not _requirements_covered(checked.spec, catalog, user_message, evidence):
                    return _fallback_interpretation("Vui lòng làm rõ điều kiện lọc hoặc thời gian của bạn.")
                if not _filter_values_have_evidence(checked.spec, catalog, evidence):
                    return _fallback_interpretation("Vui lòng xác nhận giá trị bộ lọc bạn muốn sử dụng.")
                return interpretation
    return _build_clarification_interpretation(raw, catalog, can_generate_metrics, user_message, evidence)


def _build_spec(raw: dict[str, Any], catalog: dict[str, Any]) -> SemanticQuerySpec | None:
    """Construct SemanticQuerySpec from raw output after verifying IDs."""
    if _unknown_nested_fields(raw) or set(raw) - (
        set(SemanticQuerySpec.model_fields) | {"status", "metric_name", "time_ranges", "clarification", "rationale"}
    ):
        return None
    try:
        spec = SemanticQuerySpec(
            metric_ids=raw.get("metric_ids", []),
            dimensions=raw.get("dimensions", []),
            filters=raw.get("filters", []),
            limit=min(max(int(raw.get("limit", 100)), 1), 1000),
            order_by=raw.get("order_by"),
            order_metric_id=raw.get("order_metric_id"),
        )
    except (TypeError, ValueError, ValidationError):
        return None
    return spec if set(spec.metric_ids).issubset({m["id"] for m in catalog.get("metrics", [])}) else None


def _unknown_nested_fields(raw: dict[str, Any]) -> bool:
    """Reject unsupported nested keys instead of silently discarding conditions."""
    for field, model in (
        ("dimensions", DimensionSelection),
        ("filters", SemanticQueryFilter),
        ("time_ranges", SemanticTimeRange),
    ):
        items = raw.get(field, [])
        if not isinstance(items, list) or any(
            not isinstance(item, dict) or set(item) - set(model.model_fields) for item in items
        ):
            return True
    return False


def _build_time_ranges(items: list[Any]) -> list[SemanticTimeRange]:
    """Parse time ranges safely."""
    ranges: list[SemanticTimeRange] = []
    for item in items:
        ranges.append(SemanticTimeRange.model_validate(item))
    return ranges


def _extract_metric_name_from_text(text: str) -> str | None:
    """Extract quoted metric name from clarification prompt if present."""
    match = re.search(r"['\"`]([^'\"`]+)['\"`]", text)
    return match.group(1).strip() if match else None


def _clean_missing_metric_prompt(prompt: str, user_message: str, can_generate_metrics: bool) -> str:
    """Ensure clarification prompt is clean and concise without listing unrelated metrics."""
    raw_name = _extract_metric_name_from_text(prompt) or _extract_metric_name_from_text(user_message) or user_message
    name = re.sub(
        r"^(xem|cho\s+tôi\s+xem|thống\s+kê|báo\s+cáo|tính)\s+",
        "",
        raw_name.strip(),
        flags=re.IGNORECASE,
    ).strip()
    name = re.sub(r"\s+(tháng\s+này|hôm\s+nay|năm\s+nay|tuần\s+này)$", "", name, flags=re.IGNORECASE).strip()
    if can_generate_metrics:
        return f"Hệ thống hiện chưa có chỉ số '{name}'. Bạn có muốn tôi đề xuất tạo Business Metric mới này không?"
    return f"Hệ thống hiện chưa có chỉ số '{name}'. Bạn có muốn gửi Data Lead đề xuất chỉ số này không?"


def _build_clarification_interpretation(
    raw: dict[str, Any],
    catalog: dict[str, Any],
    can_generate_metrics: bool = False,
    user_message: str = "",
    evidence: str = "",
) -> SemanticQueryInterpretation:
    """Build a needs_clarification interpretation from clarification payload."""
    clar_data = raw.get("clarification")
    prompt = "Tôi cần thêm thông tin để chạy truy vấn chính xác. Bạn vui lòng chọn một trong các gợi ý dưới đây:"
    options: list[ChatClarificationOption] = []
    if isinstance(clar_data, dict):
        prompt = clar_data.get("prompt") or prompt
        raw_options = clar_data.get("options", [])
        if raw.get("status") == "missing_metric":
            prompt = _clean_missing_metric_prompt(prompt, user_message, can_generate_metrics)
            name = _extract_metric_name_from_text(prompt) or user_message.strip()
            clean_name = re.sub(
                r"^(xem|cho\s+tôi\s+xem|thống\s+kê|báo\s+cáo|tính)\s+", "", name, flags=re.IGNORECASE
            ).strip()
            label = (
                f"Tạo Business Metric '{clean_name}'"
                if can_generate_metrics
                else f"Gửi Data Lead đề xuất chỉ số '{clean_name}'"
            )
            options.append(
                ChatClarificationOption(
                    id="create_metric",
                    label=label,
                    description="Yêu cầu AI đề xuất định nghĩa metric này",
                    spec=None,
                    action="create_metric",
                )
            )
        elif isinstance(raw_options, list):
            valid_ids = {m["id"] for m in catalog.get("metrics", [])}
            for opt in raw_options:
                if isinstance(opt, dict) and "id" in opt and "label" in opt:
                    spec_obj = None
                    spec = opt.get("spec")
                    if isinstance(spec, dict) and spec.get("metric_ids"):
                        if set(spec["metric_ids"]).issubset(valid_ids):
                            try:
                                if _unknown_nested_fields(spec) or set(spec) - (
                                    set(SemanticQuerySpec.model_fields) | {"time_ranges"}
                                ):
                                    continue
                                spec_obj = SemanticQuerySpec(**{k: v for k, v in spec.items() if k != "time_ranges"})
                                time_ranges = _build_time_ranges(spec.get("time_ranges", []))
                                checked = normalize_interpretation(
                                    SemanticQueryInterpretation(
                                        status="resolved", spec=spec_obj, time_ranges=time_ranges
                                    ),
                                    catalog,
                                )
                                if (
                                    checked.status != "resolved"
                                    or not _requirements_covered(
                                        checked.spec, catalog, user_message, evidence, suggested_grouping=True
                                    )
                                    or not _filter_values_have_evidence(checked.spec, catalog, evidence)
                                ):
                                    continue
                                spec_obj = spec_obj.model_copy(
                                    update={"filters": spec_obj.filters + checked.spec.filters[len(spec_obj.filters) :]}
                                )
                            except ValidationError as exc:
                                logger.debug("Skipping invalid option spec: %s", exc)
                                continue
                        else:
                            logger.debug("Skipping option with metric IDs outside approved catalog")
                            continue
                    try:
                        options.append(
                            ChatClarificationOption(
                                id=str(opt["id"]),
                                label=str(opt["label"]),
                                description=opt.get("description"),
                                spec=spec_obj,
                                action=opt.get("action"),
                            )
                        )
                    except ValidationError as exc:
                        logger.debug("Skipping invalid option: %s", exc)
                        continue
    return SemanticQueryInterpretation(
        status="needs_clarification",
        clarification=ChatClarificationPayload(prompt=prompt, options=options[:3]),
        rationale=raw.get("rationale"),
    )


def _fallback_interpretation(msg: str) -> SemanticQueryInterpretation:
    """Generate fallback interpretation on parse error."""
    return SemanticQueryInterpretation(
        status="needs_clarification",
        clarification=ChatClarificationPayload(prompt=msg, options=[]),
    )


def _build_node_output(interpretation: SemanticQueryInterpretation) -> dict[str, Any]:
    """Format state update for LangGraph."""
    out: dict[str, Any] = {
        "intent": "semantic_query",
        "interpretation": interpretation.model_dump(),
    }
    if interpretation.status == "needs_clarification":
        prompt = interpretation.clarification.prompt if interpretation.clarification else "Vui lòng làm rõ câu hỏi."
        out["chat_response"] = prompt
        out["clarification"] = interpretation.clarification.model_dump() if interpretation.clarification else None
    return out
