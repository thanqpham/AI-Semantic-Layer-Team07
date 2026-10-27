"""Reconcile physical FK evidence without overwriting human relationship decisions."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from src.models.db import CanonicalRelationshipModel as Active
from src.models.db import ImportedSchemaModel, LiveTargetDbModel, SemanticColumnModel, SemanticTableModel, utc_now
from src.models.db_relationships import RelationshipCandidateModel as Candidate
from src.models.relationship_review import RelationshipDraft
from src.models.schema_metadata import ForeignKeyMetadata, RawSchemaMetadata
from src.services.relationship_review_service import claim_revision, impact_state, lock_database, published_metrics
from src.services.relationship_validation import fingerprint


async def _metadata(db: AsyncSession, db_id: int, raw: RawSchemaMetadata) -> tuple[dict, dict]:
    tables = (await db.scalars(select(SemanticTableModel).where(SemanticTableModel.db_id == db_id))).all()
    columns = (
        await db.scalars(select(SemanticColumnModel).where(SemanticColumnModel.table_id.in_([t.id for t in tables])))
    ).all()
    return {((t.physical_schema or "").lower(), t.table_name.lower()): t for t in tables}, {
        (c.table_id, c.column_name): c.id for c in columns
    }


def _detections(raw: RawSchemaMetadata, tables: dict, columns: dict) -> list[dict]:
    detections = []
    for table in raw.tables:
        source = tables.get((table.schema_name.raw_name.lower(), table.table_name.raw_name.lower()))
        for fk in table.foreign_keys:
            target = tables.get((fk.referred_schema.raw_name.lower(), fk.referred_table.raw_name.lower()))
            if source is None or target is None:
                raise ValueError("FK endpoints must be persisted before reconciliation")
            detections.append(_detection(source, target, fk, columns))
    return detections


def _detection(source: SemanticTableModel, target: SemanticTableModel, fk: ForeignKeyMetadata, columns: dict) -> dict:
    pairs = [
        {"from_column_id": columns[(source.id, a.raw_name)], "to_column_id": columns[(target.id, b.raw_name)]}
        for a, b in zip(fk.constrained_columns, fk.referred_columns, strict=True)
    ]
    draft = RelationshipDraft(
        from_entity_id=source.id, to_entity_id=target.id, column_pairs=pairs, relationship_type="many_to_one"
    )
    snapshot = {
        "from": [source.physical_schema, source.table_name],
        "to": [target.physical_schema, target.table_name],
        "pairs": [[a.raw_name, b.raw_name] for a, b in zip(fk.constrained_columns, fk.referred_columns, strict=True)],
    }
    return {
        "draft": draft,
        "key": fingerprint(draft),
        "snapshot": snapshot,
        "constraint_name": fk.constraint_name.raw_name if fk.constraint_name else None,
        "join": " AND ".join(
            f"{source.table_name}.{a.raw_name} = {target.table_name}.{b.raw_name}"
            for a, b in zip(fk.constrained_columns, fk.referred_columns, strict=True)
        ),
    }


def _same(row: Active, detection: dict) -> bool:
    physical_key = (row.evidence or {}).get("physical_fk_key")
    if physical_key is not None:
        return physical_key == detection["key"]
    snapshot = (row.evidence or {}).get("physical_fk")
    if snapshot is not None and (row.human_modified or snapshot == detection["snapshot"]):
        return snapshot == detection["snapshot"]
    draft = detection["draft"]
    return (
        row.from_entity_id == draft.from_entity_id
        and row.to_entity_id == draft.to_entity_id
        and row.column_pairs == [p.model_dump() for p in draft.column_pairs]
    )


def _previous(rows: list[Active], detection: dict) -> Active | None:
    draft, name = detection["draft"], detection["constraint_name"]
    scoped = [r for r in rows if r.from_entity_id == draft.from_entity_id]
    named = next((r for r in scoped if name is not None and r.constraint_name == name), None)
    endpoints = [r for r in scoped if r.to_entity_id == draft.to_entity_id]
    return named or (endpoints[0] if len(endpoints) == 1 and name is None else None)


async def _candidate(db: AsyncSession, db_id: int, detection: dict, target: Active | None) -> None:
    draft = detection["draft"]
    key = fingerprint(draft, target.id if target else None)
    existing = await db.scalar(select(Candidate).where(Candidate.connection_id == db_id, Candidate.fingerprint == key))
    if existing is not None:
        return
    db.add(
        Candidate(
            connection_id=db_id,
            target_relationship_id=target.id if target else None,
            from_entity_id=draft.from_entity_id,
            to_entity_id=draft.to_entity_id,
            column_pairs=[p.model_dump() for p in draft.column_pairs],
            relationship_type="many_to_one",
            source="fk",
            fingerprint=key,
            evidence={
                "physical_fk": detection["snapshot"],
                "physical_fk_key": detection["key"],
                "constraint_name": detection["constraint_name"],
            },
        )
    )


async def _invalidate(db: AsyncSession, db_id: int, row: Active, reason: str) -> list[int]:
    state = await impact_state(db, db_id, row, "active", "disable")
    await claim_revision(db, row, row.revision)
    if row.review_status != "disabled":
        row.review_status = "needs_review"
    row.validation_status = "invalid"
    affected = [m.id for m in state["metrics"]]
    for metric in state["metrics"]:
        metric.status = "needs_review"
    row.evidence = {**(row.evidence or {}), "sync_reason": reason, "affected_metric_ids": affected}
    return affected


async def _detect_one(
    db: AsyncSession, db_id: int, rows: list[Active], detection: dict, published: bool
) -> tuple[str, int | None]:
    same = next((r for r in rows if _same(r, detection)), None)
    if same is not None:
        same.evidence = {
            **(same.evidence or {}),
            "physical_fk": detection["snapshot"],
            "physical_fk_key": detection["key"],
            "detected_at": utc_now().isoformat(),
        }
        return "unchanged", same.id
    previous = _previous(rows, detection)
    if previous is not None:
        await _candidate(db, db_id, detection, previous)
        if previous.validation_status == "valid":
            await _invalidate(db, db_id, previous, "Physical foreign key mapping changed")
        return "changed", previous.id
    return await _add_detection(db, db_id, detection, published)


async def _add_detection(db: AsyncSession, db_id: int, detection: dict, published: bool) -> tuple[str, None]:
    rejected = await db.scalar(
        select(Candidate.id).where(Candidate.connection_id == db_id, Candidate.fingerprint == detection["key"])
    )
    row = _active_detection(db_id, detection)
    impact = await impact_state(db, db_id, row, "active", "add") if published else {"metrics": []}
    if impact["metrics"] or rejected is not None:
        await _candidate(db, db_id, detection, None)
        return ("unchanged" if rejected is not None else "added"), None
    db.add(row)
    return "added", None


def _active_detection(db_id: int, detection: dict) -> Active:
    draft = detection["draft"]
    return Active(
        connection_id=db_id,
        from_entity_id=draft.from_entity_id,
        to_entity_id=draft.to_entity_id,
        column_pairs=[p.model_dump() for p in draft.column_pairs],
        relationship_type="many_to_one",
        relationship_key=detection["key"],
        constraint_name=detection["constraint_name"],
        join_condition=detection["join"],
        source="fk",
        evidence={"physical_fk": detection["snapshot"], "physical_fk_key": detection["key"]},
    )


async def reconcile_relationships(db: AsyncSession, db_id: int, raw_schema: RawSchemaMetadata) -> dict[str, int]:
    """Reconcile a successfully acquired complete snapshot under the review graph lock."""
    await lock_database(db, db_id)
    await db.flush()
    counts = dict.fromkeys(("added", "unchanged", "changed", "missing"), 0)
    # shortcut: empty acquisition cannot prove removal; require a nonempty complete snapshot.
    if not raw_schema.tables:
        return counts
    rows = await _locked_rows(db, db_id)
    tables, columns = await _metadata(db, db_id, raw_schema)
    published = bool(await published_metrics(db, db_id))
    seen = set()
    for detection in _detections(raw_schema, tables, columns):
        kind, row_id = await _detect_one(db, db_id, rows, detection, published)
        counts[kind] += 1
        if row_id is not None:
            seen.add(row_id)
    counts["missing"] = await _missing(db, db_id, rows, seen)
    await _invalidate_missing_columns(db, db_id, rows, raw_schema, tables, columns)
    _refresh_join_conditions(rows, tables, columns, raw_schema.dialect.value)
    await _refresh_sources(db, db_id, raw_schema)
    await db.flush()
    return counts


async def _invalidate_missing_columns(
    db: AsyncSession, db_id: int, rows: list[Active], raw: RawSchemaMetadata, tables: dict, columns: dict
) -> None:
    present = {
        columns[(tables[(t.schema_name.raw_name, t.table_name.raw_name)].id, c.column_name.raw_name)]
        for t in raw.tables
        for c in t.columns
        if (t.schema_name.raw_name, t.table_name.raw_name) in tables
    }
    for row in rows:
        used = {value for pair in row.column_pairs for value in pair.values()}
        if row.validation_status == "valid" and not used.issubset(present):
            await _invalidate(db, db_id, row, "Relationship endpoint table or column disappeared")


async def _locked_rows(db: AsyncSession, db_id: int) -> list[Active]:
    stmt = (
        select(Active).where(Active.connection_id == db_id).with_for_update().execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


async def _missing(db: AsyncSession, db_id: int, rows: list[Active], seen: set[int]) -> int:
    missing = 0
    for row in rows:
        if row.source == "fk" and row.id not in seen and row.validation_status == "valid":
            await _invalidate(db, db_id, row, "Physical foreign key disappeared")
            missing += 1
    return missing


async def invalidate_relationship_columns(db: AsyncSession, db_id: int, column_ids: set[int]) -> None:
    """Require review when a participating physical key changes its data type."""
    if not column_ids:
        return
    await lock_database(db, db_id)
    for row in await _locked_rows(db, db_id):
        used = {value for pair in row.column_pairs for value in pair.values()}
        if row.validation_status == "valid" and used.intersection(column_ids):
            await _invalidate(db, db_id, row, "Relationship key data type changed")


async def _refresh_sources(db: AsyncSession, db_id: int, raw: RawSchemaMetadata) -> None:
    for model in (ImportedSchemaModel, LiveTargetDbModel):
        await db.execute(
            update(model).where(model.semantic_db_id == db_id).values(schema_metadata=raw.model_dump(mode="json"))
        )


def _refresh_join_conditions(rows: list[Active], tables: dict, columns: dict, dialect: str) -> None:
    by_id = {table.id: table for table in tables.values()}
    names = {column_id: name for (_, name), column_id in columns.items()}
    dialect = "postgres" if dialect == "postgresql" else dialect
    for row in rows:
        if not row.column_pairs or any(value not in names for pair in row.column_pairs for value in pair.values()):
            continue
        clauses = []
        for pair in row.column_pairs:
            left, right = by_id[row.from_entity_id], by_id[row.to_entity_id]
            source = exp.column(
                names[pair["from_column_id"]], table=left.table_name, db=left.physical_schema, quoted=True
            )
            target = exp.column(
                names[pair["to_column_id"]], table=right.table_name, db=right.physical_schema, quoted=True
            )
            clauses.append(source.eq(target).sql(dialect=dialect))
        row.join_condition = " AND ".join(clauses)
