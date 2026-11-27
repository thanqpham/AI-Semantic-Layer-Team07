# `frontend/` — Giao diện web (Next.js 16)

Ứng dụng một-trang theo App Router: landing, đăng nhập/đăng ký, **workspace** (sáu view làm việc) và trang chấp nhận lời mời. Giao tiếp với backend qua REST + SSE (`NEXT_PUBLIC_API_URL` hoặc `NEXT_PUBLIC_API_BASE_URL`).

**Stack:** Next.js 16.2, React 19, TypeScript, Tailwind CSS 4, `@xyflow/react` + dagre (sơ đồ), `@dnd-kit` (kéo-thả dashboard), Recharts (biểu đồ), `react-markdown` + `remark-gfm`, `yaml`, `@react-oauth/google`. Test: Vitest + Testing Library, Playwright.

## Chạy

```bash
npm install
npm run dev          # http://localhost:3000
npm run build && npm start
npm run lint         # ESLint
npm test             # Vitest (jsdom)
npm run test:e2e     # Playwright (tự khởi động `npm run dev` nếu chưa chạy)
```

## Cấu trúc

| Đường dẫn | Chức năng |
| --- | --- |
| [`src/`](src/README.md) | Toàn bộ mã nguồn ứng dụng (route, component, context, lib, i18n). |
| [`e2e/`](e2e/README.md) | Test end-to-end Playwright. |
| `public/` | Tài nguyên tĩnh (các SVG mặc định của Next). |
| `package.json`, `package-lock.json` | Phụ thuộc và script. |
| `next.config.ts` | Cấu hình Next. |
| `tsconfig.json` | Cấu hình TypeScript (alias `@/` → `src/`). |
| `eslint.config.mjs` | Cấu hình ESLint (`eslint-config-next`). |
| `postcss.config.mjs` | PostCSS + `@tailwindcss/postcss`. |
| `vitest.config.mts` | Cấu hình Vitest (jsdom, setup tại `src/test/setup.ts`). |
| `playwright.config.ts` | Playwright: `testDir: ./e2e`, project Chromium, `PLAYWRIGHT_BASE_URL` (mặc định `http://localhost:3000`), tái sử dụng dev server đang chạy. |
| `Dockerfile` | Build image production (multi-stage, Node 20); nhận build-arg `NEXT_PUBLIC_*`. |

## Biến môi trường (build-time)

| Biến | Ý nghĩa |
| --- | --- |
| `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_API_BASE_URL` | URL backend (`src/lib/api.ts` ưu tiên biến đầu). |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Client ID đăng nhập Google. |

> `NEXT_PUBLIC_*` được nhúng vào bundle lúc build, vì vậy không đặt giá trị bí mật vào đây.
