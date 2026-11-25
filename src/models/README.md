# `src/models/` — ORM và contract dữ liệu

Hai loại thứ nằm ở đây:

1. **ORM SQLAlchemy 2.0** (`db*.py`, `llm_settings.py`) — ánh xạ bảng của Metadata Store (PostgreSQL), 24 bảng.
2. **Contract Pydantic** — kiểu dữ liệu dùng chung giữa API, service, agent và compiler (request/response, schema thô, định nghĩa metric…).

Tầng này **không truy vấn DB**; việc đó thuộc [`src/services/`](../services/README.md). Mọi thay đổi ORM phải đi kèm migration Alembic mới.

## ORM (Metadata Store)

| File | Bảng / lớp | Chức năng |
| --- | --- | --- |
| `db_base.py` | `Base`, `utc_now()` | Declarative base và helper cột dùng chung cho mọi model. |
| `db.py` | `users`, `user_sessions`, `organizations`, `organization_members`, `organization_invitations`, `organization_audit_logs`, `imported_schemas`, `live_target_databases`, `semantic_databases`, `schema_sync_logs`, `semantic_tables`, `semantic_columns`, `semantic_metrics`, `canonical_relationships`, `metric_versions`, `dashboard_layouts`, `metric_requests`, `notifications` | Model trung tâm: định danh, workspace/RBAC (ràng buộc CHECK cho `role` và `status`), nguồn dữ liệu (URL đã mã hóa, TLS), toàn bộ semantic metadata, vòng đời metric và phiên bản, thông báo, dashboard, nhật ký sync. |
| `db_chat.py` | `chat_sessions`, `chat_messages` | Phiên chat và tin nhắn (có `client_message_id` để idempotent, `metadata_json` chứa trace thực thi). |
| `db_metric_proposals.py` | `metric_proposals` | Bằng chứng review bền vững của metric do AI sinh. |
| `db_relationships.py` | `relationship_candidates` | Relationship được đề xuất, **tách khỏi** đồ thị canonical đang phục vụ truy vấn. |
| `db_categorical_proposals.py` | `column_value_proposals` | Đề xuất giá trị cột (khai báo hoặc quan sát) chờ duyệt. |
| `llm_settings.py` | `user_llm_settings` + contract | Cấu hình AI theo tài khoản (key mã hóa) và các model request/response công khai (`LLMSettingsRequest`, `LLMSettingsResponse`, `LLMProviderResponse`, `LLMUsageSummaryResponse`). |
| `review_mixin.py` | `ReviewStateMixin`, `REVIEW_STATUS_CHECK` | Cột `review_status` (`pending_review` / `approved`) dùng cho `semantic_tables` và `semantic_columns` để tên AI đề xuất không bao giờ được publish trực tiếp. |

## Contract Pydantic

| File | Chức năng |
| --- | --- |
| `schemas.py` | Request/response cho hầu hết API: đăng ký/đăng nhập/token, workspace, kết nối Live DB, metric, query (`SemanticQueryRequest`, `DimensionSelection`, `SemanticQueryFilter`, phản hồi query/compile), chat (`ChatRequest`), dashboard, … (hơn 1000 dòng). |
| `raw_schema.py` | Schema thô dùng giữa adapter trích xuất và AI node: `RawSchema`, `TableMetadata`, `ColumnMetadata`, `ForeignKeyMetadata`, `LiveSchemaRequest`, `DumpSchemaRequest`, `SchemaExtractionResult`. |
| `schema_metadata.py` | Contract schema **canonical** chung cho mọi nguồn: `RawSchemaMetadata`, `Identifier` / `QualifiedIdentifier` (chuẩn hóa tên), `SchemaDialect`, `DiagnosticCode`, `ParseCompleteness`. |
| `metric_definition.py` | `MetricDefinition` v2 — hợp đồng giữa sinh, lưu và biên dịch: `MetricSpec`, `MetricAggregate`, `MetricRatio`, `MetricFormula`, `MetricFilter`, `MetricGrain`, `MetricQueryPlan` (và các `MetricPlan*`), `MetricExpressionNode`, `MetricDiagnostic`. |
| `metric_agent_output.py` | Bản nháp metric phía provider LLM (`AgentMetricSpec`, `AgentAggregate`, `AgentRatio`, `AgentFormula`, `AgentFilter`, `AgentCandidate`) — **không chứa** metadata do backend sở hữu. |
| `metric_review.py` | Contract đề xuất metric chưa lưu đã review: `MetricBuildBatch`, `MetricReviewBatch`, `MetricReviewDecision`, `MetricReview`, `MetricCandidateReport`, `MetricProposalReviewRequest/Response`. |
| `relationship_review.py` | Contract API review relationship: `RelationshipDraft`, `RelationshipDecision`, `RelationshipReviewItem`, `RelationshipImpact`, `ColumnPair`. **Cố ý không cho phép nhập SQL.** |
| `review_schemas.py` | Request/response cổng review schema (Flow 1): `SchemaReviewResponse`, `ReviewTableItem`, `ReviewColumnItem`, `SchemaApproveRequest/Response`, `SchemaReviewBatchRequest/Response`, `MetricVersionDecisionRequest`. |
| `tls_settings.py` | `TlsMode` (`prefer` / `disable` / `require` / `verify_ca` / `verify_full`) và `TlsSettings`. |

## Lưu ý

- Quy ước tên bảng/ràng buộc: xem `src/models/db.py` và [`alembic/versions/`](../../alembic/versions/README.md).
- Thiết kế quan hệ giữa các bảng: mục 9 của [ARCHITECTURE.md](../../ARCHITECTURE.md).
