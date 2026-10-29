"""Conversation Agent: answer greetings and supported general questions."""

from __future__ import annotations

import logging

from src.services.llm import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Bạn là trợ lý AI của hệ thống AI Semantic Layer Agent — "
    "nền tảng giúp doanh nghiệp tự động phân tích cấu trúc database, "
    "đặt tên nghiệp vụ tiếng Việt và quản lý Business Metrics.\n\n"
    "Nhiệm vụ của bạn:\n"
    "- Chào hỏi, cảm ơn hoặc giải thích các tính năng của hệ thống một cách thân thiện, ngắn gọn bằng tiếng Việt khi người dùng chào hỏi hoặc hỏi về danh tính/tính năng hệ thống.\n"
    "- BẮT BUỘC TỪ CHỐI mọi câu hỏi, yêu cầu hoặc chuỗi ký tự vô nghĩa/ký tự rác/không thuộc phạm vi dữ liệu (ví dụ: thời tiết, đời sống, nấu ăn, giải trí, kiến thức phổ thông, lập trình ngoài lề, v.v.).\n"
    "- Khi từ chối, hãy nói rõ: 'Câu hỏi hoặc yêu cầu của bạn hiện không thuộc phạm vi hỗ trợ của hệ thống. Tôi chỉ hỗ trợ các câu hỏi liên quan đến cơ sở dữ liệu, schema, Business Metrics và Semantic Layer. Bạn có câu hỏi nào về dữ liệu cần tôi hỗ trợ không?'"
)

_FALLBACK_RESPONSE = "Xin lỗi, tôi không thể phản hồi lúc này. Vui lòng thử lại!"
_MAX_HISTORY_CHARS = 12000


async def respond(user_message: str, chat_history: list[dict[str, str]] | None = None) -> str:
    """Generate a friendly natural-language response to chitchat messages.

    Uses the shared deterministic LLM configuration.
    """
    user_message = user_message.strip()
    if not user_message:
        return "Xin chào! Tôi có thể giúp gì cho bạn?"

    try:
        llm = get_llm()
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        messages.extend(_history_messages(chat_history or []))
        messages.append({"role": "user", "content": user_message})
        response = await llm.ainvoke(messages)
        reply = (response.content if hasattr(response, "content") else str(response)).strip()
        logger.info("Conversation Agent replied (len=%d chars)", len(reply))
        return reply

    except Exception as exc:
        logger.warning("Chitchat node failed: %s", exc)
        return _FALLBACK_RESPONSE


def _history_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Normalize prior messages and keep the prompt within a bounded budget."""
    result: list[dict[str, str]] = []
    remaining = _MAX_HISTORY_CHARS
    for item in reversed(history):
        role = item.get("role")
        content = item.get("content", "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        content = content[-remaining:]
        result.append({"role": role, "content": content})
        remaining -= len(content)
        if remaining <= 0:
            break
    result.reverse()
    return result
