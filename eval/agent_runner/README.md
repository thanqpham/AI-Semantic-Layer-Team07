# `eval/agent_runner/` — Chạy pipeline thật để thu candidate

Chạy **pipeline sản phẩm thật** (`src/`) trong sandbox cô lập, từng stage, và lưu đầu ra thành *candidate* để evaluator chấm (`--source agent`). Cần `LLM_*` hợp lệ; không dùng dữ liệu production.

```
bootstrap → discovery → enrichment → metrics_stage → query_stage
```

| File | Chức năng chi tiết |
| --- | --- |
| `bootstrap.py` | `prepare_run` → `AgentRunContext`: tạo Target DB tạm, metadata store cô lập và user đánh giá. |
| `collect.py` | `collect_candidates`, `collect_guardrails`, `write_candidates`, `write_resolver_diagnostics`: điều phối mọi stage và lưu candidate của một lượt chạy (`AgentCandidates`). |
| `discovery.py` | **Stage 1** — chạy introspection thật trên target (`introspect_target`, `collect_discovery`). |
| `enrichment.py` | **Stage 2** — chạy pipeline enrichment thật rồi đọc lại trạng thái semantic (`run_enrichment_pipeline`, `load_enrichment_state`). |
| `metrics_stage.py` | **Stage 3** — sinh metric cho từng case golden qua đường sản phẩm thật (`collect_metrics`). |
| `query_stage.py` | **Stage 4** — biên dịch truy vấn từ lựa chọn của resolver hoặc của "oracle" (ground truth, chỉ để debug tách lỗi compiler khỏi resolver) (`collect_queries`). |
| `resolver.py` | `resolve_question`, `build_catalog`: resolver **chỉ chọn** metric/dimension đã duyệt cho một câu hỏi (không sinh SQL); kèm `ResolverTrace`/`ResolverAttempt`. |
| `canonical_resolver.py` | `CanonicalResolver`: ánh xạ định danh vật lý do agent phát ra sang tên canonical của golden, **chỉ dùng ánh xạ chính xác có bằng chứng**. |
| `adapters.py` | Chuyển contract sản phẩm sang contract candidate của evaluator (`to_eval_raw_schema`, `to_enrichment_candidate`, `to_metric_candidate`, `to_compiler_candidate`, `ProductionGuardrailAdapter`). |
| `golden_view.py` | `iter_*_cases`: view **chống rò rỉ** của golden (collector không thấy đáp án). |
