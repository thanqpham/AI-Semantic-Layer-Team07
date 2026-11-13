# Kiểm thử thủ công trên dataset 100.000 đơn

## Chuẩn bị

1. Đăng ký Live DB `issue51_100k`, host `postgres` nếu backend chạy trong Docker.
   Dùng tài khoản/mật khẩu môi trường; không lưu URL chứa mật khẩu làm bằng chứng.
2. Chạy introspection/Flow 1. Ghi connection ID thực tế, thời gian, model/provider.
3. Trong workbook, dùng các dòng quy mô 100.000. Mỗi lần chạy lại thêm dòng với lần chạy mới.
4. Ảnh trước chỉnh sửa thể hiện hành vi ban đầu. Ảnh sau sửa tay không chứng minh hệ thống tự nhận đúng cardinality.
5. Chỉ đánh Pass khi kết quả mong đợi được kiểm chứng. Chưa thực hiện để trống; không thể thực hiện ghi Blocked kèm lý do.

## Kiểm tra AI sửa cardinality

Mỗi batch chỉ nhận các tham chiếu liên kết tới bảng có trong batch đó. Nếu gửi ID bảng ngoài
batch, AI có thể lặp lại ID này và backend sẽ từ chối lượt quét. Kiểm tra hồi quy đã chạy model thật
trên connection 7 với 42 bảng: hoàn tất 45 batch, 9 đề xuất chờ duyệt, khoảng 130 giây;
các bản ghi thử đã rollback. Thời gian/số đề xuất này là kết quả của một lượt chạy, không phải SLA.

Sau khi backend chạy code mới, vào Liên kết và bấm **AI đề xuất**. AI có thể đề xuất sửa
liên kết FK tự động đang approved/valid từ N → 1 sang 1 → 1 trên cùng cặp cột.
Đề xuất ở trạng thái pending_review và nhắm vào liên kết cũ; quan hệ phục vụ chỉ đổi sau khi duyệt.
Quan hệ disabled, đã sửa tay, nguồn manual hoặc đề xuất đã bị từ chối được bảo vệ.
Live DB cung cấp thêm bộ cột UNIQUE qua Inspector để AI suy luận; bước duyệt tự kiểm tra
UNIQUE hiện tại khi bằng chứng PK đã lưu chưa đủ (ví dụ payments.order_id), không cần nhập xác nhận.
Thiếu bằng chứng duy nhất vẫn bị chặn. Đề xuất đã xử lý được giữ làm lịch sử trong DB và ẩn khỏi danh sách.
Với payments, bấm Xác nhận và xác nhận tác động nếu có. Chụp đề xuất và trạng thái
trước/sau duyệt; kiểm tra liên kết cũ được cập nhật thay vì sinh hai liên kết phục vụ trùng nhau.

## Thứ tự thực hiện

