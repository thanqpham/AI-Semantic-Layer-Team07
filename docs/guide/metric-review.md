# Thẩm định metric AI trước HITL

Luồng hoạt động: chuẩn bị context → sinh đề xuất → kiểm tra kỹ thuật →
Metric Review Agent → tối đa một lượt sửa và kiểm tra lại → người duyệt.
Reviewer gọi model riêng với cùng cấu hình `get_llm(role="metric")`, temperature 0;
đây chưa phải một model Judge độc lập.

## Sử dụng

Trong Studio, nhập yêu cầu một KPI hoặc chọn **Khám phá KPI từ schema**.
Hệ thống giữ yêu cầu gốc, tham chiếu tin nhắn, lựa chọn làm rõ và metadata;
context vượt ngân sách sẽ yêu cầu thu hẹp phạm vi hoặc mở hội thoại mới.
Không có bước lấy mẫu hay chạy truy vấn dữ liệu doanh nghiệp.

Đề xuất đạt hiển thị **AI đã thẩm định — chờ người duyệt**. Mở báo cáo để xem
yêu cầu đã đối chiếu, nhận xét, nguồn và định nghĩa trước/sau. Member gửi request
cho Data Lead; Lead lưu đề xuất vào catalog chờ duyệt. Luồng duyệt request hiện có
vẫn là hành động con người tạo và phê duyệt metric. AI không tự xuất bản.

Đề xuất `needs_revision`, `needs_clarification`, `rejected`, `unsupported` hoặc
`error` không được lưu/gửi. Lỗi còn lại sau một lượt sửa sẽ được hiển thị thay vì
lặp vô hạn. Khi sửa thủ công, dùng **Thẩm định lại bản sửa**, kiểm tra định nghĩa
cuối rồi xác nhận lưu/duyệt. Metadata thay đổi làm mất hiệu lực báo cáo cũ.

Khám phá trả tối đa 5 đề xuất đạt và 5 KPI chưa khả thi, không ép đủ số lượng.
Với schema lớn, AI đọc inventory gọn của tất cả bảng rồi chọn tối đa 5 bảng nghiệp vụ
trong ngân sách context. Các bảng đã chọn giữ nguyên đầy đủ cột, kiểu, khóa, nullable,
giá trị khai báo và quan hệ; không cắt bớt điều kiện để vừa prompt. Phạm vi đã chọn
được ghi trong context báo cáo, không đại diện cho mọi KPI có thể có của toàn database.
KPI ratio tổng hợp như AOV, biên lợi nhuận hay tỷ lệ chuyển đổi được đánh dấu
chưa hỗ trợ; compiler v1 không bị mở rộng hoặc nhận phép chia ID giả công thức.

## Tri thức tham khảo

`src/knowledge/retail_metrics.yaml` chứa 10 nhóm KPI và registry URL nguồn.
Các biến thể Shopify/WooCommerce được giữ riêng. Các công thức vận hành nội bộ
được ghi rõ là cần doanh nghiệp xác nhận, không gán cho chuẩn bên ngoài.
Không tìm web runtime, không dùng vector database hoặc đáp án evaluation.
Nguồn tham khảo không ghi đè yêu cầu và quy tắc doanh nghiệp đã xác nhận.

## API và lưu dấu vết

- Chat/stream và `POST /api/v1/semantic/{db_id}/metrics/generate` nhận
  `proposal_mode: requested | discovery`, mặc định `requested`.
- Suggestion có `proposal_id`, `review`, `definition`, `yaml_preview`;
  response có `blocked_candidates` và `clarification` khi cần hỏi lại.
- Tạo metric với `source=ai` phải gửi `proposal_id` cùng định nghĩa đã thẩm định.
  Proposal giả, khác người/database, chưa đạt, bị sửa, đã lưu hoặc lỗi thời bị từ chối.
- `POST /api/v1/semantic/{db_id}/metric-proposals/{proposal_id}/review` nhận
  `{ "definition": ... }`, tạo proposal mới với context gốc và metadata hiện tại.
  Với request Member, Lead gửi `proposal_id` mới khi duyệt bản sửa.
- Bảng `metric_proposals` lưu context, bản gốc/cuối, báo cáo, fingerprint,
  quan hệ proposal cha, request và metric/version được tạo.
- Lịch sử chat giữ báo cáo; màn hình HITL và lịch sử version hiển thị báo cáo
  theo quyền hiện có. Nguồn câu hỏi trong báo cáo version chỉ hiển thị cho Lead.

## Triển khai và kiểm tra

Chạy migration trước khi khởi động backend mới:

```powershell
python -m alembic upgrade head
```

Migration `c02b7c2cd880` chỉ thêm bảng proposal và index, không sửa dữ liệu catalog.
Triển khai frontend cùng phiên bản API mới. Đề xuất AI cũ chưa có proposal phải
được sinh lại; metric đã lưu và luồng nhập metric thủ công giữ nguyên.

Langfuse có node `metric_review`, action `metric_review_decision`, `metric_repair`
và span `metric_review_result`. Span kết quả chỉ ghi status và số lượt sửa trong
`status_message`; prompt/context vẫn tuân thủ cấu hình che nội dung hiện tại.
SQL Dump tiếp tục chỉ dùng metadata; compiler/query chỉ chạy metric đã được
người duyệt theo cơ chế cũ.

Test dùng mock LLM và SQLite. Cần đánh giá thêm với model và schema doanh nghiệp
trước khi dùng thực tế: metadata không chứng minh được chất lượng dữ liệu,
và Reviewer cùng model có thể lặp lại sai sót của Generator.
