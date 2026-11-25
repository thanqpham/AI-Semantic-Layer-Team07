# `components/workspace/` — Khung ứng dụng

| File | Chức năng chi tiết |
| --- | --- |
| `WorkspaceApp.tsx` | Component gốc của `/workspace`: dựng sidebar + header + **view đang chọn** (`ai-studio` / `schema` / `catalog` / `explorer` / `dashboard` / `export`), mở các modal (kết nối DB, cài đặt, quản lý workspace), tải danh sách database. |
| `WorkspaceSidebar.tsx` | Thanh bên: chọn workspace, danh sách database/nguồn dữ liệu (kèm trạng thái kết nối), chuyển view, lịch sử chat (`ChatHistorySection`), nút kết nối DB, cài đặt, đổi theme/ngôn ngữ, đăng xuất. Ẩn/hiện mục theo quyền RBAC. |
| `ViewHeader.tsx` | Header chung cho mỗi view: tiêu đề, mô tả, vùng hành động. |
| `NotificationCenter.tsx` | Chuông thông báo: nhận thông báo realtime qua SSE (`lib/notificationStream`), đánh dấu đã đọc, điều hướng tới mục cần duyệt. |
| `SchemaDriftBanner.tsx` | Cảnh báo khi schema nguồn đã đổi (`sync-status`): hiển thị khác biệt, nút đồng bộ ngay và xem nhật ký. |
| `ChatHistorySection.tsx` | Danh sách phiên chat theo database: tạo, mở, đổi tên, xóa phiên. |
| `shared.tsx` | Kiểu và helper dùng chung: `ViewId`, `DbEngine`, `WorkspaceDatabase`, `engineLabels`, `EngineIcon`, `statusMeta`, `StatusPill`, `SectionLabel`. |
| `Settings01Icon.tsx`, `MoonAltToSunnyOutlineLoopTransitionIcon.tsx` | Icon cài đặt và icon chuyển sáng/tối có hoạt ảnh. |
