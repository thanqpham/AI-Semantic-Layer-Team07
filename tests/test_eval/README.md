# `tests/test_eval/` — Test seed và benchmark dữ liệu

| File | Kiểm tra |
| --- | --- |
| `test_ecommerce_scale_seed.py` | Script `scripts/ecommerce_scale_seed.py` sinh seed quy mô lớn cho database **mới, trống**. |
| `test_ecommerce_append_500k.py`, `test_ecommerce_append_1m.py` | Các script SQL/PowerShell nối thêm 500k / 1M dòng ecommerce. |
| `test_relationship_benchmark.py` | `eval/relationship_benchmark.py` (kết quả mock không phải kết quả benchmark LLM). |
