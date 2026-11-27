# `tests/test_agents/` — Test agent, node, graph

LLM luôn được mock; kiểm tra routing, hợp đồng đầu ra và xử lý lỗi.

| File | Kiểm tra |
| --- | --- |
| `test_chat_graph.py` | Routing của `chat_graph` theo từng `intent`, nhánh `out_of_scope` kết thúc sớm. |
| `test_semantic_layer_graph.py` | Flow 1: `introspect → enrich → metric_coordinator → save`, dừng trước `save` (HITL), quay lại `enrich` khi từ chối. |
| `test_orchestrator_node.py` | Phân loại ý định của orchestrator. |
| `test_data_assistant_node.py` | Trợ lý dữ liệu chỉ đọc. |
| `test_introspect_node.py` | Node introspect (lỗi kết nối, DB rỗng…). |
| `test_enrich_node.py` | Node enrichment. |
| `test_save_node.py` | Lưu sau HITL, `raw_schema_to_canonical`. |
| `test_metric_coordinator_node.py` | Coordinator metric. |
| `test_metric_proposal_workflow.py` | Workflow builder → validate → reviewer → repair, giới hạn vòng lặp. |
| `test_metric_reason_tracing.py` | Mã lý do (`MISSING_GRAIN`, `VARIANT_CONFLICT`…) và trace. |
| `test_semantic_query_parser_node.py`, `test_semantic_query_llm_contract.py`, `test_semantic_query_parser_business_filters.py` | Parser câu hỏi: node, hợp đồng JSON với LLM, filter nghiệp vụ qua value mapping. |
