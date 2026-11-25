# `src/agents/nodes/metric/` — Node của quy trình sinh metric

Các node này là các bước của [`metric_proposal_workflow`](../../workflows/README.md), đồng thời `coordinator_node` là node `metric_coordinator` trong cả chat graph và Flow 1.

| File | Hàm | Chức năng chi tiết |
| --- | --- | --- |
| `coordinator_node.py` | `coordinator_node` | Chạy workflow metric dùng chung với **đầy đủ bằng chứng của request** (ngữ cảnh schema, metric đã có để chống trùng, prompt người dùng). Điểm vào chính của việc đề xuất metric. |
| `validate_node.py` | `validate_node` | Kiểm tra **bằng code** đầu ra của Metric Designer trước khi tới Reviewer: schema hợp lệ, tham chiếu bảng/cột tồn tại, định nghĩa biên dịch được (phối hợp với `metric_review_validation`). Phát hiện lỗi sớm để không tốn lượt LLM. |
| `metric_review_node.py` | `metric_review_node`, `reviewed_state` | Cổng chặn đề xuất trước khi tới HITL hoặc lưu: gộp kết quả review vào state, đánh dấu từng đề xuất `pass` hay cần sửa. |
| `repair_node.py` | `repair_node` | Chỉ sửa **các candidate do coordinator chọn** (không động vào phần đã đạt), gọi lại Metric Designer ở chế độ repair. |
| `metric_node_helpers.py` | `record_failure` | Cập nhật state dùng chung khi workflow thất bại (ghi lý do, giữ trạng thái nhất quán). |

Luồng: `coordinator → validate → (review) → repair → validate …` với số vòng bị giới hạn bởi workflow. Agent LLM tương ứng: `metric_designer_agent`, `metric_reviewer_agent` trong [`../../roles/`](../../roles/README.md).
