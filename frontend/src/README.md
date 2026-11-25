# `frontend/src/` — Mã nguồn ứng dụng

| Thư mục | Chức năng |
| --- | --- |
| [`app/`](app/README.md) | Route theo App Router: landing, đăng nhập/đăng ký, workspace, chấp nhận lời mời; layout và providers. |
| [`components/`](components/README.md) | Toàn bộ UI, chia theo miền (views, studio, schema-review, metrics, dashboard, modals, workspace, auth, landing, ui). |
| [`context/`](context/README.md) | React Context: đăng nhập, workspace đang chọn, ngôn ngữ, theme. |
| [`lib/`](lib/README.md) | Client REST (`api.ts`), SSE, helper miền (metric, dashboard, dimension, relationship, trace agent). |
| [`i18n/`](i18n/README.md) | Từ điển dịch Việt ↔ Anh. |
| [`test/`](test/README.md) | Setup và fixture dùng cho Vitest. |

## Quy ước

- Alias import `@/…` trỏ vào `src/`.
- Test đơn vị đặt **cạnh file** (`Component.test.tsx`, `module.test.ts`).
- Văn bản hiển thị đi qua `LanguageContext` / `Translated` để hỗ trợ tiếng Việt và tiếng Anh.
