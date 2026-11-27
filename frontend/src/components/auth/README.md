# `components/auth/` — Xác thực

| File | Chức năng chi tiết |
| --- | --- |
| `auth-form.tsx` | `AuthForm`: form dùng chung cho `/login` và `/register` — email/username, mật khẩu (tối thiểu 8 ký tự khi đăng ký), nút **Đăng nhập bằng Google** (`@react-oauth/google`), hiển thị lỗi, chuyển hướng sau khi thành công. Gọi `useAuth` (`login`, `register`, `loginWithGoogle`). |
