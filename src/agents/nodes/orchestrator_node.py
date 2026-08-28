"""Classify chat requests for direct data guidance or metric generation."""

from __future__ import annotations

import logging
from typing import Any

from src.agents.state import AgentState
from src.observability import trace_node
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

- "metric_query": Yêu cầu tạo mới, định nghĩa, xây dựng, tính toán công thức hoặc đề xuất Business Metric / KPI mới cho hệ thống Semantic Layer. Bao gồm:
  + Các câu hỏi mô tả công thức, logic tính toán, chỉ số kinh doanh (ví dụ: "Tính giá trị trung bình trên mỗi đơn hàng (Average Order Value - AOV)", "Tính tổng doanh thu thuần của các đơn hàng có trạng thái hoàn thành (Net Revenue)", "Tính tổng số lượng đơn đặt hàng phát sinh trong toàn hệ thống", "Tính tỷ lệ hủy đơn hàng", "Doanh thu thực nhận sau khi trừ chiết khấu, hoàn trả", "Giá trị đơn hàng trung bình", "Lợi nhuận gộp Gross Profit", "Thời gian giao hàng trung bình", "Tỷ lệ đơn hàng thành công", "Số lượng khách hàng mới").
  + Các câu hỏi yêu cầu tạo/đề xuất metric (ví dụ: "Tạo metric mới Doanh thu thuần", "Đề xuất metric cho bảng orders", "Định nghĩa công thức AOV", "Xây dựng chỉ số khách hàng mới", "Thêm KPI tỷ lệ hoàn hàng").
  BẤT KỲ CÂU HỎI NÀO MÔ TẢ ĐỊNH NGHĨA/CÔNG THỨC CHỈ SỐ HOẶC YÊU CẦU TÍNH TOÁN/TẠO METRIC (không kèm yêu cầu trích xuất bảng báo cáo dữ liệu cụ thể theo thời gian hay chiều lọc) ĐỀU THUỘC NHÓM NÀY.

- "semantic_query": Câu hỏi yêu cầu truy vấn, trích xuất dữ liệu, xem kết quả bảng số liệu, báo cáo hoặc thống kê cụ thể từ Live Database theo các chiều phân tích (dimensions: theo khách hàng, theo ngày/tháng/năm, theo chi nhánh, theo sản phẩm) hoặc theo bộ lọc (filters) (ví dụ: "cho tôi kết quả Tổng doanh thu theo từng khách hàng", "Xem kết quả doanh thu", "Tổng doanh thu theo khách hàng năm 2024", "Doanh thu tháng này theo chi nhánh", "Số lượng đơn hàng hoàn thành năm 2024", "Báo cáo doanh số theo sản phẩm", "Thống kê đơn hàng tháng này", "Top 5 khách hàng chi tiêu nhiều nhất").

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


@trace_node("orchestrator")
async def orchestrator_node(state: AgentState) -> dict[str, Any]:
    """Classify user message into chitchat, semantic_query, data_question, metric_query, or out_of_scope.

    Uses LLM with temperature=0.0 for deterministic classification.
    Falls back to 'chitchat' on error to avoid breaking the conversation.
    """
    existing_intent = state.get("intent")
    if existing_intent in _INTENTS:
        if existing_intent == "out_of_scope":
            return {
                "intent": "out_of_scope",
                "chat_response": state.get("chat_response") or _OUT_OF_SCOPE_RESPONSE,
            }
        return {"intent": existing_intent}
    user_message = state.get("user_message", "").strip()
    if not user_message:
        return {"intent": "chitchat", "chat_response": "Bạn chưa nhập câu hỏi. Tôi có thể giúp gì?"}
    try:
        response = await get_llm().ainvoke(_classification_prompt(state, user_message))
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
        logger.warning("Orchestrator failed; defaulting to metric query: %s", exc)
        return {"intent": "metric_query"}


def _classification_prompt(state: AgentState, user_message: str) -> str:
    """Build a bounded classification prompt from the recent chat history."""
    history = _format_history(state.get("chat_history", []))
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


def _format_history(history: list[dict[str, str]]) -> str:
    """Format a small untrusted history excerpt for intent classification."""
    lines = []
    for item in history[-6:]:
        role = item.get("role")
        content = item.get("content", "").strip()[:1000]
        if role in {"user", "assistant"} and content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(none)"
