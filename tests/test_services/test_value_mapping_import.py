"""Import value mappings without changing metadata."""

import json
from io import BytesIO

import pytest
from openpyxl import Workbook

from src.services.value_mapping_import import parse_value_mapping_batch, parse_value_mapping_file


def test_json_selects_one_column_and_checks_database() -> None:
    data = {"db_id": 10, "columns": [{"column_id": 21, "items": [{"db_value": "paid", "business_value": "Đã trả"}]}]}
    payload = json.dumps(data, ensure_ascii=False).encode()
    assert parse_value_mapping_file(payload, "json", 10, 21) == data["columns"][0]["items"]
    with pytest.raises(ValueError, match="database"):
        parse_value_mapping_file(payload, "json", 11, 21)


def test_csv_preserves_strings_and_selects_column() -> None:
    content = b"column_id,db_value,business_value\n21,001,Code\n22,other,Other\n"
    assert parse_value_mapping_file(content, "csv", 10, 21) == [{"db_value": "001", "business_value": "Code"}]


def test_duplicate_values_are_rejected() -> None:
    content = b"db_value,business_value\npaid,Paid\npaid,Other\n"
    with pytest.raises(ValueError, match="Duplicate"):
        parse_value_mapping_file(content, "csv", 10, 21)


def test_batch_groups_csv_and_requires_column_id() -> None:
    content = b"column_id,db_value,business_value\n21,001,One\n22,paid,Paid\n"
    assert parse_value_mapping_batch(content, "csv", 10) == {
        21: [{"db_value": "001", "business_value": "One"}],
        22: [{"db_value": "paid", "business_value": "Paid"}],
    }
    with pytest.raises(ValueError, match="column_id"):
        parse_value_mapping_batch(b"db_value,business_value\npaid,Paid\n", "csv", 10)


def test_batch_json_checks_database_and_duplicate_columns() -> None:
    column = {"column_id": 21, "items": [{"db_value": "paid", "business_value": "Paid"}]}
    content = json.dumps({"db_id": 10, "columns": [column, column]}).encode()
    with pytest.raises(ValueError, match="Duplicate column_id"):
        parse_value_mapping_batch(content, "json", 10)
    with pytest.raises(ValueError, match="database"):
        parse_value_mapping_batch(content, "json", 11)


def test_xlsx_preserves_numeric_value_and_rejects_formula() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["db_value", "business_value"])
    sheet.append([1, "One"])
    output = BytesIO()
    workbook.save(output)
    assert parse_value_mapping_file(output.getvalue(), "xlsx", 10, 21) == [{"db_value": 1, "business_value": "One"}]
    sheet.cell(2, 2, "=1+1")
    output = BytesIO()
    workbook.save(output)
    with pytest.raises(ValueError, match="formula"):
        parse_value_mapping_file(output.getvalue(), "xlsx", 10, 21)


def test_batch_xlsx_uses_column_ids() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["column_id", "db_value", "business_value"])
    sheet.append([21, "paid", "Paid"])
    sheet.append([22, 3, "Three"])
    output = BytesIO()
    workbook.save(output)
    assert parse_value_mapping_batch(output.getvalue(), "xlsx", 10) == {
        21: [{"db_value": "paid", "business_value": "Paid"}],
        22: [{"db_value": 3, "business_value": "Three"}],
    }
