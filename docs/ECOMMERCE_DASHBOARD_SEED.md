# Ecommerce dashboard demo (PostgreSQL)

[`scripts/ecommerce_dashboard_demo_pg.sql`](../scripts/ecommerce_dashboard_demo_pg.sql) là **file seed duy nhất**: tạo đủ **42 bảng** ecommerce, dữ liệu tài chính/dashboard và các phân bố chênh lệch theo khu vực, mùa vụ, kênh bán, thanh toán, truy cập, kho và giao vận. Toàn bộ file chạy trong một transaction. File không đụng vào Metadata Store hoặc xóa bảng; chỉ nạp vào database trống, và chạy lại trên database đã nạp sẽ báo lỗi thay vì ghi đè. Repo không tự đăng ký connection hoặc tự duyệt metric trong ứng dụng.

## Dùng database đã tạo trên máy phát triển

Database `ecommerce_dashboard_demo` đã được nạp bộ seed này trên PostgreSQL của Docker Compose. Kết nối trong UI bằng Live DB URL:

```text
postgresql://postgres:<POSTGRES_PASSWORD>@localhost:5432/ecommerce_dashboard_demo
```

Nếu backend kết nối từ trong Docker, host là `postgres` thay vì `localhost`. Dùng mật khẩu PostgreSQL trong cấu hình môi trường của bạn; không đưa URL chứa mật khẩu vào repo. Sau khi kết nối, chạy Flow 1, duyệt các metric cần dùng, rồi mở Metrics Dashboard và thêm widget. Nếu bạn đã kết nối database trước khi thêm 29 bảng mới, hãy đồng bộ/introspect lại schema trong ứng dụng để chúng xuất hiện. SQL Dump chỉ có schema nên không thể hiển thị số liệu.

Để nạp trên môi trường PostgreSQL khác, tạo **database trống, riêng** trước, rồi chạy:

```powershell
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -d ecommerce_dashboard_demo -f scripts/ecommerce_dashboard_demo_pg.sql
```

Seed lấy `CURRENT_DATE` lúc nạp: 730 ngày giao dịch kết thúc hôm nay, khoảng 24 tháng tài chính, 5 nhóm tuổi nợ. Dữ liệu sẽ không tự cập nhật sau khi nạp.

## Các bảng và metric nên duyệt

| Bảng | Metric gợi ý | Công thức | Chiều thời gian / phân loại |
| --- | --- | --- | --- |
| `order_facts` | Doanh thu thuần, giá vốn, lãi gộp | `SUM(net_revenue)`, `SUM(cogs)`, `SUM(gross_profit)` | `ordered_on` theo tháng; `channel`, `region`, `customer_segment` |
| `order_facts` | Số đơn hoàn tất | `COUNT(order_id)` với `order_status = completed` | `ordered_on`, `channel` |
| `finance_daily` | Chi phí vận hành, lợi nhuận ròng, tiền thu | `SUM(operating_expense)`, `SUM(net_profit)`, `SUM(cash_collected)` | `business_date` theo ngày/tháng |
| `finance_monthly` | Phải thu, phải trả, tồn kho, vốn lưu động | `AVG(receivables_balance)`, `AVG(payables_balance)`, `AVG(inventory_value)`, `AVG(net_working_capital)` | `month_start` theo tháng |
| `finance_monthly` | Equity ratio, debt/equity, current ratio, DSO, DPO, DSI | `AVG` của cột tương ứng | `month_start`; chọn **Tháng này** cho KPI hiện tại |
| `aging_balances` | Phải thu / phải trả theo tuổi nợ | `SUM(receivable_amount)`, `SUM(payable_amount)` | `aging_bucket` |
| `funnel_daily` | Lượt truy cập, giỏ hàng, chuyển đổi | `SUM(sessions_count)`, `SUM(carts_count)`, `SUM(conversions_count)` | `business_date` |
| `fulfillment_daily` | Giao hàng, trả hàng, hoàn tiền | `SUM(shipments_count)`, `SUM(returns_count)`, `SUM(refunds_amount)` | `business_date` |

`finance_monthly` có **một dòng cho mỗi tháng**. Các cột balance/ratio là ảnh chụp theo tháng: không dùng `SUM` qua nhiều tháng vì sẽ biến một số dư thành tổng số dư. Với KPI hiện tại, lọc `month_start` vào tháng này; biểu đồ xu hướng có thể dùng `AVG` theo tháng. `finance_daily` và `order_facts` là dòng giao dịch, nên các khoản tiền ở hai bảng đó có thể cộng theo kỳ.

