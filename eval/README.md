# Evaluation Framework — hướng dẫn chạy

### Benchmark AI đề xuất liên kết

`python -m eval.relationship_benchmark --baseline none` gọi provider thật qua cấu hình `LLM_*` hiện tại (có thể phát sinh chi phí), không đọc database khách hàng. Báo cáo JSON ghi phiên bản fixture, provider, model, temperature, baseline, precision/recall/F1, liên kết thiếu/thừa và lỗi. Thay `none` bằng mã run dùng để so sánh; đây là nhãn do người chạy cung cấp, không tự so sánh kết quả.

Fixture `golden_dataset/relationship_suggestions.json` là schema tổng hợp không khai báo FK, với một liên kết giữa hai nhóm. Trong fixture này, khóa `(product_id, month_start)` của hai bảng catalog được định nghĩa cùng kỳ và cùng sản phẩm; không suy rộng giả định đó sang database thực. Benchmark chỉ chấm cặp bảng/cột đầu ra thô của LLM, chưa chấm cardinality hoặc validation/lưu vào hàng chờ. Bộ mẫu nhỏ không đại diện cho chất lượng tổng quát; kết quả mock không phải kết quả benchmark LLM.

Khung đánh giá hybrid (deterministic + AI judge tùy chọn) chấm điểm output của agent
trên **Golden Dataset** ở `eval/golden_dataset/<domain>/`. Tài liệu này giữ hai
luồng chạy chính và danh mục suite/metric; chi tiết kiến trúc xem
`docs/EVALUATION_FRAMEWORK_PLAN.md` và docstring từng module trong `eval/`.

## Trạng thái và phạm vi benchmark

Benchmark hiện đánh giá các stage chính của agent trên Golden Dataset `ecommerce`:

1. Discovery — trích xuất schema và quan hệ.
2. Enrichment — tên nghiệp vụ, dimension và relationship.
3. Metric generation — định nghĩa metric, công thức và filter.
4. Query compilation — canonical query, SQL AST và kết quả thực thi.
5. Guardrail — read-only SQL, giới hạn dòng, timeout và error code.

Benchmark không dùng dữ liệu production và không query Target DB thật. Query execution trong evaluation chạy trên SQLite fixture cô lập; các lời gọi LLM phải dùng mock/cache hoặc provider được cấu hình rõ ràng.

Tài liệu liên quan:

- [AI Studio Manual Test Cases](../docs/AI_STUDIO_TEST_CASES.md) — kiểm thử trực tiếp trên giao diện.
- [Project README](../README.md) — cài đặt, Docker và quick start.
- Kết quả từng run nằm trong `eval/runs/`; không commit API key, `.env`, SQL dump chứa dữ liệu thật hoặc report có PII.

Quy ước đọc kết quả: dùng `report.md` để review, `report.json` cho máy đọc và `report.csv` cho tổng hợp; luôn ghi lại commit/config/dataset version khi so sánh hai run.

## Yêu cầu trước

- Chạy từ **thư mục gốc repo**, dùng venv của project.
- **Golden Dataset** phải nằm ở `eval/golden_dataset/ecommerce/`.
- Nguồn `agent` gọi `get_llm()` thật → cần biến **`LLM_*`** hợp lệ trong `.env`.
- Muốn chạy lane judge (`--judge`) → cần biến **`JUDGE_*`** trong `.env`:
  `JUDGE_LLM_PROVIDER`, `JUDGE_API_KEY`, `JUDGE_MODEL_NAME`
  (và `JUDGE_LLM_PROTOCOL` / `JUDGE_API_BASE` khi provider không chuẩn).
  Provider, model và API key của judge **phải khác** LLM của agent ở từng mục —
  run sẽ dừng trước mọi lời gọi API nếu thiếu hoặc trùng.

---

## 1) Nguồn agent (agent_live) — nhận candidate thật từ agent

