# `tests/` — Bộ kiểm thử backend (pytest)

```bash
make test                      # pytest tests/ -v
pytest tests/test_services -k compiler
```

**Quy tắc** (AGENTS.md): mọi node/service có unit test; **mock LLM** (không gọi OpenAI thật); **mock DB** bằng SQLite in-memory. `pytest.ini`: `asyncio_mode = auto`, `pythonpath = .`, `testpaths = tests`. CI chạy `APP_ENV=test` và bỏ qua `test_compiler_cross_database_live.py` ở job thường (job riêng dùng PostgreSQL/MySQL thật).

| Thư mục / File | Phạm vi |
| --- | --- |
| `conftest.py` | Fixture dùng chung: `async_session` (SQLite in-memory), `client` (FastAPI test client gắn session), `mock_llm`, và fixture tự động reset registry tiến độ enrichment giữa các test. |
| `metric_review_helpers.py` | Helper dựng metric/đề xuất review cho nhiều test. |
| `test_auth.py` | Đăng ký, đăng nhập, refresh token, Google OAuth, JWT. |
| `test_startup_lifespan.py` | Lifespan của app (khởi động/tắt cron, tracing). |
| `test_log_codex.py` | Script khôi phục log prompt từ transcript Codex (`scripts/log_codex.py`). |
| [`test_agents/`](test_agents/README.md) | Graph, node, role. |
| [`test_api/`](test_api/README.md) | Endpoint HTTP. |
| [`test_services/`](test_services/README.md) | Service (compiler, enrichment, metric, relationship, sync…). |
| [`test_models/`](test_models/README.md) | ORM và contract Pydantic. |
| [`test_migrations/`](test_migrations/README.md) | Đồ thị Alembic và từng migration. |
| [`test_integration/`](test_integration/README.md) | Luồng nhiều thành phần, compiler đa DB. |
| [`test_evaluation/`](test_evaluation/README.md) | Evaluation Framework (`eval/`). |
| [`test_eval/`](test_eval/README.md) | Seed dữ liệu ecommerce và relationship benchmark. |
| [`fixtures/`](fixtures/README.md) | SQL dump mẫu và script tạo tài khoản reader cho test compiler. |
