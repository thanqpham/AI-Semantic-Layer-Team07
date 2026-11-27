# `components/dashboard/` — Dashboard kéo-thả

| File | Chức năng chi tiết |
| --- | --- |
| `DashboardGrid.tsx` | Lưới widget kéo-thả (`@dnd-kit`): sắp xếp lại (`reorderWidgets`), độ rộng theo cột (`widthToSpanClass`). |
| `DashboardCard.tsx` | Khung một widget: tiêu đề, trạng thái tải/lỗi/rỗng, menu sửa/xóa, chọn kiểu hiển thị. |
| `DashboardChart.tsx` | Vẽ biểu đồ theo `DashboardChartType` (`kpi`, `line`, `area`, `bar`, `pie`, `table`) bằng Recharts. |
| `DashboardMultiSeriesChart.tsx` | Biểu đồ nhiều chuỗi (so sánh metric), trục dùng chung (`ChartAxes`). |
| `WidgetConfigModal.tsx` | Hộp thoại thêm/sửa widget với bản xem trước trực tiếp. |
| `WidgetConfigFields.tsx` | Các trường cấu hình: chọn metric (`MetricPicker`, `MetricComparePicker`), dimension, bộ lọc ngày, gợi ý widget, bố cục. |
| `widgetConfigForm.ts` | Trạng thái form (`WidgetFormState`), nhãn loại biểu đồ/độ rộng/độ cao/grain, chuyển form ↔ cấu hình widget. |
| `useWidgetConfigMeta.ts` | Hook nạp metadata cần cho form (dimension/filter khả dụng của metric). |
| `useDashboardWidgetData.ts` | Hook lấy dữ liệu widget: gọi `query`, cache payload (`clearDashboardPayloadCache`), trạng thái `DashboardWidgetStatus`. |
| `dashboardQuery.ts` | Dựng query cho widget, **giới hạn số truy vấn đồng thời** (`MAX_CONCURRENT_WIDGET_QUERIES`) và số dòng (`WIDGET_ROW_LIMIT`), chọn grain hiệu lực. |
| `dashboardFormatters.ts` | Định dạng số/ngày kiểu Việt (`formatNumberVi`, `formatShortNumber`), nhãn cột, giá trị dimension, giới hạn lát biểu đồ tròn/xếp hạng. |

Mô hình dữ liệu và API: [`lib/dashboard.ts`](../../lib/README.md), `lib/dashboardApi.ts`.