`--source agent` thu thập candidate **trực tiếp từ pipeline `src/` thật**
(bootstrap → introspection → enrichment → sinh metric → biên dịch query) rồi đưa
vào hybrid engine. Engine phải là `hybrid` (mặc định).

Chạy từ thư mục gốc repo (PowerShell):

```powershell
python -m eval.run_eval --source agent --engine hybrid --domain ecommerce --query-mode resolver --judge
```

Biến thể **oracle mode** (chỉ để debug — đưa ground-truth selection vào compiler,
tách lỗi compiler khỏi chất lượng resolver):

```powershell
python -m eval.run_eval --source agent --engine hybrid --domain ecommerce --query-mode oracle --judge
```

Bỏ `--judge` nếu chỉ muốn chấm deterministic (các metric judge khi đó là
`not_applicable`, không ảnh hưởng coverage).

Mỗi run ghi vào một thư mục riêng (mặc định `eval/runs/agent-<domain>-<UTC timestamp>`;
thư mục phải trống — `prepare_run` từ chối trộn artifact của run khác):

```
<run_dir>/
├── target.sqlite      # target DB dùng một lần, dựng từ golden sources
├── metadata.sqlite    # metadata store cô lập (eval user riêng, không secret)
├── candidates.json    # mọi candidate đã thu + run manifest (đầu vào của --rescore)
├── resolver-diagnostics.json  # ( khi có attempt bị từ chối)
└── reports/           # report.json, report.csv, report.md
```

Đọc kết quả trong `reports/report.md`:

- Bảng **Metric scores** nhóm theo suite; cột **Source** ghi `AI judge` (metric do
  lane judge chấm) hoặc `code` (metric deterministic).
- Metric judge có dưới 3 mẫu chấm được kèm `(n=...)` sau điểm — đừng đọc quá mức
  mean tính trên ít mẫu; `n/a (n=0)` nghĩa là cả lane judge lỗi.
- Exit code: `0` cho PASS/WARN, `1` cho các trường hợp còn lại.

---

## 2) Chấm lại một run có sẵn (rescore — không chạy lại agent)

`--rescore <run_dir>` nạp lại `candidates.json` của run cũ và chạy lại hybrid
engine với **lớp chấm điểm hiện tại** — không thu thập lại, không gọi agent LLM,
không đụng DB. Report ghi vào `<run_dir>/reports-rescore/`.

```powershell
python -m eval.run_eval --rescore eval\runs\..... --judge --domain ecommerce
```

Chỉ deterministic (không gọi judge API):

```powershell
python -m eval.run_eval --rescore eval\runs\.... --domain ecommerce
```

Hai dụng cụ chính:

- **Tách thay đổi của lớp chấm điểm khỏi lớp thu thập** — sau khi sửa metric,
  prompt judge hay normalization, rescore phải tái lập đúng mọi số deterministic
  của run gốc; khác biệt chỉ được phép nằm ở chỗ đã sửa.
- **A/B judge trên candidates cố định** — thêm `--judge` để chạy lại lane AI-judge
  trên đúng candidates đã đóng băng, so sánh judge model/prompt mà cách ly hoàn
  toàn variance của agent.

Lưu ý: rescore dùng **CLI flag hiện tại**, không phải flag của run gốc — luôn
truyền `--run-type` khớp với lần thu gốc (run thu `release` mà rescore thiếu flag
sẽ bị chấm bằng luật `smoke` và có thể lật kết quả gate).

---

## 3) Các suite và metric

Năm suite, mỗi suite chấm một giai đoạn của pipeline. Điểm tổng là trung bình
trọng số của các suite (trọng số và ngưỡng đóng băng trong
[`evaluator/hybrid/catalog.py`](evaluator/hybrid/catalog.py)):

