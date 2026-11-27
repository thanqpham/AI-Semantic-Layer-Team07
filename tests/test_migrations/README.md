# `tests/test_migrations/` — Test migration Alembic

| File | Kiểm tra |
| --- | --- |
| `test_revision_graph.py` | **Đồ thị revision:** revision ID duy nhất, chỉ một head, không vòng lặp — bắt buộc chạy sau mỗi migration mới. |
| `test_schema_qualified_tables.py` | Migration tên bảng kèm schema. |
| `test_workspace_admin_role.py`, `test_drop_user_role.py` | Vai trò workspace/tài khoản. |
| `test_metric_status.py`, `test_metric_rejection_reason.py`, `test_metric_proposals.py` | Trạng thái, lý do từ chối, bảng proposals của metric. |
| `test_notifications_columns.py` | Cột `db_id`, `handled_at` của `notifications`. |
| `test_relationship_review.py` | `relationship_candidates` và metadata review. |
| `test_dashboard_layouts.py` | Bảng `dashboard_layouts`. |
| `test_llm_settings.py` | Bảng `user_llm_settings`. |
