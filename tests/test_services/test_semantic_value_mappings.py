"""Approved business mappings use explicit approval, not sample-value heuristics."""

from src.services.semantic_value_mappings import read_approved_business_mappings


def test_approved_mappings_preserve_json_scalar_types_and_unrestricted_labels() -> None:
    mappings = [
        {"db_value": "001", "business_value": "Paid by Account Manager!", "status": "approved"},
        {"db_value": 7, "business_value": "KHU VỰC, ƯU TIÊN", "status": "approved"},
        {"db_value": True, "business_value": "Miền Bắc (đặc biệt)", "status": "approved"},
        {"db_value": 1.5, "business_value": "Café - đã thanh toán", "status": "approved"},
    ]

    result = read_approved_business_mappings(mappings, "approved")

    assert [item["db_value"] for item in result] == ["001", 7, True, 1.5]
    assert [type(item["db_value"]) for item in result] == [str, int, bool, float]
    assert result[0]["business_value"] == "Paid by Account Manager!"


def test_approved_mappings_have_no_sample_count_limit_or_sensitive_name_filter() -> None:
    mappings = [
        {"db_value": f"code-{index}", "business_value": f"Customer Name, Tier {index}!", "status": "approved"}
        for index in range(25)
    ]

    assert len(read_approved_business_mappings(mappings, "approved")) == 25


def test_reader_excludes_unapproved_columns_rows_and_malformed_records() -> None:
    mappings = [
        {"db_value": "pending", "business_value": "Pending", "status": "pending"},
        {"db_value": "dismissed", "business_value": "Dismissed", "status": "dismissed"},
        {"db_value": "empty", "business_value": "  ", "status": "approved"},
        {"business_value": "Missing db value", "status": "approved"},
        {"db_value": [], "business_value": "Bad value type", "status": "approved"},
        "not an object",
        {"db_value": "valid", "business_value": "Đã duyệt!", "status": "approved"},
    ]

    assert read_approved_business_mappings(mappings, "pending_review") == []
    assert read_approved_business_mappings(mappings, "approved") == [
        {"db_value": "valid", "business_value": "Đã duyệt!", "status": "approved"}
    ]


def test_normalized_label_matching_is_shared_and_boundary_aware() -> None:
    from src.services.semantic_value_mappings import business_label_matches, normalize_business_label

    assert normalize_business_label("  MIỀN   Bắc! ") == normalize_business_label("miền bắc!")
    assert business_label_matches("Doanh thu MIỀN BẮC! năm nay", "miền bắc!")
    assert not business_label_matches("Northstar", "North")


def test_scalar_value_identity_never_confuses_boolean_number_or_numeric_code() -> None:
    from src.services.semantic_value_mappings import scalar_value_key

    assert scalar_value_key(True) != scalar_value_key(1)
    assert scalar_value_key("001") != scalar_value_key(1)
    assert scalar_value_key(1) != scalar_value_key(1.0)


def test_label_normalization_collisions_remain_ambiguous():
    from src.services.semantic_value_mappings import approved_mapping_candidates

    column = {
        "review_status": "approved",
        "allowed_values": [],
        "_approved_mappings": [
            {"db_value": "north-1", "business_value": "North!", "status": "approved"},
            {"db_value": "north-2", "business_value": "NORTH", "status": "approved"},
        ],
    }

    assert len(approved_mapping_candidates(" north ", column)) == 2


def test_leading_grammatical_or_column_prefix_resolves_without_matching_suffix_variants() -> None:
    from src.services.semantic_value_mappings import approved_mapping_candidates

    column = {
        "column_name": "order_status",
        "business_name": "Trạng thái đơn",
        "review_status": "approved",
        "allowed_values": [],
        "_approved_mappings": [{"db_value": "completed", "business_value": "Hoàn tất", "status": "approved"}],
    }

    assert approved_mapping_candidates("đã hoàn tất", column) == ["completed"]
    assert approved_mapping_candidates("trạng thái đơn đã hoàn tất", column) == ["completed"]
    assert approved_mapping_candidates("hoàn tất một phần", column) == []


