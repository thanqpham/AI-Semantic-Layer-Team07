# `eval/evaluator/hybrid/` — Engine đánh giá lai (xác định + AI Judge)

Engine hướng **mẫu (sample-centric)**: mỗi mẫu được chấm bởi một tập metric xác định và, tùy chọn, metric do AI Judge cô lập chấm. Lỗi của từng metric được cô lập; metric judge chỉ chạy khi được bật (`--judge`).

| File | Chức năng chi tiết |
| --- | --- |
| `runner.py` | `run_hybrid_evaluation(HybridRunRequest)`: pipeline đầu-cuối — nạp dataset, dựng mẫu, chấm, tổng hợp, ghi báo cáo; `default_implementations`, `build_run_result`. |
| `samples.py` | `build_samples`: dựng `EvaluationSample` từ dataset (`DiscoveryInput`, `EnrichmentInput`, `MetricGenerationInput`, `QueryCompilationInput`, `GuardrailInput` + các `*Reference`). |
| `catalog.py` | Danh mục **đóng băng** của task, metric, trọng số, ngưỡng và cổng (`MetricSpec`, `catalog_spec`, `metrics_for_task`). |
| `engine.py` | `score_sample`: thực thi metric trên mẫu, cô lập lỗi, chặn judge khi không bật (`EvaluationMetric`, `EvaluationContext`). |
| `contracts.py` | `MetricResult`, `MetricProvenance` — contract chung cho metric xác định và AI Judge. |
| `aggregation.py` | Tổng hợp có trọng số theo metric → suite → điểm tổng, kèm độ phủ (`coverage`). |
| `run_result.py` | `HybridRunResult`, `SuiteScore`, `GateResult`, `RunProvenance`; `evaluate_gates` (cổng chất lượng), `resolve_run_status`. |
| `reporting.py` | `write_json_report`, `write_csv_report`, `write_markdown_report` → `report.json` / `report.csv` / `report.md`. |
| `smoke.py` | Candidate sinh từ chính golden để chạy thử cục bộ không cần agent/LLM. |
| [`metrics/`](metrics/README.md) | Metric xác định theo task. |
| [`judge/`](judge/README.md) | AI Judge cô lập. |
