"""Parse natural-language questions into structured SemanticQueryInterpretation."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

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
2. ĐỘ CHÍNH XÁC VỀ KHÁI NIỆM NGHIỆP VỤ (CỰC KỲ QUAN TRỌNG):
   - CHỈ ĐƯỢC CHỌN status: "resolved" khi chỉ số trong CATALOG thực sự mang đúng tên/định nghĩa hoặc là từ đồng nghĩa trực tiếp 100% của câu hỏi người dùng (ví dụ: "Doanh thu" <-> "Tổng doanh thu", "Số đơn" <-> "Số lượng đơn hàng").
   - TUYỆT ĐỐI CẤM TỰ Ý GÁN / ÉP CHỈ SỐ GẦN GIỐNG KHI KHÁC KHÁI NIỆM:
     + "Tỷ lệ giữ chân khách hàng (Retention Rate)" KHÔNG PHẢI LÀ "Tỷ lệ khách hàng quay lại mua hàng" hay "Số lượng khách hàng". Nếu catalog chỉ có "Tỷ lệ khách hàng quay lại mua hàng" mà người dùng hỏi "Tỷ lệ giữ chân khách hàng" -> BẮT BUỘC trả về status: "needs_clarification", TUYỆT ĐỐI KHÔNG CHỌN metric này!
     + "Doanh thu thuần (Net Revenue)" KHÔNG PHẢI LÀ "Tổng doanh thu (Gross Revenue)".
     + "Tỷ lệ chuyển đổi (Conversion Rate)" KHÔNG PHẢI LÀ "Số lượt xem" hay "Số đơn hàng".
     + "Giá trị đơn hàng trung bình (AOV)" KHÔNG PHẢI LÀ "Tổng doanh thu".
   - BẤT KỲ KHI NÀO chỉ số người dùng hỏi chưa có đúng định nghĩa trong CATALOG:
     + BẮT BUỘC trả về status: "needs_clarification".
     + TUYỆT ĐỐI KHÔNG CHỌN bất kỳ metric_ids nào trong catalog.
     + clarification.prompt: Giải thích ngắn gọn rằng chỉ số này chưa có trong danh mục được phê duyệt của hệ thống và hỏi người dùng có muốn {action_prompt} không.
       TUYỆT ĐỐI KHÔNG liệt kê các metric khác không đúng người dùng hỏi ở phía sau câu trả lời (ví dụ KHÔNG viết "Các chỉ số liên quan hiện có trong danh mục bao gồm...").
       Mẫu câu chuẩn: "Hệ thống hiện chưa có chỉ số '<Tên chỉ số người dùng hỏi>'. Bạn có muốn {action_prompt} này không?"
     + clarification.options: BẮT BUỘC trả về DUY NHẤT 1 option nút bấm:
       [
         {{"id": "create_metric", "label": "{action_label} '<Tên chỉ số người dùng hỏi>'", "description": "Yêu cầu AI đề xuất định nghĩa metric này", "spec": null, "action": "create_metric"}}
       ]
3. Nếu câu hỏi rõ ràng và map được metric/dimension/filter hợp lệ:
   - PHÂN TÁCH CÂU THEO CẤU TRÚC "<chỉ số X> theo <Y>" (bao gồm các cách nói: "theo chiều dữ liệu", "theo chiều", "phân tích theo", "phân theo", "thống kê theo", "báo cáo theo"):
     + Phần TRƯỚC cụm "theo..." là TÊN CHỈ SỐ (metric).
     + Phần SAU cụm "theo..." là TÊN CHIỀU (dimension) hoặc GIÁ TRỊ LỌC (filter). TUYỆT ĐỐI KHÔNG được coi phần đứng sau "theo" là tên chỉ số.
   - Quy tắc phân tách này KHÔNG làm suy yếu quy tắc 2: chỉ được "resolved" khi phần metric thực sự khớp metric trong CATALOG; nếu phần metric không khớp thì vẫn áp dụng quy tắc 2 (needs_clarification + đề xuất tạo metric).
   - Nếu metric khớp nhưng dimension/filter người dùng nêu KHÔNG có trong CATALOG: áp dụng quy tắc 4 (needs_clarification kèm các option chiều hợp lệ của chính metric đó).
   - status: "resolved"
   - metric_ids: danh sách ID chỉ số đã chọn (ví dụ [1])
   - dimensions: danh sách {{"column_id": int, "time_grain": "day"|"week"|"month"|"quarter"|"year"|null}}
   - filters: danh sách {{"column_id": int, "operator": "eq"|"neq"|"gt"|"gte"|"lt"|"lte"|"in"|"not_in"|"is_null"|"is_not_null", "value": any}}
   - time_ranges: danh sách {{"column_id": int, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "label": "Năm 2024"}} (khoảng thời gian nửa mở [start_date, end_date))
   - limit: số dòng tối đa (mặc định 100, tối đa 1000)
4. Nếu câu hỏi về một metric CÓ trong catalog nhưng mơ hồ về chiều phân tích hoặc bộ lọc (ví dụ: người dùng hỏi "Xem doanh thu" mà catalog có "Tổng doanh thu"):
   - status: "needs_clarification"
   - clarification: {{"prompt": "Câu hỏi làm rõ tiếng Việt", "options": [
       {{"id": "opt_1", "label": "Nhãn hiển thị ngắn", "description": "Mô tả chi tiết", "spec": {{"metric_ids": [...], "dimensions": [...], "filters": [], "limit": 100}}}}
     ]}} (tối đa 3 options có spec phân tích theo các dimension/filter hợp lệ của chính metric đó).
5. rationale: Giải thích ngắn gọn lý do chọn metric/dimension hoặc lý do cần làm rõ.

VÍ DỤ MẪU BẮT BUỘC TUÂN THEO:
- Ví dụ 1 (Khớp đúng): User "Xem tổng doanh thu 2024", Catalog có "Tổng doanh thu" (id=1) -> status: "resolved", metric_ids: [1]
- Ví dụ 2 (Chưa có chỉ số được hỏi, catalog chỉ có chỉ số gần giống): User "Xem tỷ lệ giữ chân khách hàng", Catalog có "Tỷ lệ khách hàng quay lại mua hàng" (id=9) -> KHÔNG ĐƯỢC CHỌN id=9 -> status: "needs_clarification", clarification.prompt: "Hệ thống hiện chưa có chỉ số 'Tỷ lệ giữ chân khách hàng'. Bạn có muốn {action_prompt} này không?", clarification.options: [{{"id": "create_metric", "label": "{action_label} 'Tỷ lệ giữ chân khách hàng'", "spec": null, "action": "create_metric"}}]
- Ví dụ 3 (Câu dạng "chỉ số X theo Y" — Y là chiều phân tích, KHÔNG phải chỉ số): User "hãy thực hiện tính toán chỉ số tổng số đơn hàng theo chiều dữ liệu 'trạng thái đơn hàng'", Catalog có metric "Tổng số đơn hàng" (id=2) và dimension "Trạng thái đơn hàng" (column_id=12) -> status: "resolved", metric_ids: [2], dimensions: [{{"column_id": 12, "time_grain": null}}]. TUYỆT ĐỐI KHÔNG trả về needs_clarification vì 'trạng thái đơn hàng' là chiều phân tích, không phải chỉ số bị thiếu.

CHỈ TRẢ VỀ DUY NHẤT 1 JSON OBJECT hợp lệ theo cấu trúc sau:
{{
  "status": "resolved" | "needs_clarification",
  "metric_ids": [1],
  "dimensions": [{{"column_id": 2, "time_grain": null}}],
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
    if not metrics:
        return _empty_catalog_fallback()

    user_message = user_message.strip()
    direct = _try_direct_resolution(user_message, catalog)
    if direct is not None:
        logger.info("Semantic parser resolved query deterministically without LLM")
        return _build_node_output(direct)
    prompt = _build_parse_prompt(user_message, catalog, can_generate_metrics, chat_history or [])
    try:
        raw_json = await trace_action(
            "semantic_parse", {"catalog_metrics": len(metrics)}, ainvoke_json(get_llm(), prompt, retries=1)
        )
        interpretation = _parse_interpretation(raw_json, catalog, can_generate_metrics, user_message)
    except Exception as exc:
        logger.warning("Semantic parse node failed: %s", exc)
        interpretation = _fallback_interpretation(
            "Tôi chưa hiểu rõ câu hỏi số liệu của bạn. Bạn có thể diễn đạt cụ thể hơn không?"
        )

    return _build_node_output(interpretation)


# Folded (accent-stripped) dimension markers, longest first so specific ones win.
_DIM_MARKERS = (
    "theo chieu du lieu",
    "theo chieu",
    "phan tich theo",
    "phan theo",
    "thong ke theo",
    "bao cao theo",
    "nhom theo",
)
_LEAD_PREFIXES = (
    "hay thuc hien",
    "thuc hien",
    "truy van",
    "vui long",
    "giup toi",
    "cho toi",
    "hay",
    "tinh toan",
    "phan tich",
    "thong ke",
    "bao cao",
    "xem",
    "tinh",
    "chi so",
    "chi tieu",
    "so lieu",
)


def _fold(text: str) -> str:
    """Casefold and strip Vietnamese diacritics for accent-insensitive matching."""
    return "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char)
    ).replace("đ", "d")


def _strip_lead_words(folded: str) -> str:
    """Drop common request prefixes so the metric phrase starts at its name."""
    changed = True
    while changed:
        changed = False
        for prefix in _LEAD_PREFIXES:
            if folded.startswith(prefix + " "):
                folded = folded[len(prefix) :].strip()
                changed = True
    return folded


def _unique_match(phrase: str, items: list[dict[str, Any]], name_keys: tuple[str, ...]) -> dict[str, Any] | None:
    """Return the single item whose folded name equals/contains the phrase, else None."""
    matches = []
    for item in items:
        names = [_fold(str(item.get(key) or "")) for key in name_keys]
        if any(name and (name == phrase or name in phrase or phrase in name) for name in names):
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _exact_unique_match(phrase: str, items: list[dict[str, Any]], name_keys: tuple[str, ...]) -> dict[str, Any] | None:
    """Return the single item whose folded name equals the phrase exactly, else None."""
    matches = [item for item in items if phrase and any(_fold(str(item.get(key) or "")) == phrase for key in name_keys)]
    return matches[0] if len(matches) == 1 else None


def _resolved_interpretation(
    metric_ids: list[int],
    dims: list[DimensionSelection],
    metric: dict[str, Any],
    dim: dict[str, Any] | None,
) -> SemanticQueryInterpretation:
    """Build a resolved interpretation for deterministically matched catalog items."""
    spec = SemanticQuerySpec(metric_ids=metric_ids, dimensions=dims, filters=[], limit=100)
    metric_name = metric.get("business_name") or metric.get("name")
    rationale = f"Phân tách trực tiếp: chỉ số '{metric_name}'"
    if dim is not None:
        rationale += f" theo chiều '{dim.get('business_name') or dim.get('column_name')}'"
    return SemanticQueryInterpretation(
        status="resolved",
        spec=spec,
        time_ranges=[],
        rationale=rationale + ".",
    )


def _try_direct_resolution(user_message: str, catalog: dict[str, Any]) -> SemanticQueryInterpretation | None:
    """Deterministically resolve verbatim metric or "<metric> theo <dimension>" sentences without an LLM pass.

    Returns None whenever either side is missing or ambiguous so the LLM flow stays in charge.
    """
    text = _fold(user_message)
    phrase = _strip_lead_words(text.strip(" .,;'\""))
    # shortcut: metric names may embed their own "theo ..." suffix, so verbatim match wins before the split.
    exact = _exact_unique_match(phrase, catalog.get("metrics", []), ("business_name", "name"))
    if exact is not None:
        return _resolved_interpretation([exact["id"]], [], exact, None)
    marker = next((m for m in _DIM_MARKERS if m in text), None)
    if marker is None:
        return None
    head, _, tail = text.partition(marker)
    metric_phrase = _strip_lead_words(head.strip(" .,;'\""))
    dim_phrase = tail.strip(" .,;'\"")
    metric = _unique_match(metric_phrase, catalog.get("metrics", []), ("business_name", "name"))
    dim = _unique_match(dim_phrase, catalog.get("dimensions", []), ("business_name", "column_name"))
    if metric is None or dim is None:
        return None
    return _resolved_interpretation(
        [metric["id"]],
        [DimensionSelection(column_id=dim["column_id"])],
        metric,
        dim,
    )


def _empty_catalog_fallback() -> dict[str, Any]:
    """Return polite clarification when no approved metrics exist."""
    msg = "Chưa có Business Metric nào được phê duyệt để truy vấn. Bạn vui lòng duyệt metric trước."
    interp = SemanticQueryInterpretation(
        status="needs_clarification",
        clarification=ChatClarificationPayload(prompt=msg, options=[]),
    )
    return {"intent": "semantic_query", "interpretation": interp.model_dump(), "chat_response": msg}


def _build_parse_prompt(
    user_message: str,
    catalog: dict[str, Any],
    can_generate_metrics: bool,
    chat_history: list[dict[str, str]],
) -> str:
    """Format catalog, history, and current Vietnam time into the prompt."""
    now_vn = datetime.now(_VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    history_str = _format_history(chat_history)
    compact_catalog = json.dumps(catalog, ensure_ascii=False, indent=2)
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
    raw: dict[str, Any], catalog: dict[str, Any], can_generate_metrics: bool, user_message: str
) -> SemanticQueryInterpretation:
    """Convert raw LLM dict into validated SemanticQueryInterpretation."""
    status = raw.get("status")
    if status == "resolved":
        spec = _build_spec(raw, catalog)
        if spec is not None:
            if _is_forced_mismatch(user_message, spec.metric_ids, catalog):
                raw = {
                    "status": "needs_clarification",
                    "clarification": {
                        "prompt": f"Hệ thống hiện chưa có chỉ số '{user_message.strip()}'.",
                        "options": [],
                    },
                    "rationale": "Chỉ số được hỏi chưa tồn tại chính xác trong danh mục.",
                }
            else:
                time_ranges = _build_time_ranges(raw.get("time_ranges", []))
                return SemanticQueryInterpretation(
                    status="resolved",
                    spec=spec,
                    time_ranges=time_ranges,
                    rationale=raw.get("rationale"),
                )
    return _build_clarification_interpretation(raw, catalog, can_generate_metrics, user_message)


def _build_spec(raw: dict[str, Any], catalog: dict[str, Any]) -> SemanticQuerySpec | None:
    """Construct SemanticQuerySpec from raw output after verifying IDs."""
    metric_ids = [int(m) for m in raw.get("metric_ids", []) if isinstance(m, (int, str)) and str(m).isdigit()]
    if not metric_ids:
        return None

    valid_metric_ids = {m["id"] for m in catalog.get("metrics", [])}
    if not set(metric_ids).issubset(valid_metric_ids):
        return None

    dims = [DimensionSelection(**d) for d in raw.get("dimensions", []) if isinstance(d, dict) and "column_id" in d]
    filters = [SemanticQueryFilter(**f) for f in raw.get("filters", []) if isinstance(f, dict) and "column_id" in f]
    limit = min(max(int(raw.get("limit", 100)), 1), 1000)

    return SemanticQuerySpec(metric_ids=metric_ids, dimensions=dims, filters=filters, limit=limit)


def _build_time_ranges(items: list[Any]) -> list[SemanticTimeRange]:
    """Parse time ranges safely."""
    ranges: list[SemanticTimeRange] = []
    for item in items:
        if isinstance(item, dict) and "column_id" in item and "start_date" in item and "end_date" in item:
            ranges.append(
                SemanticTimeRange(
                    column_id=item["column_id"],
                    start_date=str(item["start_date"]),
                    end_date=str(item["end_date"]),
                    label=str(item.get("label", "")),
                )
            )
    return ranges


def _is_missing_metric_prompt(prompt: str) -> bool:
    """Detect if clarification prompt explains that requested metric is missing."""
    lowered = prompt.lower()
    markers = (
        "chưa có chỉ số",
        "chưa định nghĩa",
        "chưa có metric",
        "không có chỉ số",
        "không có metric",
        "chưa hỗ trợ",
        "chưa có trong",
        "không tồn tại",
    )
    return any(m in lowered for m in markers)


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
    raw: dict[str, Any], catalog: dict[str, Any], can_generate_metrics: bool = False, user_message: str = ""
) -> SemanticQueryInterpretation:
    """Build a needs_clarification interpretation from clarification payload."""
    clar_data = raw.get("clarification")
    prompt = "Tôi cần thêm thông tin để chạy truy vấn chính xác. Bạn vui lòng chọn một trong các gợi ý dưới đây:"
    options: list[ChatClarificationOption] = []
    if isinstance(clar_data, dict):
        prompt = clar_data.get("prompt") or prompt
        raw_options = clar_data.get("options", [])
        if _is_missing_metric_prompt(prompt):
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
                                spec_obj = SemanticQuerySpec(**spec)
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
