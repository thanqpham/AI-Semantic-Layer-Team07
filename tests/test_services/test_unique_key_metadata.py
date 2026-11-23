"""UNIQUE-key metadata feeds the initial cardinality proposal without reading rows."""

from unittest.mock import MagicMock

import pytest

from src.agents.nodes.schema.save_node import _convert_unique_keys
from src.models.schema_metadata import ColumnMetadata, Identifier, SchemaDialect, TableMetadata
from src.services.unique_key_metadata import build_unique_keys

DIALECT = SchemaDialect.POSTGRESQL


def _names(keys):
    return [[item.raw_name for item in key] for key in keys]


def _inspector(constraints=(), indexes=()):
    inspector = MagicMock()
    inspector.get_unique_constraints.return_value = list(constraints)
    inspector.get_indexes.return_value = list(indexes)
    return inspector


def test_build_unique_keys_collects_constraints_and_unique_indexes():
    inspector = _inspector(
        constraints=[{"name": "uq_email", "column_names": ["email"]}],
        indexes=[
            {"name": "ix_a", "column_names": ["a", "b"], "unique": True},
            {"name": "ix_email", "column_names": ["email"], "unique": True},
            {"name": "ix_plain", "column_names": ["c"], "unique": False},
        ],
    )
    keys = build_unique_keys(inspector, "t", {"email", "a", "b", "c"}, DIALECT)
    assert _names(keys) == [["email"], ["a", "b"]]


def test_build_unique_keys_skips_partial_and_functional_indexes():
    inspector = _inspector(
        indexes=[
            {"name": "ix_partial", "column_names": ["a"], "unique": True, "dialect_options": {"postgresql_where": "x"}},
            {"name": "ix_expr", "column_names": [None], "unique": True},
            {"name": "ix_unknown", "column_names": ["missing"], "unique": True},
        ]
    )
    assert build_unique_keys(inspector, "t", {"a"}, DIALECT) == ()


def test_build_unique_keys_tolerates_dialect_without_unique_constraints():
    inspector = _inspector(indexes=[{"name": "ix", "column_names": ["a"], "unique": True}])
    inspector.get_unique_constraints.side_effect = NotImplementedError
    assert _names(build_unique_keys(inspector, "t", {"a"}, DIALECT)) == [["a"]]


def test_convert_unique_keys_ignores_non_unique_and_unknown_columns():
    columns = (
        ColumnMetadata(
            column_name=Identifier.from_raw("a", DIALECT),
            ordinal_position=1,
            raw_data_type="INT",
            data_type="INT",
            nullable=False,
        ),
    )
    indexes = [
        {"index_name": "u", "columns": ["a"], "is_unique": True},
        {"index_name": "dup", "columns": ["a"], "is_unique": True},
        {"index_name": "n", "columns": ["a"], "is_unique": False},
        {"index_name": "f", "columns": ["None"], "is_unique": True},
    ]
    assert _names(_convert_unique_keys(indexes, columns, DIALECT)) == [["a"]]


def _table(unique_keys, primary=("id",)):
    def ident(name):
        return Identifier.from_raw(name, DIALECT)

    return TableMetadata(
        schema_name=ident("public"),
        table_name=ident("t"),
        columns=tuple(
            ColumnMetadata(
                column_name=ident(n),
                ordinal_position=i,
                raw_data_type="INT",
                data_type="INT",
                nullable=False,
                primary_key=n in primary,
            )
            for i, n in enumerate(("id", "a", "b"), start=1)
        ),
        primary_key={"constrained_columns": tuple(ident(n) for n in primary)} if primary else None,
        unique_keys=tuple(tuple(ident(n) for n in key) for key in unique_keys),
    )


@pytest.mark.parametrize(
    ("unique_keys", "columns", "expected"),
    [
        ((), {"id"}, True),
        ((), {"a"}, False),
        ((("a",),), {"a", "b"}, True),
        ((("a", "b"),), {"a"}, False),
    ],
)
def test_covers_unique_key(unique_keys, columns, expected):
    assert _table(unique_keys).covers_unique_key(columns) is expected


def test_unique_key_must_reference_known_columns():
    with pytest.raises(ValueError, match="Unique key references an unknown local column"):
        _table((("missing",),))
