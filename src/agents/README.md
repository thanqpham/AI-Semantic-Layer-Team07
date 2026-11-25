# `src/agents/` — Agent LangGraph

Chứa mọi thứ liên quan đến LLM agent. Tầng này tách rõ bốn lớp để mỗi lớp chỉ làm một việc:

```
graphs/      lắp node + edge thành LangGraph (chỉ routing)
workflows/   workflow con có giới hạn vòng lặp (metric proposal)
nodes/       adapter: AgentState  ↔  role/service        (không chứa prompt)
roles/       prompt + gọi model + ràng buộc output của từng agent (không ghi DB)
state.py     AgentState dùng chung
```

Mọi lời gọi model đi qua `get_llm()` ở [`src/services/llm.py`](../services/llm.py).

| Thư mục / File | Chức năng |
| --- | --- |
| [`state.py`](state.py) | `AgentState` (`TypedDict`, `total=False`): trạng thái dùng chung của các graph — schema thô, bản làm giàu, metric đề xuất, `intent`, cờ `hitl_approved`, `semantic_layer_id`… |
| [`graphs/`](graphs/README.md) | Hai graph chính: `semantic_layer_graph` (Flow 1) và `chat_graph` (AI Studio). |
| [`workflows/`](workflows/README.md) | `metric_proposal_workflow`: builder → validate → reviewer → repair, có giới hạn vòng lặp. |
| [`nodes/`](nodes/README.md) | Adapter node cho `chat/`, `metric/`, `schema/`. |
| [`roles/`](roles/README.md) | Các agent LLM: orchestrator, conversation, data assistant, schema enrichment, metric designer/reviewer, semantic query parser. |
| `tools/` | Thư mục dành cho tool của agent (hiện chỉ có `__init__.py`). |

## Nguyên tắc

- **LLM chỉ đề xuất** (tên nghiệp vụ, metric, lựa chọn metric/dimension). Việc kiểm tra, ghi DB và sinh SQL do code xác định đảm nhiệm.
- Temperature `0.0`, prompt đặt tên nghiệp vụ yêu cầu **tiếng Việt**.
- Trace node/chuyển trạng thái qua [`src/observability/agent_trace.py`](../observability/agent_trace.py) (`trace_node`, `trace_transition`).
- Mỗi node/role phải có unit test trong [`tests/test_agents/`](../../tests/test_agents/README.md) với LLM được mock.
