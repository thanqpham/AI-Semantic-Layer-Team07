# Evaluation Framework (Khung đánh giá)

Khung đánh giá **deterministic** (tính toán xác định, không ngẫu nhiên) và **có version**
cho AI Semantic Layer Agent. Khung này chấm điểm các output do agent sinh ra — schema
discovery, enrichment, sinh metric, biên dịch query, và SQL guardrails — dựa trên một
**Golden Dataset** kết quả kỳ vọng, dùng precision/recall/F1 và text similarity tiếng Việt
thay vì đánh giá tự do bằng LLM.

> **Phạm vi PR này (chỉ phần framework):** package `eval/dataset/` và `eval/evaluator/`
> cùng các unit test pure-logic. Golden Dataset fixture và các integration test phụ thuộc
> golden nằm ở PR golden-data xếp chồng (`eval/golden_dataset/`).

---

## Kiến trúc

Hai lớp độc lập, đều async và có type hint đầy đủ.

### 1. Lớp Dataset — `eval/dataset/`

Tải và validate một domain Golden Dataset có version. Mọi contract đều là Pydantic model
strict, frozen (`extra="forbid"`).

| Module | Trách nhiệm |
|--------|-------------|
| `models.py` | Các contract strict: `DomainManifest` và 4 loại case (`DiscoveryCase`, `MetricDefinitionCase`, `QueryCase`, `GuardrailCase`), định nghĩa canonical cho entity/metric/dimension/relationship, và `QueryReferenceCatalog`. Mọi artifact đều mang `dataset_version` + `contract_version`. |
| `loader.py` | `load_domain_dataset(golden_root, domain)` (async) → `DomainDataset`. Tải manifest, 4 bộ case, canonical YAML registry, raw schema, và kết quả query kỳ vọng, sau đó chạy cross-validation đầy đủ. Các tham chiếu đường dẫn được bảo vệ chống path-traversal. |
| `validator.py` | Validate tính toàn vẹn, tham chiếu chéo, và **SQL AST read-only** bằng `sqlglot`. Ép buộc case_id duy nhất toàn cục, dialect coverage khớp manifest, số metric ground-truth khớp registry, chỉ cho phép đúng một `SELECT` không có side-effect, và cấm các hàm nguy hiểm. |

### 2. Lớp Evaluator — `eval/evaluator/`

Chấm điểm các output của agent (candidate output) một cách deterministic so với dataset đã tải.

| Module | Trách nhiệm |
|--------|-------------|
| `schemas.py` | Evaluation contract **v2.0.0**: `EvaluationConfig` (ngưỡng + giới hạn an toàn) và mọi contract kết quả (`MatchCounts`, `PrecisionRecallF1`, `FieldScore`, `CaseEvaluationResult`, `SuiteEvaluationResult`, `GroupScore`, `DomainEvaluationResult`), cùng contract cho candidate output (`CandidateEnrichmentOutput`, `CandidateMetricOutput`, `CandidateCompilerOutput`, `CandidateGuardrailOutput`, `DomainCandidateOutputs`). |
| `scoring.py` | Set matching, precision/recall/F1 (có chính sách zero-division cho tập rỗng được tài liệu hóa rõ), micro/macro averaging, và phát hiện trùng lặp. |
| `text_similarity.py` | So sánh tên tiếng Việt: exact (chuẩn hóa NFC), fuzzy (accent-insensitive bằng `SequenceMatcher`), và một semantic provider tùy chọn có thể inject qua `compare_business_name()`. |
| `sql_normalization.py` | Parse và chuẩn hóa SQL fail-closed bằng `sqlglot`: `normalize_sql()`, `structurally_equal()` (bỏ qua format và alias có thể bỏ đi), `effective_limit()`, và ép buộc read-only. |
| `execution.py` | Thực thi `SELECT` được guard trong SQLite in-memory cô lập: `execute_guarded_sql()` (statement timeout qua progress handler, validate LIMIT/timeout) và `compare_query_result()` (theo thứ tự hoặc multiset, với dung sai float). |
| `aggregation.py` | `build_suite_result()` tổng hợp kết quả từng case thành một `SuiteEvaluationResult` đầy đủ provenance (micro, macro, và group score theo tag). |
| `discovery_eval.py` | Suite đánh giá độ chính xác trích xuất schema ở Stage 1 — chấm tables, columns, primary keys, relationships bằng PRF1 (`evaluate_discovery_suite`). |
| `enrichment_eval.py` | Suite đánh giá enrichment entity/dimension/relationship ở Stage 2. |
| `metric_eval.py` | Suite đánh giá sinh định nghĩa metric ở Stage 3 (ngôn ngữ tự nhiên → `CanonicalMetric`). |
| `compiler_eval.py` | Suite đánh giá biên dịch canonical-query và SQL guardrail ở Stage 4 (`evaluate_compiler_suite`, `evaluate_guardrail_suite`, `GuardrailAdapter`). |
| `domain_eval.py` | Orchestrator. `evaluate_domain_suite()` chạy các suite enrichment, metric, compiler, guardrail và lắp thành `DomainEvaluationResult`; `EvaluationDependencies` inject `TextSimilarityProvider` và `GuardrailAdapter` (tùy chọn). |

