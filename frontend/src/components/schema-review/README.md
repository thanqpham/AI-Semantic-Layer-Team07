# `components/schema-review/` — Duyệt schema (HITL)

Các thành phần của `SchemaReviewView`: biến đề xuất AI thành metadata đã duyệt.

## Bảng & cột

| File | Chức năng chi tiết |
| --- | --- |
| `TableTree.tsx` | Cây database → bảng; hiển thị số mục đang chờ duyệt (`pendingCount`), chọn bảng. |
| `TableDetail.tsx` | Chi tiết một bảng: sửa tên/mô tả nghiệp vụ của bảng và từng cột (nháp `Draft`/`DraftMap`), huy hiệu trạng thái review (`ReviewBadge`), cột khóa/kiểu dữ liệu. |
| `ColumnValueProposals.tsx` | `ColumnValueEditor`: duyệt/sửa đề xuất giá trị của cột phân loại và ánh xạ giá trị nghiệp vụ. |
| `ValueMappingBatchImport.tsx` | Nhập hàng loạt ánh xạ giá trị từ file, xem trước trước khi lưu. |
| `DatabaseOverview.tsx` | Mô tả tổng quan database (xem/sửa/sinh bằng AI/duyệt) và thống kê (`OverviewStats`). |
| `EnrichmentProgressBanner.tsx` | Banner tiến độ khi enrichment đang chạy nền (poll `enrich/status`). |

## Relationship

| File | Chức năng chi tiết |
| --- | --- |
| `RelationshipsPanel.tsx` | Panel chính (~585 dòng): danh sách + sơ đồ, gợi ý bằng AI, tạo/sửa/tắt/duyệt relationship, xem tác động lên metric, lọc theo trạng thái. |
| `RelationshipToolbar.tsx` | Thanh công cụ: chuyển chế độ xem (`RelationshipView`: danh sách / sơ đồ), lọc, gợi ý AI. |
| `RelationshipCardList.tsx` | Danh sách thẻ relationship. |
| `RelationshipDetail.tsx` | Chi tiết một relationship và hành động. |
| `RelationshipMeta.tsx` | Metadata: cardinality, nguồn gốc (FK vật lý / AI / người dùng), cảnh báo. |
| `RelationshipStatusBadge.tsx` | Huy hiệu trạng thái (`approved` / `disabled` / `needs_review`…) theo `statusTone`. |
| `ColumnPairEditor.tsx` | Trình sửa cặp cột của một relationship (hỗ trợ khóa nhiều cột). |

Sơ đồ quan hệ: xem [`diagram/`](diagram/README.md).
