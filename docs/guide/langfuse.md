# Theo dõi xử lý AI bằng Langfuse

Tích hợp dùng Python SDK v4.7 trở lên (vẫn dưới v5) và callback LangChain
chính thức. Không cần đổi frontend, schema DB hay API response. Cấu hình được
đọc một lần mỗi process; đổi cấu hình cần khởi động lại backend.

## Cấu trúc trace

```text
POST /api/v1/...                 # một trace cho mỗi request
  orchestrator                  # node, nếu request chạy graph
    ChatOpenAI                  # generation: model, token, latency, lỗi
  metric_suggest
    metric_generation           # action đã được instrument trong code
      ChatOpenAI
  metric_review
    metric_review_decision       # đối chiếu nghiệp vụ với context gốc
      ChatOpenAI
    metric_repair                # chỉ khi cần, tối đa một lượt sửa
      ChatOpenAI
    metric_review_result         # status và repair_count, không chứa context
```

Tên root dùng route template, không chứa query string hoặc ID thực trong URL.
Middleware ASGI giữ context xuyên suốt response streaming và background task
được await trong request. Các tác vụ cron hoặc lời gọi LLM ngoài HTTP vẫn có
span/generation riêng. Các node có `session_id` truyền thuộc tính session trước
khi tạo observation; Langfuse v4 áp dụng nó cho observation đang hoạt động và
các observation con, gồm root request và generation có usage. Session không
đồng nghĩa một trace: mỗi lượt HTTP vẫn tạo trace riêng.

Tái sử dụng `trace_node`, `trace_action`, `trace_value` và `get_llm()` hiện có;
không thay thế trace sink của benchmark. Chỉ những bước đã có các hook này
mới có span riêng. Generation vẫn được ghi nhận cho mọi provider đi qua
`get_llm()`, kể cả structured output và retry.

## Bật tracing

Tạo project trên Langfuse, lấy public key và secret key từ project settings.
Thêm hoặc cập nhật trong `.env` ở thư mục gốc dự án:

```dotenv
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_CAPTURE_CONTENT=false
```

Đổi `LANGFUSE_BASE_URL` theo region của project hoặc địa chỉ Langfuse tự host.
Trong Docker, `localhost` là container backend; nếu Langfuse chạy trên Windows
host, dùng `http://host.docker.internal:<port>`.

```powershell
docker compose up -d --build backend
docker compose logs -f backend
```

Với cấu hình dev:

```powershell
docker compose -f docker-compose.dev.yml up -d --build backend
```

Gửi một tin nhắn trong Studio hoặc chạy enrichment/sinh metric. Mở mục Traces
trong Langfuse, tìm theo route, môi trường `development`/`production`, hoặc
session. Export chạy theo batch; đợi vài giây để trace xuất hiện. Hàng đợi được
drain khi backend shutdown bình thường; kill cưỡng bức có thể mất batch cuối.

Langfuse có thể tính chi phí từ model và usage được provider trả về. Model
tùy chỉnh có thể cần khai báo bảng giá trên Langfuse; không có usage thì không
ước lượng token hoặc chi phí trong ứng dụng.

## Nội dung được gửi

- Mặc định: tên bước, thời gian, trạng thái, loại lỗi, model và usage token.
- Input/output/metadata của SDK bị thay bằng `[REDACTED]` khi
  `LANGFUSE_CAPTURE_CONTENT=false`. HTTP body, headers, graph state, connection
  string và kết quả SQL không được đưa vào các span thủ công.
- `LANGFUSE_CAPTURE_CONTENT=true` cho phép callback gửi prompt/response và
  metadata LLM. Chỉ bật khi chấp nhận gửi nội dung câu hỏi/schema lên máy chủ
  Langfuse; đây không phải chế độ tự động lọc PII hay bí mật trong prompt.
- Lỗi node/action và lỗi provider chỉ gửi tên loại lỗi; lỗi được node trả về
  trong state được đánh dấu `node_error`, không gửi nội dung lỗi.

Tracing tắt mặc định; thiếu key hoặc khởi tạo SDK thất bại sẽ bỏ qua tracing.
Exporter gửi nền, không chặn request để chờ Langfuse. Lỗi export xuất hiện trong
log SDK. Không đưa secret key vào frontend hay commit `.env`.

LangSmith là cấu hình độc lập. Nếu không dùng, đặt `LANGCHAIN_TRACING_V2=false`
để tránh gửi trace sang cả hai hệ thống. Masking ở đây chỉ áp dụng cho Langfuse.

## Tài liệu SDK

Luồng thẩm định, giới hạn compiler và migration được mô tả ở
[Thẩm định metric AI trước HITL](metric-review.md).

- [Python SDK v3 → v4 migration](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4)
- [LangChain integration](https://langfuse.com/integrations/frameworks/langchain)
- [Sessions](https://langfuse.com/docs/observability/features/sessions)
- [Masking](https://langfuse.com/docs/observability/features/masking)
