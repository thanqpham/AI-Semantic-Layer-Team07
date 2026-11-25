# `tests/fixtures/` — Dữ liệu mẫu cho test

| Thư mục | Nội dung |
| --- | --- |
| `compiler_postgres/01-reader.sql` | Khởi tạo **tài khoản chỉ đọc** `compiler_reader` cho PostgreSQL test (`GRANT CONNECT`, `USAGE`, `SELECT` mặc định) — được mount vào container của `infra/docker-compose.compiler-test.yml`. |
| `compiler_mysql/01-reader.sql` | Tương tự cho MySQL. |
| `sql_dumps/` | SQL dump mẫu để test scanner/parser: `postgresql_schema.sql`, `postgresql_dump_schema.sql`, `mysql_schema.sql`, `mysql_dump.sql`, `test_schema_dump.sql`, thư mục `source/`, và [`README.md`](sql_dumps/README.md) mô tả từng file. |
