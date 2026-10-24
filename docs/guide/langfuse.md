# Tracing agent bằng Langfuse

Backend dùng Langfuse Python SDK v4.18 trở lên và callback LangChain. Mỗi lần chạy agent tạo một trace; request API thông thường không tạo trace. Không cần thay đổi frontend, API response hay schema DB.

## Bật tracing

Tạo project Langfuse và cấu hình trong `.env`:

```dotenv
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Khởi động lại backend sau khi đổi cấu hình. Với Docker, URL `localhost` trỏ tới container; dùng `host.docker.internal` nếu Langfuse chạy trên host. Export chạy theo batch và được drain khi backend shutdown bình thường.

## Cấu trúc trace

```text
chat_agent / metric_workflow / node schema chạy độc lập
  orchestrator / metric_suggest / metric_review / ...
    action nghiệp vụ đã gắn trace_action
      LLM generation: model, token, latency, lỗi
```

Trace chat bắt đầu sau khi xác thực và kiểm tra replay; workflow metric được lồng trong trace chat khi được gọi từ chat, hoặc tự làm root khi gọi riêng. Node schema chạy riêng tự làm root. Các generation ngoài agent và span của request API không được xuất. Session chat được gắn vào trace để tìm kiếm; mỗi lần chạy vẫn là một trace riêng. Trace công khai cho giao diện Studio tiếp tục dùng cơ chế hiện có.

## Nội dung gửi sang Langfuse

- Node/action hiển thị tên, thời gian, trạng thái và tóm tắt từ allowlist: intent, trạng thái parse, mode, số proposal, kết quả review, lượt repair, số bảng và mã lỗi an toàn khi có.
- Generation giữ model, token, thời gian và loại lỗi. Prompt, phản hồi LLM và metadata tự do bị thay bằng `[REDACTED]`.
- Graph state, HTTP body/headers, schema thô, connection string, SQL, kết quả truy vấn và thông báo lỗi thô không được đưa vào tóm tắt.
- `LANGFUSE_CAPTURE_CONTENT` đã bị loại bỏ. Giá trị cũ trong `.env` không còn tác dụng; tracing luôn áp dụng chính sách tóm tắt an toàn.

Tóm tắt được kiểm tra trước khi đưa vào SDK và được lọc lại ở lớp mask trước khi xuất. Langfuse tắt mặc định; thiếu key hoặc lỗi khởi tạo SDK thì ứng dụng vẫn chạy mà không có trace. LangSmith là cấu hình độc lập; đặt `LANGCHAIN_TRACING_V2=false` nếu không dùng.

Tham khảo [Langfuse instrumentation](https://langfuse.com/docs/observability/sdk/instrumentation) và [masking](https://langfuse.com/docs/observability/features/masking).
