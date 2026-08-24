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

## Chạy đánh giá (How to run)

### Yêu cầu trước

- **Python 3.11.**
- Cài dependency: `pip install -r requirements-dev.txt` (đã bao gồm runtime deps cùng `ruff`, `pytest`, `pyyaml`, `sqlglot`).
- `pytest.ini` đặt `pythonpath = .`, nên `pytest` tự thấy package `eval`/`src`. Khi chạy **script riêng** (không qua pytest), hãy chạy từ **thư mục gốc repo** để `import eval` hoạt động.
- **Golden Dataset** phải nằm ở `eval/golden_dataset/<domain>/` — thuộc PR golden-data xếp chồng. Nếu chỉ có PR framework này thì `load_domain_dataset` sẽ báo thiếu dataset (điều này bình thường).

### 1) Kiểm tra (verify) framework

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

## Test

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

Cách chạy xem mục [Chạy đánh giá](#chạy-đánh-giá-how-to-run) — Bước 1.

---

## Hybrid evaluator (flag-gated)

Run the Ragas-style hybrid engine (deterministic metrics + optional AI judge)
against the golden dataset, with the legacy evaluator still the default:

```bash
python -m eval.run_eval --domain ecommerce --engine hybrid            # smoke, no judge
python -m eval.run_eval --domain ecommerce --engine hybrid --judge    # + AI judge lane
```

`--judge` uses the dedicated `JUDGE_*` configuration. Judge provider, model,
and API key must each differ from the Agent LLM; missing or matching values
stop the run before any API call. There is no fallback to Agent credentials.
Judge temperature is always `0.0`.

Reports go to `--report-dir` (default `eval/reports/hybrid`) as `report.json`
(full contract), `report.csv` (one row per sample), and `report.md` (summary).
Status follows the spec gates: PASS ≥ 90, WARN 80–90, FAIL on a critical-gate
failure or < 80, INCOMPLETE when coverage < 95% or evidence gates block the
score. Without `--judge`, judge metrics are reported as `not_applicable` and
excluded from coverage and suite weights. `--run-type` selects
smoke/benchmark/release evidence rules: judge metrics that are entirely
`not_applicable` are always exempt from the required-metric check, while
deterministic metrics are exempt only in `smoke` runs — `benchmark` and
`release` require deterministic evidence for the score to be valid. The legacy
engine remains the default (`--engine legacy`).

### 4) Agent source (agent_live)

`--source agent` replaces the golden-derived smoke candidates with candidates
collected **live from the real `src/` pipeline** (bootstrap → introspection →
enrichment → metric generation → compilation), then feeds them to the hybrid
engine. It requires `--engine hybrid` (any other engine is a `parser.error`,
exit 2). The legacy engine and the smoke source are unchanged — `--source smoke`
remains the default:

```bash
.venv/Scripts/python.exe -m eval.run_eval --engine hybrid --source agent --domain ecommerce
.venv/Scripts/python.exe -m eval.run_eval --engine hybrid --source agent --query-mode oracle --domain ecommerce
```

**Requires `LLM_*` in `.env`** — unlike the smoke source, this lane calls the
real `get_llm()` boundary, so it cannot run without credentials. The guardrail
suite stays offline: it reuses the product's read-only validator via
`ProductionGuardrailAdapter` and never executes SQL. Collected guardrail
decisions are persisted in `candidates.json` and passed to the engine as the
request's `guardrail` mapping — the `guardrail_adapter` kwarg alone only
serves the compiler execution lane, so without the mapping the guardrail
suite would score 0.0 with "no candidate response" warnings.

Each run writes to its own throwaway directory (default
`eval/runs/agent-<domain>-<UTC timestamp>`, override with `--run-dir`; the
directory must not already contain files — `prepare_run` refuses a non-empty
run dir instead of mixing artifacts from different runs):

```
<run_dir>/
├── target.sqlite      # throwaway target DB built from the golden sources
├── metadata.sqlite    # isolated metadata store (own eval user, no secrets)
├── candidates.json    # every collected candidate + run manifest
└── reports/           # report.json, report.csv, report.md
```

Notes on reading the result:

- **SQL normalization for the execution lane:** the connector strips the
  product's `__default__` namespace qualifier (the compiler's placeholder for
  schema-less targets like SQLite; the engine's fixtures are schema-less) and
  inlines the compiler's named bind parameters (`:runtime_N`, `:metric_N`) as
  literals, taking the values from `CompiledQuery.parameters` — the compiler's
  own bind map. The engine's SQLite lane executes the raw SQL string with no
  parameter binding, so without this serialization normalization every
  compiled query would fail with EXECUTION_FAILED regardless of correctness.
  Query semantics are unchanged.
- **`run_type=smoke` until the golden dataset is approved** — keep the default
  `--run-type smoke` until the golden dataset passes review; `benchmark` and
  `release` enforce stricter evidence rules.
- **Oracle mode is debug-only.** `--query-mode oracle` feeds ground-truth
  selections to the compiler to isolate compiler errors from resolver quality;
  the default `--query-mode resolver` is the honest end-to-end path.
- **Exit code:** `0` for PASS/WARN, `1` otherwise.
- **Contract gaps (disclosed permanent misses, spec §9.1 / decision D6):** the
  eval contract has no empty representation for the metric fields
  `business_formula` and `default_time_grain` (the `TimeGrain` Literal admits
  no empty value), and the deterministic pipeline cannot produce a meaningful
  value for either — `business_formula` is always submitted empty and
  `default_time_grain` is always the placeholder `"day"`. The run manifest in
  `candidates.json` records both fields under `contract_gaps`, and the engine
  now scores these fields `not_applicable` (excluded from coverage and suite
  weights) when the run declares them via `contract_gap_fields` — they remain
  **contract artifacts, not agent quality**, and no longer drag the score.
- **ORDER BY is presentation, not semantics (AST lane):** golden reference SQL
  always carries `ORDER BY <dim>` (fixture determinism) while the product
  compiler never emits one, and the execution lane already compares row
  multisets (`ordered=False`). `structurally_equal(..., ignore_limit=True)`
  therefore strips top-level ORDER BY and LIMIT from both sides — a query
  differing only in ordering/limit now compares by semantics alone. The
  default comparison path (guardrail/`effective_limit`) is unchanged.
- **Resolver entity scoping, abstain, unsafe-intent screen:** the resolver
  catalog lists each dimension with its table's business name
  (`entity.column — business name (bảng: ...)`), the system prompt requires
  dimensions to belong to the selected metric's entity, a cross-entity pick is
  retried up to twice with corrective feedback, and exhaustion fails closed with
  `RESOLVER_SCOPE_VIOLATION`. The LLM may abstain
  (`{"metrics": [], "abstain": true}` → `UNKNOWN_METRIC`), and questions
  starting with a destructive verb (xóa/hủy/drop/delete/truncate/alter/
  insert/update, diacritics-insensitive) are rejected `UNSAFE_INTENT` before
  any LLM call. Evidence: all 32 golden query cases use same-entity
  dimensions; only case 032 matches the destructive-verb screen.
- **Judge prompts are contract-gap aware:** fields declared in
  `contract_gap_fields` (`business_formula` today) are not rendered into
  judge prompts — the judge scores the remaining real signals
  (`description`, `sql_expression`). This mirrors the deterministic lane's
  `not_applicable` policy for the same gap; when the pipeline later produces
  the field, it is removed from `CONTRACT_GAPS` and judged again with no code
  change (prompt versions bumped to `business-definition-v2` /
  `formula-semantics-v2`).
- **Enrichment naming artifact (RESOLVED):** entity/dimension/relationship
  identifiers are now resolved to canonical names via `CanonicalResolver`
  (exact canonical-name mapping from the registry plus provenance), so
  agent-live enrichment scoring compares canonical-to-canonical instead of
  penalizing the PHYSICAL-vs-CANONICAL naming mismatch. Every resolution is
  auditable via the `identity_resolutions` log in `candidates.json`.

### 5) Re-scoring an existing run (no LLM)

`--rescore <run_dir>` reloads a run's `candidates.json` and re-runs the hybrid
engine with the current scoring layer — no collection, no LLM. Reports go to
`<run_dir>/reports-rescore/`. Use it to isolate scoring-layer changes from
collection-layer changes, and for revertible what-if experiments on golden
expectations (edit a golden copy, rescore, revert).

Note that rescoring uses the **current CLI flags**, not the original run's —
a run collected under `--run-type release` and rescored without the flag is
evaluated with the default `smoke` gate rules and can flip gate outcomes, so
pass `--run-type` explicitly to match the original collection.
