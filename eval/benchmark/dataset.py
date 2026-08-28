"""Load trace benchmark cases kept separate from output golden cases."""

from __future__ import annotations

import json
from pathlib import Path

from eval.benchmark.contracts import BenchmarkCase


async def load_benchmark_cases(golden_root: Path, domain: str) -> tuple[BenchmarkCase, ...]:
    """Load the versioned benchmark scenario list for one golden domain."""
    path = golden_root / domain / "benchmark_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(BenchmarkCase.model_validate(item) for item in payload["cases"])