### Ánh xạ lifecycle Canonical-model

```
Stage 1  Discovery   (độ chính xác introspect schema)         → discovery_eval
Stage 2  Enrichment  (đặt tên nghiệp vụ, dim, relationship)   → enrichment_eval
Stage 3  Metric      (ngôn ngữ tự nhiên → CanonicalMetric)    → metric_eval
Stage 4  Query       (NL → CanonicalQueryModel → SQL)         → compiler_eval + guardrails
```

> `evaluate_domain_suite()` nối Stage 2–4 và guardrail. Stage 1
> (`evaluate_discovery_suite`) là suite live-mode độc lập.

---

## Public API

```python
from pathlib import Path

from eval.dataset.loader import load_domain_dataset
from eval.evaluator import (
    EvaluationConfig,
    EvaluationDependencies,
    evaluate_domain_suite,
)

dataset = await load_domain_dataset(Path("eval/golden_dataset"), "ecommerce")
deps = EvaluationDependencies(config=EvaluationConfig())
result = await evaluate_domain_suite(dataset, candidates, deps)

result.enrichment  # SuiteEvaluationResult
result.metrics  # SuiteEvaluationResult
result.compiler  # SuiteEvaluationResult
result.guardrails  # SuiteEvaluationResult
```

---

## Nguyên tắc thiết kế

- **Deterministic và không dùng LLM.** Việc chấm điểm dựa trên PRF1 và text similarity.
  Semantic similarity là tùy chọn và được inject — **không** được gọi mặc định, nên
  evaluation không phụ thuộc OpenAI.
- **Contract có version để tái lập.** Contract của dataset và evaluation đều pin theo
  semver, mỗi domain ghi lại `frozen_evaluation_date`.
- **An toàn fail-closed.** `SELECT` read-only được ép buộc bằng `sqlglot` AST ở cả lúc
  validate dataset lẫn lúc thực thi; thực thi chạy trong SQLite in-memory cô lập, có
  statement timeout và `LIMIT` giới hạn trong `[1, 1000]`.
- **Model strict, frozen** (`extra="forbid"`) để loại fixture sai định dạng sớm.
- **Async xuyên suốt** — loader, evaluator, và execution đều là `async`.

---

## Cách chạy đánh giá

### Yêu cầu trước

- **Python 3.11.**
- Cài dependency: `pip install -r requirements-dev.txt` (đã bao gồm runtime deps cùng `ruff`, `pytest`, `pyyaml`, `sqlglot`).
- `pytest.ini` đặt `pythonpath = .`, nên `pytest` tự thấy package `eval`/`src`. Khi chạy **script riêng** (không qua pytest), hãy chạy từ **thư mục gốc repo** để `import eval` hoạt động.
- **Golden Dataset** phải nằm ở `eval/golden_dataset/<domain>/` — thuộc PR golden-data xếp chồng. Nếu chỉ có PR framework này thì `load_domain_dataset` sẽ báo thiếu dataset (điều này bình thường).

### 1) Kiểm tra framework