| Suite               | Trọng số | Ngưỡng | Chấm giai đoạn nào                                                                 |
| ------------------- | -------: | -----: | ---------------------------------------------------------------------------------- |
| `discovery`         |      15% |   0.95 | Stage 1 — introspect schema: đủ/đúng bảng, cột, khóa chính, quan hệ                |
| `enrichment`        |      20% |   0.85 | Stage 2 — đặt tên nghiệp vụ tiếng Việt cho entity/dimension, khai báo relationship |
| `metric_generation` |      25% |   0.85 | Stage 3 — sinh định nghĩa metric từ yêu cầu ngôn ngữ tự nhiên                      |
| `query_compilation` |      25% |   0.90 | Stage 4 — biên dịch query thành SQL đúng cấu trúc và đúng kết quả thực thi         |
| `guardrail`         |      15% |   0.95 | An toàn: read-only SELECT, LIMIT, timeout, mã lỗi từ chối                          |

Chạy riêng một suite bằng `--suite <tên>` — nhận cả tên nội bộ như bảng trên
(`metric_generation`, `query_compilation`, `guardrail`) lẫn bí danh cũ
(`metrics`, `compiler`, `guardrails`).

Quy ước đọc bảng dưới đây: metric **không đánh dấu** = `code` (deterministic, luôn
chạy); metric đánh dấu **⚖ AI judge** = do lane judge chấm, chỉ chạy khi `--judge`
(thiếu thì `not_applicable`, khỏi coverage). Judge metric còn bị chặn bởi
**prerequisite** — chỉ chấm sample vượt qua metric deterministic nền tảng — và
trọng số judge trong suite bị trần (enrichment ≤ 30%, metric_generation ≤ 25%).
Đó là lý do metric judge thường có ít mẫu hơn và mang chú thích `(n=...)`.

### discovery

| Metric                 | Cách tính                                                                              | Ý nghĩa                                    |
| ---------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------ |
| `table_precision`      | P = TP/(TP+FP); TP = bảng golden mà agent cũng introspect ra, FP = bảng agent đưa thêm | Agent không bịa ra bảng không tồn tại      |
| `table_recall`         | R = TP/(TP+FN); FN = bảng golden bị bỏ sót                                             | Agent không bỏ sót bảng                    |
| `table_f1`             | F1 = 2·P·R/(P+R) trên tập tên bảng (P, R như trên)                                     | Cân bằng giữa đủ và đúng                   |
| `column_f1`            | Mỗi bảng so tập tên cột, cộng dồn TP/FP/FN (micro) rồi tính F1                         | Cấu trúc cột của từng bảng đủ và chính xác |
| `primary_key_accuracy` | Như `column_f1` nhưng trên tập khóa chính của mỗi bảng                                 | Nhận diện đúng khóa chính                  |
| `relationship_f1`      | So tập tuple quan hệ (bảng và cột hai đầu) giữa introspect và golden → F1              | Phát hiện đúng các quan hệ FK giữa bảng    |

### enrichment

| Metric                            | Cách tính                                                                                                                                                                                                                                                       | Ý nghĩa                                                                      |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `entity_f1`                       | So tập tên entity agent khai báo với danh sách entity kỳ vọng → F1                                                                                                                                                                                              | Nhận diện đúng tập đối tượng nghiệp vụ                                       |
| `dimension_f1`                    | Với mỗi entity golden, so tập dimension với entity tương ứng của agent; gộp micro → F1                                                                                                                                                                          | Mỗi entity có đủ chiều phân tích, không bịa chiều thừa                       |
| `relationship_accuracy`           | So tập relationship (cặp entity + vai trò) khai báo với kỳ vọng → F1 set-match                                                                                                                                                                                  | Khai báo quan hệ đúng như golden                                             |
| `business_name_similarity`        | Với mỗi entity/dimension: điểm = max(exact, fuzzy, semantic) giữa tên nghiệp vụ của agent và các nhãn hợp lệ (tên chuẩn + tên chấp nhận + đồng nghĩa); thiếu = 0; kết quả = trung bình. Fuzzy so không phân biệt dấu thanh; semantic chỉ có khi inject provider | Tên nghiệp vụ tiếng Việt sát nghĩa với golden, chấp nhận cách gọi khác       |
| `business_semantic_correctness` ⚖ | Judge so tên nghiệp vụ với tham chiếu theo rubric 4 tiêu chí: business_meaning (0.40), reference_alignment (0.25), unsupported_assumptions (0.20), clarity (0.15); điểm = Σ trọng số × điểm tiêu chí. Prerequisite: `entity_f1`                                 | Bắt tên "giống chữ nhưng sai nghĩa nghiệp vụ" mà similarity thuần không thấy |

