# `src/agents/roles/` — Các agent LLM

Mỗi file là **một agent**: sở hữu prompt, gọi model qua `get_llm()`, parse và ràng buộc output (JSON có cấu trúc). Role **không ghi DB** và không biết về graph; node (`../nodes/`) gọi role.

| File | Hàm chính | Chức năng chi tiết |
| --- | --- | --- |
| `orchestrator_agent.py` | `classify_request` | Phân loại tin nhắn vào đúng 1 trong 5 nhóm: `metric_query` (tạo/định nghĩa metric), `semantic_query` (lấy số liệu chỉ số, kèm dimension/filter), `data_question` (hỏi cấu trúc/ metric đã có), `chitchat` (chào hỏi, hỏi về trợ lý), `out_of_scope` (ngoài phạm vi/ký tự rác). Có bộ chuẩn hóa Unicode và câu từ chối chuẩn khi ngoài phạm vi. Nhìn cả lịch sử hội thoại để phân loại. |
| `conversation_agent.py` | `respond` | Trả lời chào hỏi và các câu hỏi chung được hệ thống hỗ trợ (giới thiệu khả năng). |
| `data_assistant_agent.py` | `answer_data_question` | Trợ lý dữ liệu **chỉ đọc** cho Member/Data Lead: giải thích schema, bảng/cột, quan hệ, metric đã duyệt và hướng dẫn chọn dimension/filter; không tạo metric, không chạy truy vấn. |
| `schema_enrichment_agent.py` | `enrich_schema` | Điều phối pipeline enrichment 2-pass cho Flow 1 (gọi `pass1_global_glossary`, `clustering`, `pass2_cluster_enrichment`); trả `business_name` và `description` tiếng Việt cho bảng và cột. |
| `metric_designer_agent.py` | `generate_metric_drafts`, `repair_metric_drafts` | **Metric Designer:** soạn và sửa định nghĩa metric bám schema, trả cấu trúc `AgentCandidate` (aggregate / ratio / formula / filter) chứ **không viết SQL**. |
| `metric_reviewer_agent.py` | `review_metric_batch` | **Metric Reviewer:** đánh giá theo batch các định nghĩa đã hợp lệ kỹ thuật (đúng nghiệp vụ, grain, biến thể, giả định chưa giải quyết) và trả `MetricReviewDecision`. |
| `metric_prompt_rules.py` | — | Hằng số ràng buộc dùng chung cho prompt designer và reviewer (một nguồn quy tắc cho cả hai). |
| `semantic_query_parser_agent.py` | `parse_semantic_query` | Parse câu hỏi ngôn ngữ tự nhiên thành `SemanticQueryInterpretation`: chọn **metric/dimension/filter/time grain từ danh mục đã duyệt**, hoặc trả câu hỏi làm rõ khi mơ hồ. Không sinh SQL. |
| `semantic_query_parser_integration.py` | `parse_semantic_query` | Lớp tích hợp: đưa metadata mapping giá trị đã duyệt vào prompt parser mà **không lộ fingerprint** của mapping. |

## Quy tắc chung

- `temperature = 0.0`, luôn dùng `get_llm()`; không import `ChatOpenAI` trực tiếp.
- Prompt sinh tên nghiệp vụ yêu cầu tiếng Việt.
- Output LLM phải qua parse/validate (`llm_json`, `MetricCallError`/`invalid_output` trong `metric_runtime`) trước khi dùng.
