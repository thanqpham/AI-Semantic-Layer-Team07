# `tests/test_evaluation/` — Test Evaluation Framework

Kiểm thử chính [`eval/`](../../eval/README.md) (không dùng LLM thật).

| File | Kiểm tra |
| --- | --- |
| `test_dataset_loader.py`, `test_dataset_validation.py` | Nạp và validate Golden Dataset (tham chiếu chéo, SQL read-only). |
| `test_golden_ecommerce.py`, `test_raw_schema_fixtures.py` | Tính toàn vẹn dữ liệu golden ecommerce và raw schema fixture. |
| `test_discovery_eval.py`, `test_domain_eval.py`, `test_metric_eval.py`, `test_compiler_eval.py` | Evaluator xác định theo stage. |
| `test_evaluator_schemas.py`, `test_scoring.py`, `test_text_similarity.py`, `test_sql_normalization.py` | Contract, tính điểm, so khớp tiếng Việt, chuẩn hóa SQL. |
| `test_execution_safety.py` | Thực thi SQLite cô lập **fail-closed**. |
| `test_benchmark.py` | Benchmark nhận biết trace. |
| `test_run_eval_cli.py` | CLI `eval.run_eval`. |
| [`agent_runner/`](agent_runner/) | Test từng stage của `eval/agent_runner/` (bootstrap, discovery, enrichment, metrics_stage, query_stage, resolver, canonical_resolver, golden_view, guardrail_adapter, collect smoke, CLI agent). |
| [`hybrid/`](hybrid/) | Test engine hybrid: aggregation, catalog, contracts, engine, runner, run_result, reporting, samples, smoke, metric xác định (discovery/enrichment/metric_generation/compiler/guardrail) và AI Judge (base, metrics, output/cache). |
