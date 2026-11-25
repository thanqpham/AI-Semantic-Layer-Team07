# `frontend/src/context/` — React Context

| File | Hook | Chức năng chi tiết |
| --- | --- | --- |
| `AuthContext.tsx` | `useAuth` | Giữ người dùng hiện tại và token (lưu cookie, dự phòng localStorage, qua `lib/jwt.ts`); `login`, `register`, `loginWithGoogle`, `logout`; **làm mới access token** bằng refresh token (`refreshAccessToken`) và tải hồ sơ người dùng (`fetchUserProfile`) khi khởi động. |
| `WorkspaceContext.tsx` | `useWorkspace` | Danh sách workspace (`workspaces`), workspace đang chọn (`currentWorkspace`), vai trò (`role`) và bảng quyền (`permissions`) của người dùng trong workspace đó; `switchWorkspace`, `reloadWorkspaces`, `createWorkspace`. UI dựa vào `permissions` để ẩn/hiện chức năng theo RBAC. |
| `LanguageContext.tsx` | `useLanguage` | Ngôn ngữ giao diện `vi`/`en`, tra cứu chuỗi trong `i18n/catalog.json`. |
| `ThemeContext.tsx` | `useTheme` | Chủ đề sáng/tối (đặt `data-theme`, ghi nhớ lựa chọn). |

Các provider được lắp trong [`../app/providers.tsx`](../app/README.md).
