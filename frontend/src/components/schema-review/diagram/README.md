# `components/schema-review/diagram/` — Sơ đồ quan hệ

Vẽ đồ thị bảng–quan hệ bằng `@xyflow/react`, bố cục tự động bằng `@dagrejs/dagre` (logic dựng đồ thị ở [`lib/relationshipGraph.ts`](../../../lib/README.md)).

| File | Chức năng chi tiết |
| --- | --- |
| `RelationshipDiagram.tsx` | Component chính: nạp nút/cạnh, zoom/pan, chọn cạnh/nút, ngữ cảnh hành động (`DiagramActionsContext`), tự căn khung khi mở lần đầu. |
| `TableNode.tsx` | Nút bảng: tên nghiệp vụ/kỹ thuật, danh sách cột (giới hạn số cột hiển thị), điểm nối cho relationship, tô màu theo trạng thái. |
| `RelationshipEdge.tsx` | Cạnh tùy biến: đường nối có nhãn cardinality, kiểu nét theo trạng thái, `selfLoopPath` cho quan hệ tự tham chiếu. |
| `DiagramControls.tsx` | Nút điều khiển: phóng to/thu nhỏ, vừa khung, bố cục lại. |
| `DiagramLegend.tsx` | Chú giải màu/kiểu nét theo trạng thái relationship. |
