"""Generate a database overview from persisted schema metadata."""

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import CanonicalRelationshipModel, SemanticDatabaseModel, SemanticTableModel
from src.services.llm import get_llm
from src.services.llm_json import response_text


async def generate_overview(db: AsyncSession, database: SemanticDatabaseModel) -> str:
    """Summarize all tables without reading target database data."""
    tables = list(
        (
            await db.scalars(
                select(SemanticTableModel).where(
                    SemanticTableModel.db_id == database.id,
                    ~SemanticTableModel.business_name.startswith("[Deprecated]"),
                )
            )
        ).all()
    )
    if not tables:
        raise ValueError("Chưa có metadata bảng để tạo mô tả")
    relationships = list(
        (
            await db.scalars(
                select(CanonicalRelationshipModel).where(
                    CanonicalRelationshipModel.connection_id == database.id,
                    CanonicalRelationshipModel.review_status == "approved",
                )
            )
        ).all()
    )
    names = {table.id: f"{table.physical_schema or ''}.{table.table_name}" for table in tables}
    inventory = [
        {
            "schema": t.physical_schema,
            "table": t.table_name,
            "description": t.description,
            "relations": [
                names[r.to_entity_id] for r in relationships if r.from_entity_id == t.id and r.to_entity_id in names
            ],
        }
        for t in tables
    ]
    llm = get_llm()
    summaries = []
    for index in range(0, len(inventory), 40):
        prompt = "Tóm tắt thận trọng các nhóm nghiệp vụ dựa trên metadata sau, không suy đoán quy tắc: " + json.dumps(
            inventory[index : index + 40], ensure_ascii=False
        )
        summaries.append(response_text(await asyncio.wait_for(llm.ainvoke(prompt), timeout=30)))
    prompt = (
        "Viết một đoạn mô tả tổng quan database bằng tiếng Việt, khoảng 100–200 từ, tối đa 2000 ký tự. "
        "Chỉ dựa vào metadata, không khẳng định quy tắc chưa rõ; chỉ trả đoạn mô tả. "
        + json.dumps({"database": database.display_name, "summaries": summaries}, ensure_ascii=False)
    )
    description = response_text(await asyncio.wait_for(llm.ainvoke(prompt), timeout=30)).strip()
    if not description or len(description) > 2000:
        raise ValueError("AI trả mô tả rỗng hoặc dài quá 2000 ký tự")
    return description
