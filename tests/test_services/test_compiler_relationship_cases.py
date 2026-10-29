"""Tests for Task 4: schema-qualified identifiers, composite/multi-hop joins, and one-to-many EXISTS filters."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.schemas import DimensionSelection, SemanticQueryFilter, SemanticQuerySpec
from src.services.query_compiler import SemanticQueryCompiler
from src.services.relationship_runtime import safe_join_path
from src.services.semantic_compile_error import SemanticCompileError


async def _add_table(
    session: AsyncSession,
    db_id: int,
    name: str,
    columns: list[tuple[str, str, bool]],
    schema: str | None = None,
) -> tuple[SemanticTableModel, dict[str, SemanticColumnModel]]:
    table = SemanticTableModel(
        db_id=db_id,
        table_name=name,
        physical_schema=schema,
        business_name=name,
        description="",
        primary_key_column=columns[0][0],
    )
    session.add(table)
    await session.flush()
    col_models = {
        col_name: SemanticColumnModel(
            table_id=table.id,
            column_name=col_name,
            data_type=dtype,
            business_name=col_name,
            is_primary_key=is_pk,
        )
        for col_name, dtype, is_pk in columns
    }
    session.add_all(col_models.values())
    await session.flush()
    return table, col_models


def _make_sum_metric(
    db_id: int,
    name: str,
    base_entity: str,
    base_entity_id: int | None,
    amount_col_id: int,
    grain_col_id: int,
    filters: list[dict[str, object]] | None = None,
    expression: str = "amount",
) -> SemanticMetricModel:
    return SemanticMetricModel(
        db_id=db_id,
        created_by=1,
        name=name,
        description="",
        sql_template="",
        source="ai",
        status="approved",
        base_entity_id=base_entity_id,
        formula="",
        aggregation_type="SUM",
        definition={
            "schema_version": 2,
            "metric": {
                "name": name,
                "formula": {
                    "function": "SUM",
                    "expression": expression,
                    "expression_ast": {"kind": "column", "column_id": amount_col_id},
                },
                "base_entity": base_entity,
                "base_entity_id": base_entity_id,
                "grain": {"column_ids": [grain_col_id]},
                "filters": filters or [],
                "status": "approved",
                "confidence": "high",
                "excluded_notes": "",
            },
        },
    )


@pytest.mark.asyncio
async def test_duplicate_table_names_across_schemas_resolve_by_id_and_reject_ambiguous_name(
    async_session: AsyncSession,
) -> None:
    db = SemanticDatabaseModel(
        created_by=1, display_name="MultiSchema", db_type="postgresql", conn_url_enc="enc", status="ready"
    )
    async_session.add(db)
    await async_session.flush()

    sales_orders, sales_cols = await _add_table(
        async_session,
        db.id,
        "orders",
        [("id", "INTEGER", True), ("amount", "NUMERIC", False), ("customer_id", "INTEGER", False)],
        schema="sales",
    )
    archive_orders, archive_cols = await _add_table(
        async_session,
        db.id,
        "orders",
        [("id", "INTEGER", True), ("amount", "NUMERIC", False)],
        schema="archive",
    )
    customers, cust_cols = await _add_table(
        async_session,
        db.id,
        "customers",
        [("id", "INTEGER", True), ("segment", "TEXT", False)],
        schema="crm",
    )
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=db.id,
            from_entity_id=sales_orders.id,
            to_entity_id=customers.id,
            relationship_type="many_to_one",
            join_condition="sales.orders.customer_id = crm.customers.id",
            relationship_key="sales_orders_customers",
            column_pairs=[{"from_column_id": sales_cols["customer_id"].id, "to_column_id": cust_cols["id"].id}],
            validation_status="valid",
            review_status="approved",
        )
    )
    metric_by_id = _make_sum_metric(
        db.id, "Sales Revenue", "orders", sales_orders.id, sales_cols["amount"].id, sales_cols["id"].id
    )
    metric_ambiguous = _make_sum_metric(
        db.id, "Ambiguous Revenue", "orders", None, archive_cols["amount"].id, archive_cols["id"].id
    )
    async_session.add_all([metric_by_id, metric_ambiguous])
    await async_session.commit()

    compiled = await SemanticQueryCompiler(async_session).compile(
        db.id,
        SemanticQuerySpec(
            metric_ids=[metric_by_id.id],
            dimensions=[DimensionSelection(column_id=cust_cols["segment"].id)],
            filters=[SemanticQueryFilter(column_id=sales_cols["amount"].id, operator="gt", value=10)],
        ),
    )
    assert 'FROM "sales"."orders"' in compiled.sql
    assert 'JOIN "crm"."customers" ON "sales"."orders"."customer_id" = "crm"."customers"."id"' in compiled.sql
    assert 'SUM("sales"."orders"."amount")' in compiled.sql
    assert '"crm"."customers"."segment"' in compiled.sql
    assert '"sales"."orders"."amount" > :runtime_0' in compiled.sql

    with pytest.raises(SemanticCompileError) as exc_info:
        await SemanticQueryCompiler(async_session).compile(
            db.id,
            SemanticQuerySpec(metric_ids=[metric_ambiguous.id]),
        )
    assert exc_info.value.code == "UNKNOWN_REFERENCE"


@pytest.mark.asyncio
async def test_identifier_quoting_with_spaces_keywords_and_case_across_dialects(
    async_session: AsyncSession,
) -> None:
    for db_type, q in (("postgresql", '"'), ("mysql", "`"), ("sqlite", '"')):
        db = SemanticDatabaseModel(
            created_by=1, display_name=f"Quote-{db_type}", db_type=db_type, conn_url_enc="enc", status="ready"
        )
        async_session.add(db)
        await async_session.flush()

        orders, order_cols = await _add_table(
            async_session,
            db.id,
            "Order Header",
            [("Order ID", "INTEGER", True), ("select", "NUMERIC", False), ("Cust Ref", "INTEGER", False)],
            schema="Sales Schema",
        )
        customers, cust_cols = await _add_table(
            async_session,
            db.id,
            "Customer Dim",
            [("Cust ID", "INTEGER", True), ("Group Name", "TEXT", False)],
            schema="Sales Schema",
        )
        async_session.add(
            CanonicalRelationshipModel(
                connection_id=db.id,
                from_entity_id=orders.id,
                to_entity_id=customers.id,
                relationship_type="many_to_one",
                join_condition="fallback",
                relationship_key=f"rel_{db_type}",
                column_pairs=[{"from_column_id": order_cols["Cust Ref"].id, "to_column_id": cust_cols["Cust ID"].id}],
                validation_status="valid",
                review_status="approved",
            )
        )
        metric = _make_sum_metric(
            db.id,
            "Quoted Revenue",
            "Order Header",
            orders.id,
            order_cols["select"].id,
            order_cols["Order ID"].id,
            expression='"select"',
        )
        async_session.add(metric)
        await async_session.commit()

        compiled = await SemanticQueryCompiler(async_session).compile(
            db.id,
            SemanticQuerySpec(
                metric_ids=[metric.id],
                dimensions=[DimensionSelection(column_id=cust_cols["Group Name"].id)],
            ),
        )
        assert f"FROM {q}Sales Schema{q}.{q}Order Header{q}" in compiled.sql
        assert (
            f"JOIN {q}Sales Schema{q}.{q}Customer Dim{q} "
            f"ON {q}Sales Schema{q}.{q}Order Header{q}.{q}Cust Ref{q} = "
            f"{q}Sales Schema{q}.{q}Customer Dim{q}.{q}Cust ID{q}"
        ) in compiled.sql
        assert f"SUM({q}Sales Schema{q}.{q}Order Header{q}.{q}select{q})" in compiled.sql


@pytest.mark.asyncio
async def test_composite_key_and_multi_hop_safe_path_compile_and_execute(
    async_session: AsyncSession,
) -> None:
    db = SemanticDatabaseModel(
        created_by=1, display_name="CompositeHop", db_type="sqlite", conn_url_enc="enc", status="ready"
    )
    async_session.add(db)
    await async_session.flush()

    orders, order_cols = await _add_table(
        async_session,
        db.id,
        "t4_orders",
        [
            ("id", "INTEGER", True),
            ("tenant_id", "INTEGER", False),
            ("customer_id", "INTEGER", False),
            ("amount", "NUMERIC", False),
        ],
    )
    customers, cust_cols = await _add_table(
        async_session,
        db.id,
        "t4_customers",
        [
            ("id", "INTEGER", True),
            ("tenant_id", "INTEGER", False),
            ("region_id", "INTEGER", False),
        ],
    )
    regions, region_cols = await _add_table(
        async_session,
        db.id,
        "t4_regions",
        [("id", "INTEGER", True), ("region_name", "TEXT", False)],
    )
    rel1 = CanonicalRelationshipModel(
        connection_id=db.id,
        from_entity_id=orders.id,
        to_entity_id=customers.id,
        relationship_type="many_to_one",
        join_condition="t4_orders.tenant_id = t4_customers.tenant_id AND t4_orders.customer_id = t4_customers.id",
        relationship_key="t4_orders_customers",
        column_pairs=[
            {"from_column_id": order_cols["tenant_id"].id, "to_column_id": cust_cols["tenant_id"].id},
            {"from_column_id": order_cols["customer_id"].id, "to_column_id": cust_cols["id"].id},
        ],
        validation_status="valid",
        review_status="approved",
    )
    rel2 = CanonicalRelationshipModel(
        connection_id=db.id,
        from_entity_id=customers.id,
        to_entity_id=regions.id,
        relationship_type="one_to_one",
        join_condition="t4_customers.region_id = t4_regions.id",
        relationship_key="t4_customers_regions",
        column_pairs=[{"from_column_id": cust_cols["region_id"].id, "to_column_id": region_cols["id"].id}],
        validation_status="valid",
        review_status="approved",
    )
    async_session.add_all([rel1, rel2])
    metric = _make_sum_metric(
        db.id, "Order Amount", "t4_orders", orders.id, order_cols["amount"].id, order_cols["id"].id
    )
    async_session.add(metric)
    await async_session.commit()

    compiled = await SemanticQueryCompiler(async_session).compile(
        db.id,
        SemanticQuerySpec(
            metric_ids=[metric.id],
            dimensions=[DimensionSelection(column_id=region_cols["region_name"].id)],
        ),
    )
    assert (
        'JOIN "t4_customers" ON "t4_orders"."tenant_id" = "t4_customers"."tenant_id" '
        'AND "t4_orders"."customer_id" = "t4_customers"."id"'
    ) in compiled.sql
    assert 'JOIN "t4_regions" ON "t4_customers"."region_id" = "t4_regions"."id"' in compiled.sql
    assert compiled.metadata["relationship_ids"] == [rel1.id, rel2.id]


@pytest.mark.asyncio
async def test_one_to_many_exists_groups_same_path_separates_distinct_paths_and_handles_is_null(
    async_session: AsyncSession,
) -> None:
    db = SemanticDatabaseModel(
        created_by=1, display_name="OneToManyExists", db_type="sqlite", conn_url_enc="enc", status="ready"
    )
    async_session.add(db)
    await async_session.flush()

    orders, order_cols = await _add_table(
        async_session,
        db.id,
        "t4_ex_orders",
        [("id", "INTEGER", True), ("revenue", "NUMERIC", False)],
    )
    items, item_cols = await _add_table(
        async_session,
        db.id,
        "t4_ex_items",
        [
            ("id", "INTEGER", True),
            ("order_id", "INTEGER", False),
            ("product_name", "TEXT", False),
            ("qty", "INTEGER", False),
            ("discount_code", "TEXT", False),
        ],
    )
    payments, pay_cols = await _add_table(
        async_session,
        db.id,
        "t4_ex_payments",
        [
            ("id", "INTEGER", True),
            ("order_id", "INTEGER", False),
            ("method", "TEXT", False),
        ],
    )
    rel_items = CanonicalRelationshipModel(
        connection_id=db.id,
        from_entity_id=orders.id,
        to_entity_id=items.id,
        relationship_type="one_to_many",
        join_condition="t4_ex_orders.id = t4_ex_items.order_id",
        relationship_key="t4_orders_items",
        column_pairs=[{"from_column_id": order_cols["id"].id, "to_column_id": item_cols["order_id"].id}],
        validation_status="valid",
        review_status="approved",
    )
    rel_payments = CanonicalRelationshipModel(
        connection_id=db.id,
        from_entity_id=orders.id,
        to_entity_id=payments.id,
        relationship_type="one_to_many",
        join_condition="t4_ex_orders.id = t4_ex_payments.order_id",
        relationship_key="t4_orders_payments",
        column_pairs=[{"from_column_id": order_cols["id"].id, "to_column_id": pay_cols["order_id"].id}],
        validation_status="valid",
        review_status="approved",
    )
    async_session.add_all([rel_items, rel_payments])
    metric = _make_sum_metric(
        db.id,
        "Order Revenue",
        "t4_ex_orders",
        orders.id,
        order_cols["revenue"].id,
        order_cols["id"].id,
        expression="revenue",
    )
    async_session.add(metric)
    await async_session.commit()

    await async_session.execute(text("CREATE TABLE t4_ex_orders (id INTEGER PRIMARY KEY, revenue NUMERIC)"))
    await async_session.execute(
        text(
            "CREATE TABLE t4_ex_items (id INTEGER PRIMARY KEY, order_id INTEGER, product_name TEXT, qty INTEGER, discount_code TEXT)"
        )
    )
    await async_session.execute(
        text("CREATE TABLE t4_ex_payments (id INTEGER PRIMARY KEY, order_id INTEGER, method TEXT)")
    )
    # Order 1: revenue=100, has TWO matching Widget rows (qty >= 2) and card payment -> should count once (100)
    # Order 2: revenue=250, has Widget (qty=1) and Gadget (qty=5) -> should NOT match combined EXISTS
    # Order 3: revenue=75, has NO child items at all -> should NOT match is_null on child discount_code
    await async_session.execute(text("INSERT INTO t4_ex_orders VALUES (1, 100), (2, 250), (3, 75)"))
    await async_session.execute(
        text(
            "INSERT INTO t4_ex_items VALUES "
            "(10, 1, 'Widget', 2, NULL), "
            "(11, 1, 'Widget', 4, 'PROMO'), "
            "(20, 2, 'Widget', 1, 'PROMO'), "
            "(21, 2, 'Gadget', 5, 'PROMO')"
        )
    )
    await async_session.execute(text("INSERT INTO t4_ex_payments VALUES (100, 1, 'card'), (200, 2, 'card')"))
    await async_session.commit()

    compiler = SemanticQueryCompiler(async_session)
    compiled = await compiler.compile(
        db.id,
        SemanticQuerySpec(
            metric_ids=[metric.id],
            filters=[
                SemanticQueryFilter(column_id=item_cols["product_name"].id, operator="eq", value="Widget"),
                SemanticQueryFilter(column_id=item_cols["qty"].id, operator="gte", value=2),
                SemanticQueryFilter(column_id=pay_cols["method"].id, operator="eq", value="card"),
            ],
        ),
    )
    assert "JOIN" not in compiled.sql
    assert compiled.sql.upper().count("EXISTS") == 2
    assert f'AS "t_{items.id}"' in compiled.sql
    assert f'AS "t_{payments.id}"' in compiled.sql
    rows = (await async_session.execute(text(compiled.sql), compiled.parameters)).mappings().all()
    assert len(rows) == 1
    assert float(rows[0][f"metric_{metric.id}"]) == 100.0

    # Verify is_null on child column only matches orders that have a child row with discount_code IS NULL (Order 1),
    # and does NOT match Order 3 (which has no child rows at all).
    null_compiled = await compiler.compile(
        db.id,
        SemanticQuerySpec(
            metric_ids=[metric.id],
            filters=[SemanticQueryFilter(column_id=item_cols["discount_code"].id, operator="is_null")],
        ),
    )
    null_rows = (await async_session.execute(text(null_compiled.sql), null_compiled.parameters)).mappings().all()
    assert len(null_rows) == 1
    assert float(null_rows[0][f"metric_{metric.id}"]) == 100.0


@pytest.mark.asyncio
async def test_rejects_one_to_many_dimension_self_join_ambiguous_path_and_unapproved_relationship(
    async_session: AsyncSession,
) -> None:
    db = SemanticDatabaseModel(
        created_by=1, display_name="Rejections", db_type="sqlite", conn_url_enc="enc", status="ready"
    )
    async_session.add(db)
    await async_session.flush()

    orders, order_cols = await _add_table(
        async_session,
        db.id,
        "t4_rej_orders",
        [
            ("id", "INTEGER", True),
            ("amount", "NUMERIC", False),
            ("parent_order_id", "INTEGER", False),
            ("billing_customer_id", "INTEGER", False),
            ("shipping_customer_id", "INTEGER", False),
        ],
    )
    items, item_cols = await _add_table(
        async_session,
        db.id,
        "t4_rej_items",
        [("id", "INTEGER", True), ("order_id", "INTEGER", False), ("sku", "TEXT", False)],
    )
    customers, cust_cols = await _add_table(
        async_session,
        db.id,
        "t4_rej_customers",
        [("id", "INTEGER", True), ("name", "TEXT", False)],
    )
    vendors, vendor_cols = await _add_table(
        async_session,
        db.id,
        "t4_rej_vendors",
        [("id", "INTEGER", True), ("vendor_name", "TEXT", False)],
    )
    async_session.add_all(
        [
            # 1:N child relationship
            CanonicalRelationshipModel(
                connection_id=db.id,
                from_entity_id=orders.id,
                to_entity_id=items.id,
                relationship_type="one_to_many",
                join_condition="t4_rej_orders.id = t4_rej_items.order_id",
                relationship_key="rej_orders_items",
                column_pairs=[{"from_column_id": order_cols["id"].id, "to_column_id": item_cols["order_id"].id}],
                validation_status="valid",
                review_status="approved",
            ),
            # Self-join without explicit role
            CanonicalRelationshipModel(
                connection_id=db.id,
                from_entity_id=orders.id,
                to_entity_id=orders.id,
                relationship_type="many_to_one",
                join_condition="t4_rej_orders.parent_order_id = t4_rej_orders.id",
                relationship_key="rej_orders_self",
                column_pairs=[
                    {"from_column_id": order_cols["parent_order_id"].id, "to_column_id": order_cols["id"].id}
                ],
                validation_status="valid",
                review_status="approved",
            ),
            # Two ambiguous paths to customers
            CanonicalRelationshipModel(
                connection_id=db.id,
                from_entity_id=orders.id,
                to_entity_id=customers.id,
                relationship_type="many_to_one",
                join_condition="t4_rej_orders.billing_customer_id = t4_rej_customers.id",
                relationship_key="rej_orders_billing_cust",
                column_pairs=[
                    {"from_column_id": order_cols["billing_customer_id"].id, "to_column_id": cust_cols["id"].id}
                ],
                validation_status="valid",
                review_status="approved",
            ),
            CanonicalRelationshipModel(
                connection_id=db.id,
                from_entity_id=orders.id,
                to_entity_id=customers.id,
                relationship_type="many_to_one",
                join_condition="t4_rej_orders.shipping_customer_id = t4_rej_customers.id",
                relationship_key="rej_orders_shipping_cust",
                column_pairs=[
                    {"from_column_id": order_cols["shipping_customer_id"].id, "to_column_id": cust_cols["id"].id}
                ],
                validation_status="valid",
                review_status="approved",
            ),
            # Unapproved relationship to vendors
            CanonicalRelationshipModel(
                connection_id=db.id,
                from_entity_id=orders.id,
                to_entity_id=vendors.id,
                relationship_type="many_to_one",
                join_condition="t4_rej_orders.id = t4_rej_vendors.id",
                relationship_key="rej_orders_vendors_pending",
                column_pairs=[{"from_column_id": order_cols["id"].id, "to_column_id": vendor_cols["id"].id}],
                validation_status="valid",
                review_status="needs_review",
            ),
        ]
    )
    metric = _make_sum_metric(
        db.id, "Rej Revenue", "t4_rej_orders", orders.id, order_cols["amount"].id, order_cols["id"].id
    )
    async_session.add(metric)
    await async_session.commit()

    compiler = SemanticQueryCompiler(async_session)

    # 1. Dimension on one_to_many child table -> UNSAFE_FANOUT
    with pytest.raises(SemanticCompileError) as fanout_err:
        await compiler.compile(
            db.id,
            SemanticQuerySpec(
                metric_ids=[metric.id],
                dimensions=[DimensionSelection(column_id=item_cols["sku"].id)],
            ),
        )
    assert fanout_err.value.code == "UNSAFE_FANOUT"

    # 2. Ambiguous join path on dimension -> AMBIGUOUS_JOIN_PATH
    with pytest.raises(SemanticCompileError) as amb_dim_err:
        await compiler.compile(
            db.id,
            SemanticQuerySpec(
                metric_ids=[metric.id],
                dimensions=[DimensionSelection(column_id=cust_cols["name"].id)],
            ),
        )
    assert amb_dim_err.value.code == "AMBIGUOUS_JOIN_PATH"

    # 3. Ambiguous join path on filter -> AMBIGUOUS_JOIN_PATH
    with pytest.raises(SemanticCompileError) as amb_filter_err:
        await compiler.compile(
            db.id,
            SemanticQuerySpec(
                metric_ids=[metric.id],
                filters=[SemanticQueryFilter(column_id=cust_cols["name"].id, operator="eq", value="Acme")],
            ),
        )
    assert amb_filter_err.value.code == "AMBIGUOUS_JOIN_PATH"

    # 4. Unapproved relationship -> UNSAFE_JOIN for dimension, UNREACHABLE_FILTER for filter
    with pytest.raises(SemanticCompileError) as unapproved_dim_err:
        await compiler.compile(
            db.id,
            SemanticQuerySpec(
                metric_ids=[metric.id],
                dimensions=[DimensionSelection(column_id=vendor_cols["vendor_name"].id)],
            ),
        )
    assert unapproved_dim_err.value.code in {"UNREACHABLE_DIMENSION", "UNSAFE_JOIN"}

    with pytest.raises(SemanticCompileError) as unapproved_filter_err:
        await compiler.compile(
            db.id,
            SemanticQuerySpec(
                metric_ids=[metric.id],
                filters=[SemanticQueryFilter(column_id=vendor_cols["vendor_name"].id, operator="eq", value="V1")],
            ),
        )
    assert unapproved_filter_err.value.code in {"UNREACHABLE_FILTER", "UNSAFE_JOIN"}

    # 5. Self-join without explicit role -> UNSAFE_JOIN
    self_rel = CanonicalRelationshipModel(
        id=999,
        connection_id=db.id,
        from_entity_id=orders.id,
        to_entity_id=orders.id,
        relationship_type="many_to_one",
        join_condition="t4_rej_orders.parent_order_id = t4_rej_orders.id",
        relationship_key="self_join_direct",
        column_pairs=[{"from_column_id": order_cols["parent_order_id"].id, "to_column_id": order_cols["id"].id}],
        validation_status="valid",
        review_status="approved",
    )
    with pytest.raises(SemanticCompileError) as self_join_err:
        safe_join_path([self_rel], orders.id, orders.id)
    assert self_join_err.value.code == "UNSAFE_JOIN"