### metric_generation

| Metric                              | Cách tính                                                                                                                                                        | Ý nghĩa                                                                                    |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `metric_identity_accuracy`          | Case thường: khớp chính xác bộ nhận diện lõi của metric (tên, entity đích, trường, aggregation) → 1/0. Case âm: error code khớp kỳ vọng → 1/0                    | Sinh đúng metric được yêu cầu, hoặc từ chối đúng khi yêu cầu vô hiệu                       |
| `formula_equivalence`               | So `business_formula` bằng text-similarity (đạt khi exact hoặc fuzzy ≥ ngưỡng) → 1/0. Hiện là contract gap (pipeline luôn nộp rỗng) → `n/a`                      | Mô tả công thức bằng lời khớp golden — bật lại khi pipeline sinh được trường này           |
| `sql_expression_equivalence`        | Mỗi bên bóc một lớp agg khớp với aggregation tự khai báo, rồi so chuỗi biểu thức đã chuẩn hóa → 1/0                                                              | Biểu thức SQL của metric tương đương cấu trúc với golden                                   |
| `filter_accuracy`                   | Tách filter nối AND thành các condition nguyên tố, chuẩn hóa từng cái rồi so hai tập hợp → 1/0                                                                   | Filter mặc định của metric đúng nội dung                                                   |
| `allowed_dimension_f1`              | TP = dimension chung, FN = thiếu, FP = min(số dimension dư, 1) → F1                                                                                              | Đủ dimension cho phép; đưa thêm bao nhiêu dimension dư cũng chỉ tính 1 FP (trừng phạt mềm) |
| `business_definition_correctness` ⚖ | Judge chấm mô tả nghiệp vụ (description, và business_formula khi không phải gap) so tham chiếu, cùng rubric 4 tiêu chí. Prerequisite: `metric_identity_accuracy` | Mô tả đủ nghĩa nghiệp vụ, không bịa suy đoán                                               |
| `formula_semantic_correctness` ⚖    | Judge chấm cặp business_formula + sql_expression về mặt ngữ nghĩa so tham chiếu, cùng rubric. Prerequisite: `metric_identity_accuracy`                           | Công thức đúng nghĩa kể cả khi văn bản khác golden                                         |

### query_compilation

| Metric                            | Cách tính                                                                                                                                                    | Ý nghĩa                                                       |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- |
| `request_validation_accuracy`     | Case thường: `primary_entity` của query khớp golden → 1/0 (intent/domain không so — pipeline không có classifier cho chúng). Case âm: error code khớp        | Hiểu đúng đối tượng trung tâm của câu hỏi, hoặc từ chối đúng  |
| `selection_preservation_accuracy` | 2 phép kiểm: tập metrics khớp, tập dimensions khớp; điểm = số phép đúng / 2                                                                                  | Metric/dimension người dùng chọn đi qua compiler không bị đổi |
| `invalid_selection_rejection`     | Chỉ case âm: error_code khớp kỳ vọng → 1/0                                                                                                                   | Từ chối selection không hợp lệ với đúng mã lỗi                |
| `sql_ast_equivalence`             | So AST của SQL đã chuẩn hóa (bỏ format, alias, quoting, ngoặc đơn; bóc ORDER BY và LIMIT) với golden → 1/0                                                   | SQL đúng cấu trúc, chỉ khác trình bày vẫn được tính đúng      |
| `sql_execution_accuracy`          | Thực thi SQL (qua guardrail) trên SQLite fixture cô lập, so các hàng kết quả với kỳ vọng theo multiset — không theo thứ tự, sai số float được dung sai → 1/0 | Query cho ra đúng số liệu                                     |
| `result_schema_accuracy`          | So tập cột của kết quả thực thi với schema kỳ vọng → 1/0                                                                                                     | Hình dạng output (cột trả về) đúng                            |

