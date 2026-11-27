# AI Semantic Layer Agent — P-069

> **Dự án thuộc VinUni AI20K Build Phase (Cohort 3).**
> Nền tảng AI Agent hỗ trợ xây dựng, quản trị **Semantic Layer** tập trung cho cơ sở dữ liệu doanh nghiệp và biên dịch truy vấn chỉ số kinh doanh một cách xác định, có kiểm soát.

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.118+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-black?style=flat&logo=next.js&logoColor=white)](https://nextjs.org/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?style=flat&logo=react&logoColor=black)](https://react.dev/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-FF6F61?style=flat)](https://langchain-ai.github.io/langgraph/)
[![SQLGlot](https://img.shields.io/badge/sqlglot-30.x-blue?style=flat)](https://github.com/tobymao/sqlglot)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)

**Mục lục:** [Bài toán](#1-bài-toán) · [Phạm vi](#2-phạm-vi-dự-án) · [Tính năng](#3-tính-năng-chính) · [Kiến trúc](#4-kiến-trúc-tổng-quan) · [Cài đặt](#5-cài-đặt--chạy-nhanh) · [Cấu hình](#6-cấu-hình-biến-môi-trường) · [Database & seed](#7-cơ-sở-dữ-liệu--dữ-liệu-mẫu) · [API](#8-danh-mục-api) · [Kịch bản](#9-kịch-bản-sử-dụng) · [Kiểm thử](#10-kiểm-thử--đánh-giá) · [Bảo mật](#11-an-toàn--bảo-mật) · [Phát triển](#12-quy-ước-phát-triển) · [Tài liệu](#13-tài-liệu-liên-quan)

---

## 1. Bài toán

Dữ liệu doanh nghiệp lưu trong CSDL quan hệ (PostgreSQL, MySQL, SQLite) thường gặp hai thách thức:

1. **Khoảng cách ngữ cảnh nghiệp vụ (Business Context Gap):** tên bảng/cột mang tính kỹ thuật (`usr_tbl_01`, `amt_vat_inc`, `ord_sts_cd`) khiến người làm nghiệp vụ, BA, DA mất thời gian tra cứu và dễ hiểu sai số liệu.
2. **Hỗn loạn định nghĩa chỉ số (Metric Definition Chaos):** thiếu "nguồn sự thật duy nhất" cho doanh thu thuần, tỷ lệ chuyển đổi, ARPU… Mỗi phòng ban tự tính theo logic riêng nên báo cáo không thống nhất.

### Giải pháp

**AI Semantic Layer Agent** tự động hóa chuỗi:

> Đọc schema → AI đặt tên nghiệp vụ tiếng Việt & đề xuất chỉ số → con người duyệt (HITL) → lưu vào Metadata Store → export JSON/YAML **hoặc** truy vấn chỉ số đã duyệt qua compiler xác định.

## 2. Phạm vi dự án

Hệ thống có **hai luồng chính**:

| | **Flow 1 — Generate & Manage** | **Flow 2 — Semantic Query (chỉ Live DB)** |
| --- | --- | --- |
| Mục đích | Sinh và quản trị Semantic Layer | Truy vấn chỉ số/chiều đã duyệt |
| Đầu vào | Live DB (connection string) hoặc SQL Dump | `metric_ids` + `dimensions` + `filters` đã duyệt |
| Cơ chế | SQLAlchemy Inspector → enrichment 2-pass → metric agent → HITL | `SemanticQueryCompiler` xác định + guardrail `sqlglot` |
| Ràng buộc | Chỉ đọc **schema metadata**, không `SELECT` dữ liệu để introspect | Chỉ `SELECT`; `LIMIT` mặc định 100 (tối đa 1000); timeout 15 giây |

- Flow 2 **không phải** text-to-SQL tự do. Câu hỏi ngôn ngữ tự nhiên chỉ được *parse thành lựa chọn metric/dimension đã duyệt*; SQL do compiler sinh ra.
- **SQL Dump** chỉ chứa DDL nên chỉ dùng cho Flow 1, không hỗ trợ Flow 2.
- Không dùng vector store (ChromaDB, FAISS).

## 3. Tính năng chính

| Nhóm | Mô tả |
| --- | --- |
| **Kết nối nguồn dữ liệu** | Live DB (PostgreSQL / MySQL / SQLite, hỗ trợ TLS `prefer`/`require`/`verify_ca`/`verify_full`, mTLS) hoặc upload SQL Dump (PostgreSQL / MySQL / SQLite, tối đa 20 MB). Connection URL mã hóa Fernet. |
| **Enrichment 2-pass** | Pass 1: glossary toàn cục → phân cụm bảng theo đồ thị (Hub-Detached Partitioning) → Pass 2: làm giàu từng cụm song song, có fallback. Chạy nền, chỉ điền ô còn trống, theo dõi tiến độ qua `enrich/status`. |
| **Schema Review (HITL)** | Duyệt tên/mô tả bảng và cột; sơ đồ quan hệ (React Flow + dagre); AI gợi ý relationship, duyệt/sửa/tắt, xem tác động lên metric đã publish; duyệt value mapping cho cột phân loại; mô tả tổng quan database. |
| **Metrics Catalog** | Metric kèm công thức/filter chuẩn hóa (`MetricDefinition` v2), phiên bản append-only, so sánh phiên bản, duyệt/từ chối, rollback, khôi phục; metric request & thông báo realtime (SSE). |
| **AI Studio** | Chat đa agent (`orchestrator` → `chitchat` / `data_assistant` / `metric_coordinator` / `semantic_parse`), streaming SSE, nhiều phiên chat, tiếp tục/hủy tác vụ, xem luồng agent; dedupe metric trước khi đề xuất mới. |
| **Metric Explorer** | Chọn metric + dimension + filter, xem SQL biên dịch và kết quả. |
| **Metrics Dashboard** | Dashboard singleton theo workspace, widget kéo-thả, cấu hình biểu đồ theo metric. |
| **Schema Sync** | Fingerprint phát hiện drift, đồng bộ thủ công hoặc cron 02:00 hằng ngày, self-healing công thức metric khi đổi tên cột/bảng, audit log. |
| **Export** | Semantic Layer đã duyệt ra JSON hoặc YAML. |
| **Workspace & RBAC** | Tổ chức, mời thành viên, vai trò `admin` / `data_lead` / `member`; đăng nhập email/mật khẩu hoặc Google OAuth, refresh token xoay vòng. |
| **Cấu hình AI theo tài khoản** | Chọn provider/model ngay trong giao diện (OpenAI, Gemini, Anthropic, DeepSeek, Groq, OpenRouter, MiMo, endpoint OpenAI-compatible tùy chỉnh). Key mã hóa Fernet, không trả về qua API. |
| **Observability** | Langfuse, LangSmith, Prometheus (`/metrics`, nếu đã cài `prometheus-fastapi-instrumentator`), ghi nhận usage LLM. |
| **Evaluation Framework** | Golden Dataset + evaluator xác định + AI Judge cô lập (xem [eval/README.md](eval/README.md)). |

## 4. Kiến trúc tổng quan

```mermaid
graph TB
    subgraph Client["Client — Next.js 16 / React 19"]
        V["AI Studio · Schema Review · Metrics Catalog<br/>Metric Explorer · Dashboard · Export"]
    end

    subgraph API["API — FastAPI async, /api/v1"]
        A["Auth & Org · Semantic · Review · Relationship<br/>Chat · Query · Sync · Dashboard · LLM Settings"]
    end

    subgraph Core["Xử lý lõi"]
        F1["Flow 1: introspect → pass 1 → clustering → pass 2<br/>→ canonical builder → HITL → save"]
        F2["Flow 2: resolver → SemanticQueryCompiler<br/>→ sqlglot guardrails → read-only execution"]
        CH["Chat graph (LangGraph):<br/>orchestrator → chitchat | data_assistant |<br/>metric_coordinator | semantic_parse"]
        SY["Schema Sync: fingerprint → drift → self-healing"]
    end

    subgraph Store["Lưu trữ"]
        META[("Metadata Store<br/>PostgreSQL — 24 bảng ORM")]
        TARGET[("Target DB (Live, read-only)<br/>PostgreSQL / MySQL / SQLite")]
    end

    Client --> API --> Core
    Core --> META
    F1 -. "chỉ đọc schema metadata" .-> TARGET
    F2 -- "SELECT có guardrail" --> TARGET
```

Mô tả chi tiết từng thành phần, sơ đồ luồng, mô hình dữ liệu và RBAC: [ARCHITECTURE.md](ARCHITECTURE.md).
Bản đồ từng thư mục/file và vai trò của chúng: [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

### Cấu trúc thư mục (rút gọn)

```
├── src/                 # Backend FastAPI
│   ├── api/             #   Routers: auth, organization, routes (semantic), review, relationship,
│   │                    #   categorical, overview, dashboard, sync, llm_settings
│   ├── agents/          #   LangGraph: graphs/, nodes/, roles/ (agent LLM), workflows/, state.py
│   ├── services/        #   Logic nghiệp vụ: introspection, enrichment, metric_*, query_compiler*, ...
│   ├── models/          #   ORM (db*.py) + Pydantic contracts
│   ├── observability/   #   Langfuse, agent trace, LLM usage
│   ├── knowledge/       #   retail_metrics.yaml (KPI recipes tùy chọn)
│   ├── config.py        #   Settings (pydantic-settings)
│   └── main.py          #   FastAPI app, middleware, lifespan (cron sync)
├── frontend/            # Next.js 16 App Router (landing, auth, workspace, invite) + Vitest + Playwright
├── alembic/             # Migrations (versions/)
├── eval/                # Evaluation Framework (golden dataset, hybrid evaluator, benchmark)
├── tests/               # pytest: agents, api, services, models, migrations, evaluation, integration
├── infra/               # Dockerfile(s), docker-compose.{dev,yml,compiler-test}.yml, pgAdmin
├── scripts/             # Seed DB, TLS, AI-usage logging hooks, tiện ích
├── data/                # Golden Retail schema & seed
└── docs/                # PRD, BRIEF, DATABASE_DESIGN, UI_FLOW, guide/, ...
```

---

## 5. Cài đặt & chạy nhanh

### 5.1. Yêu cầu

- **Python 3.11**
- **Node.js 20+** và npm
- **Docker & Docker Compose** (cho PostgreSQL Metadata Store)
- **Git**

### 5.2. Backend

```bash
git clone https://github.com/AI20K-Build-Phase-Cohort-3/P-069.git
cd P-069

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt     # pytest, ruff... (để chạy test/lint)
```

### 5.3. Frontend

```bash
cd frontend
npm install
cd ..
```

### 5.4. Cấu hình môi trường

```bash
cp .env.example .env
```

Tối thiểu cần đặt `ENCRYPTION_KEY` (khóa Fernet):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Xem chi tiết các biến ở [mục 6](#6-cấu-hình-biến-môi-trường).

### 5.5. Metadata Store & migrations

```bash
# PostgreSQL + pgAdmin 4
docker compose -f infra/docker-compose.dev.yml up postgres pgadmin -d

# Áp dụng migration
alembic upgrade head
```

- **pgAdmin 4:** http://localhost:8081 — tài khoản dev `admin@admin.com` / `admin` (chỉ dùng cục bộ).
- Metadata Store dev: `postgresql+asyncpg://dev:devpassword@localhost:5432/semantic_layer_dev`.

### 5.6. Chạy ứng dụng

**Cách 1 — Cục bộ (khuyên dùng khi phát triển):**

```bash
# Terminal 1 — Backend
make run            # hoặc: uvicorn src.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

| Dịch vụ | URL |
| --- | --- |
| Web app | http://localhost:3000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Health | http://localhost:8000/health |
| Prometheus | http://localhost:8000/metrics (nếu đã cài instrumentator) |

**Cách 2 — Docker Compose trọn gói (postgres + backend + frontend):**

```bash
docker compose -f infra/docker-compose.yml up --build -d
```

Frontend phục vụ tại http://localhost:3000, backend tại http://localhost:8000. Biến build của frontend: `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.

**Cách 3 — Compose dev (backend hot-reload trong container):**

```bash
docker compose -f infra/docker-compose.dev.yml up --build -d
docker compose -f infra/docker-compose.dev.yml logs -f backend
docker compose -f infra/docker-compose.dev.yml down
```

Compose dev gồm `postgres`, `backend` (hot-reload, debugpy cổng `5678`) và `pgadmin`; frontend vẫn chạy bằng `npm run dev`.

### 5.7. Thiết lập AI Usage Logging (dành cho học viên AI20K)

```bash
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts\setup_hooks.ps1
# Linux / macOS / Git Bash
bash scripts/setup_hooks.sh
```

Log được gửi tự động qua pre-push hook; không chạy script log thủ công sau mỗi task và không sửa thư mục `.ai-log/`.

---

## 6. Cấu hình biến môi trường

Danh sách đầy đủ kèm chú thích: [.env.example](.env.example). Giá trị mặc định lấy từ [src/config.py](src/config.py).

### 6.1. Chọn provider/model trong giao diện (khuyên dùng)

Sau `alembic upgrade head`, đăng nhập rồi mở **Cài đặt → Nhà cung cấp & model AI**:

1. Chọn provider (OpenRouter, Google Gemini, OpenAI, Anthropic, DeepSeek, Groq, MiMo…).
2. Nhập API key, bấm **Tải danh sách model** rồi chọn model, hoặc nhập chính xác model ID.
3. Bấm **Lưu cấu hình AI** — có hiệu lực ngay cho các yêu cầu tiếp theo, không cần restart.

Key được mã hóa Fernet trong Metadata Store theo tài khoản, không lưu trong trình duyệt và không trả về qua API. Mỗi provider nhớ key/model đã lưu (để trống ô key để giữ key cũ). Tác vụ đồng bộ schema định kỳ dùng cấu hình AI của người tạo nguồn dữ liệu. Khi dùng cách này **không cần** đặt API key LLM trong `.env`, nhưng vẫn cần `DATABASE_URL` và `ENCRYPTION_KEY` hợp lệ và ổn định.

### 6.2. Bảng biến môi trường

| Nhóm | Biến | Mặc định | Mô tả |
| --- | --- | --- | --- |
| **App** | `APP_ENV` | `development` | `development` / `production` / `test`. `production` tự bật rate limit; `test` tắt cron sync |
| | `APP_HOST`, `APP_PORT` | `0.0.0.0`, `8000` | Địa chỉ/cổng backend |
| | `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| | `CORS_ORIGINS` | `http://localhost:3000` | Danh sách origin, phân tách bằng dấu phẩy |
| | `FRONTEND_APP_URL` | `http://localhost:3000` | URL frontend (link mời thành viên, OAuth) |
| | `SECRET_KEY` | giá trị dev | Khóa ký JWT. **Bắt buộc đổi khi chạy production** |
| **Security** | `ENCRYPTION_KEY` | *(trống)* | **Bắt buộc.** Khóa Fernet mã hóa connection URL và API key; giữ cố định để giải mã dữ liệu đã lưu |
| | `TARGET_DB_REQUIRE_READ_ONLY` | `true` | Từ chối Live DB dùng tài khoản có quyền ghi. Chỉ đặt `false` cho dev/test |
| **Database** | `DATABASE_URL` | `postgresql+asyncpg://dev:devpassword@localhost:5432/semantic_layer_dev` | Metadata Store (PostgreSQL asyncpg) |
| | `TARGET_DATABASE_URL`, `CSV_DATA_DIR` | — | Dùng cho script seed/import dữ liệu mẫu |
| **Rate limit** | `RATE_LIMIT_ENABLED`, `RATE_LIMIT_RPM` | `false`, `15` | Giới hạn request cho endpoint AI (tự bật ở production) |
| **LLM (dự phòng)** | `LLM_PROVIDER` | `mimo` | `openai` \| `gemini` \| `groq` \| `mimo` \| `anthropic` \| `openrouter` \| `deepseek` \| tên tùy ý + `LLM_API_BASE` |
| | `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` | — | Ghi đè chung cho mọi endpoint OpenAI-compatible (ưu tiên cao nhất) |
| | `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, `MIMO_API_KEY`, `ANTHROPIC_API_KEY` | — | Key theo provider (dùng khi `LLM_API_KEY` trống) |
| | `MODEL_NAME` | theo provider | Model mặc định |
| | `LLM_MODEL_ENRICH`, `LLM_MODEL_METRIC` | — | Model riêng cho bước enrichment / sinh metric |
| | `LLM_PROTOCOL` | tự suy ra | `openai` hoặc `anthropic`; chỉ đặt khi endpoint không chuẩn OpenAI |
| | `LLM_TEMPERATURE` | `0.0` | Giữ `0.0` để kết quả ổn định |
| | `METRIC_KNOWLEDGE_ENABLED` | `false` | Bật KPI recipes từ `src/knowledge/retail_metrics.yaml` |
| **AI Judge** | `JUDGE_LLM_PROVIDER`, `JUDGE_API_KEY`, `JUDGE_MODEL_NAME`, `JUDGE_API_BASE` | — | Chỉ cần khi chạy evaluation `--judge`; phải khác provider/model/key của agent, không có fallback |
| **Observability** | `LANGFUSE_TRACING_ENABLED`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | `false`, …, `https://cloud.langfuse.com` | Tracing Langfuse (restart backend sau khi đổi) — xem [docs/guide/langfuse.md](docs/guide/langfuse.md) |
| | `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `LANGCHAIN_TRACING_V2` | — | LangSmith (tự tắt nếu không có key hợp lệ) |
| **AI logging** | `AI_LOG_SERVER`, `AI_LOG_API_KEY`, `AI_LOG_DIR` | — | Hook ghi log sử dụng AI của khóa học |
| **Frontend** | `NEXT_PUBLIC_API_URL` (hoặc `NEXT_PUBLIC_API_BASE_URL`) | — | URL backend mà frontend gọi tới |
| | `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | — | Client ID cho Google OAuth |

> Thứ tự resolve LLM: `api_base` = `LLM_API_BASE` > `<PROVIDER>_API_BASE` > mặc định trong code; `api_key` = `LLM_API_KEY` > `<PROVIDER>_API_KEY` > `OPENAI_API_KEY`; `model` = `LLM_MODEL_<ROLE>` > `LLM_MODEL` > `MODEL_NAME` > mặc định theo provider.

---

## 7. Cơ sở dữ liệu & dữ liệu mẫu

Hệ thống tách **hai cơ sở dữ liệu**:

1. **Metadata Store (PostgreSQL):** người dùng, workspace/RBAC, schema kỹ thuật, tên/mô tả nghiệp vụ, canonical relationships, metrics + `metric_versions`, chat, dashboard, thông báo, cấu hình LLM theo tài khoản…
2. **Target DB (chỉ đọc):** CSDL kinh doanh của doanh nghiệp. Flow 1 chỉ đọc cấu trúc; Flow 2 chỉ chạy `SELECT` đã biên dịch.

Quản lý schema Metadata Store **chỉ qua Alembic**:

```bash
alembic upgrade head          # áp dụng migration
alembic heads                 # phải chỉ có 1 head
alembic revision --autogenerate -m "mô tả thay đổi"   # khi sửa models
```

> Không sửa migration đã apply, không drop/recreate database. Nếu merge nhánh sinh nhiều head, thêm migration merge mới.

### 7.1. Golden Retail Benchmark DB (36 bảng) — khuyên dùng

```bash
python scripts/setup_target_db.py
```

Script **xóa và tạo lại** database `golden_retail_db` trên PostgreSQL rồi nạp 36 bảng Enterprise Retail (`order_header`, `order_line`, `products`, `customers`, `stores`, `sales_channels`, `inventory`, `payments`…) từ `data/`.

Connection URL để kết nối trong UI/API:

- Từ máy host: `postgresql://dev:devpassword@localhost:5432/golden_retail_db`
- Từ trong Docker network: `postgresql://dev:devpassword@postgres:5432/golden_retail_db`

### 7.2. Sinh lại bộ dữ liệu

```bash
python scripts/seed_data_generator.py   # sinh DDL + dữ liệu giao dịch giả lập
python scripts/convert_to_postgres.py   # chuyển sang cú pháp PostgreSQL
python scripts/setup_target_db.py       # nạp vào database đích
```

### 7.3. Ecommerce Dashboard demo (42 bảng, có dữ liệu tài chính)

Dùng database riêng, không thay thế Golden Retail. Xem [docs/ECOMMERCE_DASHBOARD_SEED.md](docs/ECOMMERCE_DASHBOARD_SEED.md) và [docs/ECOMMERCE_SCALE_SEED.md](docs/ECOMMERCE_SCALE_SEED.md).

---

## 8. Danh mục API

Tất cả endpoint nằm dưới `/api/v1`, yêu cầu JWT `Authorization: Bearer <token>` (trừ auth, xem lời mời, `/health`). Swagger tại `/docs` là nguồn chính xác nhất.

### 8.1. Xác thực & Workspace

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| POST | `/auth/register` | Đăng ký, cấp access + refresh token |
| POST | `/auth/login` | Đăng nhập email/username + mật khẩu |
| POST | `/auth/google` | Đăng nhập/đăng ký bằng Google ID token |
| POST | `/auth/refresh` | Quay vòng refresh token |
| POST | `/auth/logout` | Thu hồi phiên |
| GET | `/auth/me` | Thông tin tài khoản hiện tại |
| POST / GET | `/org`, `/org/current`, `/org/my-orgs` | Tạo / xem workspace |
| GET / PUT / DELETE | `/org/members`, `/org/members/{user_id}` | Quản lý thành viên và vai trò |
| POST / GET / DELETE | `/org/invite`, `/org/invites`, `/org/invite/{invitation_id}` | Lời mời |
| GET / POST | `/invite/{token}`, `/invite/{token}/accept` | Xem / chấp nhận lời mời |
| GET / POST | `/notifications`, `/notifications/read`, `/notifications/{id}/read`, `/notifications/stream` | Thông báo (SSE) |

### 8.2. Nguồn dữ liệu & Flow 1

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| POST | `/semantic/import/preview` | Parse SQL Dump, trả schema kỹ thuật + diagnostics |
| POST / GET | `/semantic/import/saved` | Lưu / liệt kê schema từ SQL Dump |
| GET / DELETE | `/semantic/import/saved/{schema_id}` | Xem / xóa schema dump |
| POST | `/semantic/db/connect` | Kết nối Live DB, mã hóa URL, introspect, lưu metadata |
| GET / DELETE | `/semantic/db/saved`, `/semantic/db/saved/{db_id}` | Danh sách / chi tiết / xóa kết nối |
| POST | `/semantic/generate` | Chạy nền enrichment 2-pass (202 `{"db_id", "status": "started"}`) |
| GET | `/semantic/{db_id}/enrich/status` | Tiến độ enrichment |
| GET / POST | `/semantic/{db_id}/schema/review`, `/schema/approve` | Cổng HITL duyệt schema |
| PUT | `/semantic/{db_id}/schema/review/batch` | Duyệt/sửa hàng loạt |
| PUT | `/semantic/{db_id}/table/{table_name}`, `/column/{table_name}/{column_name}` | Sửa inline tên/mô tả |
| GET / PUT / POST | `/semantic/{db_id}/overview` (+ `/generate`, `/approve`, `/published`) | Mô tả tổng quan database |
| GET | `/semantic/{db_id}/catalog` | Canonical tables, columns, relationships |
| GET | `/semantic/{db_id}/export?format=json\|yaml` | Export Semantic Layer đã duyệt |

### 8.3. Relationship & giá trị cột

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| GET | `/semantic/{db_id}/relationships` | Danh sách relationship |
| POST | `.../relationships/suggest`, `/candidates`, `/preview` | AI gợi ý, tạo candidate, xem trước SQL an toàn |
| PATCH / POST | `.../relationships/candidates/{item_id}` (+ `/approve`, `/reject`) | Duyệt candidate |
| POST / GET | `.../relationships/{item_id}/edit`, `/disable`, `/impact` | Sửa, tắt, xem tác động lên metric |
| GET / POST / PUT | `/semantic/{db_id}/column-value-proposals` (+ `/scan`, `/review`, `/settings`) | Đề xuất giá trị phân loại (opt-in) |
| GET / PUT / POST | `/semantic/{db_id}/columns/{column_id}/value-mappings` (+ `/preview`, `/review`) | Ánh xạ giá trị nghiệp vụ |
| POST | `/semantic/{db_id}/value-mappings/preview` | Xem trước import mapping |

### 8.4. Business Metrics

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| GET | `/semantic/{db_id}/metrics`, `/metrics/comparison` | Danh sách / so sánh metric |
| POST | `/semantic/{db_id}/metrics/generate` | AI sinh đề xuất metric từ prompt |
| GET | `/semantic/{db_id}/metric-prompt-suggestions` | Gợi ý prompt dựa trên schema |
| POST / PUT / DELETE | `/semantic/{db_id}/metric`, `/metric/{metric_id}` | Tạo / sửa (copy-on-write) / xóa mềm |
| POST | `.../metric/{id}/approve`, `/reject`, `/restore`, `/rollback/{target_version}` | Vòng đời và rollback |
| GET | `.../metric/{id}/history`, `/pending-version`, `/dimensions`, `/filter-columns` | Lịch sử, phiên bản chờ duyệt, dimension/filter khả dụng |
| POST | `/semantic/{db_id}/metric-proposals/{proposal_id}/review` | Duyệt đề xuất AI |
| POST / GET | `/semantic/{db_id}/metric-requests` (+ `/{id}/approve`, `/reject`) | Member gửi yêu cầu metric |

### 8.5. Query (Flow 2 — chỉ Live DB)

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| POST | `/semantic/{db_id}/query/compile` | Biên dịch SQL + diagnostics, **không** chạm Target DB |
| POST | `/semantic/{db_id}/query` | Biên dịch và thực thi read-only (`LIMIT` ≤ 1000, timeout 15s) |

### 8.6. AI Studio & Chat

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| POST | `/semantic/{db_id}/chat` | Chat không streaming |
| POST | `/semantic/{db_id}/chat/stream` | SSE: `snapshot`, `progress`, `result`, `error`. Bắt buộc `client_message_id`; kết nối lại bằng cùng mã để tiếp tục tác vụ |
| POST | `/semantic/{db_id}/chat/cancel` | Hủy tác vụ đang chạy |
| GET / POST / PATCH / DELETE | `/semantic/{db_id}/chat/sessions[/{session_id}]` | Quản lý phiên chat |

Trace thực thi an toàn được lưu trong `metadata_json.execution_trace` của message. Tác vụ đang chạy chỉ khôi phục được trong cùng một backend worker (không qua restart).

### 8.7. Sync, Dashboard, Cài đặt

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| POST / GET | `/semantic/{db_id}/sync`, `/sync-status`, `/sync-logs` | Đồng bộ, kiểm tra drift, audit log |
| POST | `/admin/sync-all` | Đồng bộ toàn bộ nguồn dữ liệu |
| GET / PUT | `/semantic/{db_id}/dashboard` | Layout dashboard (optimistic concurrency) |
| GET / PUT / POST / DELETE | `/settings/llm`, `/settings/llm/models`, `/settings/llm/usage` | Cấu hình AI theo tài khoản |

---

## 9. Kịch bản sử dụng

Các ví dụ dưới đây dùng `curl`; thay `<ACCESS_TOKEN>` bằng token từ `/auth/login`. Chi tiết schema request/response: Swagger tại `/docs`.

### Kịch bản 1 — Kết nối Live DB và chạy Flow 1

```bash
# 1. Kết nối Target DB (URL được mã hóa Fernet trước khi lưu)
curl -X POST http://localhost:8000/api/v1/semantic/db/connect \
  -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{
    "display_name": "Golden Retail",
    "dialect": "auto",
    "conn_url": "postgresql://dev:devpassword@localhost:5432/golden_retail_db",
    "tls_mode": "prefer"
  }'

# 2. Chạy enrichment nền, chỉ điền ô còn trống → 202 {"db_id": 1, "status": "started"}
curl -X POST http://localhost:8000/api/v1/semantic/generate \
  -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{"db_id": 1}'

# 3. Theo dõi tiến độ
curl http://localhost:8000/api/v1/semantic/1/enrich/status \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

Sau đó duyệt schema và relationship trong giao diện (**Schema Review**), rồi duyệt metric trong **Metrics Catalog**. API cũng nhận `db_user` / `db_password` tách riêng khỏi URL.

### Kịch bản 2 — Biên dịch và thực thi truy vấn (Flow 2)

Request dùng **ID** của metric và cột (lấy từ `/metrics` và `/catalog`), không dùng tên bảng/cột thô:

```bash
# Chỉ biên dịch, xem SQL và diagnostics (không chạy trên Target DB)
curl -X POST http://localhost:8000/api/v1/semantic/1/query/compile \
  -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{
    "metric_ids": [1],
    "dimensions": [
      {"column_id": 42},
      {"column_id": 17, "time_grain": "month"}
    ],
    "filters": [{"column_id": 23, "operator": "eq", "value": "completed"}],
    "limit": 100
  }'
```

Phản hồi gồm `sql`, `parameters`, `metadata`, `diagnostics`. Gọi `/query` với cùng payload để thực thi; phản hồi gồm `sql`, `parameters`, `columns`, `rows`, `row_count`. `time_grain` nhận `day` / `week` / `month` / `quarter` / `year`; `order_by` nhận `metric_desc` / `dimension_desc`.

### Kịch bản 3 — AI Studio

```bash
curl -X POST http://localhost:8000/api/v1/semantic/1/chat \
  -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{"message": "Gợi ý các chỉ số đo lường hiệu quả bán hàng, ví dụ giá trị đơn hàng trung bình"}'
```

`orchestrator` phân loại ý định: trò chuyện chung, hỏi về dữ liệu (`data_assistant`), đề xuất metric (`metric_coordinator`) hoặc câu hỏi truy vấn (`semantic_parse` → chọn metric/dimension đã duyệt rồi qua compiler). Yêu cầu ngoài phạm vi được từ chối trực tiếp, không đi qua pipeline metric/query.

### Kịch bản 4 — Export Semantic Layer

```bash
curl "http://localhost:8000/api/v1/semantic/1/export?format=yaml" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" -o semantic_layer_export.yaml
```

Chỉ các thành phần đã duyệt được đưa vào file export (JSON hoặc YAML). Cấu trúc cụ thể do `src/services/export_service.py` quyết định.

---

## 10. Kiểm thử & đánh giá

### Backend

```bash
make check      # ruff check + ruff format + pytest — chạy trước khi kết thúc task
make test       # pytest tests/ -v
make lint       # ruff check src/ tests/ eval/
make format     # ruff format src/ tests/ eval/
```

- Test **mock LLM** và dùng **SQLite in-memory**; không gọi API thật.
- Test tích hợp compiler với PostgreSQL/MySQL cần fixture:

  ```bash
  docker compose -f infra/docker-compose.compiler-test.yml up -d
  pytest
  docker compose -f infra/docker-compose.compiler-test.yml down
  ```

- Thư mục test: `tests/test_agents`, `test_api`, `test_services`, `test_models`, `test_migrations` (kiểm tra đồ thị revision), `test_evaluation`, `test_integration`.

### Frontend

```bash
cd frontend
npm test            # Vitest (jsdom)
npm run test:e2e    # Playwright (frontend/e2e)
npm run lint        # ESLint
```

### Evaluation Framework

Đánh giá agent trên **Golden Dataset** (`eval/golden_dataset/ecommerce/`) qua 5 stage: Discovery → Enrichment → Metric generation → Query compilation → Guardrail; kết hợp evaluator xác định và AI Judge cô lập.

```bash
python -m eval.run_eval --source agent --engine hybrid --domain ecommerce --query-mode resolver --judge
```

Nguồn `agent` gọi LLM thật nên phát sinh chi phí. Hướng dẫn đầy đủ: [eval/README.md](eval/README.md).

### CI

`.github/workflows/`: `test.yml`, `build.yml`, `security.yml`, `gitops.yml`, `main.yml`.

---

## 11. An toàn & bảo mật

1. **Flow 1 chỉ đọc schema metadata** (`get_tables`, `get_columns`, `get_foreign_keys`, unique constraints). Không `SELECT` dữ liệu của khách hàng để introspect.
2. **Fernet Encryption:** mọi connection URL được mã hóa trước khi lưu, chỉ giải mã trong RAM khi cần và không bao giờ ghi log. API key LLM theo tài khoản cũng được mã hóa.
3. **Guardrail kép cho Flow 2:** kiểm AST bằng `sqlglot` (đúng một câu `SELECT`, chặn `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE`, `SELECT INTO`, CTE chứa DML); `LIMIT` mặc định 100 (tối đa 1000); `statement_timeout` 15 giây.
4. **Biên dịch xác định:** SQL do `SemanticQueryCompiler` sinh từ metric/relationship đã duyệt; không text-to-SQL tự do, không `eval()`/`exec()` với chuỗi SQL.
5. **Tài khoản DB chỉ đọc được kiểm tra tại database:** khi kết nối Live DB, hệ thống đọc catalog quyền (`pg_roles`, `has_table_privilege`, `SHOW GRANTS`) và **từ chối** tài khoản có quyền ghi, superuser hoặc chủ sở hữu bảng. Kết nối PostgreSQL còn bị ép `default_transaction_read_only = on`. Chỉ tắt bằng `TARGET_DB_REQUIRE_READ_ONLY=false` cho dev/test.
6. **RBAC theo workspace:** mọi truy cập tài nguyên đều được ràng buộc theo tổ chức.
7. **Rate limit** cho endpoint AI (tự bật ở production), JWT với refresh token xoay vòng.
8. **Observability an toàn:** trace chỉ lưu tóm tắt do server kiểm soát; artifact benchmark được redact trước khi lưu.

### Tạo tài khoản chỉ đọc cho Target DB

PostgreSQL (chạy bằng owner/superuser):

```sql
CREATE ROLE semantic_reader LOGIN PASSWORD '<mat_khau_manh>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT CONNECT ON DATABASE app_db TO semantic_reader;
GRANT USAGE ON SCHEMA public TO semantic_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO semantic_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO semantic_reader;  -- chạy bằng role sở hữu bảng
ALTER ROLE semantic_reader SET default_transaction_read_only = on;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;  -- PostgreSQL < 15
```

MySQL / MariaDB:

```sql
CREATE USER 'semantic_reader'@'%' IDENTIFIED BY '<mat_khau_manh>';
GRANT SELECT, SHOW VIEW ON app_db.* TO 'semantic_reader'@'%';
```

SQLite không có tài khoản: đặt quyền file ở mức hệ điều hành là chỉ đọc.

---

## 12. Quy ước phát triển

- **Async** toàn bộ (node, service, route), **type hint** đầy đủ, mỗi function ≤ 30 dòng, mỗi file ≤ 500 dòng, docstring tiếng Anh cho public function.
- **Ruff** cho lint/format; import order: stdlib → third-party → local.
- **LLM:** luôn dùng `get_llm()` từ [src/services/llm.py](src/services/llm.py); không khởi tạo `ChatOpenAI` trực tiếp; temperature `0.0`; prompt sinh `business_name` yêu cầu tiếng Việt.
- **Migration:** đổi DB schema → tạo migration Alembic mới; revision ID duy nhất; kiểm tra `alembic heads`.
- **Dependency:** thêm package phải cập nhật `requirements.txt`; `sqlglot` được phép dùng cho AST validation.
- **Không commit** `.env`, SQL dump/data dump chứa dữ liệu thật.
- Quy tắc đầy đủ cho người và AI assistant: [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md).

## 13. Tài liệu liên quan

| Tài liệu | Nội dung |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Kiến trúc chi tiết, luồng xử lý, mô hình dữ liệu, RBAC |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | Cây thư mục và vai trò từng file |
| [docs/PRD.md](docs/PRD.md) | Yêu cầu sản phẩm, User Stories |
| [docs/BRIEF.md](docs/BRIEF.md) | Tổng quan dự án |
| [docs/ACTION_PLAN.md](docs/ACTION_PLAN.md) | Kế hoạch và tiến độ |
| [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md) | Thiết kế CSDL |
| [docs/FEATURE_SPECIFICATIONS.md](docs/FEATURE_SPECIFICATIONS.md) | Đặc tả tính năng |
| [docs/UI_FLOW.md](docs/UI_FLOW.md) | Luồng màn hình |
| [docs/guide/](docs/guide/) | Hướng dẫn LangGraph, metric workflow, troubleshooting, Langfuse |
| [eval/README.md](eval/README.md) | Evaluation Framework |
| [AGENTS.md](AGENTS.md) | Quy tắc phát triển & AI |

## 14. Giấy phép

Repo hiện chưa có file `LICENSE`. Hãy bổ sung giấy phép phù hợp trước khi phát hành công khai.
