# `eval/benchmark/` — Benchmark nhận biết trace

Chấm không chỉ *đầu ra* mà cả **hành vi thực thi** (trace): agent nào được gọi, chi phí/token, ràng buộc trên luồng. Chạy bằng `python -m eval.run_benchmark`, trên sandbox SQLite cô lập.

| File | Chức năng chi tiết |
| --- | --- |
| `contracts.py` | Contract có phiên bản: `BenchmarkCase`, `TraceConstraints`, `TraceEvent`, `ScenarioExecution`, `BenchmarkRunRequest`, `BenchmarkRunResult`, `BenchmarkGate`, `TraceScore`, `BaselineComparison`. |
| `dataset.py` | `load_benchmark_cases`: nạp case trace (tách khỏi golden case chấm đầu ra). |
| `runner.py` | `run_benchmark`: chạy kịch bản dưới trace opt-in của sản phẩm. |
| `graph_runner.py` | `run_flow1_graph`: chạy LangGraph production trong sandbox. |
| `product.py` | `AgentRunnerBenchmarkExecutor`: dùng `agent_runner` làm kịch bản benchmark. |
| `tracer.py` | `BenchmarkTraceRecorder`: ghi sự kiện sản phẩm thành trace đã redact (context-local). |
| `scoring.py` | `score_case`, `benchmark_gates`, `aggregate_scores`, `overall_score`: chấm ràng buộc trace xác định và cổng cứng. |
| `pricing.py`, `pricing_catalog.json` | Bảng giá cục bộ có phiên bản để ước tính chi phí lặp lại được (`PricingCatalog`, `CostEstimate`). |
| `redaction.py` | `redact_value`, `redact_state_delta`, `digest_observation`: che secret/PII trước khi lưu. |
| `reporting.py` | `write_artifacts`, `write_replay_input`, `render_markdown`: artifact có thể phát lại, không chứa secret. |
| `baseline.py` | `compare_baseline`: chỉ so sánh với baseline khi provenance tương thích. |
