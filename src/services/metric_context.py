"""Build bounded, relationship-complete schema context for Metric AI."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db import CanonicalRelationshipModel, SemanticTableModel
from src.models.metric_review import MetricScopeSelection
from src.models.schemas import ChatClarificationOption, ChatClarificationPayload
from src.services.llm import get_llm
from src.services.llm_json import ainvoke_json
from src.services.metric_runtime import MetricCallError, invoke_metric_json
from src.services.relationship_runtime import active_relationship_filters

_CLARIFICATION_OPTIONS_PROMPT = """
Khi needs_clarification=true và có các cách hiểu cụ thể để người dùng chọn,
bắt buộc trả thêm "options": ["Câu trả lời đầy đủ cho lựa chọn 1", "Câu trả lời đầy đủ cho lựa chọn 2"].
Ví dụ hỏi AOV theo giá nào: options phải nêu rõ AOV theo từng cột giá có trong inventory.
Mỗi lựa chọn phải có đủ ngữ cảnh KPI và tên bảng/cột để xử lý như tin nhắn tiếp theo.
Không bịa tên bảng/cột. Chỉ để options=[] nếu cần người dùng nhập thông tin chưa biết.
"""

_SCOPE_PROMPT = """Bạn chọn phạm vi schema cho một KPI. Chỉ trả JSON:
{{"table_names":["..."],"needs_clarification":false,"question":"..."}}
Chỉ chọn tối đa 5 bảng có trong inventory. Chọn bảng liên quan và giao đầy đủ metadata
cho Metric Designer Agent tự tạo các biến thể công thức. Không hỏi người dùng chọn cột giá,
thuế, giảm giá hoặc công thức ở bước này. Chỉ hỏi thu hẹp domain nếu không tìm được
bảng liên quan trong inventory. Không viết SQL.

Inventory schema:\n{inventory}\n\nKPI: {question}"""

_DATA_SCOPE_PROMPT = """Chọn các bảng schema cần thiết để trả lời câu hỏi khám phá dữ liệu. Chỉ trả JSON:
{{"table_names":["..."],"needs_clarification":false,"question":"..."}}
Chỉ chọn bảng có trong inventory. Chọn đủ bảng liên quan, nhưng không chọn toàn bộ schema.
Nếu câu hỏi chưa đủ rõ, đặt needs_clarification=true và hỏi lại bằng tiếng Việt theo ngôn ngữ nghiệp vụ.
Không viết SQL.

Inventory schema:\n{inventory}\n\nCâu hỏi: {question}"""

_DISCOVERY_SCOPE_PROMPT = """Chọn phạm vi để khám phá tối đa 5 KPI bán lẻ/ecommerce. Chỉ trả JSON:
{{"table_names":["..."],"needs_clarification":false,"question":""}}
Đọc TOÀN BỘ inventory trước khi chọn tối đa 5 bảng nghiệp vụ có tiềm năng KPI rõ nhất.
Ưu tiên các bảng sự kiện/đơn hàng, dòng hàng, khách hàng, phiên, giỏ hàng hoặc giao hàng
phù hợp yêu cầu; không chỉ chọn bảng lookup hoặc các bảng đầu danh sách.
Chỉ chọn bảng có trong inventory. Tổng context_tokens của bảng được chọn không vượt
ngân sách schema ghi bên dưới. Mỗi bảng sẽ được nạp đầy đủ metadata sau bước chọn này.
Không tự tạo cột, công thức hoặc SQL. Chỉ hỏi lại nếu không xác định được bảng nghiệp vụ phù hợp.

