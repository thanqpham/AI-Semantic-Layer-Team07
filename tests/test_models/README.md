# `tests/test_models/` — Test ORM và contract

| File | Kiểm tra |
| --- | --- |
| `test_db_models.py` | ORM: ràng buộc CHECK (vai trò, trạng thái), quan hệ, giá trị mặc định. |
| `test_pydantic_schemas.py` | Request/response trong `schemas.py` (validate, giới hạn `limit`, từ chối tổ hợp không hợp lệ). |
| `test_metric_definition.py` | `MetricDefinition` v2: aggregate, ratio, formula, filter, grain, plan. |
| `test_dedupe_contracts.py` | Contract dedupe metric. |
| `test_raw_schema.py` | Contract `RawSchema`. |
| `test_schema_metadata.py` | `RawSchemaMetadata`: chuẩn hóa định danh, diagnostics. |
