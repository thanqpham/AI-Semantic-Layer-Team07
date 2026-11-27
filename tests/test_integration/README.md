# `tests/test_integration/` — Test tích hợp

| File | Kiểm tra |
| --- | --- |
| `test_canonical_flow.py` | Luồng canonical đầu-cuối: raw schema → canonical → lưu. |
| `test_two_pass_pipeline.py` | Pipeline enrichment 2-pass (glossary → cluster → enrich) với LLM mock. |
| `test_relationship_review_flow.py` | Luồng gợi ý → duyệt → áp dụng relationship. |
| `test_metric_metadata_safety.py` | Metadata đưa vào Metric AI không lộ dữ liệu/giá trị nhạy cảm. |
| `test_metric_plan_sql_execution.py` | Plan metric đa bảng biên dịch ra SQL chạy đúng trên DB thử. |
| `test_compiler_cross_database.py` | Compiler cho PostgreSQL / MySQL / SQLite (không cần DB thật). |
| `test_compiler_cross_database_live.py` | Như trên nhưng **trên PostgreSQL/MySQL thật** (cần `infra/docker-compose.compiler-test.yml`); CI thường bỏ qua, có job riêng. |
| `test_live_deepseek_metric_proposals.py` | Gọi provider thật (DeepSeek) để sinh metric — **opt-in**: chỉ chạy khi đặt `RUN_LIVE_DEEPSEEK=1` và `LIVE_LLM_USER_ID` (tài khoản đã lưu cấu hình AI). |
