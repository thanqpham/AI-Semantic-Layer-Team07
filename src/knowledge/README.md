# `src/knowledge/` — Tri thức KPI có nguồn

| File | Chức năng chi tiết |
| --- | --- |
| `retail_metrics.yaml` | "Công thức KPI" (recipes) cho miền `retail_ecommerce`, phiên bản 2. Mỗi recipe có nguồn tham chiếu (`sources`: Shopify, WooCommerce, …, kèm ngày review). Được Metric AI dùng làm gợi ý về cách định nghĩa chuẩn và các biến thể. Hiện có các recipe: `net_sales`, `completed_orders`, `customers`, `net_units`, `delivery_hours`, `aov`, `gross_margin`, `conversion`, `cancellation`, `units_per_transaction`. |

## Cách dùng

- Nạp bởi [`src/services/metric_knowledge.py`](../services/metric_knowledge.py) (`load_metric_knowledge`, `find_variant`) — **không truy cập web** và **không chứa đáp án của bộ đánh giá**.
- Chỉ hoạt động khi bật `METRIC_KNOWLEDGE_ENABLED=true` (mặc định `false`).
- Thêm miền khác: thêm file YAML cùng cấu trúc và mở rộng bộ nạp; luôn ghi nguồn và ngày review.