Inventory schema:\n{inventory}\n\nYêu cầu và ngân sách:\n{question}"""


@dataclass(frozen=True)
class MetricContextResult:
    """A safe schema subgraph or a user-facing diagnostic."""

    schema: dict[str, Any]
    diagnostic: dict[str, Any]


async def build_metric_context(
    db: AsyncSession, db_id: int, question: str, token_budget: int, target_tables: list[str] | None = None
) -> MetricContextResult:
    """Select and expand a complete semantic context without raw string truncation."""
    tables, relationships = await _load_metadata(db, db_id)
    inventory = _inventory(tables)
    if _token_estimate({"inventory": inventory, "question": question}) > token_budget:
        return _clarification("Schema quá lớn; hãy nêu rõ domain hoặc bảng cần dùng.")
    selected, diagnostic = await _select_tables(question, inventory, tables, target_tables)
    if diagnostic:
        return MetricContextResult(schema={}, diagnostic=diagnostic)
    schema = _expand_context(tables, relationships, selected)
    if _token_estimate({"schema": schema, "question": question}) > token_budget:
        return _clarification("Phạm vi KPI quá rộng; hãy nêu rõ bảng hoặc dimension cần tính.")
    return MetricContextResult(schema=schema, diagnostic=_ready_diagnostic(schema))


async def build_data_context(db: AsyncSession, db_id: int, question: str, token_budget: int) -> MetricContextResult:
    """Build a focused schema context for a non-metric data question."""
    tables, relationships = await _load_metadata(db, db_id)
    if _asks_for_temporal_fields(question):
        return _temporal_context(tables)
    inventory = _inventory(tables)
    if _token_estimate(inventory) > token_budget:
        return _clarification("Schema khá lớn. Bạn muốn xem phần đơn hàng, khách hàng hay sản phẩm?")
    selected, diagnostic = await _select_tables(question, inventory, tables, None, _DATA_SCOPE_PROMPT)
    if diagnostic:
        return MetricContextResult(schema={}, diagnostic=diagnostic)
    schema = _expand_context(tables, relationships, selected)
    if _token_estimate(schema) > token_budget:
        return _clarification("Bạn muốn xem phần dữ liệu nào: đơn hàng, khách hàng hay sản phẩm?")
    return MetricContextResult(schema=schema, diagnostic=_ready_diagnostic(schema))


async def load_review_schema(db: AsyncSession, db_id: int, table_names: list[str] | None = None) -> dict[str, Any]:
    """Read complete declared metadata for discovery and proposal freshness checks."""
    tables, relationships = await _load_metadata(db, db_id)
    selected = set(table_names) if table_names is not None else {t.table_name for t in tables}
    return _expand_context(tables, relationships, selected)


async def build_discovery_context(
    db: AsyncSession,
    db_id: int,
    token_budget: int,
    table_names: list[str] | None = None,
    question: str = "Khám phá KPI phù hợp với schema bán lẻ/ecommerce.",
) -> MetricContextResult:
    """Scope large inventories before loading complete, bounded KPI evidence."""
    schema = await load_review_schema(db, db_id, table_names)
    if not schema["tables"]:
        return _clarification("Chưa có schema metadata. Hãy nhập hoặc kết nối schema trước.")
    # Reserve half for the request, KPI recipes, catalog and review feedback.
    schema_budget = token_budget // 2
    if _token_estimate(schema) <= (token_budget if table_names else schema_budget):
        return MetricContextResult(schema=schema, diagnostic=_ready_diagnostic(schema))
    if table_names:
        return _clarification("Schema quá lớn; hãy thu hẹp bảng/domain để khám phá KPI.")
    selected, diagnostic = await _select_discovery_scope(schema, question, schema_budget)
    if diagnostic:
        return MetricContextResult(schema={}, diagnostic=diagnostic)
    scoped = await load_review_schema(db, db_id, list(selected))
    if not scoped["tables"] or _token_estimate(scoped) > schema_budget:
        return _clarification("Các bảng nghiệp vụ đã chọn vẫn vượt ngân sách context; hãy chọn phạm vi KPI cụ thể hơn.")
    scoped["discovery_scope"] = {
        "inventory_table_count": len(schema["tables"]),
        "selected_table_count": len(scoped["tables"]),
    }
    return MetricContextResult(schema=scoped, diagnostic=_ready_diagnostic(scoped))


async def _select_discovery_scope(
    schema: dict[str, Any], question: str, budget: int
) -> tuple[set[str], dict[str, Any] | None]:
    inventory = _discovery_inventory(schema)
    if _token_estimate({"inventory": inventory, "question": question}) > budget:
        return set(), _clarification("Inventory quá lớn; hãy chọn domain hoặc bảng cần khám phá KPI.").diagnostic
    query = f"{question}\nNgân sách schema: {budget} token."
    selected, diagnostic = await _select_tables(query, inventory, schema["tables"], None, _DISCOVERY_SCOPE_PROMPT)
    if len(selected) > 5:
        return set(), _clarification("Hãy giới hạn phạm vi khám phá trong tối đa 5 bảng nghiệp vụ.").diagnostic
    return selected, diagnostic


def _discovery_inventory(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "table_name": table["table_name"],
            "business_name": table.get("business_name"),
            "description": table.get("description"),
            "columns": {c["column_name"]: c.get("data_type") for c in table.get("columns", [])},
            "primary_key": [c["column_name"] for c in table.get("columns", []) if c.get("is_primary_key")],
            "context_tokens": _token_estimate(table),
        }
        for table in schema["tables"]
    ]


async def _load_metadata(
    db: AsyncSession, db_id: int
) -> tuple[list[SemanticTableModel], list[CanonicalRelationshipModel]]:
    """Load semantic tables and validated relationship graph from metadata only."""
    table_stmt = (
        select(SemanticTableModel)
        .options(selectinload(SemanticTableModel.columns))
        .where(SemanticTableModel.db_id == db_id)
    )
    relationship_stmt = (
        select(CanonicalRelationshipModel)
        .options(
            selectinload(CanonicalRelationshipModel.from_entity), selectinload(CanonicalRelationshipModel.to_entity)
        )
        .where(CanonicalRelationshipModel.connection_id == db_id, *active_relationship_filters())
    )
    tables = list((await db.execute(table_stmt)).scalars().all())
    relationships = list((await db.execute(relationship_stmt)).scalars().all())
    return tables, relationships


def _inventory(tables: list[SemanticTableModel]) -> list[dict[str, Any]]:
    """Create a compact all-table inventory without values or connection details."""
    return [
        {
            "table_name": table.table_name,
            "business_name": table.business_name,
            "description": table.description,
            "columns": [column.column_name for column in table.columns],
        }
        for table in tables
    ]


async def _select_tables(
    question: str,
    inventory: list[dict[str, Any]],
    tables: list[SemanticTableModel | dict[str, Any]],
    target_tables: list[str] | None,
    prompt_template: str = _SCOPE_PROMPT,
) -> tuple[set[str], dict[str, Any] | None]:
    """Use the first controlled AI call to select a business domain."""
    valid = {table["table_name"] if isinstance(table, dict) else table.table_name for table in tables}
    if target_tables:
        selected = set(target_tables) & valid
        return (
            (selected, None)
            if selected
            else (set(), _clarification("Bảng được chọn không tồn tại trong schema.").diagnostic)
        )
    prompt = prompt_template.format(inventory=json.dumps(inventory, ensure_ascii=False), question=question)
    if prompt_template == _DATA_SCOPE_PROMPT:
        prompt += _CLARIFICATION_OPTIONS_PROMPT
    try:
        payload = (
            (await invoke_metric_json(MetricScopeSelection, prompt, "schema")).model_dump()
            if prompt_template != _DATA_SCOPE_PROMPT
            else await ainvoke_json(get_llm(role="metric"), prompt)
        )
    except MetricCallError as exc:
        return set(), {
            "status": "error",
            "message": exc.error.message,
            "execution_error": exc.error.model_dump(mode="json"),
        }
    selected = (
        {str(name) for name in payload.get("table_names", []) if str(name) in valid}
        if isinstance(payload, dict)
        else set()
    )
    if prompt_template == _SCOPE_PROMPT and not selected and len(valid) == 1:
        selected = valid
    if selected and prompt_template != _DATA_SCOPE_PROMPT:
        return selected, None
    if not isinstance(payload, dict) or payload.get("needs_clarification") or not selected:
        message = payload.get("question") if isinstance(payload, dict) else "Hãy nêu rõ phần dữ liệu bạn muốn xem."
        options = payload.get("options", []) if isinstance(payload, dict) else []
        diagnostic = _clarification(str(message or "Hãy nêu rõ phần dữ liệu bạn muốn xem."), options).diagnostic
        if prompt_template == _SCOPE_PROMPT:
            for option in diagnostic["clarification"]["options"]:
                option["action"] = "create_metric"
        return set(), diagnostic
    return selected, None


def _asks_for_temporal_fields(question: str) -> bool:
    """Recognize schema-discovery questions about date and time fields."""
    normalized = _strip_accents(question).lower()
    markers = ("thoi gian", "date/time", "date time", "timestamp", "ngay", "thang", "nam")
    return any(marker in normalized for marker in markers)


def _strip_accents(value: str) -> str:
    """Make common Vietnamese schema questions insensitive to diacritics."""
    normalized = unicodedata.normalize("NFD", value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").replace("đ", "d")


def _temporal_context(tables: list[SemanticTableModel]) -> MetricContextResult:
    """Return all temporal fields without a scope-selection call."""
    items = [_temporal_table_payload(table) for table in tables]
    schema = {"tables": [item for item in items if item is not None], "relationships": []}
    return MetricContextResult(schema=schema, diagnostic=_ready_diagnostic(schema))


def _temporal_table_payload(table: SemanticTableModel) -> dict[str, Any] | None:
    """Serialize temporal columns from one semantic table."""
    columns = [_column_payload(column) for column in table.columns if _is_temporal_column(column)]
    if not columns:
        return None
    return {
        "table_name": table.table_name,
        "business_name": table.business_name,
        "description": table.description,
        "columns": columns,
    }


def _is_temporal_column(column: Any) -> bool:
    """Identify a SQL date, time, or timestamp column."""
    data_type = (column.data_type or "").upper()
    return any(marker in data_type for marker in ("DATE", "TIME", "TIMESTAMP"))


def _expand_context(
    tables: list[SemanticTableModel], relationships: list[CanonicalRelationshipModel], selected: set[str]
) -> dict[str, Any]:
    """Keep the selected business subgraph without unrelated neighbor tables."""
    included = set(selected)
    return {
        "tables": [_table_payload(table) for table in tables if table.table_name in included],
        "relationships": _relations(relationships, included),
    }


def _table_payload(table: SemanticTableModel) -> dict[str, Any]:
    """Serialize one table without sample values or other data-bearing metadata."""
    return {
        "id": table.id,
        "table_name": table.table_name,
        "business_name": table.business_name,
        "description": table.description,
        "review_status": table.review_status,
        "columns": [_column_payload(column) for column in table.columns],
    }


def _column_payload(column: Any) -> dict[str, Any]:
    """Serialize one semantic column without data values."""
    return {
        "id": column.id,
        "column_name": column.column_name,
        "data_type": column.data_type,
        "business_name": column.business_name,
        "description": column.description,
        "is_primary_key": column.is_primary_key,
        "is_nullable": column.is_nullable,
        "allowed_values": list(column.allowed_values) if column.allowed_values else None,
        "review_status": column.review_status,
        "is_foreign_key": column.is_foreign_key,
        "fk_target_table": column.fk_target_table,
        "fk_target_column": column.fk_target_column,
    }


def _relations(relationships: list[CanonicalRelationshipModel], included: set[str]) -> list[dict[str, str]]:
    """Serialize only relationships wholly contained in the selected context."""
    return [
        {
            "from_table": relation.from_entity.table_name,
            "to_table": relation.to_entity.table_name,
            "join_condition": relation.join_condition,
            "relationship_type": relation.relationship_type,
        }
        for relation in relationships
        if relation.from_entity.table_name in included and relation.to_entity.table_name in included
    ]


def _token_estimate(value: Any) -> int:
    """Use a conservative token estimate without provider-specific tokenizers."""
    return (len(json.dumps(value, ensure_ascii=False)) + 3) // 4


def _clarification(message: str, options: Any = None) -> MetricContextResult:
    """Return a safe clarification result without calling downstream Metric AI."""
    labels = (
        [label.strip() for label in options if isinstance(label, str) and label.strip()]
        if isinstance(options, list)
        else []
    )
    clarification = ChatClarificationPayload(
        prompt=message,
        options=[
            ChatClarificationOption(id=f"scope_{index}", label=label)
            for index, label in enumerate(dict.fromkeys(labels))
        ],
    )
    return MetricContextResult(
        schema={},
        diagnostic={
            "status": "needs_clarification",
            "message": message,
            "clarification": clarification.model_dump(mode="json"),
        },
    )


def _ready_diagnostic(schema: dict[str, Any]) -> dict[str, Any]:
    """Return non-sensitive context telemetry for authorized Data Leads."""
    return {
        "status": "ready",
        "tables": [item["table_name"] for item in schema["tables"]],
        "relationship_count": len(schema["relationships"]),
    }
