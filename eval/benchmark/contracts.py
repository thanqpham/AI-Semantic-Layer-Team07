"""Versioned contracts for trace-aware benchmark runs."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field, JsonValue

from eval.evaluator.schemas import StrictEvaluationModel

BENCHMARK_CONTRACT_VERSION = "1.0.0"
BenchmarkProfileName = Literal["benchmark", "release"]
TraceStatus = Literal["started", "finished", "failed"]


class TraceConstraints(StrictEvaluationModel):
    """Partial-order trace rules for one benchmark scenario."""

    required_nodes: tuple[str, ...] = ()
    forbidden_nodes: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    required_precedence: tuple[tuple[str, str], ...] = ()
    required_state_keys: tuple[str, ...] = ()
    required_evidence_actions: tuple[str, ...] = ()
    max_iterations: int = Field(default=20, ge=1)
    max_actions: int = Field(default=50, ge=1)
    max_latency_ms: float | None = Field(default=None, gt=0)
    max_total_tokens: int | None = Field(default=None, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)


class BenchmarkCase(StrictEvaluationModel):
    """Describe one sandbox scenario and its observable terminal contract."""

    case_id: str = Field(min_length=1)
    suite: str = Field(min_length=1)
    fixture: str = Field(min_length=1)
    request: dict[str, JsonValue] = Field(default_factory=dict)
    expected_terminal: str
    expected_error: str | None = None
    constraints: TraceConstraints = Field(default_factory=TraceConstraints)
    synthetic_fault: bool = False


class BenchmarkProfile(StrictEvaluationModel):
    """Pin repeat count, model provenance, and regression policy for a run."""

    name: BenchmarkProfileName = "benchmark"
    trials: int = Field(default=3, ge=1)
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    prompt_version: str = "unknown"
    rubric_version: str = BENCHMARK_CONTRACT_VERSION
    pricing_version: str = "unknown"
    regression_tolerance: float = Field(default=0.20, ge=0.0)
    baseline_artifact: str | None = None

    @classmethod
    def release(cls, model: str, provider: str) -> BenchmarkProfile:
        """Build the fixed five-trial release profile."""
        return cls(name="release", trials=5, model=model, provider=provider)


class TraceEvent(StrictEvaluationModel):
    """Store one redacted node or action event emitted during a trial."""

    run_id: str
    case_id: str
    trial: int = Field(ge=1)
    iteration: int = Field(ge=1)
    kind: str
    status: TraceStatus
    node: str | None = None
    action: str | None = None
    state_delta: dict[str, JsonValue] = Field(default_factory=dict)
    observation_digest: str | None = None
    evidence_actions: tuple[str, ...] = ()
    error_code: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    usage_source: Literal["provider_reported", "unavailable"] | None = None
    token_precision: Literal["exact", "unavailable"] | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    cost_status: Literal["estimated", "free", "unavailable"] | None = None
    pricing_version: str | None = None


class ScenarioExecution(StrictEvaluationModel):
    """Return outcome evidence collected by a scenario adapter."""

    terminal: str
    outcome_score: float = Field(ge=0.0, le=1.0)
    error_code: str | None = None


class BenchmarkScenarioExecutor(Protocol):
    """Run a case once against the isolated product sandbox."""

    async def execute(self, case: BenchmarkCase) -> ScenarioExecution:
        """Execute one scenario with the active trace context."""


class BenchmarkRunRequest:
    """Group inputs for a complete benchmark run without serializing adapters."""

    def __init__(
        self,
        run_id: str,
        profile: BenchmarkProfile,
        cases: tuple[BenchmarkCase, ...],
        executor: BenchmarkScenarioExecutor,
        baseline: BenchmarkRunResult | None = None,
    ) -> None:
        self.run_id = run_id
        self.profile = profile
        self.cases = cases
        self.executor = executor
        self.baseline = baseline


class TraceScore(StrictEvaluationModel):
    """Expose one weighted benchmark score dimension."""

    name: str
    weight: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=1.0)


class BenchmarkGate(StrictEvaluationModel):
    """Describe a critical safety or evidence verdict."""

    name: str
    passed: bool
    detail: str


class BaselineComparison(StrictEvaluationModel):
    """Summarize a compatible pinned baseline comparison."""

    compatible: bool
    score_delta: float | None = None
    latency_delta: float | None = None
    cost_delta: float | None = None
    detail: str


class BenchmarkRunResult(StrictEvaluationModel):
    """Return complete trace benchmark evidence and aggregate results."""

    run_id: str
    contract_version: str = BENCHMARK_CONTRACT_VERSION
    status: Literal["PASS", "WARN", "FAIL", "INCOMPLETE"]
    overall_score: float | None = Field(default=None, ge=0.0, le=100.0)
    coverage: float = Field(ge=0.0, le=1.0)
    profile: BenchmarkProfile
    scores: tuple[TraceScore, ...]
    gates: tuple[BenchmarkGate, ...]
    events: tuple[TraceEvent, ...]
    executions: tuple[ScenarioExecution, ...]
    baseline: BaselineComparison | None = None
    warnings: tuple[str, ...] = ()
