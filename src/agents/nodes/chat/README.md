# `src/agents/nodes/chat/` — Node của chat graph

Mỗi file là một node mỏng (14–21 dòng) chuyển `AgentState` sang role tương ứng trong [`../../roles/`](../../roles/README.md) và ghi kết quả vào state.

| File | Hàm | Gọi vào | Ghi vào state |
| --- | --- | --- | --- |
| `orchestrator_node.py` | `orchestrator_node` | `roles/orchestrator_agent.classify_request` | `intent` (`chitchat` / `data_question` / `metric_query` / `semantic_query` / `out_of_scope`) và câu trả lời trực tiếp khi ngoài phạm vi |
| `conversation_node.py` | `conversation_node` | `roles/conversation_agent.respond` | Câu trả lời cho chào hỏi / câu hỏi chung được hỗ trợ |
| `data_assistant_node.py` | `data_assistant_node` | `roles/data_assistant_agent.answer_data_question` | Câu trả lời hướng dẫn dữ liệu (schema, bảng/cột, metric đã duyệt), chỉ đọc |
| `semantic_query_parser_node.py` | `semantic_query_parser_node` | `roles/semantic_query_parser_agent.parse_semantic_query` | Diễn giải truy vấn có cấu trúc (metric, dimension, filter, hoặc yêu cầu làm rõ) để service `natural_language_query` biên dịch tiếp |

Nhánh `metric_query` của chat graph dùng `coordinator_node` trong [`../metric/`](../metric/README.md).
