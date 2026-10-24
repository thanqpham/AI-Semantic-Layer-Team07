# Bộ metric để tạo lại catalog và kiểm tra sinh nhiều metric

Áp dụng cho database semantic **123**, ID **1**, workspace **Personal Workspace**.
Danh sách dựa trên schema metadata hiện có; không lấy mẫu dữ liệu bán hàng.

Catalog đã được đặt lại ngày 25/10/2026: xóa hẳn 27 metric (25 đang hiển thị,
2 đã xóa mềm), giữ nguyên 36 bảng và 381 cột schema. Định nghĩa, version và các
tham chiếu liên quan đã được sao lưu trước khi xóa.

## Cách sử dụng

1. Rebuild/restart backend bằng source mới trước khi kiểm tra các sửa đổi vừa làm.
   Image backend đang chạy trước đó chưa chứa đầy đủ bản sửa.
2. Refresh ứng dụng, chọn database **123**, mở cuộc trò chuyện mới để tránh context
   metric cũ. Dùng vai trò Data Lead để lưu và duyệt.
3. Gửi từng batch dưới đây, không gửi cả 30 metric cùng một lượt. Backend hiện giữ
   tối đa 5 proposal đạt mỗi lượt; thiếu căn cứ có thể trả ít hơn và nêu lý do.
4. Kiểm tra từng definition, tên, filter, đơn vị và mẫu số trước khi lưu vào catalog.
   Reviewer đạt vẫn là chờ người duyệt, không phải metric đã được xuất bản.
5. Với metric tỷ lệ, dùng formula.ratio. scale=100 cho phần trăm, scale=1 cho tỷ số
   thông thường. Mẫu số bằng 0 phải trả NULL.

Các giá trị flag sau có kiểu VARCHAR, vì vậy dùng chuỗi `'0'`/`'1'`, không dùng
boolean hay số: is_test_order, is_canceled, is_bot_traffic, is_active,
is_checkout_completed. latest_status có các giá trị khai báo **Completed,
Canceled, Delivered**, phân biệt đúng cách viết.

Các filter trong bộ này là quy ước kiểm thử được nêu rõ trong prompt; không tự
coi đây là chính sách nghiệp vụ đầy đủ cho môi trường production.
Với metric tiền tệ, cần xác nhận cùng tiền tệ trong phạm vi tính. Nếu có nhiều
tiền tệ, lọc phạm vi hoặc phân nhóm phù hợp; không tự quy đổi hay cộng tiền khác loại.

## Danh sách 30 metric và công thức đối chiếu

Các biểu thức dưới đây là cách đọc công thức, không phải SQL tự do để gửi thực thi.
Các thành phần tử/mẫu của ratio phải khai báo riêng trong definition.

