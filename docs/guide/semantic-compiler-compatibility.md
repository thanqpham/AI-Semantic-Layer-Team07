# Tương thích semantic compiler

- Nhóm theo tuần sử dụng tuần ISO bắt đầu thứ Hai; nhãn tuần trên MySQL và SQLite dùng năm ISO, có thể khác năm lịch ở đầu hoặc cuối năm. PostgreSQL trả thời điểm bắt đầu tuần.
- Timestamp có múi giờ được nhóm theo UTC; timestamp không có múi giờ giữ giờ được lưu.
- Giá trị filter được kiểm tra theo kiểu cột canonical. Giá trị không hợp lệ trả `INVALID_FILTER_VALUE` thay vì để database tự ép kiểu; chuỗi thuộc cột text không được tự chuyển thành ngày hoặc số.
- SQLite không có kiểu decimal chính xác tùy ý: NUMERIC có thể được lưu và tính bằng số thực IEEE 754. Giá trị decimal giữ nguyên chữ số khi bind, nhưng so sánh và phép tính vẫn tuân theo độ chính xác của SQLite; dùng PostgreSQL hoặc MySQL DECIMAL khi cần tính toán chính xác tuyệt đối.
- Nhiều metric được tổng hợp độc lập trước khi ghép theo dimension canonical; nhóm thiếu metric trả `NULL`. Metric cũ vẫn phải qua canonical review.
- Các kết quả kiểm thử thực tế hiện chỉ xác nhận những case có trong bộ integration; không suy rộng thành hỗ trợ mọi tổ hợp hoặc hệ database khác.
