# `tests/test_api/` — Test endpoint HTTP

Dùng client FastAPI với DB SQLite in-memory và LLM mock.

| Nhóm | File | Kiểm tra |
| --- | --- | --- |
| Nguồn dữ liệu | `test_live_db_connect.py`, `test_import_dump_preview.py`, `test_imported_schemas.py`, `test_routes.py`, `test_canonical_routes.py` | Kết nối Live DB, preview/lưu SQL Dump, route nền, catalog canonical. |
| Enrichment & review | `test_enrich_status_routes.py`, `test_review_routes.py`, `test_review_batch_routes.py`, `test_review_allowed_values.py`, `test_database_overview.py` | Tiến độ enrichment, cổng duyệt schema, sửa hàng loạt, giá trị cho phép, tổng quan database. |
| Relationship & giá trị cột | `test_relationship_review_routes.py`, `test_categorical_proposals.py`, `test_value_mapping_import.py` | Review relationship, đề xuất giá trị cột, import value mapping. |
| Metric | `test_metric_generate_api.py`, `test_metric_review_api.py`, `test_metric_reject_route.py`, `test_metric_prompt_suggestions.py`, `test_rbac_export_metric_request.py` | Sinh/duyệt/từ chối metric, gợi ý prompt, RBAC cho export & metric request. |
| Query | `test_query_routes.py` | `query/compile` và `query` (guardrail, lỗi). |
| Chat | `test_chat_stream.py`, `test_chat_cancel_api.py`, `test_chat_resume_api.py`, `test_chat_session_lifecycle.py`, `test_chat_dedupe_api.py`, `test_chat_datalead_proposal.py`, `test_chat_semantic_query_api.py` | SSE, hủy, nối lại, vòng đời phiên, chống trùng metric, đề xuất của Data Lead, truy vấn ngôn ngữ tự nhiên. |
| Workspace & thông báo | `test_organization_routes.py`, `test_notifications_api.py`, `test_notification_stream_api.py` | Workspace/lời mời/RBAC, thông báo và SSE. |
| Khác | `test_dashboard_routes.py`, `test_sync_routes.py`, `test_llm_settings_routes.py` | Dashboard, sync, cài đặt AI. |