| ID | Metric | Bảng gốc | Công thức/điểm cần kiểm tra |
|---|---|---|---|
| 01 | Tổng số đơn thực | order_header | COUNT_DISTINCT(id), is_test_order='0' |
| 02 | Số dòng hàng không hủy | order_line | COUNT(*) hoặc COUNT(1), is_canceled='0'; đây là số dòng, không phải tổng quantity |
| 03 | Tổng giá trị đơn trước thuế | order_header | SUM(price_before_tax), is_test_order='0' |
| 04 | AOV trước thuế theo AVG | order_header | AVG(price_before_tax), một dòng/một đơn, cột không NULL |
| 05 | Giá trị đơn trước thuế lớn nhất | order_header | MAX(price_before_tax) |
| 06 | Giá trị đơn trước thuế nhỏ nhất | order_header | MIN(price_before_tax) |
| 07 | Tổng giá trị đơn sau thuế | order_header | SUM(price_after_tax), không tự trừ thêm giảm giá |
| 08 | Tổng giá trị giảm giá đã khai báo | order_header | SUM(total_discount_value), không cộng thêm hai cột thành phần |
| 09 | Tổng tiền hoàn trả đã khai báo | order_header | SUM(return_amount), không suy ra trạng thái hoàn tiền từ tên cột |
| 10 | Số khách có liên kết đơn thực | order_header | COUNT_DISTINCT(customer_id); NULL không được tính, khác tổng khách trong customer |
| 11 | Tỷ lệ đơn bị hủy (%) | order_header | ratio: COUNT_DISTINCT(id) với latest_status='Canceled' / COUNT_DISTINCT(id), scale=100 |
| 12 | Tỷ lệ đơn hoàn tất (%) | order_header | ratio: COUNT_DISTINCT(id) với latest_status='Completed' / COUNT_DISTINCT(id), scale=100 |
| 13 | Tỷ lệ đơn có giảm giá (%) | order_header | ratio: COUNT_DISTINCT(id) với total_discount_value>0 / COUNT_DISTINCT(id), scale=100 |
| 14 | AOV trước thuế theo ratio | order_header | ratio: SUM(price_before_tax) / COUNT_DISTINCT(id), scale=1; so sánh với metric 04 |
| 15 | Tỷ trọng giảm giá trên giá trước giảm (%) | order_header | ratio: SUM(total_discount_value) / SUM(price_before_discount), scale=100; không AVG tỷ lệ từng đơn |
| 16 | Tổng số lượng trên dòng không hủy | order_line | SUM(quantity), is_canceled='0' |
| 17 | Tổng giá trị quantity nhân giá sau giảm | order_line | SUM(quantity * price_after_discount); là biểu thức kiểm thử, cần xác nhận đơn giá trước khi gọi là doanh thu |
| 18 | Số lượng sau trả trên các dòng có khai báo lượng trả | order_line | SUM(quantity - return_quantity), thêm return_quantity IS NOT NULL; không tự COALESCE |
| 19 | Số lượng trên mỗi đơn có dòng không hủy | order_line | ratio: SUM(quantity) / COUNT_DISTINCT(order_id), scale=1; không lấy tổng mọi order_header làm mẫu số |
| 20 | Tỷ lệ chênh giá theo chi phí hiện tại (%) | order_line | ratio: SUM((price_after_discount-current_item_cost)*quantity) / SUM(price_after_discount*quantity), scale=100; không gọi là biên lợi nhuận theo giá vốn lịch sử |
| 21 | Số khách hàng đang hoạt động | customer | COUNT_DISTINCT(id), is_active='1'; khác metric 10 |
| 22 | Số sản phẩm đang hoạt động có tồn kho | item | COUNT_DISTINCT(id), is_active='1', current_stock_quantity>0; đếm sản phẩm, không cộng các đơn vị tồn kho khác nhau |
| 23 | Tỷ lệ phiên có liên kết đơn hàng (%) | web_session | ratio: COUNT_DISTINCT(id) với order_id IS NOT NULL / COUNT_DISTINCT(id), scale=100, cả hai phía loại bot |
| 24 | Thời lượng phiên trung bình (giây) | web_session | AVG(session_duration_seconds), is_bot_traffic='0', duration IS NOT NULL |
| 25 | Tỷ lệ giỏ hàng hoàn tất checkout (%) | cart | ratio: COUNT_DISTINCT(id) với is_checkout_completed='1' / COUNT_DISTINCT(id), scale=100 |
| 26 | Thời gian giao hàng trung bình (giờ) | order_header | AVG(TIMESTAMP_DIFF_HOURS(delivered_time,created_time)), delivered_time IS NOT NULL, loại đơn thử |
| 27 | Thời lượng phiên nhỏ nhất (giây) | web_session | MIN(session_duration_seconds), loại bot và duration NULL |
| 28 | Thời lượng phiên lớn nhất (giây) | web_session | MAX(session_duration_seconds), loại bot và duration NULL |
| 29 | Tổng chênh lệch giá sau và trước thuế | order_header | SUM(price_after_tax - price_before_tax), loại đơn thử; không tự khẳng định bằng total_tax_value nếu chưa đối chiếu |
| 30 | Giá trị giảm giá trung bình mỗi đơn thực | order_header | AVG(total_discount_value), loại đơn thử; tính cả đơn giảm giá bằng 0 |

Không bắt buộc lưu cả hai metric 04 và 14: với một dòng mỗi đơn và giá không NULL,
chúng có thể tương đương. Dùng cặp này để thử phát hiện trùng/near-duplicate.
Nếu hệ thống đề nghị dùng lại metric đã có, xem định nghĩa trước khi quyết định;
không đổi tên chỉ để vượt kiểm tra trùng.

## Batch 1 — COUNT, COUNT DISTINCT, SUM, AVG, MAX

