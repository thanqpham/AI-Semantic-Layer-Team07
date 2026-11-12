"""Database overview generation tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.models.db import CanonicalRelationshipModel, SemanticDatabaseModel, SemanticTableModel
from src.services.database_overview import generate_overview


@pytest.mark.asyncio
async def test_generation_includes_all_batches(async_session):
    """Large schemas include the final table in the LLM input."""
    database = SemanticDatabaseModel(id=721, display_name="Shop", db_type="sqlite", conn_url_enc="test")
    async_session.add(database)
    async_session.add_all(
        [SemanticTableModel(db_id=721, table_name=f"table_{i}", business_name=f"table_{i}") for i in range(41)]
    )
    removed = SemanticTableModel(db_id=721, table_name="removed", business_name="[Deprecated] removed")
    async_session.add(removed)
    await async_session.commit()
    from sqlalchemy import select

    first = await async_session.scalar(select(SemanticTableModel).where(SemanticTableModel.table_name == "table_0"))
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=721,
            from_entity_id=first.id,
            to_entity_id=removed.id,
            relationship_type="many_to_one",
            join_condition="id=id",
        )
    )
    await async_session.commit()
    llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=["Nhóm một", "Nhóm hai", "Tổng quan bán hàng"]))
    with patch("src.services.database_overview.get_llm", return_value=llm):
        assert await generate_overview(async_session, database) == "Tổng quan bán hàng"
    assert all(f'"table_{i}"' in " ".join(call.args[0] for call in llm.ainvoke.call_args_list[:2]) for i in range(41))
    assert llm.ainvoke.await_count == 3
    assert "removed" not in " ".join(call.args[0] for call in llm.ainvoke.call_args_list)
