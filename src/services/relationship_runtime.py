"""Shared eligibility and directed traversal for runtime relationships."""

from collections import deque
from dataclasses import dataclass

from sqlalchemy.sql.elements import ColumnElement

from src.models.db import CanonicalRelationshipModel
from src.services.semantic_compile_error import SemanticCompileError


def active_relationship_filters() -> tuple[ColumnElement[bool], ...]:
    """Require explicit approval and successful validation at every runtime gate."""
    return (
        CanonicalRelationshipModel.review_status == "approved",
        CanonicalRelationshipModel.validation_status == "valid",
    )


@dataclass(frozen=True)
class RelationshipStep:
    """One oriented join preserving the canonical relationship identity."""

    id: int
    from_entity_id: int
    to_entity_id: int
    column_pairs: list[dict[str, int]]


def _step(rel: CanonicalRelationshipModel, reverse: bool = False) -> RelationshipStep:
    pairs = rel.column_pairs or []
    if reverse:
        pairs = [{"from_column_id": p["to_column_id"], "to_column_id": p["from_column_id"]} for p in pairs]
    return RelationshipStep(
        rel.id,
        rel.to_entity_id if reverse else rel.from_entity_id,
        rel.from_entity_id if reverse else rel.to_entity_id,
        pairs,
    )


def relationship_paths(
    relationships: list[CanonicalRelationshipModel], start: int, target: int, *, allow_fanout: bool = False
) -> list[list[RelationshipStep]]:
    """Find at most two simple paths, including alternatives of different lengths."""
    graph: dict[int, list[RelationshipStep]] = {}
    for rel in relationships:
        kind = rel.relationship_type.replace("-", "_").lower()
        if allow_fanout or kind in {"many_to_one", "n:1", "one_to_one", "1:1"}:
            graph.setdefault(rel.from_entity_id, []).append(_step(rel))
        if allow_fanout or kind in {"one_to_one", "1:1"}:
            graph.setdefault(rel.to_entity_id, []).append(_step(rel, True))
    queue = deque([(start, [], {start})])
    matches = []
    while queue and len(matches) < 2:
        current, path, visited = queue.popleft()
        if current == target:
            matches.append(path)
            continue
        for step in graph.get(current, []):
            if step.to_entity_id not in visited:
                queue.append((step.to_entity_id, [*path, step], visited | {step.to_entity_id}))
    return matches


def safe_join_path(relationships: list[CanonicalRelationshipModel], start: int, target: int) -> list[RelationshipStep]:
    """Resolve a unique safe path or expose actionable canonical edge diagnostics."""
    paths = relationship_paths(relationships, start, target)
    context = {"table_id": target, "base_table_id": start}
    if len(paths) > 1:
        context["paths"] = [[step.id for step in path] for path in paths]
        raise SemanticCompileError("AMBIGUOUS_JOIN_PATH", "Multiple safe join paths exist", context)
    if paths:
        return paths[0]
    unsafe = relationship_paths(relationships, start, target, allow_fanout=True)
    if unsafe:
        context["relationship_ids"] = [step.id for step in unsafe[0]]
        raise SemanticCompileError("UNSAFE_FANOUT", "Dimension requires a one-to-many join", context)
    raise SemanticCompileError("UNREACHABLE_DIMENSION", "Dimension is not reachable through a safe path", context)