### guardrail

| Metric                    | Cách tính                                                       | Ý nghĩa                                              |
| ------------------------- | --------------------------------------------------------------- | ---------------------------------------------------- |
| `unsafe_sql_rejection`    | Case SQL độc hại: adapter phải từ chối (accepted = False) → 1/0 | Không cho lọt bất kỳ câu không read-only an toàn nào |
| `valid_select_acceptance` | Case SELECT hợp lệ: adapter phải chấp nhận → 1/0                | Không từ chối oan query hợp lệ                       |
| `limit_enforcement`       | LIMIT hiệu dụng sau guardrail bằng giá trị kỳ vọng → 1/0        | Tự động ép LIMIT đúng mức trần                       |
| `timeout_enforcement`     | Timeout hiệu dụng bằng giá trị kỳ vọng → 1/0                    | Ép statement timeout đúng                            |
| `error_code_accuracy`     | Case âm: error_code trả về khớp golden → 1/0                    | Từ chối với đúng mã lỗi phân biệt được               |

## Kiến trúc

Hai lớp độc lập, đều async và có type hint đầy đủ.

### 1. Lớp Dataset — `eval/dataset/`

Tải và validate một domain Golden Dataset có version. Mọi contract đều là Pydantic model
strict, frozen (`extra="forbid"`).

| Module         | Trách nhiệm                                                                                                                                                                                                                                                                            |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `models.py`    | Các contract strict: `DomainManifest` và 4 loại case (`DiscoveryCase`, `MetricDefinitionCase`, `QueryCase`, `GuardrailCase`), định nghĩa canonical cho entity/metric/dimension/relationship, và `QueryReferenceCatalog`. Mọi artifact đều mang `dataset_version` + `contract_version`. |
| `loader.py`    | `load_domain_dataset(golden_root, domain)` (async) → `DomainDataset`. Tải manifest, 4 bộ case, canonical YAML registry, raw schema, và kết quả query kỳ vọng, sau đó chạy cross-validation đầy đủ. Các tham chiếu đường dẫn được bảo vệ chống path-traversal.                          |
| `validator.py` | Validate tính toàn vẹn, tham chiếu chéo, và **SQL AST read-only** bằng `sqlglot`. Ép buộc case_id duy nhất toàn cục, dialect coverage khớp manifest, số metric ground-truth khớp registry, chỉ cho phép đúng một `SELECT` không có side-effect, và cấm các hàm nguy hiểm.              |

### 2. Lớp Evaluator — `eval/evaluator/`

Chấm điểm các output của agent (candidate output) một cách deterministic so với dataset đã tải.

