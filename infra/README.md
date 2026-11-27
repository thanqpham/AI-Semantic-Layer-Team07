# `infra/` — Docker và hạ tầng

| File / Thư mục | Chức năng chi tiết |
| --- | --- |
| `Dockerfile` | Image backend **production**, multi-stage: stage build tạo venv từ `requirements.txt`, stage chạy dùng `python:3.11-slim`, chạy bằng user không phải root (`appuser`). |
| `Dockerfile.dev` | Image backend cho phát triển: chạy `uvicorn ... --reload --reload-dir src` (compose dev mở thêm cổng `5678` cho debugpy). |
| `docker-compose.yml` | Chạy trọn gói: `postgres` (16-alpine) + `backend` (chạy `alembic upgrade head` rồi `uvicorn`, healthcheck `/health`, mount `data/`) + `frontend` (cổng host 3000, build-arg `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`). |
| `docker-compose.dev.yml` | Môi trường dev: `postgres` (`dev`/`devpassword`, DB `semantic_layer_dev`, cổng 5432 chỉ bind `127.0.0.1`), `backend` (bind-mount source, hot-reload, debugpy `5678`), `pgadmin` (cổng 8081), và `target-postgres-tls` (profile `tls-demo`, cổng 15432) để demo kết nối TLS/mTLS tới Target DB. |
| `docker-compose.compiler-test.yml` | Fixture cho test compiler đa DB: `compiler-postgres` (cổng 55432) và `compiler-mysql` (cổng 53306, `ONLY_FULL_GROUP_BY`), dữ liệu trong `tmpfs`, khởi tạo tài khoản reader từ `tests/fixtures/compiler_*/01-reader.sql`. |
| `docker/pgadmin/servers.json`, `docker/pgadmin/pgpass` | Cấu hình sẵn kết nối pgAdmin tới `semantic_layer_dev` (chỉ dùng cho dev cục bộ). |

## Lệnh thường dùng

```bash
docker compose -f infra/docker-compose.dev.yml up postgres pgadmin -d      # chỉ Metadata Store + pgAdmin
docker compose -f infra/docker-compose.dev.yml --profile tls-demo up -d target-postgres-tls
docker compose -f infra/docker-compose.yml up --build -d                   # trọn gói
docker compose -f infra/docker-compose.compiler-test.yml up -d             # cho pytest compiler đa DB
```

> Mật khẩu trong các file compose chỉ là giá trị **dev cục bộ**; không dùng cho production.
