# `src/services/` — Logic nghiệp vụ

Tầng **service** chứa toàn bộ logic nghiệp vụ của hệ thống. Router (`src/api/`) chỉ xác thực, kiểm tra quyền rồi gọi vào đây; agent (`src/agents/`) gọi service để đọc/ghi dữ liệu. Service không biết gì về HTTP.

Quy ước: hàm `async`, type hint đầy đủ, mỗi hàm ≤ 30 dòng, mỗi file ≤ 500 dòng (vì vậy compiler và SQL dump được tách thành nhiều module nhỏ).

**Mục lục:** [Nền tảng & bảo mật](#1-nền-tảng--bảo-mật) · [LLM](#2-llm) · [Ingestion](#3-ingestion--introspection-flow-1) · [Enrichment](#4-enrichment--semantic-metadata) · [Relationship & giá trị cột](#5-relationship--giá-trị-cột) · [Metric](#6-metric) · [Query compiler](#7-query-compiler--thực-thi-flow-2) · [Chat](#8-chat--truy-vấn-ngôn-ngữ-tự-nhiên) · [Sync/thông báo/dashboard](#9-sync-thông-báo-dashboard)

---

## 1. Nền tảng & bảo mật

| File | Chức năng chi tiết |
| --- | --- |
| `database.py` | Tạo `AsyncEngine` và session factory cho Metadata Store (`get_async_engine`, `get_session_factory`, `get_db_session` — dependency FastAPI). Chứa **mã hóa Fernet** cho connection URL (`encrypt_conn_url`, `decrypt_conn_url`) và `lock_semantic_database` để khóa hàng khi cần ghi tuần tự. |
| `rate_limiter.py` | `InMemoryRateLimiter` (cửa sổ theo IP/người dùng) và `RateLimitMiddleware`. Chỉ áp dụng cho request AI (`is_ai_request`); chỉ bật khi `RATE_LIMIT_ENABLED` hoặc `APP_ENV=production`; trả `429` kèm `Retry-After` (`build_rate_limit_response`). In-memory nên chỉ đúng trong một worker. |
| `tls.py` | Kiểm tra cấu hình TLS (`validate_tls_settings`), tách tham số TLS khỏi URL (`strip_tls_url_params`), dựng `connect_args` SSL cho kết nối đồng bộ/bất đồng bộ (`build_sync_ssl_args`, `build_async_ssl_args`), nạp cấu hình đã lưu (`load_tls_settings`). Hỗ trợ `prefer`/`require`/`verify_ca`/`verify_full` và mTLS. |
| `target_db_privileges.py` | **Từ chối tài khoản có quyền ghi** trên Target DB. `check_read_only_privileges` đọc catalog quyền (`pg_roles`, `has_table_privilege`, `SHOW GRANTS`) → `PrivilegeReport`; `ensure_read_only_account` ném `WritablePrivilegeError`; `read_only_connect_args` ép `default_transaction_read_only=on`. Không bao giờ đọc dữ liệu hàng. |
| `organization_service.py` | Workspace: tạo tổ chức, workspace cá nhân (`ensure_personal_workspace`), liệt kê/đổi vai trò/xóa thành viên, tạo/xem/chấp nhận lời mời. Chứa bảng quyền `ROLE_PERMISSIONS` (`admin` / `data_lead` / `member`), `resolve_membership` (có cache, `invalidate_membership_cache`) và `require_permission`. |

## 2. LLM

| File | Chức năng chi tiết |
| --- | --- |
| `llm.py` | **Cổng duy nhất tạo model:** `get_llm()` trả client LangChain với `temperature=0.0`. Giải quyết provider/alias (`google→gemini`, `claude→anthropic`…), `api_base`/`api_key`/`model` theo thứ tự ưu tiên, model theo vai trò (enrich/metric/judge), giao thức `openai` hoặc `anthropic`, và cấu hình theo request qua `ContextVar`. `is_reasoning_model`, `has_configured_llm`, `reload_llm_config` hỗ trợ. Không khởi tạo `ChatOpenAI` ở nơi khác. |
| `llm_providers.py` | Bảng endpoint chính thức của từng provider hiển thị trong màn hình Cài đặt AI. |
| `llm_settings_service.py` | Đọc/lưu cấu hình AI theo tài khoản (`read_llm_settings`, `save_llm_settings` — key mã hóa Fernet), nạp cấu hình cho request (`load_account_llm_config`) và lấy danh sách model từ API provider (`list_provider_models`). |
| `llm_caller.py` | Gọi LLM an toàn cho pipeline enrichment: semaphore giới hạn đồng thời, retry, parse JSON (`execute_llm_request`, `parse_llm_json`, `enrich_cluster_with_retry`). |
| `llm_json.py` | Tách JSON khỏi phản hồi LLM (bỏ code fence markdown, trích khối JSON): `strip_code_fence`, `extract_json`, `response_text`, `ainvoke_json`. Mọi nơi cần JSON từ LLM nên dùng module này. |

## 3. Ingestion & introspection (Flow 1)

| File | Chức năng chi tiết |
| --- | --- |
| `live_db_service.py` | Kết nối Target Live DB và introspect **không đọc dữ liệu** bằng SQLAlchemy Inspector (`introspect_live_database`), tự nhận dialect (`resolve_and_validate_dialect`), lưu/liệt kê/xem/xóa kết nối với URL đã mã hóa (`create_live_target_db`, `list_live_target_dbs`, `get_live_target_db`, `delete_live_target_db`). |
| `introspection.py` | `extract_raw_schema`: điểm vào thống nhất, trả `RawSchemaMetadata` từ Live DB hoặc từ SQL dump. |
| `introspection_errors.py` | Họ lỗi an toàn phơi ra ngoài: `InvalidCredentialError`, `UnsupportedDatabaseTypeError`, `ConnectionIntrospectionError`, `SchemaIntrospectionError`, `InvalidSchemaDumpError`. |
| `unique_key_metadata.py` | `build_unique_keys`: đọc UNIQUE key từ Inspector, không đụng dữ liệu. |
| `schema_normalization.py` | Hàm thuần giúp raw schema xác định: `utc_timestamp`, `normalize_data_type`, `build_fk_links`. |
| `schema_ingestion.py` | `parse_sql_dump_preview`: điều phối preview schema kỹ thuật từ SQL dump (dùng cho `/semantic/import/preview`). |
| `schema_dump.py` | `parse_schema_dump`: parse dump PostgreSQL/MySQL sang contract raw schema chung. |
| `sql_dump_scanner.py` | `scan_sql_dump`: bộ quét từ vựng **có giới hạn** (kích thước file/statement, độ sâu, số diagnostics) cho PostgreSQL & MySQL, tách thành từng `ScannedStatement`. |
| `sql_dump_scanner_models.py` | Kiểu dữ liệu công khai của scanner (`ScannedStatement`, `ScannerLimits`, `ScanResult`, `StatementKind/Category`, `ScannerMode`) và kiểm tra đầu vào (`validate_extension`, `validate_file_size`). |
| `sql_dump_parser.py` | `parse_sql_dump`: dựng AST (sqlglot) từ các statement, trích bảng, cột, PK, FK, `ALTER TABLE`. |
| `sql_dump_parser_models.py` | Builder nội bộ (`TableBuilder`, `ColumnBuilder`, `PrimaryKeySpec`, `ForeignKeySpec`, `AlterRecord`, `SourceLocation`) và `SqlDumpParseError`. |
| `imported_schema_service.py` | CRUD cho schema import từ SQL dump theo người dùng/workspace. |
| `canonical_builder_service.py` | `CanonicalBuilderService`: kiểm tra toàn vẹn canonical (thứ tự cột, tính duy nhất tên chuẩn hóa, FK đủ cột và đúng bảng đích) và `summarize_canonical_schema` cho prompt. |

## 4. Enrichment & semantic metadata

| File | Chức năng chi tiết |
| --- | --- |
| `pass1_global_glossary.py` | **Pass 1**: sinh `business_name` + `description` cho mọi bảng theo batch (`execute_pass1`), gộp glossary (`merge_glossaries`). |
| `clustering.py` | `cluster_tables`: phân hoạch đồ thị bảng theo FK (Hub-Detached) để mỗi cụm đủ nhỏ cho ngữ cảnh LLM. |
| `pass2_cluster_enrichment.py` | **Pass 2**: làm giàu từng cụm song song (`enrich_clusters_parallel`), dựng prompt theo cụm, có fallback khi LLM lỗi. |
| `enrichment_config.py` | `EnrichmentConfig`: `max_tables_per_cluster=6`, `max_cols_per_cluster=45`, `max_concurrency=3`, `retry_max_attempts=2`, batch Pass 1. |
| `enrichment_progress.py` | Registry tiến độ in-memory (`start/try_start`, `mark_generating`, `mark_saving`, `finish`, `fail`, `get`) cho `GET /enrich/status`; chặn chạy trùng một database. |
| `semantic_fill.py` | Chính sách **chỉ điền ô trống**: `row_is_complete`, `table_needs_llm`, `apply_proposal_values`, `call_llm_enrichment`, `progress_publisher`. Không ghi đè nội dung người dùng đã sửa/duyệt. |
| `semantic_service.py` | `ensure_semantic_database`, `enrich_and_save_canonical_schema` (upsert bảng/cột, trích relationship từ FK, lưu `pending_review`), `delete_semantic_database`. |
| `schema_review_service.py` | Trạng thái HITL của bảng/cột: `load_review_tables`, `update_table_review`, `update_column_review`, `update_review_batch`, `approve_schema`, `pending_review_counts`, `apply_ai_proposal`, `preserve_approved_legacy_values`. |
| `database_overview.py` | `generate_overview`: sinh mô tả tổng quan database từ metadata đã lưu. |
| `export_service.py` | `build_semantic_layer_dict`, `serialize_to_json`, `serialize_to_yaml`: gói Semantic Layer đã duyệt để xuất. |

## 5. Relationship & giá trị cột

| File | Chức năng chi tiết |
| --- | --- |
| `relationship_sync.py` | `reconcile_relationships`: đối chiếu FK vật lý với relationship hiện có **mà không ghi đè quyết định của người dùng**; `invalidate_relationship_columns`, `inferred_relationship_type`. |
| `relationship_suggestions.py` | AI gợi ý relationship **chỉ dựa trên metadata** (`request_suggestions`, `request_all_suggestions`), kiểm tra bằng `validated_suggestions` rồi `persist_suggestion` vào hàng chờ. |
| `relationship_validation.py` | `validate_relationship`: kiểm tra metadata, cảnh báo cardinality (`cardinality_warnings`), dựng SQL preview an toàn, `fingerprint`. |
| `relationship_unique_evidence.py` | `inspect_unique_keys`, `attach_unique_keys`: bằng chứng UNIQUE cho gợi ý trên Live DB. |
| `relationship_review_service.py` | Vòng đời giao dịch của relationship: `list_relationship_reviews`, `save_relationship_candidate`, `decide_relationship`, `preview_relationship_change`, đánh giá tác động lên metric đã publish (`impact_state`, `published_metrics`, `reachable_paths`), khóa phiên bản (`claim_revision`). |
| `relationship_runtime.py` | Điều kiện hợp lệ và duyệt đồ thị **theo hướng** khi compile: `relationship_paths`, `safe_join_path`, `filter_path`, `valid_pairs`, `RelationshipStep`. |
| `categorical_value_discovery.py` | `build_probe_statement`: dựng câu probe giá trị phân loại có giới hạn, chỉ đọc (opt-in). |
| `categorical_discovery_policy.py` | `eligible_column`, sàng lọc cục bộ (`safe_observed_values`, `safe_declared_values`, `declared_check_values` từ CHECK constraint). |
| `categorical_proposals.py` | `queue_discovery`, `proposal_fingerprint`: đưa đề xuất vào hàng chờ, tách khỏi metadata đã duyệt. |
| `semantic_value_mappings.py` | Quy tắc truy cập/so sánh ánh xạ giá trị đã duyệt (`read_approved_business_mappings`, `business_label_matches`, `mentioned_business_values`, `mapping_metadata_fingerprint`…). |
| `value_mapping_import.py` | `parse_value_mapping_file`, `parse_value_mapping_batch`: parse mapping người dùng cung cấp, không ghi và không query dữ liệu. |

## 6. Metric

| File | Chức năng chi tiết |
| --- | --- |
| `metrics.py` | Sinh định nghĩa metric canonical (`generate_definitions_v2`, `generate_metrics_from_prompt`) — LLM **không viết SQL**; `build_metric_system_prompt`, `extract_schema_summary`, `validate_metric_definitions`. |
| `metric_service.py` | Vòng đời: `create_metric`, `update_metric` (copy-on-write, không ghi đè bản đã duyệt), `approve_metric`, `reject_metric_update`, `soft_delete_metric`, `restore_metric`, `get_metric_with_history`; lỗi `DuplicateMetricError`, `MetricRequiresReviewError`. |
| `metric_versioning.py` | Primitive phiên bản append-only: `record_version`, `next_version_number`, `latest_open_version`, `supersede_open_versions`, `mark_version_approved`, `reject_version`. |
| `metric_rollback.py` | `rollback_metric`: hoàn nguyên không phá hủy — phát lại snapshot cũ thành phiên bản mới. |
| `metric_comparison.py` | `compare_catalog_metrics`, `metric_identity`: so sánh xác định các metric canonical. |
| `metric_definitions.py` | `validate_metric_definition`, `with_metric_status`, `is_numeric_data_type`: validate và chiếu persist. |
| `metric_definition_resolver.py` | `MetricDefinitionResolver`: ánh xạ bản nháp (tham chiếu tên) sang metadata canonical (ID bảng/cột), dựng cây biểu thức. |
| `approved_metric_definition.py` | `build_approved_metric_definition_response`: hiển thị định nghĩa metric đã duyệt bằng code, không dùng LLM. |
| `metric_context.py` | `build_metric_context`, `build_data_context`, `build_discovery_context`, `load_review_schema`: ngữ cảnh schema đủ quan hệ, **có ngân sách token**, cho Metric AI. |
| `metric_context_graph.py` | `expand_bridges`: chọn bằng chứng bảng cầu nối an toàn (không quyết định join path). |
| `metric_proposal_context.py` | `prepare_proposal_context`, `check_context_budget`: gói bằng chứng đầy đủ cho đề xuất. |
| `metric_review.py` | `review_metric_draft`, `validate_review_draft`: batch review và cổng xác định cho coordinator. |
| `metric_review_validation.py` | `technical_review`: validate bản nháp bằng metadata và **AST do compiler thật sinh ra**. |
| `metric_correlation.py` | `correlate`: khớp phản hồi theo batch với danh tính candidate do server giữ. |
| `metric_dedupe.py` | Chống trùng trước khi đề xuất mới: `find_catalog_duplicate`, `dedupe_reviewed_suggestions`, `load_existing_for_dedupe`, `merge_dedupe`. |
| `metric_hygiene.py` | `hygiene_flag_filters`: bộ lọc xác định loại hàng test/bot khỏi metric. |
| `metric_knowledge.py` | `load_metric_knowledge`, `find_variant`: nạp KPI recipes có nguồn từ `src/knowledge/retail_metrics.yaml`. |
| `metric_prompt_suggestions.py` | `get_metric_prompt_suggestions`: gợi ý prompt xác định dựa trên schema hiện tại. |
| `metric_proposals.py` | Lưu bằng chứng review và **cổng đề xuất AI** phía server: `persist_proposal`, `require_passing_proposal`, `re_review_proposal`, `generate_reviewed_metrics`, `link_saved_proposal`. |
| `metric_request_service.py` | Quy trình metric request (`create`, `list`, `approve`, `reject`) và thông báo trong app (`list_notifications`, `mark_notification(s)_read`). |
| `metric_runtime.py` | Chính sách provider có giới hạn cho metric agent: `invoke_metric_json` (không retry lồng của SDK), `MetricCallError`, `invalid_output`, `validation_failure`. |
| `dimension_recommender.py` | `get_dimensions_for_metric`, `get_filter_columns_for_metric`, `is_valid_dimension_column`, `is_valid_filter_column`: gợi ý dimension/filter khả dụng cho từng metric. |

## 7. Query compiler & thực thi (Flow 2)

| File | Chức năng chi tiết |
| --- | --- |
| `query_compiler.py` | API công khai: lớp `SemanticQueryCompiler` (ủy quyền cho các module bên dưới). |
| `query_compiler_orchestration.py` | `QueryCompileOrchestrator` + các `*CompileContext`: chuẩn bị metadata và render SQL cho metric đơn, plan nhiều bảng, bundle nhiều metric. |
| `query_compiler_metadata.py` | `QueryCompilerMetadata`, `MetricPlanMetadata`: nạp và kiểm tra metric/cột/relationship phục vụ compile. |
| `query_compiler_validation.py` | `canonical_definitions`, `validate_definition_asts`, `apply_time_grains`: kiểm tra định nghĩa và time grain. |
| `query_compiler_plan.py` | `compile_plan_sql`, `resolve_scoped_filter_stages`: kế hoạch metric đa bảng, có giới hạn. |
| `query_compiler_plan_bundle.py` | `compile_plan_bundle_sql`: ghép nhiều metric trên cùng grain đầu ra. |
| `query_compiler_lowering.py` | `lower_simple_metric`: hạ simple metric về staged plan. |
| `query_compiler_sql.py` | Dựng chuỗi SQL thuần (không truy cập DB) và `validate_read_only` (sqlglot: đúng 1 `SELECT`, chặn `SELECT INTO`, CTE chứa DML, DDL). |
| `query_compiler_dialect.py` | `time_bucket_sql`: time bucket theo dialect PostgreSQL/MySQL/SQLite. |
| `query_compiler_parameters.py` | Ép kiểu và bind tham số filter theo kiểu cột (`coerce_filter_value`, `bind_coerced_parameter`, `validate_null_filter_value`). |
| `query_compiler_trace.py` | `CompileTraceBuilder`, `trace_join_path`, `trace_filters`: trace compile có phiên bản. |
| `query_compiler_types.py` | `CompiledQuery`: kết quả compile (`sql`, `parameters`, metadata, diagnostics). |
| `semantic_compile_error.py` | `SemanticCompileError` với mã lỗi (`read_only_violation`, `multi_statement`, `invalid_sql`…). |
| `query_execution.py` | `execute_compiled_query` → `QueryResult`: chạy `SELECT` qua adapter async read-only, đặt timeout 15 giây theo dialect (`statement_timeout` / `MAX_EXECUTION_TIME` / progress handler SQLite). |

## 8. Chat & truy vấn ngôn ngữ tự nhiên

| File | Chức năng chi tiết |
| --- | --- |
| `chat_service.py` | Lưu và phân quyền phiên/tin nhắn chat: tạo/liệt kê/đổi tên/xóa phiên, `save_chat_message`, tra theo `client_message_id`, lấy lịch sử gần nhất, phân trang. `ChatAuthorizationError`. |
| `chat_tasks.py` | `start_chat_task`, `run_chat_task`, `cancel_chat_task`: giữ tác vụ chạy khi trình duyệt ngắt, gộp retry cùng `client_message_id`. |
| `chat_execution.py` | `ChatExecution`, `execution_step`, `stream_execution`, `sse`: tiến độ thực thi công khai (allowlist) cho SSE, độc lập dữ liệu observability thô. |
| `chat_trace_storage.py` | `execute_with_trace`: gắn trace công khai vào `metadata_json.execution_trace` của message. |
| `natural_language_query.py` | `build_parser_catalog`, `normalize_interpretation`, `execute_natural_language_query`, `format_deterministic_explanation`: dựng catalog metric/dimension cho parser, xác thực lựa chọn (tương thích, với tới được), hỏi lại khi mơ hồ rồi gọi compiler. |
| `semantic_query_parser_context.py` | `prompt_catalog`, `catalog_capacity_error`: chuẩn bị prompt riêng tư cho parser. |
| `semantic_query_values.py` | `filter_value_resolution`: resolve giá trị filter theo mapping đã duyệt. |

## 9. Sync, thông báo, dashboard

| File | Chức năng chi tiết |
| --- | --- |
| `schema_fingerprint.py` | `compute_schema_fingerprint`, `fast_introspect_schema_fingerprint`: băm schema để phát hiện drift nhanh, không cần LLM. |
| `schema_self_healing_service.py` | `detect_drift_details` (thêm/xóa/đổi tên/đổi kiểu), `heal_sql_formula_ast` (sửa công thức metric bằng AST khi đổi tên), `execute_self_healing` (gắn `[Deprecated]`, đưa mục mới vào `pending_review`, đánh dấu metric phụ thuộc). |
| `schema_cron_service.py` | Cron 02:00 hằng ngày: `run_daily_schema_sync_job`, `start/stop_schema_cron_scheduler` (dùng cấu hình AI của người tạo nguồn). |
| `review_notifications.py` | `sync_schema_review_notifications`, `sync_metrics_pending_notifications`: đồng bộ idempotent thông báo "đang chờ duyệt". |
| `notification_bus.py` | Bus in-process (`subscribe`, `publish`, `unsubscribe`) đánh thức các stream đang mở. |
| `notification_stream.py` | `notification_event_stream`: SSE đẩy snapshot thông báo. |
| `dashboard_service.py` | `get_dashboard_layout`, `save_dashboard_layout`: layout dashboard singleton với **optimistic concurrency** (`DashboardVersionConflictError`). |
