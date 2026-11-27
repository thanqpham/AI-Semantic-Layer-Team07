# `alembic/versions/` — Lịch sử migration

Mỗi file là một revision Alembic của **Metadata Store**. Danh sách dưới đây theo thứ tự chuỗi `down_revision` (cũ → mới). Các file "merge" chỉ hợp nhất nhiều head, **không đổi schema**.

> **Quy tắc** (AGENTS.md): mọi thay đổi ORM → migration mới (`alembic revision --autogenerate -m "..."`). Không sửa migration đã apply, không đổi revision ID / `down_revision`, không drop/recreate DB. Revision ID phải duy nhất; kiểm tra `alembic heads` và `tests/test_migrations/test_revision_graph.py`.

## Danh sách

| # | File | Nội dung |
| --- | --- | --- |
| 1 | `a22b27560724_initial_schema.py` | Schema khởi tạo (người dùng, phiên, bảng nền). |
| 2 | `d87dc6a5afe1_add_imported_schemas.py` | Bảng `imported_schemas` (schema từ SQL Dump). |
| 3 | `e7f123456789_add_live_target_databases.py` | Bảng `live_target_databases` (kết nối Live DB, URL mã hóa). |
| 4 | `b3c4d5e6f789_add_canonical_semantic_layer_tables.py` | Các bảng semantic canonical: databases, tables, columns, relationships, metrics. |
| 5 | `f1a2b3c4d5e6_add_semantic_db_id_to_imported_schemas.py` | Liên kết `semantic_db_id` cho `imported_schemas` và `live_target_databases`. |
| 6 | `a8c9d0e1f234_add_metric_definition_json.py` | Cột `metric_definition_json` (MetricDefinition v2). |
| 7 | `ce2735d8b117_canonical_relationship_metadata_v2.py` | Metadata relationship canonical phiên bản 2. |
| 8 | `d9e0f1a2b3c4_add_row_count_approx_to_semantic_tables.py` | Thêm bảng lõi và `row_count_approx` cho `semantic_tables`. |
| 9 | `g2h3i4j5k6l7_add_chat_sessions_and_messages.py` | `chat_sessions`, `chat_messages`. |
| 10 | `h3i4j5k6l7m8_merge_chat_migration_heads.py` | *Merge* nhánh schema semantic với nhánh chat. |
| 11 | `i4j5k6l7m8n9_add_client_message_id_to_chat_messages.py` | `client_message_id` để chat idempotent / nối lại. |
| 12 | `j5k6l7m8n9o0_add_workspace_rbac.py` | Workspace: organizations, memberships, invitations, phạm vi tài nguyên. |
| 13 | `k6l7m8n9o0_enforce_workspace_resource_ownership.py` | Bắt buộc quyền sở hữu workspace cho semantic databases. |
| 14 | `l7m8n9o0p1q2_retire_workspace_admin_role.py` | Bỏ vai trò `admin` cũ, chuyển sang `data_lead`. |
| 15 | `m8n9o0p1q2r_add_metric_requests_notifications.py` | `metric_requests` và `notifications`. |
| 16 | `m8n9o0p1q2r3_constrain_metric_status.py` | CHECK constraint trạng thái metric. |
| 17 | `m9n0p1q2r3s4_add_workspace_admin_role.py` | Thêm lại vai trò `admin` workspace (có backfill dữ liệu cũ). |
| 18 | `n0p1q2r3s4t5_merge_workspace_admin_and_metric_status.py` | *Merge* hai nhánh trên. |
| 19 | `n9o0p1q2r3s_backfill_foreign_key_metadata.py` | Backfill metadata FK đã lưu từ canonical relationships. |
| 20 | `o1p2q3r4s5t6_drop_user_account_role.py` | Bỏ cột vai trò cấp tài khoản (đã chuyển sang vai trò theo workspace). |
| 21 | `p2q3r4s5t6u_merge_foreign_key_and_workspace_heads.py` | *Merge* nhánh FK và workspace. |
| 22 | `p2q3r4s5t6u7_add_hitl_review_and_metric_versioning.py` | `review_status` cho bảng/cột và metadata phiên bản metric append-only (`metric_versions`). |
| 23 | `95ff234b973e_add_dashboard_layouts.py` | Bảng singleton `dashboard_layouts`. |
| 24 | `fb92d622f1e0_merge_dashboard_and_hitl_review_heads.py` | *Merge* dashboard và HITL review. |
| 25 | `q3r4s5t6u7v8_merge_dashboard_hitl_and_foreign_key_heads.py` | *Merge* dashboard/HITL với FK. |
| 26 | `r4s5t6u7v8w9_add_schema_fingerprint_and_sync_logs.py` | `schema_fingerprint` và `schema_sync_logs` (auto-sync + self-healing). |
| 27 | `s5t6u7v8w9x0_merge_heads.py` | *Merge* dashboard layouts và sync logs. |
| 28 | `u7v8w9x0y1z2_add_is_deleted_to_semantic_metrics.py` | Cột `is_deleted` (xóa mềm metric). |
| 29 | `v8w9x0y1z2a3_merge_is_deleted_and_sync_heads.py` | *Merge* thành một head tuyến tính. |
| 30 | `0f940d398032_merge_all_heads.py` | *Merge* tất cả head còn lại. |
| 31 | `w9x0y1z2a3_merge_branch_and_main_heads.py` | *Merge* nhánh feature và `main`. |
| 32 | `bfc12f0bb328_add_user_llm_settings.py` | `user_llm_settings` (cấu hình AI theo tài khoản, key mã hóa). |
| 33 | `c02b7c2cd880_add_metric_proposals.py` | `metric_proposals` (bằng chứng review metric AI). |
| 34 | `20261027_relationship_review_persistence.py` | `relationship_candidates` cô lập + metadata review cho canonical relationships. |
| 35 | `20261027_relationship_validation_backfill.py` | Chuẩn hóa dữ liệu validation relationship cũ. |
| 36 | `f9ead304ba7e_schema_qualified_tables.py` | Tên bảng có kèm schema. |
| 37 | `625f9b05ce74_add_column_value_proposals.py` | `column_value_proposals`. |
| 38 | `9e19cc667379_categorical_values_completeness.py` | Đánh dấu giá trị cho phép có phải miền khai báo đầy đủ không. |
| 39 | `bd2ef25c54e8_opt_in_categorical_discovery.py` | Khám phá giá trị phân loại phải bật rõ ràng theo từng kết nối. |
| 40 | `v22allowedpairs_add_column_value_mappings.py` | Nhãn nghiệp vụ đã duyệt cho giá trị cột (value mappings). |
| 41 | `08b6d0db1fc1_add_notifications_db_id_and_handled_at.py` | `db_id` và `handled_at` cho `notifications`. |
| 42 | `a7c3e9f1b2d4_add_metric_rejection_reason_and_status.py` | `rejection_reason` và trạng thái `rejected` cho metric. |
| 43 | `62260812bd87_merge_notifications_and_value_mappings_.py` | *Merge* notifications và value mappings. |
| 44 | `c94fcf35e320_add_database_overview.py` | Mô tả tổng quan database (`database_overview`). |
| 45 | `082d74e1e5b6_add_tls_columns_to_live_target_databases.py` | Cột TLS cho `live_target_databases` (**head hiện tại**). |

> Thứ tự gần đúng theo thời gian; thứ tự chính xác là đồ thị `down_revision` (xem `alembic history`).

## Lệnh thường dùng

```bash
alembic upgrade head       # áp dụng tất cả
alembic heads              # phải chỉ có 1 head
alembic history            # xem đồ thị
alembic revision --autogenerate -m "mô tả"   # tạo migration mới (hoặc lệnh /new-migration)
```

Cấu hình: [`../env.py`](../env.py) (AsyncEngine, nạp `Base.metadata`), [`../script.py.mako`](../script.py.mako) (template), [`../../alembic.ini`](../../alembic.ini).
