# `eval/evaluator/` — Evaluator xác định theo từng stage

Chấm điểm **không dùng LLM** cho năm stage của agent. Mọi evaluator nhận *candidate* (đầu ra của agent) + *reference* (Golden Dataset) và trả `CaseEvaluationResult` / `SuiteEvaluationResult`. Engine mới hơn có AI Judge nằm ở [`hybrid/`](hybrid/README.md).

| File | Chức năng chi tiết |
| --- | --- |
| `domain_eval.py` | `evaluate_domain_suite`: chạy tất cả suite cho một domain đã validate (`EvaluationDependencies`, `DomainSuites`). |
| `discovery_eval.py` | `evaluate_discovery_suite`: độ trung thực trích xuất schema (bảng, cột, khóa) ở chế độ live. |
| `enrichment_eval.py` | `evaluate_enrichment_case/suite`: chấm tên nghiệp vụ, dimension và relationship (khai báo hoặc suy luận). |
| `metric_eval.py` | `evaluate_metric_case/suite`: chấm định nghĩa metric theo danh tính và từng trường (aggregate, filter, grain, dimension cho phép). |
| `compiler_eval.py` | `evaluate_compiler_case/suite`, `evaluate_guardrail_case/suite`: chấm Canonical Query Model, SQL, kết quả thực thi và hành vi guardrail. |
| `execution.py` | `execute_guarded_sql`, `compare_query_result`: **chạy SQL trên SQLite cô lập, fail-closed** (không bao giờ chạm DB thật). |
| `sql_normalization.py` | `normalize_sql`, `structurally_equal`, `canonical_sql`, `effective_limit`: chuẩn hóa/so sánh SQL theo cấu trúc bằng sqlglot, fail-closed. |
| `text_similarity.py` | `normalize_text`, `accent_insensitive`, `fuzzy_similarity`, `compare_business_name`: so khớp văn bản **nhạy tiếng Việt** (bỏ dấu, chuẩn hóa). |
| `scoring.py` | `precision_recall_f1`, `match_sets`, `match_allowed_dimensions`, `micro_average`, `macro_average`. |
| `aggregation.py` | `build_suite_result`: tổng hợp kết quả suite kèm provenance. |
| `schemas.py` | Contract strict cho đầu vào/đầu ra: `EvaluationConfig`, `CaseEvaluationResult`, `SuiteEvaluationResult`, `PrecisionRecallF1`, `FieldScore`, `CandidateEntity`/`CandidateDimension`/`CandidateRelationship`… |
