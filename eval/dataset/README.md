# `eval/dataset/` — Nạp và kiểm tra Golden Dataset

Golden Dataset (`../golden_dataset/<domain>/`) là dữ liệu chuẩn có phiên bản dùng để chấm điểm agent. Thư mục này nạp nó và **kiểm tra tính toàn vẹn trước khi chấm**.

| File | Chức năng chi tiết |
| --- | --- |
| `models.py` | Contract Pydantic **strict** cho mọi artifact: `DomainManifest`, `ManifestCaseFiles`, `DiscoveryCase`/`DiscoveryCaseExpected`, `MetricDefinitionCase` (+ `ExpectedMetricDefinition`, `ExpectedMetricFilter`, `MetricDefinitionCaseContext`), `RelationshipExpectation`, `RetrievalExpectation`, `TimeFilterExpectation`, query/guardrail case… Kế thừa `StrictModel` (cấm field lạ). |
| `loader.py` | `load_domain_dataset(domain)` → `DomainDataset`: nạp bất đồng bộ manifest, schema thô, canonical (entities/metrics/glossary), các file `cases/*.json` và kết quả kỳ vọng. |
| `validator.py` | `validate_domain_files`, `validate_discovery_cases`, `validate_metric_cases`, `validate_query_cases`, `validate_guardrail_cases`, các hàm `validate_*_references` (mọi tham chiếu chéo phải trỏ tới thực thể canonical có thật) và `validate_read_only_sql` (SQL mẫu phải parse được bằng sqlglot và chỉ là `SELECT`). Lỗi ném `DatasetValidationError`. |

Cấu trúc dữ liệu: xem [`../golden_dataset/README.md`](../golden_dataset/README.md).