```bash
pytest tests/test_evaluation/ -v   # 35 test case pure-logic, không cần Golden Dataset
ruff check src/ tests/ eval/       # lint (eval/ cũng nằm trong phạm vi)
```

### 2) Chạy đánh giá trên một domain

File [`eval/run_eval.py`](run_eval.py) đã wire sẵn luồng đầy đủ — **load dataset → dựng
candidate outputs → `evaluate_domain_suite` → in PRF1 micro**. Chạy từ thư mục gốc repo:

```bash
python -m eval.run_eval --domain ecommerce
```

Mặc định runner dùng candidate outputs rỗng (placeholder), nên mọi case báo
`not_available`. Để chấm một run thật, thay hàm `_placeholder_candidates()` trong file bằng
candidate outputs do agent sinh ra (Stage 2–4), key khớp `case_id` của dataset:

```python
candidates = DomainCandidateOutputs(
    enrichment={...},  # dict[str, CandidateEnrichmentOutput]
    metrics={...},  # dict[str, CandidateMetricOutput]
    compiler={...},  # dict[str, CandidateCompilerOutput]
)
```

> `DomainCandidateOutputs` là model strict (`extra="forbid"`). Khi không cung cấp
> `guardrail_adapter`, suite guardrail trả `status="not_available"` cho mọi case.

### 3) Stage 1 — Discovery (live mode, tùy chọn)

`evaluate_discovery_suite` chấm riêng độ chính xác introspect schema (Stage 1), độc lập
với `evaluate_domain_suite`:

```python
from eval.evaluator.discovery_eval import CandidateDiscoveryOutput, evaluate_discovery_suite
```

---

## Kiểm thử

Sáu module test pure-logic trong `tests/test_evaluation/` (35 test case), **không phụ thuộc
Golden Dataset**, nên framework verify độc lập:

| Test | Phủ |
|------|-----|
| `test_dataset_validation` | Hành vi validator: SQL read-only, tham chiếu, ID duy nhất. |
| `test_evaluator_schemas` | Validate contract kết quả/config của evaluation. |
| `test_execution_safety` | Thực thi SQLite có guard, timeout, ép LIMIT, so sánh kết quả. |
| `test_scoring` | PRF1, set matching, micro/macro averaging, chính sách tập rỗng. |
| `test_sql_normalization` | So sánh cấu trúc, chuẩn hóa alias, ép read-only. |
| `test_text_similarity` | Logic NFC/fuzzy/semantic tiếng Việt và ngưỡng chấp nhận. |

