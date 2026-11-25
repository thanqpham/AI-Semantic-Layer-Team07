# `frontend/src/app/` — Route (App Router)

| Đường dẫn | URL | Chức năng chi tiết |
| --- | --- | --- |
| `layout.tsx` | — | Layout gốc: metadata (tiêu đề "AI Semantic Layer Agent — Governance Platform"), font Instrument Sans / Instrument Serif / JetBrains Mono, bao `Providers`. |
| `providers.tsx` | — | Lắp provider toàn cục theo thứ tự `LanguageProvider` → `GoogleOAuthProvider` → `ThemeProvider` → `AuthProvider` → `WorkspaceProvider`. |
| `globals.css` | — | Tailwind 4, token màu sáng/tối, style nền. |
| `page.tsx` | `/` | Landing page: ghép các section trong `components/landing/`. |
| `(auth)/login/page.tsx` | `/login` | Đăng nhập (email/mật khẩu hoặc Google) bằng `AuthForm`. |
| `(auth)/register/page.tsx` | `/register` | Đăng ký tài khoản. |
| `workspace/page.tsx` | `/workspace` | Vào ứng dụng chính: yêu cầu đăng nhập, render `WorkspaceApp`. |
| `invite/[token]/page.tsx` | `/invite/{token}` | Xem trước và chấp nhận lời mời vào workspace. |
| `favicon.ico` | — | Icon. |

`page.test.tsx` và `workspace/page.test.tsx` là test cạnh route.