```text
Đề xuất tối đa 5 metric riêng, trả definition và báo cáo thẩm định cho từng metric.
Không tự lưu hoặc tự phê duyệt. Chỉ dùng bảng/cột trong schema.

1. Tổng số đơn thực: COUNT_DISTINCT(id) trên order_header, is_test_order='0'.
2. Số dòng hàng không hủy: COUNT(*) trên order_line, is_canceled='0'; đếm dòng, không đếm quantity.
3. Tổng giá trị đơn trước thuế: SUM(price_before_tax) trên order_header.
4. AOV trước thuế: AVG(price_before_tax) trên order_header; metadata xác nhận id là PK, mỗi dòng một đơn và giá không NULL.
5. Giá trị đơn trước thuế lớn nhất: MAX(price_before_tax) trên order_header.

Với mọi metric order_header, dùng chung is_test_order='0', không thêm filter trạng thái.
Với order_line chỉ dùng is_canceled='0', không kéo filter từ bảng khác vào definition.
Giữ tên phân biệt rõ; metric chưa đủ căn cứ phải báo riêng thay vì làm mất các metric hợp lệ.
```

## Batch 2 — MIN, tiền tệ và khách hàng duy nhất

```text
Đề xuất 5 metric riêng trên order_header. Tất cả dùng is_test_order='0', không thêm filter trạng thái:
1. Giá trị đơn trước thuế nhỏ nhất: MIN(price_before_tax).
2. Tổng giá trị đơn sau thuế: SUM(price_after_tax), không trừ thêm giảm giá.
3. Tổng giá trị giảm giá đã khai báo: SUM(total_discount_value), không cộng thêm các cột giảm giá thành phần.
4. Tổng tiền hoàn trả đã khai báo: SUM(return_amount).
5. Số khách có liên kết đơn thực: COUNT_DISTINCT(customer_id); customer_id NULL không tính.
Không đổi metric số 5 thành COUNT_DISTINCT(id) hoặc tổng khách trong bảng customer.
Trả definition và kết quả thẩm định riêng cho từng metric, chưa lưu catalog.
```

## Batch 3 — Ratio, filter riêng và mẫu số

```text
Đề xuất tối đa 5 metric riêng trên order_header, bắt buộc dùng formula.ratio:
1. Tỷ lệ đơn bị hủy (%): tử số COUNT_DISTINCT(id) với latest_status='Canceled'; mẫu số COUNT_DISTINCT(id); scale=100.
2. Tỷ lệ đơn hoàn tất (%): tử số COUNT_DISTINCT(id) với latest_status='Completed'; mẫu số COUNT_DISTINCT(id); scale=100.
3. Tỷ lệ đơn có giảm giá (%): tử số COUNT_DISTINCT(id) với total_discount_value>0; mẫu số COUNT_DISTINCT(id); scale=100.
4. AOV trước thuế theo ratio: tử số SUM(price_before_tax), mẫu số COUNT_DISTINCT(id), scale=1. Giữ ratio để kiểm tra; nếu tương đương AOV đã có thì báo trùng, không tạo bản trùng chỉ bằng đổi tên.
5. Tỷ trọng giảm giá trên giá trước giảm (%): tử số SUM(total_discount_value), mẫu số SUM(price_before_discount), scale=100.

metric.filters dùng chung is_test_order='0' cho cả hai phía. Tập mẫu số là mọi đơn thực ở mọi trạng thái.
Điều kiện riêng của các metric 1-3 chỉ đặt trong numerator.filters; denominator.filters=[] là đúng.
Không lọc Canceled/Completed cho cả mẫu số, không tự thêm IN liệt kê trạng thái.
Mẫu số bằng 0 trả NULL. Không thay ratio tổng hợp bằng AVG tỷ lệ từng dòng hoặc chia ID.
Không tự lưu/phê duyệt; trả riêng proposal và báo cáo từng metric.
```

## Batch 4 — Biểu thức số học, NULL và grain dòng hàng

Metric 17 và 20 chỉ được gọi là chỉ số kinh doanh chính thức khi bạn xác nhận
các cột giá/chi phí là trên một đơn vị sản phẩm. current_item_cost là chi phí hiện
tại theo metadata, chưa phải bằng chứng về giá vốn tại lúc bán.

