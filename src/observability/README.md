# `src/observability/` — Trace, tracing và usage

Ba module độc lập, đều **an toàn theo thiết kế**: chỉ ghi tóm tắt do server kiểm soát, không để rò prompt thô, secret hay dữ liệu khách hàng.

| File | Thành phần chính | Chức năng chi tiết |
| --- | --- | --- |
| `agent_trace.py` | `AgentTraceSink`, `activate_trace`, `trace_node`, `trace_transition`, `trace_value`, `trace_action`, `trace_llm_usage`, `trace_metric_output_error` | Sự kiện trace agent **opt-in** (chỉ hoạt động khi có sink kích hoạt, ví dụ trong benchmark). Production không phụ thuộc kho lưu trữ benchmark. Dùng làm decorator `trace_node` và ghi chuyển trạng thái giữa các node. |
| `langfuse_tracing.py` | `get_tracing_client`, `llm_trace_callbacks`, `observation`, `trace_summary`, `shutdown_tracing` | Xuất **chỉ observation của agent** lên Langfuse với bản tóm tắt có giới hạn (`LANGFUSE_*`). Bật/tắt bằng `LANGFUSE_TRACING_ENABLED`; `shutdown_tracing` được gọi trong `lifespan` khi tắt app. |
| `llm_usage.py` | `BenchmarkUsageCallback`, `record_account_usage`, `get_account_usage`, `reset_account_usage` | Chuẩn hóa usage metadata của provider (token vào/ra) thành sự kiện an toàn; ghi nhận usage theo tài khoản cho màn hình Cài đặt AI (xóa bằng `DELETE /settings/llm/usage`). |

Hướng dẫn cấu hình Langfuse: [`docs/guide/langfuse.md`](../../docs/guide/langfuse.md).
