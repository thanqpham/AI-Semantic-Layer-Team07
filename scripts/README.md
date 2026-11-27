# `scripts/` — Script tiện ích

Chạy từ **thư mục gốc repo** (có venv kích hoạt). Phần lớn là script phát triển/demo, không thuộc runtime của ứng dụng.

## Dữ liệu mẫu (Target DB)

| File | Chức năng chi tiết |
| --- | --- |
| `setup_target_db.py` | Tạo lại database `golden_retail_db` trên PostgreSQL: ngắt phiên cũ, `DROP DATABASE IF EXISTS` + `CREATE DATABASE`, rồi nạp `data/golden_retail_schema_pg.sql` và `golden_retail_seed_pg.sql`. **Xóa database cùng tên.** |
| `test_setup_target_db.py` | Unit test (unittest, mock) cho script trên. |
| `seed_data_generator.py` | Sinh DDL và dữ liệu giao dịch giả lập cho Golden Retail (36 bảng, ~5.000 orders). |
| `convert_to_postgres.py` | Chuyển schema/seed MySQL của Golden Retail sang cú pháp PostgreSQL. |
| `import_data.py` | Import CSV vào database (`CSV_DATA_DIR`). |
| `ecommerce_scale_seed.py` | Sinh seed ecommerce quy mô lớn cho database **mới, trống**. |
| `ecommerce_dashboard_demo_pg.sql` | Seed duy nhất cho demo dashboard (42 bảng, dữ liệu tài chính theo ngày/tháng) — xem `docs/ECOMMERCE_DASHBOARD_SEED.md`. |
| `ecommerce_append_500k.sql`, `ecommerce_append_1m.ps1` | Nối thêm dữ liệu synthetic lên 500k / 1M orders vào `ecommerce_dashboard_demo`; mặc định chạy thử và **rollback**, chỉ commit khi bật cờ apply. |
| `sync_supabase_to_local.py` | Đồng bộ dữ liệu từ Supabase PostgreSQL sang PostgreSQL cục bộ/VPS. |

## Đánh giá & kiểm tra

| File | Chức năng chi tiết |
| --- | --- |
| `verify_golden_results.py` | Sinh lại và kiểm kết quả kỳ vọng của một golden domain. |
| `run_manual_eval_cases.py` | Chạy các case đánh giá thủ công qua pipeline thật. |
| `generate_test_cases_excel.py` | Sinh bảng Excel test case (102 case) cho dự án. |
| `demo_on_demand_metric_suggest.py` | Demo `coordinator_node` đề xuất metric và hiển thị kết quả cho người dùng. |

## Hạ tầng & triển khai

| File / Thư mục | Chức năng chi tiết |
| --- | --- |
| `setup.sh` | Thiết lập môi trường khởi đầu: kiểm tra Python, `pip install -r requirements.txt`, tạo `.env` từ `.env.example`. |
| `migrate-prod.ps1` | Chạy `alembic upgrade head` lên database production: đọc `.env.production` (báo lỗi nếu thiếu), tạm ghi đè `DATABASE_URL` rồi chạy migration. **Tác động trực tiếp lên production** — chỉ chạy khi chắc chắn. |
| `tls/` | Demo TLS/mTLS cho Live DB: `gen_certs.sh` (sinh CA, server, client cert vào `tls/certs/` — **đã gitignore**), `pg_hba.conf`, `smoke_test.sh` (3 kiểm tra: `verify-full` + cert client phải thành công; sai CA phải thất bại; thiếu cert client phải thất bại). Dùng với `docker compose ... --profile tls-demo`. |

## Hook ghi log sử dụng AI (khóa học AI20K)

| File | Chức năng chi tiết |
| --- | --- |
| `setup_hooks.ps1`, `setup_hooks.sh` | Cài hook (pre-push) để tự ghi log sử dụng AI. |
| `log_hook.py` | Logger dùng chung cho Claude Code, Gemini CLI, Codex, Cursor, Copilot. |
| `log_manual.py` | Ghi log thủ công cho công cụ AI khác. |
| `log_codex.py`, `log_antigravity.py` | Khôi phục prompt từ transcript Codex / Antigravity IDE. |
| `submit_log.py` | Gửi `.ai-log/session.jsonl` lên server chấm. |
| `_pyrun.sh`, `_pyrun.cmd` | Launcher Python đa nền tảng cho hook (thử `python3` → `python` → `py -3`; không bao giờ làm hỏng công cụ AI nếu thiếu Python). |
| `format_on_edit.py` | Hook PostToolUse: tự `ruff format` file Python vừa sửa. |

> Theo AGENTS.md: **không** chạy script log thủ công sau mỗi task và **không** sửa/xóa `.ai-log/` — log được gửi tự động qua pre-push hook.