```text
Tạo các proposal kiểm thử trên order_line, mọi metric dùng is_canceled='0':
1. Tổng số lượng trên dòng không hủy: SUM(quantity).
2. Tổng giá trị quantity nhân giá sau giảm: SUM(quantity * price_after_discount). Chỉ mô tả đúng biểu thức kiểm thử, không tự gán là doanh thu kế toán nếu chưa xác nhận giá là đơn giá.
3. Số lượng sau trả trên các dòng có khai báo lượng trả: SUM(quantity - return_quantity), thêm return_quantity IS NOT NULL. Phạm vi chỉ là các dòng có lượng trả được khai báo, không coi NULL là 0.
4. Số lượng trên mỗi đơn có dòng không hủy: formula.ratio với SUM(quantity) / COUNT_DISTINCT(order_id), scale=1. Mẫu số chỉ gồm các đơn có dòng trong cùng tập đang tính, không JOIN order_header để lấy tổng mọi đơn.
5. Tỷ lệ chênh giá theo chi phí hiện tại (%): formula.ratio với tử số SUM((price_after_discount-current_item_cost)*quantity), mẫu số SUM(price_after_discount*quantity), scale=100. Đây là công thức kiểm thử theo chi phí hiện tại, không gắn nguồn biên lợi nhuận theo giá vốn lịch sử.

Nếu chưa đủ bằng chứng về đơn giá hoặc đơn vị cho metric 2/5, hỏi lại đúng phần thiếu, không tự giả định hoặc đổi KPI.
Không dùng COALESCE/CASE hay công thức lấy cột từ nhiều bảng. Giữ các proposal hợp lệ khác trong batch.
```

## Batch 5 — Khách hàng, sản phẩm, phiên và giỏ hàng

```text
Đề xuất tối đa 5 metric độc lập theo schema, chưa lưu/phê duyệt:
1. Số khách hàng đang hoạt động: COUNT_DISTINCT(customer.id), lọc customer.is_active='1'.
2. Số sản phẩm đang hoạt động có tồn kho: COUNT_DISTINCT(item.id), lọc is_active='1' và current_stock_quantity>0.
3. Tỷ lệ phiên có liên kết đơn hàng (%): trên web_session, formula.ratio với COUNT_DISTINCT(id) có order_id IS NOT NULL chia COUNT_DISTINCT(id) của mọi phiên không phải bot, scale=100. is_bot_traffic='0' là filter chung; order_id IS NOT NULL chỉ ở tử số. Đây là định nghĩa phiên có liên kết đơn, không tự suy ra chuẩn conversion khác.
4. Thời lượng phiên trung bình (giây): AVG(web_session.session_duration_seconds), lọc is_bot_traffic='0' và session_duration_seconds IS NOT NULL.
5. Tỷ lệ giỏ hàng hoàn tất checkout (%): trên cart, COUNT_DISTINCT(id) có is_checkout_completed='1' chia COUNT_DISTINCT(id) của mọi giỏ hàng, scale=100.

Tên bảng có trong yêu cầu chỉ để chỉ rõ nguồn; expression trong definition dùng tên cột thuộc đúng base_entity, không dùng alias/join SQL.
Không chia số đơn cho ID phiên, không tự thêm điều kiện active/hoàn tất từ bảng khác.
```

## Batch 6 — Thời gian, MIN/MAX và biểu thức trừ

```text
Đề xuất 5 metric riêng, chưa lưu/phê duyệt:
1. Thời gian giao hàng trung bình (giờ): trên order_header, AVG(TIMESTAMP_DIFF_HOURS(delivered_time, created_time)); lọc is_test_order='0' và delivered_time IS NOT NULL. Giữ nguyên mốc bắt đầu created_time và mốc kết thúc delivered_time, nêu rõ giới hạn múi giờ/chất lượng timestamp nếu chưa có bằng chứng.
2. Thời lượng phiên nhỏ nhất (giây): trên web_session, MIN(session_duration_seconds), lọc is_bot_traffic='0' và session_duration_seconds IS NOT NULL.
3. Thời lượng phiên lớn nhất (giây): trên web_session, MAX(session_duration_seconds), cùng các filter ở metric 2.
4. Tổng chênh lệch giá sau và trước thuế: trên order_header, SUM(price_after_tax-price_before_tax), is_test_order='0'. Chỉ mô tả phép chênh lệch này, không tự kết luận bằng tổng thuế đã khai báo.
5. Giá trị giảm giá trung bình mỗi đơn thực: trên order_header, AVG(total_discount_value), is_test_order='0'; tính cả đơn có giảm giá bằng 0, không thêm filter total_discount_value>0.

Nếu một metric lỗi, giữ lại các metric hợp lệ còn lại và báo lý do riêng.
```

## Case nâng cao và case không nên lưu

