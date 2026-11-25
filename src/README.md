# `src/` — Backend

Backend FastAPI bất đồng bộ + LangGraph. Điểm vào là [`main.py`](main.py).

| Thư mục / File | Chức năng |
| --- | --- |
| [`main.py`](main.py) | Tạo `FastAPI`: `GZipMiddleware` (≥ 1000 byte), `RateLimitMiddleware`, `CORSMiddleware`; gắn router dưới `/api/v1`; `lifespan` (khởi động cron đồng bộ schema trừ `APP_ENV=test`, tắt tracing khi dừng); handler lỗi validation che key của `/settings/llm`; `GET /health`; `/metrics` Prometheus nếu có instrumentator. |
| [`config.py`](config.py) | `Settings` (pydantic-settings, đọc `.env`): app, CORS, `SECRET_KEY` JWT, rate limit, LLM + Judge, giới hạn SQL dump, `DATABASE_URL`, `ENCRYPTION_KEY`, `TARGET_DB_REQUIRE_READ_ONLY`, bật/tắt khám phá giá trị phân loại. `get_settings()` có cache, `reload_settings()` xóa cache. |
| [`api/`](api/README.md) | Routers HTTP. |
| [`services/`](services/README.md) | Logic nghiệp vụ (ingestion, enrichment, metric, compiler, chat, sync…). |
| [`agents/`](agents/README.md) | Graph, node, role (agent LLM), workflow. |
| [`models/`](models/README.md) | ORM và contract Pydantic. |
| [`observability/`](observability/README.md) | Trace, Langfuse, usage LLM. |
| [`knowledge/`](knowledge/README.md) | KPI recipes có nguồn. |

## Luồng phụ thuộc

```
api  →  services  →  models  →  Metadata Store
 └────→  agents  →  services / models
services  ⇢  Target DB   (metadata-only hoặc SELECT có guardrail)
```

Tầng trên được gọi tầng dưới, **không ngược lại**. Quy tắc code: async toàn bộ, type hint đầy đủ, ≤ 30 dòng/function, ≤ 500 dòng/file, `get_llm()` là cổng duy nhất tới LLM (xem [AGENTS.md](../AGENTS.md)).
