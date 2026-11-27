# `frontend/src/test/` — Hỗ trợ kiểm thử

| File | Chức năng chi tiết |
| --- | --- |
| `setup.ts` | Setup Vitest (được trỏ tới bởi `vitest.config.mts`): nạp matcher `@testing-library/jest-dom/vitest` và dựng `ResizeObserver` giả vì jsdom không có (cần cho React Flow, Recharts). |
| `chatTraceFixture.ts` | Dữ liệu mẫu `ExecutionTrace` cho các test về luồng agent / thinking của AI Studio. |
| `metricReviewFixture.ts` | Dữ liệu mẫu metric ở các trạng thái review/phiên bản cho test Metrics Catalog. |