| Case | Prompt kiểm thử | Kết quả mong đợi |
|---|---|---|
| Cộng hai cột | “Tổng giá trị trước thuế cộng tiền thuế trên order_header: SUM(price_before_tax + total_tax_value), loại đơn thử. Nếu trùng một metric đã có thì báo, không đổi tên để tạo trùng.” | Biểu thức add hợp lệ; phải kiểm tra tương đương nghiệp vụ trước khi lưu thêm. |
| Scale/offset | “Tỷ lệ đơn không hủy (%), trên order_header loại đơn thử: formula.ratio dùng tử số đếm đơn Canceled, mẫu số đếm mọi đơn thực; offset=100, scale=-100. Đây là phần bù tỷ lệ hủy, không đổi sang tỷ lệ hủy.” | 100 - 100 × canceled/all; mẫu số 0 trả NULL. Không gắn recipe cancellation như thể cùng kết quả. |
| Khác biệt tỷ số/AVG | “Tính tỷ trọng giảm giá bằng SUM(total_discount_value)/SUM(price_before_discount), không dùng AVG(total_discount_value/price_before_discount).” | Dùng hai phép tổng hợp; chặn phép chia từng dòng bị thay thế sai. |
| NULL cần COALESCE | “Tính tổng quantity-return_quantity trên mọi dòng, coi return_quantity NULL là 0, bắt buộc dùng COALESCE.” | Báo primitive chưa hỗ trợ hoặc cần phương án được xác nhận; không tự bỏ các dòng NULL để giả kết quả tương đương. |
| Công thức nhiều bảng | “Tính lợi nhuận bằng giá trị order_header trừ tổng chi phí từ order_line trong cùng một metric.” | Không tạo SQL JOIN/subquery tự do trong expression; báo giới hạn nhiều base_entity. |
| Nhân bản grain | “Lấy giá trị tổng order_header nhân với số dòng order_line rồi gọi là doanh thu.” | Phải nhận diện nguy cơ fanout/đếm lặp, không lưu công thức sai. |
| Window function | “Tạo metric bằng ROW_NUMBER() OVER (...) hoặc LAG(...).” | Báo compiler chưa hỗ trợ window trong expression. |
| Chia ID | “Tạo tỷ lệ hủy bằng SUM(id/id), không dùng formula.ratio.” | Không lưu phép chia ID; giải thích cấu trúc ratio đúng nếu phù hợp mục tiêu. |
| Lệch thuế | “Tạo AOV sau thuế bằng AVG(price_before_tax).” | Chặn mâu thuẫn trước/sau thuế, không đổi tên để hợp thức hóa cột. |
| Dữ liệu chưa đủ | “Tính biên lợi nhuận thực tế theo giá vốn tại thời điểm bán.” | Không tự coi current_item_cost là giá vốn lịch sử; yêu cầu bằng chứng/ánh xạ phù hợp. |
| Batch có lỗi | Gửi 4 metric đơn giản hợp lệ cùng 1 metric cần window function. | Giữ 4 proposal hợp lệ, mục chưa hỗ trợ được tách riêng, không mất cả batch. |
| Đề xuất trùng | Tạo lại “Tổng số đơn thực” sau khi đã lưu metric 01. | Báo trùng/dùng lại metric hiện có; không sinh thêm bản chỉ đổi tên. |

## Kiểm tra sau khi lưu

- Catalog chỉ có metric bạn đã lưu/duyệt; không phải mọi proposal đều tự xuất bản.
- Kiểm tra nguồn bảng/cột, grain, criteria thuế, filter chung và filter từng phía.
- Phân biệt tỷ lệ 0–1 với phần trăm 0–100 và đơn vị tiền/giờ/giây.
- Test Query/Explorer theo cửa hàng, kênh và ngày chỉ khi nguồn là Live DB.
  Dimension có thể JOIN nhiều-một theo canonical relationship; điều đó không cho
  phép formula lấy cột tùy ý từ nhiều bảng. SQL Dump không chạy Flow 2.
- Các widget/dashboard lưu metric_id cũ cần chọn lại metric mới. Không tái sử dụng
  ID cũ hoặc đặt lại sequence chỉ để widget cũ trông như còn hoạt động.

Các case trên chưa được gọi LLM hay tự tạo mới trong lượt đặt lại catalog này;
đây là danh sách để bạn chủ động thử tạo, xem báo cáo và lưu.
