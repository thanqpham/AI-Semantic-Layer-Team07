# `frontend/src/components/` — UI theo miền

| Thư mục | Vai trò |
| --- | --- |
| [`workspace/`](workspace/README.md) | **Khung ứng dụng:** `WorkspaceApp`, sidebar, thông báo, banner drift; định nghĩa `ViewId`. |
| [`views/`](views/README.md) | **Sáu màn hình chính** (AI Studio, Schema Review, Metrics Catalog, Metric Explorer, Dashboard, Export). |
| [`studio/`](studio/README.md) | Thành phần của AI Studio: chat streaming, "thinking", luồng agent, thẻ đề xuất metric. |
| [`schema-review/`](schema-review/README.md) | Duyệt schema, relationship, giá trị cột, tổng quan database. |
| [`schema-review/diagram/`](schema-review/diagram/README.md) | Sơ đồ quan hệ (React Flow + dagre). |
| [`metrics/`](metrics/README.md) | Catalog metric: thẻ, review, lịch sử, diff, rollback. |
| [`dashboard/`](dashboard/README.md) | Dashboard kéo-thả và cấu hình widget. |
| [`modals/`](modals/README.md) | Hộp thoại: kết nối DB, cài đặt, workspace, nhật ký sync, metric. |
| [`auth/`](auth/README.md) | Form đăng nhập/đăng ký. |
| [`landing/`](landing/README.md) | Các section của landing page. |
| [`ui/`](ui/README.md) | Primitive UI và icon dùng chung. |

Phân tầng: `views/` (container, gọi API qua `lib/`) → các component miền (`studio`, `schema-review`, `metrics`, `dashboard`, `modals`) → `ui/` (primitive).
