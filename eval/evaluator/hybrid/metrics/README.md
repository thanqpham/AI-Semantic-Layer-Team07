# `eval/evaluator/hybrid/metrics/` — Metric xác định

Mỗi file cung cấp hàm `build_*_metrics()` trả danh sách metric cho một task; mọi metric kế thừa `DeterministicMetric` (`base.py`).

| File | Task | Metric |
| --- | --- | --- |
| `base.py` | — | Lớp nền `DeterministicMetric`, hàm dựng kết quả (`score_result`, `boolean_result`, `set_match_result`, `error_result`, `not_applicable_result`), `CandidateFailure`, tiện ích đọc payload. |
| `discovery.py` | Discovery | `DiscoverySetMetric` — so khớp tập bảng/cột/khóa trích xuất với schema chuẩn. |
| `enrichment.py` | Enrichment | `EntityF1`, `DimensionF1`, `RelationshipAccuracy`, `BusinessNameSimilarity`. |
| `metric_generation.py` | Metric generation | `MetricIdentityAccuracy`, `FormulaEquivalence`, `SqlExpressionEquivalence`, `FilterAccuracy`, `AllowedDimensionF1`. |
| `compiler.py` | Query compilation | `RequestValidationAccuracy`, `SelectionPreservationAccuracy`, `InvalidSelectionRejection`, `SqlAstEquivalence`, `SqlExecutionAccuracy`, `ResultSchemaAccuracy` (thực thi qua guarded execution). |
| `guardrail.py` | Guardrail | `GuardrailAspectMetric` — mọi metric đều **critical** (read-only, giới hạn dòng, timeout, mã lỗi). |
