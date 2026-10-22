"""Save Node — Flow 1 Step 5 (after HITL approval).

Persist approved Semantic Layer into Metadata Store via semantic_service.
Converts pipeline RawSchema (TypedDict) to RawSchemaMetadata (Pydantic) before
calling enrich_and_save_canonical_schema().
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.state import AgentState
from src.models.metric_definition import MetricDefinition
from src.models.raw_schema import RawSchema
from src.models.schema_metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    Identifier,
    PrimaryKeyMetadata,
    RawSchemaMetadata,
    SchemaDialect,
    SchemaMetadata,
    TableMetadata,
)
from src.observability import trace_action, trace_node
from src.services.database import get_db_session
from src.services.semantic_service import (
    approve_metric,
    create_metric,
    enrich_and_save_canonical_schema,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TypedDict -> Pydantic conversion
# ---------------------------------------------------------------------------


def raw_schema_to_canonical(raw: RawSchema, dialect: str) -> RawSchemaMetadata:
    """Convert pipeline TypedDict RawSchema to Pydantic RawSchemaMetadata."""
    schema_dialect = SchemaDialect(dialect)
    tables: list[TableMetadata] = []
    schemas_seen: dict[str, SchemaMetadata] = {}

    for tbl in raw.get("tables", []):
        schema_name_raw: str = tbl.get("schema_name") or _default_schema(schema_dialect)
        if schema_name_raw not in schemas_seen:
            schemas_seen[schema_name_raw] = SchemaMetadata(
                schema_name=Identifier.from_raw(schema_name_raw, schema_dialect),
            )

        columns = tuple(
            _convert_column(col, pos, schema_dialect) for pos, col in enumerate(tbl.get("columns", []), start=1)
        )
        pk = _convert_primary_key(tbl.get("primary_keys", []), schema_dialect)
        fks = tuple(_convert_fk(fk, schema_dialect) for fk in tbl.get("foreign_keys", []))

        tables.append(
            TableMetadata(
                schema_name=Identifier.from_raw(schema_name_raw, schema_dialect),
                table_name=Identifier.from_raw(tbl["table_name"], schema_dialect),
                columns=columns,
                primary_key=pk,
                foreign_keys=fks,
            )
        )

    return RawSchemaMetadata(
        dialect=schema_dialect,
        schemas=tuple(schemas_seen.values()),
        tables=tuple(tables),
    )


def _default_schema(dialect: SchemaDialect) -> str:
    if dialect == SchemaDialect.SQLITE:
        return "main"
    if dialect == SchemaDialect.MYSQL:
        return "__default__"
    return "public"


def _convert_column(col: dict, ordinal: int, dialect: SchemaDialect) -> ColumnMetadata:
    sample = col.get("sample_values")
    return ColumnMetadata(
        column_name=Identifier.from_raw(col["column_name"], dialect),
        ordinal_position=ordinal,
        raw_data_type=col["data_type"],
        data_type=col["data_type"],
        nullable=col.get("is_nullable", True),
        default_expression=col.get("default_value"),
        primary_key=col.get("is_primary_key", False),
        sample_values=tuple(sample) if sample else None,
    )


def _convert_primary_key(pk_cols: list[str], dialect: SchemaDialect) -> PrimaryKeyMetadata | None:
    if not pk_cols:
        return None
    return PrimaryKeyMetadata(
        constrained_columns=tuple(Identifier.from_raw(c, dialect) for c in pk_cols),
    )


def _convert_fk(fk: dict, dialect: SchemaDialect) -> ForeignKeyMetadata:
    constraint_name = fk.get("constraint_name")
    return ForeignKeyMetadata(
        constraint_name=(Identifier.from_raw(constraint_name, dialect) if constraint_name else None),
        constrained_columns=tuple(Identifier.from_raw(c, dialect) for c in fk["constrained_columns"]),
        referred_schema=Identifier.from_raw(fk.get("referred_schema") or _default_schema(dialect), dialect),
        referred_table=Identifier.from_raw(fk["referred_table"], dialect),
        referred_columns=tuple(Identifier.from_raw(c, dialect) for c in fk["referred_columns"]),
    )


# ---------------------------------------------------------------------------
# Save node
# ---------------------------------------------------------------------------


@trace_node("save")
async def save_node(state: AgentState) -> dict:
    """Persist approved Semantic Layer to Metadata Store via semantic_service.

    Input state fields: db_id, user_id, db_type, raw_schema, hitl_approved
    Output state fields: semantic_layer_id | error
    """
    if not state.get("hitl_approved"):
        return {"error": "save_node: HITL not approved, cannot save"}

    raw_schema: RawSchema | None = state.get("raw_schema")
    if not raw_schema or not raw_schema.get("tables"):
        return {"error": "save_node: raw_schema is empty"}

    db_id: int = state["db_id"]
    user_id: int = state["user_id"]
    dialect: str = state.get("db_type", "postgresql")

    try:
        canonical = raw_schema_to_canonical(raw_schema, dialect)
        enrichment = state.get("enriched_schema")
        async for session in get_db_session():
            result = await trace_action(
                "semantic_persist",
                {"connection_id": db_id, "table_count": len(raw_schema["tables"])},
                enrich_and_save_canonical_schema(
                    db=session,
                    user_id=user_id,
                    connection_id=db_id,
                    raw_schema=canonical,
                    dialect=dialect,
                    enrichment=enrichment,
                ),
            )
            await _save_approved_metrics(session, state, db_id, user_id)
            await session.commit()
            break

        semantic_layer_id = db_id
        logger.info(
            "Semantic layer saved db_id=%s tables=%d relationships=%d",
            semantic_layer_id,
            len(result.get("tables", [])),
            len(result.get("relationships", [])),
        )
        return {"semantic_layer_id": semantic_layer_id}
    except Exception as exc:
        logger.exception("save_node failed")
        return {"error": f"save_node: {exc}"}


async def _save_approved_metrics(
    session: Any,
    state: AgentState,
    db_id: int,
    user_id: int,
) -> None:
    """Persist and approve reviewed metric definitions from graph state."""
    from src.services.metric_proposals import persist_reviewed_state

    await _refresh_legacy_reviews(session, state, db_id)
    await persist_reviewed_state(session, db_id, user_id, state)
    for payload in state.get("suggested_metrics", []):
        definition = MetricDefinition.model_validate(payload["definition"])
        await trace_action(
            "metric_approve",
            {"connection_id": db_id},
            _create_and_approve_metric(session, db_id, user_id, definition, payload.get("proposal_id")),
        )


async def _create_and_approve_metric(
    session: Any,
    db_id: int,
    user_id: int,
    definition: MetricDefinition,
    proposal_id: str | None = None,
) -> Any:
    """Create and approve a reviewed metric in one traced action boundary."""
    metric = await create_metric(
        session,
        db_id,
        {"definition": definition.model_dump(mode="json"), "source": "ai", "proposal_id": proposal_id},
        user_id,
    )
    await approve_metric(session, metric.id, user_id)
    return metric


async def _refresh_legacy_reviews(session: Any, state: AgentState, db_id: int) -> None:
    """Recheck newly persisted legacy metadata without changing the human-approved draft."""
    from src.agents.nodes.metric_review_node import reviewed_state
    from src.services.metric_context import load_review_schema
    from src.services.metric_review import review_metric_draft

    if not state.get("suggested_metrics"):
        return
    if not state.get("reviewed_proposals"):
        raise ValueError("Legacy AI metrics require a passing review before save.")
    schema = await load_review_schema(session, db_id)
    proposals = []
    for previous in _selected_review_evidence(state):
        context = {**previous["context"], "schema": schema}
        draft = {"name": previous["name"], "definition": previous["final_definition"]}
        result = await review_metric_draft(context, draft, allow_repair=False)
        if result["review"]["status"] != "pass" or result["final_definition"] != previous["final_definition"]:
            raise ValueError("Metadata sau lưu cần thẩm định và HITL lại.")
        result["original_definition"] = previous["original_definition"]
        for key in ("original_definition", "revised", "repair_count", "repair_reason", "repair_feedback"):
            result["review"][key] = previous["review"].get(key, result["review"].get(key))
        proposals.append(result)
    state.update(reviewed_state(proposals, state))


def _selected_review_evidence(state: AgentState) -> list[dict[str, Any]]:
    """Preserve human selection and reject edits that have not been reviewed."""
    selected = []
    for item in state.get("suggested_metrics", []):
        evidence = next(
            (
                p
                for p in state.get("reviewed_proposals", [])
                if p["final_definition"] == item.get("definition") and p["review"]["status"] == "pass"
            ),
            None,
        )
        if evidence is None:
            raise ValueError("Định nghĩa sau HITL đã thay đổi. Hãy thẩm định và duyệt lại.")
        selected.append(evidence)
    return selected
