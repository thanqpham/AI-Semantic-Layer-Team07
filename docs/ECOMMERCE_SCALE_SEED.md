# Dataset thử nghiệm theo số đơn

Sinh SQL từ seed dashboard hiện có, chạy trên database PostgreSQL **mới, trống**:

```powershell
python scripts/ecommerce_scale_seed.py --orders 100000 --output scratch/issue51-100k.sql
docker exec p-069-postgres createdb -U dev issue51_100k
docker cp scratch/issue51-100k.sql p-069-postgres:/tmp/issue51-100k.sql
docker exec p-069-postgres psql -X -v ON_ERROR_STOP=1 -U dev -d issue51_100k -f /tmp/issue51-100k.sql
```

Tên container và tài khoản cần khớp môi trường. Không nạp lên database đang có dữ liệu.
Không tự động xóa hoặc ghi đè database/file đã tồn tại. Seed chạy trong một transaction;
nếu lỗi thì rollback. Công cụ chỉ tạo file SQL, không lưu connection URL hoặc mật khẩu.

`--orders` nhận 5.840–1.000.000; dùng 100.000, 500.000 hoặc 1.000.000 cho issue #51.
Số đơn chính xác được phân bố trên cửa sổ 730 ngày. Các bảng phụ thuộc đơn được sinh lại
qua logic seed; carts, web_sessions và support_tickets mở rộng theo tỷ lệ số đơn, làm tròn xuống.
Các bảng danh mục giữ kích thước seed. Bảng tổng hợp giữ grain ngày/tháng và tính lại giá trị.
Các bảng mua hàng và danh mục không tăng tuyến tính theo orders. Đây là bộ thử tải theo số đơn,
không phải công cụ nhân đồng đều số dòng của cả 42 bảng.

Ghi ngày nạp, commit, hash seed gốc và SQL sinh ra, số dòng từng bảng và dung lượng thực tế.
SQL dùng CURRENT_DATE nên nội dung dữ liệu phụ thuộc ngày nạp. Không dùng kết quả SQL trực tiếp
để tuyên bố Flow 1 hoặc semantic compiler đã Pass; phải kiểm tra riêng trên ứng dụng.

Kiểm tra công cụ không cần database:

```powershell
python -m unittest discover -s tests/test_eval -p test_ecommerce_scale_seed.py
```

## Bổ sung DB ID 3 từ 100.000 lên 500.000 đơn

[`scripts/ecommerce_append_500k.sql`](../scripts/ecommerce_append_500k.sql) dành riêng cho
DB ID 3 hiện trỏ tới `ecommerce_dashboard_demo`. Script thêm 400.000 orders và dữ liệu liên quan,
tính lại các bảng tổng hợp, giữ nguyên các giao dịch cũ và không thay đổi schema.

Script kiểm tra database, baseline đúng 100.000 orders và khóa/số liệu đối soát. Mọi bước nằm
trong một transaction; khi sai điều kiện hoặc SQL lỗi thì rollback. Chạy lại sau khi đã đạt
500.000 đơn sẽ bị từ chối. Schema và ID connection không đổi.

Trên môi trường Docker hiện tại, chạy thử **không ghi dữ liệu**:

```powershell
Get-Content -Raw -Encoding utf8 scripts/ecommerce_append_500k.sql |
  docker exec -i infra-postgres-1 psql -X -U dev -d ecommerce_dashboard_demo -v ON_ERROR_STOP=1 -v target_orders=100010
```

Kết quả thành công kết thúc bằng `DRY_RUN_OK`. Đây là lượt thử 10 đơn, tự rollback. Nếu container
hoặc tài khoản khác, đổi tên container/tài khoản cho đúng; không ghi mật khẩu trong lệnh.

Khi muốn **thực sự thêm đủ 400.000 đơn**, chạy:

```powershell
Get-Content -Raw -Encoding utf8 scripts/ecommerce_append_500k.sql |
  docker exec -i infra-postgres-1 psql -X -U dev -d ecommerce_dashboard_demo -v ON_ERROR_STOP=1 -v apply=true
```

Lệnh thành công kết thúc bằng `COMMIT_OK`. Với lệnh này không đặt `target_orders`: mặc định là
500.000. Script chỉ cho phép commit 500.000 hoặc 1.000.000 đơn với baseline tương ứng. Tập dữ liệu synthetic được tạo theo ngày chạy; các bảng ngày/tháng
được cập nhật lại, và các bảng danh mục giữ nguyên. Kích thước và thời gian chạy phụ thuộc máy.
Một lượt rollback vẫn có thể tạo WAL và dữ liệu tạm trong PostgreSQL; không chạy thử toàn bộ
500.000 đơn trên database đang dùng nếu muốn giữ baseline hiệu năng nguyên trạng.

## Bổ sung DB ID 3 từ 500.000 lên 1.000.000 đơn

[`scripts/ecommerce_append_1m.ps1`](../scripts/ecommerce_append_1m.ps1) dùng cùng SQL đã được mở rộng
cho hai mức 500.000 và 1.000.000. DB ID 3 phải vẫn trỏ tới `ecommerce_dashboard_demo` và có baseline
đúng 500.000 orders; script giữ giao dịch cũ, bổ sung dữ liệu liên quan và tính lại bảng tổng hợp.
ID dòng giỏ hàng và biến động kho mới dùng vùng ID riêng để tránh trùng dữ liệu cũ.

Chạy thử 10 đơn rồi tự rollback:

```powershell
.\scripts\ecommerce_append_1m.ps1
```

Khi muốn nạp thật thêm 500.000 đơn:

```powershell
.\scripts\ecommerce_append_1m.ps1 -Apply
```

Chỉ lệnh có `-Apply` mới commit và phải kết thúc bằng `COMMIT_OK`. Nếu có lỗi, transaction rollback;
chạy lại sau khi đã đạt 1.000.000 đơn sẽ bị từ chối. Các metric/quan hệ trong Metadata Store không
được tạo hoặc duyệt lại; làm mới dashboard sau khi nạp để xem số liệu mới.
