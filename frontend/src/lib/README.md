# `frontend/src/lib/` — Client API và helper miền

Logic không phụ thuộc giao diện: gọi backend, xử lý SSE, định dạng/dựng dữ liệu cho các view. Mỗi file có `*.test.ts` cạnh bên.

## API và streaming

| File | Chức năng chi tiết |
| --- | --- |
| `api.ts` | **Client REST trung tâm** (hơn 2000 dòng). Kiểu dữ liệu (`SemanticTable`, `SemanticColumn`, metric, trạng thái…) và các hàm gọi mọi endpoint `/api/v1`: auth, workspace, kết nối DB, enrichment, schema review, metric, query/compile, chat, export, sync, cài đặt AI. Tự gắn `Authorization`, tự làm mới token khi `401`. URL gốc lấy từ `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_API_BASE_URL`. |
| `chatStream.ts` | `sendChatStream`: gửi chat qua `/chat/stream` và đọc SSE (`snapshot`, `progress`, `result`, `error`); `ChatStreamError`. |
| `notificationStream.ts` | `streamNotifications`, `createSseDataParser`: đọc SSE `/notifications/stream` bằng `fetch` (kèm header token). |
| `pendingChat.ts` | `storePendingChat` / `readPendingChat`: nhớ tác vụ chat đang chạy (theo `client_message_id`) để **kết nối lại** sau khi tải lại trang. |
| `dashboardApi.ts` | `loadDashboardApi`, `saveDashboardApi`, `DashboardVersionConflictError` (xung đột phiên bản lạc quan). |
| `relationshipReviewApi.ts` | Kiểu và hàm gọi API review relationship (`RelationshipItem`, `RelationshipDraft`, `ColumnPair`…). |
| `jwt.ts` | Lưu/đọc/xóa access & refresh token (cookie `js-cookie`, dự phòng localStorage), giải mã payload JWT. |

## Helper nghiệp vụ

| File | Chức năng chi tiết |
| --- | --- |
| `metrics.ts` | Định dạng công thức/aggregate/filter metric dễ đọc (`formatMetricFormula`, `formatMetricFilters`), cột được dùng (`getMetricUsedColumns`), nhãn trạng thái (`statusLabel`), tên metric. |
| `metric-version-diff.ts` | `buildMetricVersionDiff`: dựng diff từng dòng giữa hai phiên bản metric (cho dialog lịch sử). |
| `dimensions.ts` | Phân loại cột: thời gian, khóa kỹ thuật, số đo, nhạy cảm, dimension nghiệp vụ (`getDimensionCategory`, `isBusinessDimension`…). |
| `dimensionGroups.ts` | `groupDimensions`, `joinPathLabel`: nhóm dimension theo bậc (cùng bảng, qua join…) cho bộ chọn dimension. |
| `dashboard.ts` | Mô hình dashboard: `DashboardWidgetConfig`, `DashboardLayout`, giới hạn (`DASHBOARD_MAX_WIDGETS`, `DASHBOARD_GRID_COLUMNS`), chuẩn hóa/validate layout. |
| `relationshipGraph.ts` | Dựng nút/cạnh cho sơ đồ quan hệ: kiểu cạnh theo trạng thái (`STATUS_STYLE`), cardinality, giới hạn cột hiển thị, bố cục dagre. |
| `agentFlowGraph.ts` | Dựng đồ thị luồng agent (`KNOWN_AGENTS`, `AgentFlowNode/Edge`, trạng thái từng agent) từ trace. |
| `chatTrace.ts` | `ExecutionTrace`, `appendTraceEvent`, `traceSteps`, `traceAgents`: xử lý sự kiện tiến độ thành các bước hiển thị trong "Thinking". |
| `utils.ts` | `cn` (gộp class Tailwind), `formatRelativeTime`. |
