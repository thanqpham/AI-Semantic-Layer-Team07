"""Load small, sourced KPI recipes without web access or evaluation answers."""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.models.metric_review import KnowledgeSource


def normalized_text(value: str) -> str:
    """Normalize Vietnamese text for transparent keyword retrieval."""
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(c)).replace(
        "đ", "d"
    )


@lru_cache(maxsize=1)
def load_metric_knowledge() -> dict[str, Any]:
    """Read and validate the bundled knowledge source registry."""
    path = Path(__file__).resolve().parents[1] / "knowledge" / "retail_metrics.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = {KnowledgeSource.model_validate(s).id for s in data["sources"]}
    for metric in data["metrics"]:
        for variant in metric["variants"]:
            if set(variant["source_ids"]) - sources:
                raise ValueError("Unknown curated KPI source")
    return data


def metric_knowledge(question: str, discovery: bool = False) -> dict[str, Any]:
    """Select recipes by their declared aliases; discovery considers the full bundle."""
    data = load_metric_knowledge()
    query = normalized_text(question)
    matches = [m for m in data["metrics"] if any(normalized_text(a) in query for a in [m["name"], *m["aliases"]])]
    metrics = data["metrics"] if discovery else matches
    source_ids = {s for m in metrics for v in m["variants"] for s in v["source_ids"]}
    return {"metrics": metrics, "sources": [s for s in data["sources"] if s["id"] in source_ids]}
