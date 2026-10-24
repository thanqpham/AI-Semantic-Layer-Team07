"""Load small, sourced KPI recipes without web access or evaluation answers."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

import yaml

from src.config import get_settings
from src.models.metric_review import KnowledgeSource


def normalized_text(value: str) -> str:
    """Normalize Vietnamese text for transparent keyword retrieval."""
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(c)).replace(
        "đ", "d"
    )


def load_metric_knowledge() -> dict[str, Any]:
    """Read and validate the current bundle for each new review context."""
    path = Path(__file__).resolve().parents[1] / "knowledge" / "retail_metrics.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = {KnowledgeSource.model_validate(s).id for s in data["sources"]}
    variant_ids: set[str] = set()
    for metric in data["metrics"]:
        for variant in metric["variants"]:
            identity = variant["id"]
            if identity in variant_ids or not variant.get("criteria"):
                raise ValueError("Duplicate or incomplete KPI variant")
            variant_ids.add(identity)
            if set(variant["source_ids"]) - sources:
                raise ValueError("Unknown curated KPI source")
            for field in ("meaning", "grain", "required_data", "unit", "limitations"):
                variant.setdefault(field, metric[field])
    return data


def metric_knowledge(question: str, discovery: bool = False) -> dict[str, Any]:
    """Select recipes by their declared aliases; discovery considers the full bundle."""
    if not get_settings().metric_knowledge_enabled:
        return {"metrics": [], "sources": []}
    data = load_metric_knowledge()
    query = normalized_text(question)
    matches = [m for m in data["metrics"] if any(normalized_text(a) in query for a in [m["name"], *m["aliases"]])]
    metrics = data["metrics"] if discovery else matches
    source_ids = {s for m in metrics for v in m["variants"] for s in v["source_ids"]}
    return {"metrics": metrics, "sources": [s for s in data["sources"] if s["id"] in source_ids]}


def find_variant(knowledge: dict[str, Any], metric_id: str | None, variant_id: str | None) -> dict[str, Any] | None:
    """Resolve only a declared variant belonging to the selected KPI family."""
    for metric in knowledge.get("metrics", []):
        if metric["id"] == metric_id:
            return next((variant for variant in metric["variants"] if variant["id"] == variant_id), None)
    return None
