# `components/studio/` — Thành phần AI Studio

| File | Chức năng chi tiết |
| --- | --- |
| `StudioChatStream.tsx` | Khung hội thoại chính: render tin nhắn người dùng/AI (Markdown, `remark-gfm`), gửi tin qua `sendChatStream`, nhận SSE theo thời gian thực, hủy tác vụ, kết nối lại tác vụ đang chạy, lưu `ChatMessage` và khóa yêu cầu metric (`metricRequestKey`). |
| `AgentThinking.tsx` | Khối "Thinking" (mặc định thu gọn): các bước thực thi (`ThinkingSteps`), trạng thái từng bước và thời gian (`TraceDuration`); có nút mở **Luồng agent**. |
| `AgentFlowPanel.tsx` | Panel hiển thị luồng agent của một lượt trả lời. |
| `AgentFlowCanvas.tsx` | Canvas React Flow vẽ đồ thị agent (orchestrator, data assistant, metric coordinator, parser…) và đường đi thực tế. |
| `AgentFlowNode.tsx` | Nút agent tùy biến: tên, trạng thái (đang chạy / xong / lỗi), thời lượng. |
| `ChatSessionSwitcher.tsx` | Chuyển/tạo/đổi tên/xóa phiên chat ngay trong khung chat. |
| `ChatQueryResultCard.tsx` | Thẻ kết quả truy vấn trong chat: metric, SQL, bảng dữ liệu rút gọn, giải thích xác định. |
| `SuggestionCard.tsx` | Thẻ đề xuất metric do AI sinh: công thức, filter, trạng thái review, hành động lưu/gửi duyệt/yêu cầu. |
| `DedupeWarnings.tsx` | Cảnh báo trùng metric: `ChatDuplicateNotice`, `DuplicateNoticeCard`, `ConflictWarningStrip` (cho phép dùng lại metric tương đương). |
| `SqlCodeViewer.tsx` | Hiển thị SQL có tô màu cú pháp và nút sao chép. |
| `YamlCodeViewer.tsx` | Hiển thị YAML có tô màu (xuất Semantic Layer). |
