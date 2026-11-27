# `src/api/` — Routers HTTP (FastAPI)

Tầng giao tiếp HTTP. Mỗi file là một `APIRouter`; tất cả được gắn dưới prefix `/api/v1` trong [`src/main.py`](../main.py). Router chỉ làm bốn việc: **xác thực** (JWT), **kiểm tra quyền/workspace**, **validate request** (Pydantic từ `src/models/`), rồi **gọi service**. Logic nghiệp vụ nằm ở [`src/services/`](../services/README.md).

Các router `routes`, `review`, `overview`, `sync` có dependency `use_account_llm` để mọi lời gọi LLM trong request dùng cấu hình AI của tài khoản đang đăng nhập.

| File | Prefix / phạm vi | Chức năng chi tiết |
| --- | --- | --- |
| `auth.py` | `/auth` | `register`, `login`, `google` (Google OAuth ID token), `refresh` (**xoay vòng refresh token**), `logout` (thu hồi phiên), `me`. Băm mật khẩu bcrypt, ký/giải mã JWT, dependency `get_current_user` dùng chung cho mọi router khác. |
| `organization_routes.py` | `/org`, `/invite` | Tạo workspace, liệt kê workspace của tôi (`my-orgs`, `current`), thành viên (xem/đổi vai trò/xóa), lời mời (tạo/liệt kê/hủy/xem trước/chấp nhận). |
| `routes.py` | `/semantic/...`, `/status` | Router lớn nhất, gồm: kết nối Live DB (`db/connect`, `db/saved`), import SQL Dump (`import/preview`, `import/saved`), `generate` (enrichment nền, trả 202) và `enrich/status`, `catalog`, sửa inline bảng/cột, CRUD metric + `metrics/generate` + `approve/restore/rollback/history/dimensions/filter-columns`, `metric-requests`, `metric-proposals/{id}/review`, `notifications` (liệt kê, đánh dấu đã đọc, **SSE `/notifications/stream`**), `query/compile` và `query` (Flow 2), `chat`, `chat/stream` (SSE), `chat/cancel`, `chat/sessions`, `export`. |
| `review_routes.py` | `/semantic/{db_id}/schema/*`, `/metric/{id}/*` | Cổng HITL: `schema/review` (lấy dữ liệu duyệt), `schema/review/batch` (sửa hàng loạt), `schema/approve`; quyết định phiên bản metric: `metric/{id}/pending-version` và `metric/{id}/reject`. |
| `relationship_review_routes.py` | `/semantic/{db_id}/relationships` | Danh sách relationship; `suggest` (AI gợi ý), `candidates` (tạo/sửa/duyệt/từ chối), `preview` (SQL xem trước an toàn), `{id}/edit`, `{id}/disable`, `{id}/impact` (tác động lên metric đã publish). Quyết định có ranh giới nguyên tử. |
| `categorical_routes.py` | `/semantic/{db_id}/column-value-proposals`, `/columns/{id}/value-mappings` | Quét và duyệt đề xuất giá trị cột phân loại (opt-in, quyền riêng), `settings`, ánh xạ giá trị nghiệp vụ (xem/lưu/preview/review), `value-mappings/preview` cho import hàng loạt. |
| `overview_routes.py` | `/semantic/{db_id}/overview` | Xem/sửa mô tả tổng quan database; `generate` (AI), `approve`, `published`. |
| `dashboard_routes.py` | `/semantic/{db_id}/dashboard` | `GET`/`PUT` layout dashboard singleton theo workspace (phiên bản lạc quan). |
| `sync_routes.py` | `/semantic/{db_id}/sync*`, `/admin/sync-all` | `sync` (kích hoạt đồng bộ + self-healing), `sync-status` (kiểm tra drift nhanh bằng fingerprint), `sync-logs` (audit), `admin/sync-all`. |
| `llm_settings_routes.py` | `/settings/llm` | Đọc/lưu cấu hình AI theo tài khoản, `models` (tải danh sách model từ provider), `usage` (xóa dữ liệu usage); chứa dependency `use_account_llm`. Lỗi validation được che key (xem handler trong `main.py`). |

## Ghi chú

- `routes.py` rất lớn (hơn 3000 dòng) — vượt quy ước 500 dòng/file; khi thêm endpoint mới nên tạo router riêng thay vì thêm vào đây.
- Mọi endpoint (trừ auth, xem lời mời, `/health`) yêu cầu `Authorization: Bearer <token>`.
- Danh sách endpoint đầy đủ: Swagger tại `/docs` hoặc mục 8 của [README gốc](../../README.md).
