"""Tạo target DB mẫu (EAV) để demo và manual test Flow 2 với nguồn EAV.

Pure Python, chỉ dùng stdlib. Hai chế độ:

    python scripts/setup_target_eav_db.py                      # sqlite scratch/eav_demo.db
    python scripts/setup_target_eav_db.py --path demo.db       # sqlite theo đường dẫn chỉ định
    python scripts/setup_target_eav_db.py --dialect postgres   # in SQL ra stdout (psql -f)

Dữ liệu mẫu (entity 1..4, thuộc tính mỗi dòng một giá trị):
    revenue  number  reject  → theo khu vực: Miền Bắc 300, Miền Nam 125
    region   string  reject  → 1,2=Miền Bắc; 3,4=Miền Nam
    clicks   number  sum     → entity 1 có 2 dòng (10+5); Bắc 18, Nam 10
    segment  string  history → entity 1 đổi VIP→Thường từ 2026-07-01; entity 3 VIP từ 2026-03-01
    attr_dict/attr_fk        → biến thể dictionary: R1=Khách lẻ (1,2), R2=Khách VIP (3,4)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCHEMA_SQL = [
    "CREATE TABLE IF NOT EXISTS entity_eav ("
    " entity_id INTEGER NOT NULL,"
    " attr_code TEXT, attr_fk TEXT,"
    " value_str TEXT, value_num REAL,"
    " eff_at TEXT, end_at TEXT)",
    "CREATE TABLE IF NOT EXISTS attr_dict (dict_code TEXT PRIMARY KEY, dict_label TEXT NOT NULL)",
]

# (entity_id, attr_code, attr_fk, value_str, value_num, eff_at, end_at)
ROWS: list[tuple] = [
    (1, "revenue", None, None, 100.0, None, None),
    (2, "revenue", None, None, 200.0, None, None),
    (3, "revenue", None, None, 50.0, None, None),
    (4, "revenue", None, None, 75.0, None, None),
    (1, "region", None, "Miền Bắc", None, None, None),
    (2, "region", None, "Miền Bắc", None, None, None),
    (3, "region", None, "Miền Nam", None, None, None),
    (4, "region", None, "Miền Nam", None, None, None),
    (1, "clicks", None, None, 10.0, None, None),
    (1, "clicks", None, None, 5.0, None, None),
    (2, "clicks", None, None, 3.0, None, None),
    (3, "clicks", None, None, 8.0, None, None),
    (4, "clicks", None, None, 2.0, None, None),
    (1, "segment", None, "VIP", None, "2026-01-01", "2026-06-30"),
    (1, "segment", None, "Thường", None, "2026-07-01", None),
    (3, "segment", None, "VIP", None, "2026-03-01", None),
    (1, None, "R1", None, None, None, None),
    (2, None, "R1", None, None, None, None),
    (3, None, "R2", None, None, None, None),
    (4, None, "R2", None, None, None, None),
]

DICT_ROWS = [("R1", "Khách lẻ"), ("R2", "Khách VIP")]


def build_sql() -> list[str]:
    """Render schema + seed statements in portable SQL."""
    statements = [f"{stmt};" for stmt in SCHEMA_SQL]
    statements.append("DELETE FROM entity_eav;")
    statements.append("DELETE FROM attr_dict;")
    statements.extend(
        "INSERT INTO entity_eav (entity_id, attr_code, attr_fk, value_str, value_num, eff_at, end_at)"  # noqa: S608 - static seed
        f" VALUES ({', '.join(_literal(value) for value in row)});"
        for row in ROWS
    )
    statements.extend(
        f"INSERT INTO attr_dict (dict_code, dict_label)"  # noqa: S608 - static seed
        f" VALUES ({_literal(code)}, {_literal(label)});"
        for code, label in DICT_ROWS
    )
    return statements


def _literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def setup_sqlite(path: Path) -> None:
    """Create and seed one sqlite target database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript("\n".join(build_sql()))
        connection.commit()
        _verify(connection)
    finally:
        connection.close()
    print(f"Đã tạo sqlite target DB EAV: {path}")
    print("Số liệu kỳ vọng — revenue theo region: Miền Bắc 300, Miền Nam 125.")


def _verify(connection: sqlite3.Connection) -> None:
    """Fail loudly if the seed does not produce the documented totals."""
    revenue = connection.execute(
        "SELECT r.value_str AS region, SUM(v.value_num) AS total"
        " FROM entity_eav r JOIN entity_eav v"
        " ON v.entity_id = r.entity_id AND v.attr_code = 'revenue'"
        " WHERE r.attr_code = 'region' GROUP BY r.value_str ORDER BY r.value_str"
    ).fetchall()
    assert revenue == [("Miền Bắc", 300.0), ("Miền Nam", 125.0)], revenue
    clicks = connection.execute(
        "SELECT r.value_str AS region, SUM(v.value_num) AS total"
        " FROM entity_eav r JOIN entity_eav v"
        " ON v.entity_id = r.entity_id AND v.attr_code = 'clicks'"
        " WHERE r.attr_code = 'region' GROUP BY r.value_str ORDER BY r.value_str"
    ).fetchall()
    assert clicks == [("Miền Bắc", 18.0), ("Miền Nam", 10.0)], clicks


def main() -> None:
    parser = argparse.ArgumentParser(description="Tạo target DB mẫu cho nguồn EAV")
    parser.add_argument("--dialect", choices=["sqlite", "postgres"], default="sqlite")
    parser.add_argument("--path", default=os.path.join("scratch", "eav_demo.db"), help="Đường dẫn file sqlite")
    args = parser.parse_args()
    if args.dialect == "postgres":
        print("\n".join(build_sql()))
        print("-- Chạy: python scripts/setup_target_eav_db.py --dialect postgres | psql <target_url>", file=sys.stderr)
        return
    setup_sqlite(Path(args.path))


if __name__ == "__main__":
    main()
