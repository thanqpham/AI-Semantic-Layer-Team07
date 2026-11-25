# `src/agents/nodes/schema/` — Node của Flow 1

Ba node tạo nên pipeline `introspect → enrich → … → save` của [`semantic_layer_graph`](../../graphs/README.md).

| File | Hàm | Chức năng chi tiết |
| --- | --- | --- |
| `introspect_node.py` | `introspect_node` | **Bước 1.** Gọi `extract_raw_schema` để lấy schema (chỉ metadata, không đọc dữ liệu) từ Live DB hoặc SQL Dump; ghi `raw_schema` vào state. Nếu lỗi thì ghi lỗi để graph dừng sớm (`route_after_introspect`). |
| `enrich_node.py` | `enrich_node` | **Bước 2.** Chuyển state sang `schema_enrichment_agent.enrich_schema` (pipeline 2-pass: glossary toàn cục → phân cụm → làm giàu cụm), nhận `business_name` + `description` tiếng Việt. |
| `save_node.py` | `save_node`, `raw_schema_to_canonical` | **Bước 5, chạy sau khi HITL duyệt.** Chuyển schema pipeline (TypedDict) sang `RawSchemaMetadata` canonical (`raw_schema_to_canonical`) rồi lưu vào Metadata Store qua `semantic_service`, kèm metric đã qua review; đặt `semantic_layer_id`. Là node duy nhất ghi DB — graph dừng trước node này (`interrupt_before=["save"]`). |

Bước 3–4 (sinh và review metric) do [`metric_coordinator`](../metric/README.md) đảm nhiệm.
