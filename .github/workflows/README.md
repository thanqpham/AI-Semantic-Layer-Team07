# `.github/workflows/` — CI/CD

| File | Tên | Chức năng chi tiết |
| --- | --- | --- |
| `main.yml` | CI/CD Pipeline | **Điểm vào.** Kích hoạt khi `push`/`pull_request` vào `main` hoặc `dev` và thủ công (`workflow_dispatch`). Chạy: `test` (luôn) → `build` (chỉ khi `push` lên `main`/`dev`) → `deploy` (GitOps handoff, chỉ khi backend hoặc frontend có thay đổi). Job `security` đang được **comment tắt**. |
| `test.yml` | Lint & Unit Tests | Workflow tái sử dụng: Python 3.11, cài `requirements-dev.txt`, `ruff check src/ tests/`, `pytest tests/` (bỏ qua `test_compiler_cross_database_live.py`, `APP_ENV=test`); thêm job **compiler-live-integration** chạy compiler trên PostgreSQL/MySQL thật. |
| `build.yml` | Build & Push Images | Nhận diện thay đổi (`dorny/paths-filter`: backend/frontend), build và push image backend/frontend, xuất `image_tag` và cờ `backend_changed` / `frontend_changed`. |
| `gitops.yml` | GitOps Sync | Checkout repo `cloud-infra` và cập nhật tag image trong `values.yaml` có điều kiện (chỉ thành phần có thay đổi) để triển khai. Cần secret `GITOPS_TOKEN`. |
| `security.yml` | Security Scan | `gitleaks` (quét secret) và job SAST + audit phụ thuộc (Bandit, pip-audit). Hiện chưa được `main.yml` gọi. |