Cách chạy xem mục [Cách chạy đánh giá](#cách-chạy-đánh-giá) — Bước 1.

---

## Hybrid evaluator (bật bằng flag)

Chạy hybrid engine kiểu Ragas (metric deterministic + AI judge tùy chọn) trên
golden dataset, trong khi evaluator legacy vẫn là mặc định:

```bash
python -m eval.run_eval --domain ecommerce --engine hybrid            # smoke, không chạy judge
python -m eval.run_eval --domain ecommerce --engine hybrid --judge    # kèm lane AI judge
```

`--judge` dùng cấu hình `JUDGE_*` riêng. Provider, model và API key của judge
phải khác với LLM của Agent ở từng mục; thiếu giá trị hoặc trùng giá trị sẽ
dừng run trước mọi lời gọi API. Không có cơ chế fallback sang credential của
Agent. Temperature của judge luôn là `0.0`.

Report được ghi vào `--report-dir` (mặc định `eval/reports/hybrid`) gồm
`report.json` (contract đầy đủ), `report.csv` (mỗi sample một dòng) và
`report.md` (tóm tắt). Trạng thái tuân theo gate của spec: PASS ≥ 90, WARN
80–90, FAIL khi rơi critical-gate hoặc điểm < 80, INCOMPLETE khi coverage
< 95% hoặc evidence gate chặn điểm. Khi không dùng `--judge`, các metric judge
được báo `not_applicable` và loại khỏi coverage cũng như trọng số suite.
`--run-type` chọn luật evidence cho smoke/benchmark/release: metric judge hoàn
toàn `not_applicable` luôn được miễn khỏi kiểm required-metric, còn metric
deterministic chỉ được miễn trong run `smoke` — `benchmark` và `release` đòi
bằng chứng deterministic để điểm hợp lệ. Engine legacy vẫn là mặc định
(`--engine legacy`).

### 4) Nguồn agent (agent_live)

`--source agent` thay các smoke candidate suy ra từ golden bằng candidate thu
thập **trực tiếp từ pipeline `src/` thật** (bootstrap → introspection →
enrichment → sinh metric → biên dịch), rồi đưa vào hybrid engine. Cần kèm
`--engine hybrid` (engine khác sẽ bị `parser.error`, exit 2). Engine legacy và
nguồn smoke giữ nguyên — `--source smoke` vẫn là mặc định:

```bash
.venv/Scripts/python.exe -m eval.run_eval --engine hybrid --source agent --domain ecommerce
.venv/Scripts/python.exe -m eval.run_eval --engine hybrid --source agent --query-mode oracle --domain ecommerce
```

**Cần `LLM_*` trong `.env`** — khác với nguồn smoke, lane này gọi boundary
`get_llm()` thật nên không thể chạy khi thiếu credential. Suite guardrail vẫn
offline: nó tái dụng read-only validator của sản phẩm qua
`ProductionGuardrailAdapter` và không bao giờ thực thi SQL. Các quyết định
guardrail đã thu được lưu trong `candidates.json` và truyền vào engine qua
mapping `guardrail` của request — kwarg `guardrail_adapter` chỉ phục vụ lane
thực thi của compiler, nên thiếu mapping thì suite guardrail sẽ bị chấm 0.0
kèm cảnh báo "no candidate response".

Mỗi run ghi vào một thư mục dùng-một-lần riêng (mặc định
`eval/runs/agent-<domain>-<UTC timestamp>`, ghi đè bằng `--run-dir`; thư mục
không được chứa sẵn file — `prepare_run` từ chối run dir không rỗng thay vì
trộn artifact của các run khác):

```
<run_dir>/
├── target.sqlite      # target DB dùng một lần, dựng từ golden sources
├── metadata.sqlite    # metadata store cô lập (eval user riêng, không secret)
├── candidates.json    # mọi candidate đã thu + run manifest
└── reports/           # report.json, report.csv, report.md
```

Lưu ý khi đọc kết quả:

- **Chuẩn hóa SQL cho lane thực thi:** connector bóc qualifier namespace
  `__default__` của sản phẩm (placeholder của compiler cho target không có
  schema như SQLite; fixture của engine không có schema) và inline các bind
  parameter có tên của compiler (`:runtime_N`, `:metric_N`) thành literal, lấy
  giá trị từ `CompiledQuery.parameters` — chính bind map của compiler. Lane
  SQLite của engine thực thi chuỗi SQL thô không bind tham số, nên thiếu bước
  chuẩn hóa serialization này thì mọi compiled query đều fail EXECUTION_FAILED
  dù đúng đến đâu. Ngữ nghĩa truy vấn không đổi.
- **`run_type=smoke` cho đến khi golden dataset được duyệt** — giữ mặc định
  `--run-type smoke` đến khi golden dataset qua review; `benchmark` và
  `release` áp dụng luật evidence chặt hơn.
- **Oracle mode chỉ dùng để debug.** `--query-mode oracle` đưa selection
  ground-truth vào compiler để tách lỗi compiler khỏi chất lượng resolver;
  `--query-mode resolver` mặc định là đường end-to-end trung thực.
- **Exit code:** `0` cho PASS/WARN, `1` cho các trường hợp còn lại.
- **Contract gap (thiếu hụt vĩnh viễn đã công bố, spec §9.1 / decision D6):**
  contract của eval không có biểu diễn rỗng cho các trường metric
  `business_formula` và `default_time_grain` (Literal `TimeGrain` không nhận
  giá trị rỗng), còn pipeline deterministic không thể sinh giá trị có nghĩa cho
  cả hai — `business_formula` luôn nộp rỗng và `default_time_grain` luôn là
  placeholder `"day"`. Run manifest trong `candidates.json` ghi cả hai trường
  dưới `contract_gaps`, và engine chấm các trường này `not_applicable` (loại
  khỏi coverage và trọng số suite) khi run khai báo chúng qua
  `contract_gap_fields` — chúng là **artifact của contract, không phải chất
  lượng agent**, và không còn kéo điểm xuống.
- **ORDER BY là trình bày, không phải ngữ nghĩa (lane AST):** SQL golden luôn
  mang `ORDER BY <dim>` (để fixture tất định) trong khi compiler của sản phẩm
  không bao giờ phát, và lane thực thi đã so multiset hàng (`ordered=False`).
  Vì vậy `structurally_equal(..., ignore_limit=True)` bóc ORDER BY và LIMIT
  top-level khỏi cả hai phía — query chỉ khác nhau về thứ tự/limit giờ so
  thuần ngữ nghĩa. Đường so sánh mặc định
  (guardrail/`effective_limit`) không đổi.
- **Phạm vi entity của resolver, abstain, sàng lọc intent phá hoại:** catalog
  resolver liệt kê mỗi dimension kèm tên nghiệp vụ của bảng chứa nó
  (`entity.column — business name (bảng: ...)`), system prompt yêu cầu
  dimension phải thuộc entity của metric đã chọn, chọn sai entity được thử lại
  tối đa 2 lần kèm phản hồi sửa lỗi, hết lượt thì fail closed với
  `RESOLVER_SCOPE_VIOLATION`. LLM được phép abstain
  (`{"metrics": [], "abstain": true}` → `UNKNOWN_METRIC`), và câu hỏi mở đầu
  bằng động từ phá hoại (xóa/hủy/drop/delete/truncate/alter/insert/update,
  không phân biệt dấu thanh) bị từ chối `UNSAFE_INTENT` trước mọi lời gọi LLM.
  Bằng chứng: cả 32 query case golden đều dùng dimension cùng entity; chỉ case
  032 khớp sàng lọc động từ phá hoại.
- **Judge prompt nhận biết contract gap:** các trường khai báo trong
  `contract_gap_fields` (hiện là `business_formula`) không được render vào
  prompt judge — judge chỉ chấm các tín hiệu thật còn lại (`description`,
  `sql_expression`). Điều này phản chiếu chính sách `not_applicable` của lane
  deterministic cho cùng gap; khi pipeline sau này sinh được trường này, nó
  được bỏ khỏi `CONTRACT_GAPS` và chấm lại mà không cần sửa code (bump prompt
  version thành `business-definition-v2` / `formula-semantics-v2`).
- **Artifact đặt tên enrichment (ĐÃ XỬ LÝ):** định danh
  entity/dimension/relationship giờ được phân giải về tên canonical qua
  `CanonicalResolver` (ánh xạ exact canonical-name từ registry kèm
  provenance), nên chấm agent-live enrichment so canonical-với-canonical thay
  vì phạt lệch PHYSICAL-vs-CANONICAL. Mỗi lần phân giải đều kiểm toán được qua
  log `identity_resolutions` trong `candidates.json`.

### 5) Chấm lại một run có sẵn (không dùng LLM)

`--rescore <run_dir>` nạp lại `candidates.json` của một run và chạy lại hybrid
engine với lớp chấm điểm hiện tại — không thu thập lại, không LLM. Report được
ghi vào `<run_dir>/reports-rescore/`. Dùng để tách thay đổi của lớp chấm điểm
khỏi lớp thu thập, và cho các thử nghiệm what-if hoàn nguyên được trên kỳ vọng
golden (sửa một bản copy golden, rescore, revert).

Lưu ý: rescore dùng **CLI flag hiện tại**, không phải flag của run gốc — một
run thu dưới `--run-type release` mà rescore không kèm flag sẽ bị đánh giá
bằng luật gate `smoke` mặc định và có thể lật kết quả gate, nên hãy truyền
`--run-type` tường minh khớp với lần thu gốc.

---

## Các metric đánh giá

Khung đánh giá đo bằng hai lớp: **suite evaluator** legacy (chấm từng case theo
component `FieldScore`) và **hybrid engine** (danh bạ metric "đóng băng" kèm
trọng số — ngưỡng; đây là các metric xuất hiện trong `report.md` của hybrid
run). Cả hai dùng chung bộ nguyên thủy tính điểm dưới đây.

### Nguyên thủy tính điểm — `evaluator/scoring.py`

Mọi metric so tập hợp đều quy về **Precision / Recall / F1**:

- `precision = TP / (TP + FP)` — trong số những gì agent đưa ra, bao nhiêu là đúng.
- `recall = TP / (TP + FN)` — trong số kỳ vọng của golden, agent tìm được bao nhiêu.
- `F1 = 2·P·R / (P + R)`.
- Chính sách tập rỗng: predicted rỗng → precision = 1.0; expected rỗng →
  recall = 1.0; hai tập rỗng là khớp hoàn toàn (F1 = 1.0).

Các helper chính:

- `match_sets` — so kiểu **tập hợp**, không tính thứ tự. Giá trị lặp không làm
  tăng FP nhưng được báo cáo riêng (`duplicates`) và khiến case không được coi
  là khớp hoàn toàn dù F1 = 1.0.
- `match_allowed_dimensions` — dimension thừa nhưng hợp lệ chỉ bị tính tối đa
  **1 FP** (soft penalty; dùng cho `allowed_dimension_f1`).
- **micro** — cộng dồn TP/FP/FN của mọi case rồi tính PRF1 trên tổng (case lớn
  nặng hơn); **macro** — trung bình cộng điểm (mọi case nặng như nhau).

### So sánh text tiếng Việt — `evaluator/text_similarity.py`

Một tên nghiệp vụ được **chấp nhận** khi: `exact HOẶC fuzzy ≥ 0.85 HOẶC
semantic ≥ 0.85` (ngưỡng nằm trong `EvaluationConfig`):

- **Exact** — chuẩn hóa NFC + casefold + bỏ dấu câu/khoảng trắng rồi so bằng.
- **Fuzzy** — `SequenceMatcher`, lấy max của bản có dấu và bản bỏ dấu thanh
  (accent-insensitive): `"Doanh thu." ≈ "doanh thu"`.
- **Semantic** — provider tùy chọn inject vào; không có thì bỏ qua, không fail.

### So sánh SQL — `evaluator/sql_normalization.py`

- `structurally_equal` — so **AST sqlglot** sau chuẩn hóa: bỏ alias, bỏ format,
  viết lại boolean (`FALSE` → `0`); với `ignore_limit=True` còn bỏ `LIMIT` và
  `ORDER BY` top-level của cả hai phía (dùng ở lane compiler vì LIMIT là
  guardrail được ép thêm còn ORDER BY chỉ là trình bày — lane thực thi đã so
  multiset hàng).
- `normalize_expression` — chuẩn hóa biểu thức SQL của trường metric/filter.
- `unwrap_declared_aggregation` — bóc đúng **một** wrapper aggregation khi và
  chỉ khi khớp `aggregation` khai báo của chính phía đó: golden `SUM(x)`
  (khai báo `sum`) tương đương candidate `x`; wrapper mâu thuẫn với khai báo
  bị giữ nguyên để mismatch trung thực.

### Danh bạ metric hybrid — `evaluator/hybrid/catalog.py`

Năm suite, mỗi suite có trọng số và ngưỡng riêng. Mỗi metric có `threshold`
(đạt khi điểm ≥ ngưỡng; đa số 0.95, riêng `formula_equivalence` và
`business_name_similarity` là 0.85, metric judge là 0.80, guardrail là 1.0),
`weight` (trọng số trong suite) và `prerequisites` (metric phải chạy được
trước).

| Suite | Trọng số | Ngưỡng suite | Metric |
|---|---:|---:|---|
| `discovery` | 0.15 | 0.95 | 6 deterministic |
| `enrichment` | 0.20 | 0.85 | 4 deterministic + 1 AI-judge |
| `metric_generation` | 0.25 | 0.85 | 5 deterministic + 2 AI-judge |
| `query_compilation` | 0.25 | 0.90 | 6 deterministic |
| `guardrail` | 0.15 | 0.95 | 5 deterministic (ngưỡng 1.0) |

#### Suite `discovery` — độ trung thực trích xuất schema

| Metric | Trọng số | Ý nghĩa | Cách tính |
|---|---:|---|---|
| `table_precision` / `table_recall` | 0 | Báo cáo bổ sung (đã bao hàm trong F1) | P/R của tập tên bảng |
| `table_f1` | 0.40 | Nhận diện đúng các bảng | F1 của tập tên bảng |
| `column_f1` | 0.30 | Đủ cột trong từng bảng | Micro-F1: so tập cột từng bảng golden rồi gộp |
| `primary_key_accuracy` | 0.15 | Nhận diện đúng khóa chính | F1 của tập PK theo từng bảng |
| `relationship_f1` | 0.15 | Nhận diện đúng quan hệ FK | F1 của tập tuple `(from_table, from_col, to_table, to_col)` |

#### Suite `enrichment` — đặt tên nghiệp vụ và quan hệ

| Metric | Trọng số | Ý nghĩa | Cách tính |
|---|---:|---|---|
| `entity_f1` | 0.30 | Đúng tập entity canonical | F1 của tập tên entity |
| `dimension_f1` | 0.20 | Đủ dimension của từng entity | Micro-F1 tập tên dimension theo từng canonical entity |
| `relationship_accuracy` | 0.10 | Đúng quan hệ, đúng loại, đúng cờ inferred | F1 của tuple 6 phần tử `(source_entity, source_field, target_entity, target_field, relation_type, inferred)` |
| `business_name_similarity` | 0.10 | Mức giống tên golden | Trung bình `max(exact, fuzzy, semantic)` trên mọi entity + dimension (thiếu entity → 0.0) |
| `business_semantic_correctness` | 0.30 | Tên nghiệp vụ đúng ngữ nghĩa kinh doanh (AI-judge) | LLM judge chấm theo rubric; điều kiện tiên quyết `entity_f1` |

#### Suite `metric_generation` — sinh định nghĩa chỉ số

| Metric | Trọng số | Ý nghĩa | Cách tính |
|---|---:|---|---|
| `metric_identity_accuracy` | 0.25 | Danh tính chỉ số khớp golden | So tuple `(target_entity, aggregation, field, sql_expression, dependencies, default_filters)`; case âm: so error code |
| `formula_equivalence` | 0.15 | Công thức nghiệp vụ tương đương | So `business_formula` qua `compare_business_name`; contract gap → `not_applicable` |
| `sql_expression_equivalence` | 0.15 | Biểu thức SQL tương đương | So chuỗi canonical sau `unwrap_declared_aggregation` hai phía |
| `filter_accuracy` | 0.05 | Default filter đúng | So tập điều kiện đã chuẩn hóa; `A AND B` tách thành hai phép so con |
| `allowed_dimension_f1` | 0.15 | Dimension đi kèm chỉ số | `match_allowed_dimensions` — dimension thừa hợp lệ chỉ tính 1 FP |
| `business_definition_correctness` | 0.15 | Mô tả nghiệp vụ đúng ngữ nghĩa (AI-judge) | Judge chấm `description` (+ `business_formula` khi không phải contract gap) |
| `formula_semantic_correctness` | 0.10 | Ngữ nghĩa công thức đúng (AI-judge) | Judge chấm `business_formula` + `sql_expression` |

Các metric từ `formula_equivalence` trở xuống chỉ áp dụng cho case dương; case
âm trả `not_applicable`.

#### Suite `query_compilation` — biên dịch chỉ số thành SQL

| Metric | Trọng số | Ý nghĩa | Cách tính |
|---|---:|---|---|
| `request_validation_accuracy` | 0.15 | Xác định đúng entity chính của request | So `primary_entity` của Canonical Query Model; case âm: so error code |
| `selection_preservation_accuracy` | 0.15 | Giữ nguyên metrics/dimensions được chọn | `(tập metrics khớp + tập dimensions khớp) / 2` — mỗi tập đúng cho 0.5 |
| `invalid_selection_rejection` | 0.10 | Từ chối selection không hợp lệ | Chỉ case âm: `error_code` có khớp kỳ vọng không |
| `sql_ast_equivalence` | 0.30 | SQL biên dịch tương đương golden | `structurally_equal(..., ignore_limit=True)` — so AST đã chuẩn hóa |
| `sql_execution_accuracy` | 0.20 | Kết quả thực thi đúng | Chạy SQL (qua guardrail thật) trên SQLite fixture cô lập, so **multiset hàng** không theo thứ tự, sai số float 1e-6 |
| `result_schema_accuracy` | 0.10 | Đúng bộ cột kết quả | So tập tên cột của kết quả với golden |

#### Suite `guardrail` — an toàn (mọi ngưỡng = 1.0, critical)

Mỗi aspect chỉ chấm trên đúng cực của case (metric dành cho case dương trả
`not_applicable` với case âm và ngược lại) nên không bị phạt kép:

| Metric | Trọng số | Ý nghĩa | Cách tính |
|---|---:|---|---|
| `unsafe_sql_rejection` | 0.30 | Chặn SQL nguy hiểm | Case âm: guardrail phải `accepted = False` |
| `valid_select_acceptance` | 0.20 | Cho qua SELECT hợp lệ | Case dương: guardrail phải `accepted = True` |
| `limit_enforcement` | 0.20 | Ép LIMIT đúng | Case dương: `effective_limit == expected_limit` |
| `timeout_enforcement` | 0.15 | Ép timeout đúng | Case dương: `effective_timeout == expected_timeout` (15s) |
| `error_code_accuracy` | 0.15 | Trả error code đúng | Case âm: `error_code` khớp golden |

### AI-judge metric — `evaluator/hybrid/judge/`

Ba metric judge (kiểu Ragas) dùng chung một luồng: render prompt **mù thông
tin** (judge không biết bên nào là golden), gọi LLM với temperature `0.0`, nhận
verdict cấu trúc theo **rubric có phiên bản**; điểm = tổng có trọng số của
rubric (tiêu chí thiếu tính 0). Mỗi kết quả mang provenance (rubric version,
prompt version, model) và được cache theo content-hash; judge crash trả
`error`, không làm sập run. Trọng số judge bị giới hạn (`JUDGE_WEIGHT_CAPS`:
enrichment ≤ 0.30, metric_generation ≤ 0.25) để không lấn át phần
deterministic.

### Gom điểm và gates — `evaluator/hybrid/aggregation.py`, `run_result.py`

```
Điểm metric = mean(điểm của metric đó trên mọi sample được chấm)
Điểm suite  = Σ(weight × điểm metric) / Σ(weight)      # chỉ tính metric có điểm
Overall     = 100 × Σ(suite_weight × điểm suite) / Σ(suite_weight)
Coverage    = (sample được chấm) / (sample phù hợp, đã loại not_applicable)
```

Trọng số được chuẩn hóa lại trên tập metric khả dụng — metric `not_applicable`
nhường trọng số cho các metric còn lại thay vì kéo điểm suite xuống. Trạng
thái run được xử lý theo thứ tự ưu tiên: **FAIL** khi rơi critical gate;
**INCOMPLETE** khi điểm không hợp lệ hoặc coverage < 95%; **PASS** khi overall
≥ 90; **WARN** khi 80–90; còn lại **FAIL**.

### Các component của suite evaluator legacy

Tầng suite chấm mỗi case theo các component `FieldScore`; điểm case = macro
trung bình các component khả dụng, điểm suite = macro trung bình các case, kèm
group score theo tag và micro cho component đặc thù:

- **discovery** — `tables`, `columns`, `primary_keys`, `relationships` (F1).
- **enrichment** — `entities`, tập `dimensions` của từng entity, tên nghiệp vụ
  từng entity/dimension, `relationships`.
- **metric** — `core_identity` + 14 trường: `name`, `business_name`,
  `metric_type`, `target_entity`, `source_table`, `aggregation`, `field`,
  `business_formula`, `sql_expression`, `dependencies`, `default_filters`,
  `allowed_dimensions`, `default_time_grain`, `expected_preview_facts`.
- **compiler** — các trường `cqm.*` của Canonical Query Model, `sql_ast`,
  `execution`.
- **guardrail** — `accepted`, `error_code`, `effective_limit`,
  `effective_timeout`.
