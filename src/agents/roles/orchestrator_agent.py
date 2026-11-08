"""Classify chat requests for direct data guidance or metric generation."""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

from src.services.llm import get_llm

logger = logging.getLogger(__name__)

_OUT_OF_SCOPE_RESPONSE = (
    "Tôi là trợ lý AI chuyên về Semantic Layer và phân tích dữ liệu doanh nghiệp. "
    "Câu hỏi hoặc yêu cầu của bạn hiện không thuộc phạm vi hỗ trợ của hệ thống. "
    "Tôi chỉ hỗ trợ các câu hỏi liên quan đến cơ sở dữ liệu, schema, bảng, cột, "
    "Business Metrics và tính năng của hệ thống Semantic Layer. "
    "Bạn có câu hỏi nào về dữ liệu cần tôi hỗ trợ không?"
)

_CLASSIFY_PROMPT = """Bạn là bộ phân loại câu hỏi thông minh cho hệ thống AI Semantic Layer.
Phân loại câu hỏi của người dùng vào đúng 1 trong 5 nhóm:

- "metric_query": Yêu cầu tạo mới, định nghĩa, xây dựng hoặc đề xuất định nghĩa/công thức Business Metric / KPI mới cho hệ thống Semantic Layer (ví dụ: "Tạo metric mới Doanh thu thuần", "Đề xuất metric cho bảng orders", "Định nghĩa công thức AOV", "Xây dựng chỉ số khách hàng mới", "Thêm KPI tỷ lệ hoàn hàng"). Các yêu cầu mô tả logic cần thiết để tạo một chỉ số cũng thuộc nhóm này.

- "semantic_query": Yêu cầu truy vấn, xem, lấy hoặc tính giá trị/kết quả số liệu của chỉ số từ dữ liệu, kể cả khi câu dùng từ "tính toán"; không cần chiều phân tích hoặc bộ lọc. Chỉ số có thể được phân tích theo dimension hoặc filter nếu người dùng yêu cầu. Ưu tiên nhóm này khi người dùng muốn kết quả, không tự suy đoán họ muốn tạo định nghĩa metric. Ví dụ: "Giúp tôi thực hiện truy vấn chỉ số tính toán tổng số khách hàng", "Tính giá trị chỉ số tổng số khách hàng", "Xem kết quả doanh thu", "Tổng doanh thu theo khách hàng năm 2024", "Doanh thu tháng này theo chi nhánh", "Báo cáo doanh số theo sản phẩm", "Top 5 khách hàng chi tiêu nhiều nhất".

- "data_question": Hỏi về cấu trúc database, schema, bảng, cột, kiểu dữ liệu, glossary, quan hệ bảng, danh sách metric đã có hoặc hướng dẫn chọn dữ liệu/dimension/filter để tìm hiểu dữ liệu (không yêu cầu tạo metric hay lấy số liệu cụ thể) (ví dụ: "Bảng orders có những cột nào?", "Quan hệ giữa bảng orders và customers", "Có những metric doanh thu nào đã được phê duyệt?").

- "chitchat": CHỈ DÀNH CHO các câu chào hỏi rõ ràng (ví dụ: "xin chào", "hello", "hi", "cảm ơn", "tạm biệt") hoặc hỏi trực tiếp về danh tính/khả năng của AI trợ lý ("bạn là ai", "bạn có thể làm được gì"). TUYỆT ĐỐI KHÔNG xếp các ký tự vô nghĩa, ký tự rác, câu hỏi gõ sai hoặc chuỗi ngẫu nhiên vào nhóm này.

- "out_of_scope": BẤT KỲ câu hỏi, yêu cầu hoặc chuỗi ký tự nào KHÔNG LIÊN QUAN ĐẾN DỮ LIỆU hoặc không phải lời chào hỏi hợp lệ. Bao gồm:
  + Các ký tự vô nghĩa, ký tự rác, escape characters, chuỗi gõ sai/gõ nhầm (ví dụ: "\\n \\t", "asdfgh", "12345", "???", "...", ký tự ngẫu nhiên).
  + Các chủ đề ngoài lề (thời tiết, công thức nấu ăn, viết thơ, kể chuyện, giải toán ngoài lề, tin tức xã hội, thể thao, giải trí, lập trình ứng dụng ngoài lề...).

Chỉ trả về DUY NHẤT 1 từ trong 5 từ: "metric_query", "semantic_query", "data_question", "chitchat", hoặc "out_of_scope"

Câu hỏi trước đây:
{history}

Latest request: {user_message}"""