### Biên lợi nhuận gộp theo khu vực

Tạo metric tỷ lệ `SUM(gross_profit) / SUM(net_revenue) * 100` trên `order_facts`, chọn dimension `region`. Đây là tỷ lệ có trọng số theo doanh thu; không lấy trung bình cộng tỷ lệ từng đơn. Bốn khu vực nằm khoảng **43%–63%**, thay vì cùng quanh 51%. Biểu đồ theo tháng cũng thay đổi theo mùa. Nếu widget đang mở, bấm **Làm mới tất cả** để xóa cache dữ liệu dashboard.

Seed làm lệch phân bố khách hàng/khu vực, danh mục và mức giá sản phẩm, kênh bán, phương thức thanh toán, chi phí, tồn kho, nhà cung cấp, lượng mua hàng, nguồn truy cập/thiết bị, giỏ hàng, thời gian giao, lý do trả hàng, đánh giá và phiếu hỗ trợ. Các bảng tổng hợp, tiền thu, tuổi nợ, thuế và hoàn tiền được tính lại trong cùng giao dịch. Các bảng danh mục như `categories`, `brands`, `warehouses` giữ giá trị định danh ổn định; mức sử dụng của chúng trong dữ liệu giao dịch là phần thay đổi.

Các bảng `orders`, `order_items`, `products`, `categories`, `customers`, `payments`, `supplier_invoices`, `inventory_snapshots` cũng có dữ liệu và khóa ngoại để thử khám phá schema, metric sản phẩm/khách hàng và quan hệ. Số liệu tài chính là demo, không phải báo cáo kế toán được đối soát với doanh nghiệp thật.

Phần mở rộng thêm thương hiệu/biến thể sản phẩm, nhà cung cấp và mua hàng, bốn kho và nhập/xuất kho, địa chỉ, khuyến mãi, giỏ hàng, wishlist, phiên truy cập và sự kiện, giao vận, đổi trả/hoàn tiền, đánh giá, hỗ trợ khách hàng, thuế và lịch sử giá. `funnel_daily` có sessions/carts/conversions theo ngày; `fulfillment_daily` có giao hàng, trả hàng, hoàn tiền và thời gian giao. Có thể tạo các metric `SUM(sessions_count)`, `SUM(conversions_count)`, `SUM(shipments_count)`, `SUM(returns_count)`, `SUM(refunds_amount)` với cột `business_date` để lên dashboard hiện tại.

Các bảng vận hành là dữ liệu giả lập để thử quan hệ và truy vấn. Khuyến mãi, thuế và hoàn tiền được lưu riêng; chúng chưa được hạch toán ngược vào `order_facts.net_revenue` hay `finance_monthly`. Muốn báo cáo doanh thu sau khuyến mãi/hoàn tiền phải định nghĩa metric riêng với quy tắc nghiệp vụ phù hợp.

## “Mở rộng cách truy vấn” nghĩa là gì?

API semantic query hiện đã nhận nhiều `metric_ids` trong cùng một request, nhưng **một widget Dashboard chỉ lưu một `metric_id`** và chỉ đọc một cột giá trị để vẽ. Vì vậy chỉ thêm dữ liệu không thể tạo hai đường `Gross/Net Working Capital` hoặc hai cột `Receivables/Payables` trong **cùng** biểu đồ.

Để làm được phần đó về sau, cần cho widget chọn nhiều metric cùng bảng nền, gửi các ID trong một truy vấn, giữ từng cột `metric_<id>` của kết quả, và vẽ một series cho mỗi metric. `finance_monthly` và `aging_balances` đặt các chỉ số so sánh cạnh nhau để đáp ứng điều kiện cùng bảng nền này. Biểu đồ gauge và cột chồng còn cần loại widget/cách vẽ tương ứng. **Seed này không thay đổi giao diện hay truy vấn Dashboard hiện tại.**

Ví dụ, thay vì truy vấn `metric_ids: [doanh_thu]` theo `month_start`, biểu đồ hai đường sẽ truy vấn `metric_ids: [doanh_thu, gia_von]` theo cùng `month_start`. API/compiler có thể tạo hai cột kết quả, nhưng Dashboard hiện chỉ đọc và vẽ cột của metric đầu tiên. Phần cần mở rộng nằm ở cấu hình widget, cách chuyển hai cột kết quả thành hai series và quy tắc sắp xếp khi có nhiều metric; không cần sửa agent/node.
