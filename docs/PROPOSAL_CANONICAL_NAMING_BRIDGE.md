# Proposal — Canonical Naming Bridge (agent ↔ golden dataset)

> **Trạng thái:** bản đề xuất cho spec owner, 2026-08-23.
> **Người quyết định:** chủ sở hữu spec eval + canonical-model redesign.
> **Bối cảnh:** 2 run agent-live (`eval/runs/agent-ecommerce-20260823-121451`,
> `agent-ecommerce-20260823-124345`), điểm tổng ~31/100, FAIL.

## 1. Vấn đề — một root-cause chặn ~45% tổng điểm

Golden dataset chấm theo **canonical slugs** (`net_revenue`, entity `order`,
dimension `order.channel`); pipeline thật chỉ sản xuất **tên nghiệp vụ tiếng
Việt** (`Doanh thu thực nhận`) và **tên physical** (`fact_orders`,
`customers.city`). Không có bước nào trong pipeline sinh hoặc nhận canonical
slug, nên các phép so khóa không bao giờ khớp — bất kể chất lượng agent:

| Suite / metric bị chặn | Weight | Cơ chế fail |
|---|---:|---|
| enrichment (`entity_f1`, `dimension_f1`, `business_name_similarity`) | 20% | join key `customers` ≠ `customer`; entity không match thì mọi metric phụ nhận 0 — kể cả khi agent đặt "Khách hàng" đúng |
| metric_generation (`metric_identity_accuracy` + các field phụ thuộc) | trong 25% | identity so `target_entity` physical vs canonical; `allowed_dimensions` physical vs canonical |
| query_compilation (`selection_preservation_accuracy`) | trong 25% | set tên metric tiếng Việt vs slug |
| query_compilation (`sql_execution_accuracy`, `result_schema_accuracy`) | trong 25% | **so tên cột trước khi so rows** (`execution.py:57`): alias `metric_1`/`dimension_32` vs `net_revenue`/`channel` |
| query_compilation (`request_validation_accuracy`) | trong 25% | `primary_entity` physical vs canonical (cộng intent/domain rỗng — đã disclose riêng) |

Bằng chứng giá trị thật của agent bị che: run 124345, query_001 — agent tổng
đúng `net_revenue = 3400` (550+1130+1720 theo kênh), nhưng vẫn 0 điểm vì tên
cột và shape rows (xem §3, tín hiệu B2).

**Connector không thể tự sửa chỗ này một cách trung thực:** mọi tên golden
(`net_revenue`) chỉ tồn tại trong golden; đưa nó vào adapter là rò rớt
expected (teaching-to-the-test). Đây là quyết định thiết kế, không phải bug.

## 2. Các phương án

### Phương án A — Canonical registry là INPUT của agent (khuyến nghị)

Biến registry canonical (entity/metric codes + synonyms) thành **cấu hình
domain của sản phẩm** (glossary), không phải bí mật của eval:

- Enrichment nhận glossary → gán canonical code cho entity/dimension cạnh
  business name tiếng Việt.
- Metric generation sinh định nghĩa mang `name = canonical code`,
  `business_name = tiếng Việt`; HITL duyệt cả hai.
- Resolver/catalog, `SemanticQueryCompiler` alias cột SQL theo canonical code.
- Adapter của eval connector chuyển `name`/`target_entity`/dimension keys/
  alias sang canonical code — các phép so khóa khớp golden (golden được author
  từ cùng registry).

**Ưu:** giải quyết sạch cả 4 nhóm chặn ở §1; glossary là governance hợp pháp
của semantic layer (không phải leak); đúng hướng canonical-model redesign đã
lên kế hoạch. **Nhược:** cần công sức authoring glossary + thay đổi
prompt/schema pipeline; phải đồng bộ quy ước code với golden đã có.

### Phương án B — Engine chấm theo business name + synonyms (thay đổi engine)

Giữ nguyên agent; engine đổi các phép so tên từ exact-slug sang
`compare_business_name` với `accepted_business_names`/`synonyms` (hạ tầng đã
có trong `text_similarity.py`).

**Ưu:** không chạm pipeline. **Nhược:** engine đang là contract frozen v2.0.0
("unmodifiable") — cần spec owner duyệt bump; matching mềm có thể tạo điểm
mập mờ ở biên; không sửa được `target_entity`/alias cột (vẫn exact).

### Phương án C — Chấp nhận là artifact có disclose (giữ nguyên trạng)

Ghi nhận trong `contract_gaps` (đã làm); đọc chất lượng agent từ các metric
không phụ thuộc tên: discovery (0.996), guardrail (1.0),
`sql_expression_equivalence`, `formula_equivalence`.

**Ưu:** zero công. **Nhược:** điểm tổng capped ~55–60 mãi; 2 metric execution
vĩnh viễn 0 → gate `compiler_execution_accuracy` vĩnh viễn FAIL.

## 3. Phân tách đề xuất khi chấm解读 kết quả (độc lập với A/B/C)

- **Tín hiệu agent thật (nên fix pipeline):** 5/12 case generation fail với
  metric ratio/CASE WHEN (003/004/008/009/011); không sinh default_filters
  (`is_test_order = FALSE`); resolver từng chọn thừa dimension — **đã fix
  prompt 2026-08-23** (SYSTEM_PROMPT + user prompt của connector resolver);
  không reject câu hỏi mơ hồ (012, 031) và unsafe intent (032).
- **Artifact contract (chờ §2):** mọi phép so canonical names.

## 4. Open questions cho spec owner

1. Glossary ai author và khi nào duyệt (cùng quy trình golden review)?
2. Đồng bộ `contract_version` engine nếu chọn B?
3. Migration: golden đã author xong với slug tiếng Anh — A cần mapping ban đầu
   code↔entity (một lần, con người duyệt)?
4. `intent`/`domain` rỗng trong canonical query (pipeline không có classifier)
   — gộp vào bridge hay xử lý riêng?
