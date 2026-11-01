"""Parse user-provided value mappings without persisting or querying target data."""

import csv
import json
import math
from io import BytesIO, StringIO
from itertools import islice
from typing import Any
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook


def parse_value_mapping_file(content: bytes, file_type: str, db_id: int, column_id: int) -> list[dict[str, Any]]:
    """Parse one column's mappings from JSON, CSV, or an Excel workbook."""
    try:
        if file_type == "json":
            rows = _json_rows(json.loads(content.decode("utf-8-sig")), db_id, column_id)
        elif file_type == "csv":
            rows = list(islice(csv.DictReader(StringIO(content.decode("utf-8-sig"), newline="")), 1001))
        elif file_type == "xlsx":
            rows = _safe_xlsx_rows(content)
        else:
            raise ValueError("Unsupported file type")
    except (UnicodeError, json.JSONDecodeError, csv.Error, BadZipFile, KeyError, TypeError) as exc:
        raise ValueError("Invalid file format") from exc
    return _validate_rows(rows, db_id, column_id)


def parse_value_mapping_batch(content: bytes, file_type: str, db_id: int) -> dict[int, list[dict[str, Any]]]:
    """Parse a file with explicit column IDs for a database-wide preview."""
    try:
        if file_type == "json":
            data = json.loads(content.decode("utf-8-sig"))
            rows = _batch_json_rows(data, db_id)
        elif file_type == "csv":
            rows = list(islice(csv.DictReader(StringIO(content.decode("utf-8-sig"), newline="")), 1001))
        elif file_type == "xlsx":
            rows = _safe_xlsx_rows(content)
        else:
            raise ValueError("Unsupported file type")
        return _group_batch_rows(rows, db_id)
    except (UnicodeError, json.JSONDecodeError, csv.Error, BadZipFile, KeyError, TypeError) as exc:
        raise ValueError("Invalid file format") from exc


def _batch_json_rows(data: Any, db_id: int) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("columns"), list):
        raise ValueError("JSON must contain a columns array with column_id")
    if data.get("db_id") is not None and data["db_id"] != db_id:
        raise ValueError("File belongs to another database")
    rows, seen = [], set()
    for column in data["columns"]:
        if not isinstance(column, dict) or not isinstance(column.get("items"), list):
            raise ValueError("Invalid columns list")
        identifier = _column_id(column.get("column_id"))
        if identifier in seen:
            raise ValueError("Duplicate column_id in file")
        seen.add(identifier)
        rows.extend({**item, "column_id": identifier} for item in column["items"])
        if len(rows) > 1000:
            raise ValueError("Too many rows")
    return rows


def _column_id(value: Any) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError("Each row must contain a valid column_id")
    return int(value)


def _group_batch_rows(rows: list, db_id: int) -> dict[int, list[dict[str, Any]]]:
    if len(rows) > 1000:
        raise ValueError("Too many rows")
    groups: dict[int, list] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each row must be an object")
        if all(value in (None, "") for value in row.values()):
            continue
        identifier = _column_id(row.get("column_id"))
        groups.setdefault(identifier, []).append(row)
    if not groups or len(groups) > 100:
        raise ValueError("File must contain between 1 and 100 columns")
    return {identifier: _validate_rows(items, db_id, identifier) for identifier, items in groups.items()}


def _json_rows(data: Any, db_id: int, column_id: int) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise ValueError("JSON must contain mappings")
    if data.get("db_id") is not None and data["db_id"] != db_id:
        raise ValueError("File belongs to another database")
    if "columns" in data:
        if not isinstance(data["columns"], list) or any(not isinstance(item, dict) for item in data["columns"]):
            raise ValueError("Invalid columns list")
        columns = [item for item in data["columns"] if item.get("column_id") == column_id]
        if len(columns) != 1:
            raise ValueError("Column missing or duplicated in file")
        return columns[0]["items"]
    if data.get("column_id") is not None and data["column_id"] != column_id:
        raise ValueError("File belongs to another column")
    return data["items"]


def _safe_xlsx_rows(content: bytes) -> list[dict]:
    try:
        return _xlsx_rows(content)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid Excel workbook") from exc


def _xlsx_rows(content: bytes) -> list[dict]:
    with ZipFile(BytesIO(content)) as archive:
        if len(archive.infolist()) > 1000 or sum(item.file_size for item in archive.infolist()) > 10_000_000:
            raise ValueError("Workbook is too large")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise ValueError("Invalid Excel workbook") from exc
    try:
        if workbook.active.max_column and workbook.active.max_column > 20:
            raise ValueError("Workbook has too many columns")
        if workbook.active.max_row and workbook.active.max_row > 1001:
            raise ValueError("Too many rows")
        rows = workbook.active.iter_rows()
        headers = [cell.value for cell in next(rows, [])]
        result = []
        for cells in rows:
            if len(result) >= 1000:
                raise ValueError("Too many rows")
            if any(cell.data_type == "f" for cell in cells):
                raise ValueError("Excel formula cells are not supported")
            result.append(dict(zip(headers, (cell.value for cell in cells), strict=False)))
        return result
    finally:
        workbook.close()


def _validate_rows(rows: Any, db_id: int, column_id: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Invalid or too many rows")
    selected = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each row must be an object")
        if all(value in (None, "") for value in row.values()):
            continue
        if row.get("db_id") not in (None, "", db_id, str(db_id)):
            raise ValueError("File belongs to another database")
        if "column_id" in row and row["column_id"] in (None, ""):
            raise ValueError("Each row must contain a valid column_id")
        if row.get("column_id") not in (None, "", column_id, str(column_id)):
            continue
        if "db_value" not in row or "business_value" not in row:
            raise ValueError("Required columns: db_value, business_value")
        value, meaning = row["db_value"], row["business_value"]
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Database value must be text, a number, or a boolean")
        if not isinstance(meaning, str) or not meaning.strip() or len(meaning) > 200:
            raise ValueError("Business value must be text of 1–200 characters")
        key = (type(value).__name__, str(value))
        if key in seen:
            raise ValueError("Duplicate database values")
        seen.add(key)
        selected.append({"db_value": value, "business_value": meaning})
    if not selected or len(selected) > 100:
        raise ValueError("Column must have between 1 and 100 values")
    return selected
