# `docs/` — Tài liệu dự án

Tổng quan sản phẩm và cách chạy: [README gốc](../README.md). Kiến trúc: [ARCHITECTURE.md](../ARCHITECTURE.md). Bản đồ file: [PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md).

## Tài liệu sản phẩm

| File | Nội dung |
| --- | --- |
| `BRIEF.md` | Tóm tắt dự án: bối cảnh, mục tiêu, phạm vi. |
| `PRD.md` | Product Requirements Document: tính năng, User Stories, Acceptance Criteria. |
| `FEATURE_SPECIFICATIONS.md` | Đặc tả chi tiết từng tính năng. |
| `UI_FLOW.md` | Luồng màn hình và wireframe (v2.0). |
| `DATABASE_DESIGN.md` | Thiết kế CSDL Metadata Store và xác thực (v2.1), ERD. |
| `ACTION_PLAN.md` | Kế hoạch hành động, task list, tiến độ. |

## Dữ liệu thử nghiệm & kiểm thử thủ công

| File | Nội dung |
| --- | --- |
| `ECOMMERCE_DASHBOARD_SEED.md` | Seed ecommerce 42 bảng cho demo dashboard (file `scripts/ecommerce_dashboard_demo_pg.sql`), các metric nên duyệt. |
| `ECOMMERCE_SCALE_SEED.md` | Dataset thử nghiệm theo số đơn (quy mô lớn). |
| `ISSUE51_MANUAL_TEST.md` | Kiểm thử thủ công trên dataset 100.000 đơn. |
| `testing/metric-catalog-cases.md` | Bộ metric dùng tạo lại catalog và kiểm tra sinh nhiều metric. |

## Nghiên cứu & thiết kế nội bộ

| Thư mục | Nội dung |
| --- | --- |
| `research/` | `issue-22-column-values-ux.md` — nghiên cứu UX cho giá trị nghiệp vụ trong bảng và cột. |
| [`guide/`](guide/README.md) | Bộ hướng dẫn: LangGraph, code style, metric workflow, Langfuse, troubleshooting… |
| [`superpowers/`](superpowers/README.md) | Spec và kế hoạch triển khai từng tính năng (do công cụ AI hỗ trợ sinh ra). |

> Một số tài liệu sản phẩm (PRD, UI_FLOW, DATABASE_DESIGN) viết ở giai đoạn đầu và có thể chưa phản ánh hết thay đổi gần đây; khi mâu thuẫn, ưu tiên code, [README](../README.md) và [ARCHITECTURE.md](../ARCHITECTURE.md).
