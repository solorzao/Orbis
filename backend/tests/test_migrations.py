"""Static checks that keep migrations cheap to run against the live database."""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"

# A quoted literal, a number or a boolean.
CONSTANT = r"(?:'[^']*'|-?\d+(?:\.\d+)?|true|false)"


def _sql_without_comments(name: str) -> str:
    sql = (MIGRATIONS / name).read_text(encoding="utf-8")
    return re.sub(r"--[^\n]*", "", sql)


def test_gkg_fields_migration_fails_fast_on_locks():
    sql = _sql_without_comments("009_gkg_fields.sql")
    lock = re.search(r"SET lock_timeout = '\d+s';", sql)
    assert lock is not None
    assert lock.start() < sql.index("ALTER TABLE")


def test_gkg_fields_migration_adds_columns_without_a_table_rewrite():
    """A constant default keeps ADD COLUMN catalog-only; a volatile one rewrites the table."""
    sql = _sql_without_comments("009_gkg_fields.sql")
    columns = re.findall(
        r"ADD COLUMN (?:IF NOT EXISTS )?(\w+)\s+(.*?)\s*(?=,\s*ADD COLUMN|;)", sql, re.DOTALL
    )
    assert [name for name, _ in columns] == ["themes", "persons", "orgs", "names", "counts"]
    for name, definition in columns:
        pattern = rf"[\w\[\]]+\s+NOT NULL\s+DEFAULT\s+{CONSTANT}"
        assert re.fullmatch(pattern, definition, re.IGNORECASE), f"{name}: {definition}"
