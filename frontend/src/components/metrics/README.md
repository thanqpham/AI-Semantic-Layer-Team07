# `components/metrics/` — Catalog metric

| File | Chức năng chi tiết |
| --- | --- |
| `MetricCard.tsx` | Thẻ một metric: tên nghiệp vụ, công thức dễ đọc, filter, trạng thái (`approved` / `pending_approval` / `needs_review` / `unverified` / `rejected`), phiên bản, hành động theo quyền (duyệt, sửa, lịch sử, xóa). |
| `CatalogGroupedList.tsx` | Danh sách metric được nhóm theo loại. |
| `catalogGrouping.ts` | `metricKind`, `metricGroup`, `groupMetrics`, `METRIC_KIND_LABELS`: quy tắc phân loại/nhóm metric. |
| `CatalogModeBar.tsx` | Thanh chuyển tab (`CatalogTab`): `approved`, `pending`, `submitted`, `rejected`, `trash`, `audit`. |
| `MetricReviewPanel.tsx` | Panel duyệt cho Data Lead: xem phiên bản chờ duyệt, phê duyệt hoặc từ chối. |
| `MetricRejectDialog.tsx` | Hộp thoại từ chối, bắt buộc nhập lý do (lưu `rejection_reason`). |
| `MetricAuditPanel.tsx` | Dòng thời gian kiểm toán: ai đổi gì, khi nào, lý do duyệt/từ chối. |
| `MetricHistoryDialog.tsx` | Lịch sử các phiên bản của metric; chọn hai phiên bản để so sánh, khởi chạy rollback. |
| `MetricVersionDiff.tsx` | Hiển thị diff từng dòng giữa hai phiên bản (dựa `lib/metric-version-diff.ts`). |
| `MetricRollbackConfirmDialog.tsx` | Xác nhận hoàn nguyên về một phiên bản cũ (tạo phiên bản mới, không xóa lịch sử). |