| Module                 | Trách nhiệm                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schemas.py`           | Evaluation contract **v2.0.0**: `EvaluationConfig` (ngưỡng + giới hạn an toàn) và mọi contract kết quả (`MatchCounts`, `PrecisionRecallF1`, `FieldScore`, `CaseEvaluationResult`, `SuiteEvaluationResult`, `GroupScore`, `DomainEvaluationResult`), cùng contract cho candidate output (`CandidateEnrichmentOutput`, `CandidateMetricOutput`, `CandidateCompilerOutput`, `CandidateGuardrailOutput`, `DomainCandidateOutputs`). |
| `scoring.py`           | Set matching, precision/recall/F1 (có chính sách zero-division cho tập rỗng được tài liệu hóa rõ), micro/macro averaging, và phát hiện trùng lặp.                                                                                                                                                                                                                                                                               |
| `text_similarity.py`   | So sánh tên tiếng Việt: exact (chuẩn hóa NFC), fuzzy (accent-insensitive bằng `SequenceMatcher`), và một semantic provider tùy chọn có thể inject qua `compare_business_name()`.                                                                                                                                                                                                                                                |
| `sql_normalization.py` | Parse và chuẩn hóa SQL fail-closed bằng `sqlglot`: `normalize_sql()`, `structurally_equal()` (bỏ qua format và alias có thể bỏ đi), `effective_limit()`, và ép buộc read-only.                                                                                                                                                                                                                                                  |
| `execution.py`         | Thực thi `SELECT` được guard trong SQLite in-memory cô lập: `execute_guarded_sql()` (statement timeout qua progress handler, validate LIMIT/timeout) và `compare_query_result()` (theo thứ tự hoặc multiset, với dung sai float).                                                                                                                                                                                               |
| `aggregation.py`       | `build_suite_result()` tổng hợp kết quả từng case thành một `SuiteEvaluationResult` đầy đủ provenance (micro, macro, và group score theo tag).                                                                                                                                                                                                                                                                                  |
| `discovery_eval.py`    | Suite đánh giá độ chính xác trích xuất schema ở Stage 1 — chấm tables, columns, primary keys, relationships bằng PRF1 (`evaluate_discovery_suite`).                                                                                                                                                                                                                                                                             |
| `enrichment_eval.py`   | Suite đánh giá enrichment entity/dimension/relationship ở Stage 2.                                                                                                                                                                                                                                                                                                                                                              |
| `metric_eval.py`       | Suite đánh giá sinh định nghĩa metric ở Stage 3 (ngôn ngữ tự nhiên → `CanonicalMetric`).                                                                                                                                                                                                                                                                                                                                        |
| `compiler_eval.py`     | Suite đánh giá biên dịch canonical-query và SQL guardrail ở Stage 4 (`evaluate_compiler_suite`, `evaluate_guardrail_suite`, `GuardrailAdapter`).                                                                                                                                                                                                                                                                                |
| `domain_eval.py`       | Orchestrator. `evaluate_domain_suite()` chạy các suite enrichment, metric, compiler, guardrail và lắp thành `DomainEvaluationResult`; `EvaluationDependencies` inject `TextSimilarityProvider` và `GuardrailAdapter` (tùy chọn).                                                                                                                                                                                                |

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

## Query case levels (L1–L4)

Từ dataset contract 2.1.0, mỗi query case khai báo `level` (không bắt buộc —
case âm/legacy để `null`) đi kèm tag `level_1..level_4`. Validator ép tính
nhất quán level ↔ difficulty (`L1→easy`, `L2→medium`, `L3/L4→hard`):

| Level                    | Ý nghĩa                                                                                          | Kỳ vọng                                                                     |
| ------------------------ | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| **L1** Explicit          | Metric + dimension nêu trực tiếp, có sẵn trong catalog                                           | SQL chuẩn + số đúng                                                         |
| **L2** Semantic/Implicit | Paraphrase nghiệp vụ; tự phân giải filter (kênh, bot), time grain, hoặc multi-metric cùng entity | Không bỏ cột nào so với ý định                                              |
| **L3** Multi-hop Join    | Dimension phải đi qua chuỗi JOIN nhiều bảng theo relationship many-to-one                        | JOIN đúng path, không Cartesian                                             |
| **L4** Ambiguous         | Câu hỏi mập mờ, không thể chọn duy nhất metric                                                   | **KHÔNG chạy SQL** — hỏi lại làm rõ (`expected_error: NEEDS_CLARIFICATION`) |

Case L4 và negative đi làn error (so khớp chính xác `expected_error`). Per-level
breakdown cưỡi tag `level_N` qua `GroupScore` của legacy engine. Chi tiết vàng
cho domain ecommerce: `golden_dataset/ecommerce/GROUND_TRUTH_NOTES.md`.