| Case | Thao tác và bằng chứng cần giữ |
|---|---|
| REL-01 | Mở metadata orders.id và order_facts.order_id; ghi PK/FK thực sự hiển thị. Màn hình chọn cặp cột chưa đủ chứng minh PK/FK. |
| REL-02 | Trong Liên kết, chọn order_facts → orders, kiểm tra cặp order_id → id và bằng chứng unique/PK. Nếu cần sửa 1-1, chụp trước/sau; preview rồi xác nhận tác động. Duyệt metric COUNT(orders.id), nhóm theo order_facts.region và so sánh oracle. |
| REL-03 | Duyệt SUM(order_facts.net_revenue), nhóm theo orders.channel; so sánh từng nhóm với oracle. |
| REL-04 | Mở metadata payments.order_id, kiểm tra FK → orders.id và UNIQUE; chụp bằng chứng. |
| REL-05 | Duyệt COUNT(payments.id), dùng quan hệ với orders và so với số đơn có payment. Lưu SQL JOIN thực tế. |
| REL-06 | Dùng metric/chiều giữa orders và payments; ghi JOIN thực tế, so với oracle tương ứng. Không giả định đơn thiếu payment được giữ lại. |
| REL-07 | Mở order_items.order_id → orders.id; kiểm tra FK và chiều N → 1. |
| REL-08 | Duyệt SUM(order_items.quantity), nhóm theo orders.channel; so sánh oracle. |
| REL-09 | Chọn metric COUNT(orders.id) hoặc SUM ở grain đơn, thêm dimension order_items.product_id; kiểm tra compiler chặn fanout hoặc có kết quả an toàn đúng. |
| REL-10 | SUM(order_items.quantity), nhóm theo products.product_name; so sánh oracle. |
| REL-11 | Cùng metric quantity, nhóm theo categories.category_name qua products; so sánh oracle. |
| REL-12 | Tạo candidate với cột không thuộc bảng/khác kiểu và preview. Nếu UI không cho gửi dữ liệu sai, cần case API tương ứng; không kết luận validation backend Pass chỉ từ UI. |
| REL-13 | Candidate 1-1 với nguồn không unique; thử approve khi chưa xác nhận cardinality, lưu cảnh báo/từ chối. Dùng candidate thử nghiệm, không thay quan hệ chuẩn. |
| REL-14 | Cần fixture nhiều đường JOIN an toàn; chưa có fixture thì Blocked, không suy luận từ schema hiện tại. |
| REL-15 | Cần fixture candidate khóa ghép thiếu thành phần; chưa có fixture thì Blocked. |
| REL-16 | Trên bản thử nghiệm, compile khi cạnh cần thiết chỉ là candidate/disabled; lưu lỗi không có đường hợp lệ. |
| REL-17 | Chọn metric publish dùng quan hệ thử nghiệm; disable cạnh, chạy lại metric và review metric; kiểm tra cần review/bị chặn và cạnh vẫn disabled. Thực hiện sau các case đúng để tránh ảnh hưởng chúng. |
| REL-18 | Gửi semantic query với limit bỏ trống, 1000, 1001 qua API của connection thực tế; lưu request, SQL/compiler response và kết quả guardrail. |
| REL-19 | Cần truy vấn hợp lệ đi qua compiler thực sự vượt 15 giây; nếu không tái tạo được, Blocked. Không dùng pg_sleep trực tiếp làm minh chứng semantic query. |

## Oracle độc lập (chỉ đọc dataset thử nghiệm)

Chạy bằng `docker exec p-069-postgres psql -U dev -d issue51_100k -c "SQL"`.
Đối chiếu cùng điều kiện lọc và JOIN với metric đã duyệt; nếu metric thêm filter phải áp dụng filter đó vào oracle.

```sql
-- REL-02
SELECT f.region, COUNT(o.id) FROM orders o
JOIN order_facts f ON f.order_id=o.id GROUP BY f.region ORDER BY f.region;
-- REL-03
SELECT o.channel, SUM(f.net_revenue) FROM order_facts f
JOIN orders o ON o.id=f.order_id GROUP BY o.channel ORDER BY o.channel;
-- REL-05/06: đây là INNER JOIN, dùng riêng oracle LEFT JOIN khi sản phẩm thực sự dùng LEFT JOIN.
SELECT COUNT(*) FROM orders o JOIN payments p ON p.order_id=o.id;
-- REL-08
SELECT o.channel, SUM(i.quantity) FROM order_items i
JOIN orders o ON o.id=i.order_id GROUP BY o.channel ORDER BY o.channel;
-- REL-10
SELECT p.product_name, SUM(i.quantity) FROM order_items i
JOIN products p ON p.id=i.product_id GROUP BY p.product_name ORDER BY p.product_name;
-- REL-11
SELECT c.category_name, SUM(i.quantity) FROM order_items i
JOIN products p ON p.id=i.product_id JOIN categories c ON c.id=p.category_id
GROUP BY c.category_name ORDER BY c.category_name;
```

LOAD-01/02/03 cần runner tải để đo percentile/throughput có kiểm tra đúng từng response;
không dùng thời gian bấm UI hay SQL trực tiếp để thay cho hiệu năng semantic API.
LOAD-04 cần trace LLM theo giai đoạn; thiếu usage/giá ghi không có dữ liệu, không mặc định 0.
