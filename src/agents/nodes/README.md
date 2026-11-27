# `src/agents/nodes/` — Adapter node

Node là **lớp keo** giữa `AgentState` của LangGraph và các agent (`../roles/`) hoặc service (`../../services/`). Mỗi node nhận state, gọi đúng một việc, rồi trả phần state cần cập nhật. Node **không chứa prompt** và không tự ghi DB (trừ `save_node`, cố ý là điểm duy nhất lưu sau HITL).

| Thư mục | Dùng trong graph | Nội dung |
| --- | --- | --- |
| [`chat/`](chat/README.md) | `chat_graph` | Bốn node: orchestrator, conversation (chitchat), data assistant, semantic query parser. |
| [`metric/`](metric/README.md) | `chat_graph`, `semantic_layer_graph`, `metric_proposal_workflow` | Coordinator, validate, review, repair của quy trình sinh metric. |
| [`schema/`](schema/README.md) | `semantic_layer_graph` | Flow 1: introspect → enrich → save. |

> Các file `__pycache__/*.pyc` cũ trong thư mục này (ví dụ `chitchat_node`, `on_demand_metric_suggest_node`) là rác biên dịch từ phiên bản trước, không còn mã nguồn tương ứng.