_INTENTS = {"chitchat", "semantic_query", "data_question", "metric_query", "out_of_scope"}
_METRIC_ACTION_MARKERS = ("gui data lead de xuat chi so", "tao business metric", "tao metric")


async def classify_request(
    user_message: str,
    chat_history: list[dict[str, str]] | None = None,
    existing_intent: str | None = None,
    existing_response: str | None = None,
) -> dict[str, Any]:
    """Classify user message into chitchat, semantic_query, data_question, metric_query, or out_of_scope.

    Uses LLM with temperature=0.0 for deterministic classification.
    Stops routing on provider errors so one failure does not trigger more LLM calls.
    """
    if existing_intent in _INTENTS:
        if existing_intent == "out_of_scope":
            return {
                "intent": "out_of_scope",
                "chat_response": existing_response or _OUT_OF_SCOPE_RESPONSE,
            }
        return {"intent": existing_intent}
    user_message = user_message.strip()
    if not user_message:
        return {"intent": "chitchat", "chat_response": "Bạn chưa nhập câu hỏi. Tôi có thể giúp gì?"}
    if _is_metric_action_message(user_message):
        return {"intent": "metric_query"}
    try:
        response = await get_llm().ainvoke(_classification_prompt(chat_history or [], user_message))
        raw = (response.content if hasattr(response, "content") else str(response)).strip().lower()
        intent = _parse_intent(raw)
        logger.info(
            "Orchestrator classified message (len=%d) → intent=%s",
            len(user_message),
            intent,
        )
        if intent == "out_of_scope":
            return {"intent": "out_of_scope", "chat_response": _OUT_OF_SCOPE_RESPONSE}
        return {"intent": intent}
    except Exception as exc:
        logger.warning("Orchestrator classification failed: %s", type(exc).__name__)
        return {
            "intent": "chitchat",
            "chat_response": "Chưa thể phân loại yêu cầu do dịch vụ AI đang lỗi. Vui lòng thử lại sau.",
        }


def _classification_prompt(chat_history: list[dict[str, str]], user_message: str) -> str:
    """Build a bounded classification prompt from the recent chat history."""
    history = _format_history(chat_history)
    return _CLASSIFY_PROMPT.format(history=history, user_message=user_message)


def _parse_intent(raw: str) -> str:
    """Parse raw LLM response into recognized intent string."""
    cleaned = raw.strip().lower()
    if "metric_query" in cleaned:
        return "metric_query"
    if "semantic_query" in cleaned:
        return "semantic_query"
    if "data_question" in cleaned:
        return "data_question"
    if "out_of_scope" in cleaned or "unrelated" in cleaned:
        return "out_of_scope"
    if "chitchat" in cleaned:
        return "chitchat"
    return "data_question"


def _is_metric_action_message(message: str) -> bool:
    """Recognize metric action labels before an LLM can misclassify them."""
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", message.casefold()) if not unicodedata.combining(char)
    ).replace("đ", "d")
    return any(marker in normalized for marker in _METRIC_ACTION_MARKERS)


def _format_history(history: list[dict[str, str]]) -> str:
    """Format a small untrusted history excerpt for intent classification."""
    lines = []
    for item in history[-6:]:
        role = item.get("role")
        content = item.get("content", "").strip()[:1000]
        if role in {"user", "assistant"} and content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(none)"
