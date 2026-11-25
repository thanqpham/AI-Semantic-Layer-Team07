# `src/agents/workflows/` — Workflow con có giới hạn

| File | Chức năng chi tiết |
| --- | --- |
| `metric_proposal_workflow.py` | `run_metric_workflow(context, drafts=None, ...)`: coordinator LangGraph có **giới hạn vòng lặp** cho việc sinh metric. Mỗi item đi qua: **Metric Designer** (sinh bản nháp) → `validate_node` (kiểm tra bằng code) → **Metric Reviewer** (đánh giá theo batch) → `repair_node` (chỉ sửa các candidate được chọn, nếu `allow_repair`). Dùng `correlate` để khớp phản hồi theo batch với danh tính candidate do server giữ, `find_catalog_duplicate` để chặn trùng với metric đã lưu. |

## Trạng thái kết quả của mỗi item

`pass`, `needs_revision`, `needs_clarification`, `rejected`, `unsupported`, `error`.

Mỗi item kèm **mã lý do** để thống kê và hiển thị cho người duyệt: `UNRESOLVED_ASSUMPTION`, `MISSING_GRAIN`, `VARIANT_CONFLICT`, `MISSING_RATIO`, `TECHNICAL_VALIDATION`, `REVIEWER_FINDING`, `BUILDER_CLARIFICATION`, `BUILDER_UNSUPPORTED`, `BUILDER_REJECTED`, `INVALID_AGENT_OUTPUT`, `PROVIDER_FAILURE`, `OTHER`.

## State (`MetricWorkflowState`)

`context` (ngữ cảnh schema), `task_id`, `items` (các candidate), `repair_ids` (candidate cần sửa), `preset` (đã có bản nháp sẵn), `allow_repair`.

## Liên quan

- Node: [`../nodes/metric/`](../nodes/metric/README.md)
- Agent: `metric_designer_agent.py`, `metric_reviewer_agent.py` trong [`../roles/`](../roles/README.md)
- Service hỗ trợ: `metric_context`, `metric_review`, `metric_dedupe`, `metric_runtime` trong [`src/services/`](../../services/README.md)