def test_metric_technical_review_resolves_approved_business_mapping_filter_values() -> None:
    from src.services.metric_review_validation import technical_review

    schema = {
        "tables": [
            {
                "id": 1,
                "table_name": "orders",
                "columns": [
                    {"id": 10, "column_name": "id", "data_type": "INT", "is_primary_key": True, "is_nullable": False},
                    {
                        "id": 11,
                        "column_name": "amount",
                        "data_type": "DECIMAL(10,2)",
                        "is_primary_key": False,
                        "is_nullable": False,
                    },
                    {
                        "id": 12,
                        "column_name": "region",
                        "business_name": "Khu vực",
                        "data_type": "VARCHAR(32)",
                        "is_primary_key": False,
                        "is_nullable": False,
                        "review_status": "approved",
                        "allowed_values": None,
                        "allowed_values_complete": True,
                        "allowed_value_mappings": [
                            {"db_value": "North", "business_value": "Miền Bắc", "status": "approved"},
                            {"db_value": "South", "business_value": "Miền Nam", "status": "approved"},
                        ],
                    },
                ],
            }
        ],
        "relationships": [],
    }
    raw = {
        "metric": {
            "name": "Doanh thu khu vực miền Bắc",
            "base_entity": "orders",
            "formula": {"function": "SUM", "expression": "amount"},
            "filters": [{"field": "region", "operator": "eq", "value": "khu vực miền Bắc"}],
        }
    }
    definition, review = technical_review(raw, {"schema": schema})
    assert review is None
    assert definition is not None
    assert definition.metric.filters[0].value == "North"


def test_metric_technical_review_rejects_ambiguous_business_mapping_filter_value() -> None:
    from src.services.metric_review_validation import technical_review

    schema = {
        "tables": [
            {
                "id": 1,
                "table_name": "orders",
                "columns": [
                    {"id": 10, "column_name": "id", "data_type": "INT", "is_primary_key": True, "is_nullable": False},
                    {
                        "id": 12,
                        "column_name": "region",
                        "business_name": "Khu vực",
                        "data_type": "VARCHAR(32)",
                        "is_primary_key": False,
                        "is_nullable": False,
                        "review_status": "approved",
                        "allowed_values": None,
                        "allowed_values_complete": True,
                        "allowed_value_mappings": [
                            {"db_value": "north_1", "business_value": "Miền Bắc", "status": "approved"},
                            {"db_value": "north_2", "business_value": "MIỀN BẮC!", "status": "approved"},
                        ],
                    },
                ],
            }
        ],
        "relationships": [],
    }
    raw = {
        "metric": {
            "name": "Số đơn miền Bắc",
            "base_entity": "orders",
            "formula": {"function": "COUNT_DISTINCT", "expression": "id"},
            "filters": [{"field": "region", "operator": "eq", "value": "Miền Bắc"}],
        }
    }
    definition, review = technical_review(raw, {"schema": schema})
    assert definition is None
    assert review is not None
    assert review.status == "needs_revision"
    assert "mơ hồ" in review.issues[0].evidence


def test_mapping_fingerprint_changes_without_exposing_mapping_content() -> None:
    from src.services.semantic_value_mappings import mapping_metadata_fingerprint

    first = [{"db_value": "North", "business_value": "Miền Bắc", "status": "approved"}]
    edited = [{"db_value": "North", "business_value": "Miền Bắc mới", "status": "approved"}]

    digest = mapping_metadata_fingerprint(first, "approved", False)

    assert digest != mapping_metadata_fingerprint(edited, "approved", False)
    assert digest != mapping_metadata_fingerprint(first, "pending_review", False)
    assert "North" not in digest and "Miền Bắc" not in digest


def test_consistent_approved_mapping_reading_across_query_metric_and_data_contexts() -> None:
    from types import SimpleNamespace

    from src.services.metric_context import _column_payload
    from src.services.metrics import _format_columns
    from src.services.natural_language_query import _attach_filter_value_metadata
    from src.services.semantic_query_parser_context import prompt_catalog

    column = SimpleNamespace(
        id=9,
        column_name="payment_tier",
        data_type="TEXT",
        business_name="Hạng thanh toán",
        description="Hạng",
        is_primary_key=False,
        is_foreign_key=False,
        is_nullable=False,
        fk_target_table=None,
        fk_target_column=None,
        review_status="approved",
        allowed_values=[],
        allowed_values_complete=False,
        allowed_value_mappings=[
            {"db_value": "001", "business_value": "Account Manager, Tier 1!", "status": "approved"},
            {"db_value": "002", "business_value": "Pending Tier", "status": "pending"},
        ],
    )
    query_item = {"column_id": 9, "column_name": "payment_tier", "data_type": "TEXT"}
    _attach_filter_value_metadata(query_item, column)
    metric_col = _column_payload(column)
    prompt_col = prompt_catalog({"filter_columns": [query_item]})["filter_columns"][0]
    summary = _format_columns([metric_col])[0]

    expected = [{"db_value": "001", "business_value": "Account Manager, Tier 1!", "status": "approved"}]
    assert query_item["allowed_value_mappings"] == expected
    assert metric_col["allowed_value_mappings"] == expected
    assert prompt_col["allowed_value_mappings"] == expected
    assert "Account Manager, Tier 1!" in summary
    assert "Pending Tier" not in summary
