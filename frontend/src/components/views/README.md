# `components/views/` — Sáu màn hình chính

Mỗi view là một container: tự gọi API (qua `lib/api.ts`), giữ state và ghép các component miền. `WorkspaceApp` chọn view theo `ViewId`.

| File | `ViewId` | Chức năng chi tiết |
| --- | --- | --- |
| `AIStudioView.tsx` | `ai-studio` | Màn hình chat với trợ lý AI: danh sách phiên, `StudioChatStream` hiển thị hội thoại streaming, gợi ý prompt, đề xuất metric (`SuggestionCard`), kết quả truy vấn, cảnh báo trùng metric; nhớ tác vụ đang chạy để nối lại. |
| `SchemaReviewView.tsx` | `schema` | Cổng HITL cho schema: cây bảng/cột, sửa tên & mô tả nghiệp vụ, duyệt từng mục hoặc hàng loạt, tổng quan database, panel relationship + sơ đồ, đề xuất giá trị cột, banner tiến độ enrichment, nút phê duyệt schema. |
| `MetricsCatalogView.tsx` | `catalog` | Danh mục metric: nhóm theo loại, lọc theo trạng thái, thẻ metric, tạo/sửa metric, hàng chờ duyệt cho Data Lead, metric request cho Member, lịch sử/rollback. |
| `MetricExplorerView.tsx` | `explorer` | Trình dựng truy vấn trực quan (file lớn nhất, ~1650 dòng): chọn metric, dimension (`DimensionPicker`), filter, time grain, sắp xếp, giới hạn; xem SQL biên dịch (`query/compile`), chạy `query`, bảng kết quả và biểu đồ. |
| `MetricsDashboardView.tsx` | `dashboard` | Dashboard singleton của workspace: lưới widget, thêm/sửa/xóa widget, lưu layout với phát hiện xung đột phiên bản. |
| `ExportPlaygroundView.tsx` | `export` | Xem trước và tải Semantic Layer đã duyệt dạng JSON hoặc YAML. |
| `DimensionPicker.tsx` | — | Bộ chọn dimension dùng trong Explorer: nhóm theo bậc (cùng bảng / qua join), nhận diện cột thời gian để chọn grain. |

> `MetricExplorerView.tsx` và `AIStudioView.tsx` vượt quy ước ~500 dòng; khi mở rộng nên tách bớt component con.
