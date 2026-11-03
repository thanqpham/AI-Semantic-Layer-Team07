# Golden Dataset Changelog

## [3.1.0] - 2026-11-03
### Changed
- 21 metric request viết lại theo khung **"Hãy đề xuất metric ..."** — giữ nguyên
  ràng buộc nghiệp vụ, 2 negative case (011, 012) giữ nguyên bẫy.
- Đồng bộ hygiene filter theo hành vi thật của product khi lưu metric (quyết định
  nhóm 2026-11-03): `is_bot_traffic = FALSE` cho conversion_rate (004),
  add_to_cart_rate (017), average_session_duration (019) — **đảo ngược mục 4
  GROUND_TRUTH_NOTES** vì product auto-attach cột này ở fixture mới; thêm
  `is_canceled` cho returned_order_rate (008), discount_rate (013); thêm
  `is_canceled + is_delivered` cho average_delivery_lead_time_hours (014).
  Không adopt cho units_per_transaction (AVG-vs-ratio là gap thật) và
  low_stock_sku_count (filter cột-vs-chuỗi là gap thật).
- Sửa aggregation `count` → `count_distinct` cho order_count (002) và
  low_stock_sku_count (021).
- Query cases 011, 023, 033, 037, 038, 041, 047: SQL chuyển sang dạng
  WHERE-lift (default filter xuống `WHERE`, side-filter giữ CASE trong numerator)
  — engine normalization từ 2026-11-03 hội tụ 2 spelling này; expected results
  tính lại trên fixture (vd 011: 0.6154 → 0.6667; 041 mất nhóm `delivery_type`
  rỗng vì WHERE drop empty group, đúng hành vi compiler).
- Canonical registry (`canonical/metrics/*.yaml`) đồng bộ từng thay đổi
  agg/filter — validator bắt buộc cases ↔ registry khớp.

## [3.0.0] - 2026-08-25
### Added
- Đồng bộ benchmark theo 19 metric trong
  `Ecommerce_Metric_Dictionary_Ground_Truth_Expanded.xlsx`: 9 metric mới
  (discount_rate, average_delivery_lead_time_hours, order_cancellation_rate,
  units_per_transaction, add_to_cart_rate, checkout_abandonment_rate,
  average_session_duration, loyalty_order_penetration, low_stock_sku_count).
- Định nghĩa 4 level cho query cases (L1 Explicit / L2 Semantic / L3 Multi-hop
  Join / L4 Ambiguous) với `level` + tag `level_1..level_4`; validator ép tính
  nhất quán level↔difficulty.
- Chuỗi L3 many-to-one `order → customer → address → city` (bảng mới
  `cities`, `customer_addresses`, `dim_items`) + 6 case multi-hop JOIN.
- 3 case L4 ambiguous kỳ vọng `NEEDS_CLARIFICATION`; eval resolver hỗ trợ
  clarify output, dimension reachable qua relationship graph và time grain.
- 3 guardrail case mới: `FOR UPDATE` (postgresql), `PRAGMA` (sqlite),
  `pg_sleep` (postgresql) — lockstep mở rộng `exp.Lock` và `pg_sleep` trong
  eval validator + engine normalization.
- `scripts/verify_golden_results.py` tái sinh và đối chiếu expected results.
- `ecommerce/GROUND_TRUTH_NOTES.md`: chính sách đơn hợp lệ, 19 quyết định
  metric kèm audit refs, internal definitions, quy ước golden SQL compiler-shape.

### Changed
- Contract version 2.0.0 → 2.1.0 (thêm trường `level`); dataset version 3.0.0.
- Đổi tên `return_rate` → `returned_order_rate`,
  `average_fulfillment_hours` → `average_delivery_lead_time_hours`.
- Mọi metric tỷ lệ dùng `* 1.0 / NULLIF(..., 0)` và `aggregation: ratio`
  theo khuyến nghị audit; net_revenue/order_count/AOV/gross_margin đồng bộ
  chính sách "đơn hợp lệ" (`is_test_order = FALSE AND is_canceled = FALSE`).
- 4 metric session bỏ default filter `is_bot_traffic` (dataset thật của nhóm
  không có) — giữ dimension lọc ad-hoc.
- Golden SQL viết đúng compiler shape (CASE-wrap filter trong aggregate,
  JOIN trần theo thứ tự BFS, không LIMIT) để so khớp AST trực tiếp.
- 21 metric-definition cases (19 twin + 2 negative); 39 query cases
  (34 positive + 5 error) — retire 11 case clone lặp mẫu; 34 result sets.
- `allowed_dimensions` các metric order-side thêm `city.city_name`,
  `city.region_name` phục vụ multi-hop.

## [2.0.1] - 2026-08-09
### Changed
- Xóa chín metric legacy vì không có metric-definition cases, query cases hoặc
  expected results tương ứng; baseline chỉ còn 10 metric của nhóm.
- Hợp nhất customer, product và payment vào `canonical/entities/`; không còn
  `metric_extensions`, `entity_extensions` hoặc legacy raw/source directories.
- Bổ sung các support tables, seed data, foreign keys, raw schemas và discovery
  expectations để mọi canonical entity đều có physical mapping hợp lệ.

## [2.0.0] - 2026-08-09
### Changed
- Đồng bộ benchmark chính theo 10 metric trong `Ecommerce_Metric_Dictionary_Ground_Truth.xlsx`.
- Mở rộng contract cho Simple/Derived/RATIO, formula, SQL expression, source table,
  dimensions, time grain, provenance, status và owner.
- Thay fixture bằng bốn fact tables phục vụ đầy đủ revenue, order, session, cart,
  customer-returning và gross-margin scenarios.
- Viết lại 12 metric-definition cases và 32 runtime query cases; giữ 30 success
  result sets có thể tái lập trên SQLite.
- Tạm chuyển entity/metric cũ sang thư mục extension để tách khỏi baseline.
- Giữ trạng thái `pending` vì nguồn Excel đánh dấu cả 10 metric là `Draft`.

## [1.1.0] - 2026-08-09
### Fixed
- Chuẩn hóa raw-schema fixtures theo `src.models.raw_schema.RawSchema`.
- Bổ sung cross-reference validation cho canonical artifacts và expected results.
- Hoàn thiện expected execution results cho toàn bộ success query cases.
- Sửa các query dùng sai canonical Metric và loại bỏ fanout revenue ground truth.
- Bổ sung inferred-FK, negative metric/query và AST guardrail cases.
- Bổ sung NULL, repeated products và time-boundary rows vào SQLite seed data.
- Đánh dấu dataset chờ BA/DA phê duyệt lại sau khi sửa semantic ground truth.

## [1.0.0] - 2026-08-09
### Added
- Khởi tạo Golden Dataset v1.0.0 cho domain `ecommerce`.
- Thêm DDL Schemas & Seed data cho SQLite, PostgreSQL (`schema_dump.sql`), và MySQL (`schema_dump.sql`).
- Thêm Discovery Cases (bao gồm PostgreSQL DDL dump, MySQL DDL dump, và SQLite live inspection).
- Thêm Metric Definition Cases (bao gồm SUM, COUNT, AVG, COUNT_DISTINCT, default_filters).
- Thêm 32 Runtime Query Cases với đầy đủ SQL dialect cho PostgreSQL, MySQL, và SQLite.
- Thêm Guardrail Security Cases kiểm thử chống SQL Injection / Cấm DML, DDL.
- Freeze mốc thời gian đánh giá `frozen_evaluation_date = "2026-08-01T00:00:00Z"`.
