# `components/modals/` — Hộp thoại

| File | Chức năng chi tiết |
| --- | --- |
| `ConnectDbModal.tsx` | Kết nối nguồn dữ liệu: nhập connection URL Live DB (hoặc username/password tách riêng), chọn dialect, cấu hình TLS (`prefer`/`require`/`verify_ca`/`verify_full`, CA/chứng chỉ client), hoặc **tải SQL Dump**; gọi `db/connect` / `import/saved`. |
| `SettingsModal.tsx` | Hộp thoại Cài đặt: các mục tài khoản/giao diện và nhúng `AISettingsSection`. |
| `AISettingsSection.tsx` | **Cài đặt AI theo tài khoản:** chọn provider, nhập API key (không hiển thị lại key đã lưu), tải danh sách model từ API provider hoặc nhập model ID, lưu cấu hình, xem/xóa usage. |
| `MetricModal.tsx` | Tạo/sửa metric thủ công hoặc từ đề xuất AI: tên, công thức (aggregate/ratio/formula), filter, kèm xem lịch sử phiên bản (`MetricVersion`). |
| `CreateWorkspaceModal.tsx` | Tạo workspace mới. |
| `WorkspaceManagementModal.tsx` | Quản lý workspace: thành viên, đổi vai trò, mời thành viên, hủy lời mời. |
| `SyncAuditLogsModal.tsx` | Nhật ký đồng bộ schema (`sync-logs`): trạng thái `success` / `healed` / `no_change` / `failed`, chi tiết thay đổi và tác động lên metric. |
