# Metric workflow

Luồng tạo metric dùng chung cho chat, API và việc thẩm định lại:

`Designer → kiểm tra kỹ thuật → kiểm tra trùng → Reviewer → Coordinator kết luận → người dùng`

| Vai trò | Được làm | Không được làm |
| --- | --- | --- |
| Orchestrator | Phân loại yêu cầu | Sinh hoặc duyệt metric |
| Agent chọn ngữ cảnh | Chọn bảng và metadata liên quan | Đổi KPI người dùng yêu cầu |
| Designer | Tạo định nghĩa, sửa theo bằng chứng phản hồi | Đoán ID, duyệt metric, tự thay bằng metric đã có |
| Kiểm tra kỹ thuật — code | Kiểm tra contract, ánh xạ ID/AST/grain và bộ lọc theo metadata | Bịa dữ liệu hoặc quyết định nghiệp vụ |
| Kiểm tra trùng — code | Trả bằng chứng khớp chính xác với catalog | Sửa hoặc loại đề xuất |
| Reviewer | Đánh giá định nghĩa và bằng chứng theo yêu cầu nghiệp vụ | Sửa definition, thêm KPI hoặc chọn bước tiếp theo |
| Coordinator — code | Kết hợp kết quả, chọn tạo mới/dùng metric có sẵn/làm rõ/từ chối/lỗi | Sinh công thức hoặc tự phê duyệt |
| Người dùng/Data Lead | Lưu, gửi duyệt hoặc phê duyệt theo quyền | Bỏ qua điều kiện thẩm định phía server |

Reviewer `pass` là đạt thẩm định, không phải human approval. Chỉ kết luận dùng metric có sẵn khi có bằng chứng khớp chính xác và Reviewer cho pass. Nếu cần sửa, Designer sửa tối đa một lần; bản sửa phải chạy lại kiểm tra kỹ thuật, kiểm tra trùng và Reviewer. Reviewer lỗi cấu trúc được thử lại theo chính sách hiện có; không tự đổi định nghĩa đã đạt kỹ thuật.

Định danh phép tính gồm aggregation, expression, bảng gốc, grain, bộ lọc chung và toàn bộ `formula.ratio`: aggregation/expression tử và mẫu, bộ lọc từng phía, scale, offset. Tỷ lệ hủy/tổng không tương đương tổng đơn. So khớp cấu trúc không chứng minh được mọi dạng tương đương đại số; trường hợp chưa chắc phải giữ đề xuất để xem xét.

Sau khi Coordinator chốt, tầng lưu proposal không được thay đề xuất thành một thông báo trùng khác. Khi lưu/gửi duyệt, server kiểm tra catalog hiện tại lần nữa; nếu metric tương đương mới xuất hiện thì báo lỗi rõ ràng, không thay payload đã được thẩm định.

Trace ghi các bước kiểm tra bằng code và bước `metric_conclude` riêng. Dấu hoàn tất của một bước chỉ chứng minh bước đã chạy xong; trạng thái thẩm định và kết luận nằm trong kết quả proposal.

Lỗi cấu trúc có `execution_error.validation_errors` gồm đường dẫn trường (`issues.0.action`), loại lỗi (`missing`, `extra_forbidden`, `missing_candidate_id`, `duplicate_candidate_id`...) và thông báo. `candidate_id` cùng `attempt` xác định mục và lần thử (0 là lần đầu). Chi tiết xuất hiện trong proposal, bảng thẩm định và sự kiện trace `metric_output_validation`; lần lỗi đầu vẫn còn trong trace khi thử lại thành công. Không lưu giá trị input hay toàn bộ phản hồi provider vào các chẩn đoán này. Trace cũ chỉ chứa lỗi chung không thể được bổ sung hồi tố.
