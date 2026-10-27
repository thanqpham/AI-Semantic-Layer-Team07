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


def valid_pairs(payload: object) -> bool:
    """Recognize canonical pairs without coercing or modifying historical payloads."""
    return (
        isinstance(payload, list)
        and bool(payload)
        and all(
            isinstance(pair, dict)
            and set(pair) == {"from_column_id", "to_column_id"}
            and all(type(value) is int and value > 0 for value in pair.values())
            for pair in payload
        )
        and all(len({pair[key] for pair in payload}) == len(payload) for key in ("from_column_id", "to_column_id"))
    )


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


def _graph(relationships: list[CanonicalRelationshipModel], allow_fanout: bool) -> dict[int, list[RelationshipStep]]:
    graph: dict[int, list[RelationshipStep]] = {}
    for rel in relationships:
        if not valid_pairs(rel.column_pairs) and not (allow_fanout and rel.column_pairs == []):
            continue
        kind = rel.relationship_type.replace("-", "_").lower()
        if allow_fanout or kind in {"many_to_one", "n:1", "one_to_one", "1:1"}:
            graph.setdefault(rel.from_entity_id, []).append(_step(rel))
        if allow_fanout or kind in {"one_to_one", "1:1"}:
            graph.setdefault(rel.to_entity_id, []).append(_step(rel, True))
    return graph


def _can_reach_target(graph: dict[int, list[RelationshipStep]], target: int) -> set[int]:
    reverse: dict[int, list[int]] = {}
    for source, steps in graph.items():
        for step in steps:
            reverse.setdefault(step.to_entity_id, []).append(source)
    reached, pending = {target}, [target]
    while pending:
        for source in reverse.get(pending.pop(), []):
            if source not in reached:
                reached.add(source)
                pending.append(source)
    return reached


def _find_path(
    graph: dict[int, list[RelationshipStep]],
    start: int,
    target: int,
    eligible: set[int],
    excluded: RelationshipStep | None = None,
) -> list[RelationshipStep] | None:
    if start not in eligible:
        return None
    previous: dict[int, RelationshipStep | None] = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current == target:
            path = []
            while (step := previous[current]) is not None:
                path.append(step)
                current = step.from_entity_id
            return list(reversed(path))
        for step in graph.get(current, []):
            if step != excluded and step.to_entity_id in eligible and step.to_entity_id not in previous:
                previous[step.to_entity_id] = step
                queue.append(step.to_entity_id)
    return None


def relationship_paths(
    relationships: list[CanonicalRelationshipModel], start: int, target: int, *, allow_fanout: bool = False
) -> list[list[RelationshipStep]]:
    """Find up to two simple paths using bounded-memory reachability searches."""
    graph = _graph(relationships, allow_fanout)
    eligible = _can_reach_target(graph, target)
    first = _find_path(graph, start, target, eligible)
    if first is None:
        return []
    if not allow_fanout:
        # Any distinct simple path omits at least one directed edge of the first path.
        for step in first:
            alternative = _find_path(graph, start, target, eligible, step)
            if alternative is not None:
                return [first, alternative]
    return [first]


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
