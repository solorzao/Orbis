"""Static checks that keep migrations cheap to run against the live database."""

import re
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"

# A quoted literal, a number or a boolean.
CONSTANT = r"(?:'[^']*'|-?\d+(?:\.\d+)?|true|false)"

# Migrations that add columns to the live articles table, and the columns each adds.
COLUMN_MIGRATIONS = {
    "009_gkg_fields.sql": ["themes", "persons", "orgs", "names", "counts"],
    "011_mentioned_countries.sql": ["mentioned_countries"],
    "012_story_key.sql": ["story_key"],
}


def _sql_without_comments(name: str) -> str:
    sql = (MIGRATIONS / name).read_text(encoding="utf-8")
    return re.sub(r"--[^\n]*", "", sql)


@pytest.mark.parametrize("name", COLUMN_MIGRATIONS)
def test_column_migration_fails_fast_on_locks(name):
    sql = _sql_without_comments(name)
    lock = re.search(r"SET lock_timeout = '\d+s';", sql)
    assert lock is not None
    assert lock.start() < sql.index("ALTER TABLE")


@pytest.mark.parametrize(
    ("name", "expected"), COLUMN_MIGRATIONS.items(), ids=list(COLUMN_MIGRATIONS)
)
def test_column_migration_adds_columns_without_a_table_rewrite(name, expected):
    """A nullable column or a constant default keeps ADD COLUMN catalog-only; a volatile
    default rewrites the table."""
    sql = _sql_without_comments(name)
    columns = re.findall(
        r"ADD COLUMN (?:IF NOT EXISTS )?(\w+)\s+(.*?)\s*(?=,\s*ADD COLUMN|;)", sql, re.DOTALL
    )
    assert [column for column, _ in columns] == expected
    for column, definition in columns:
        pattern = rf"[\w\[\]]+(?:\s+NOT NULL\s+DEFAULT\s+{CONSTANT})?"
        assert re.fullmatch(pattern, definition, re.IGNORECASE), f"{column}: {definition}"


# Migrations that only create new tables: they must fail fast on locks and
# leave the live articles table alone (it is rewritten on every embedding).
TABLE_MIGRATIONS = ["013_threads.sql"]


@pytest.mark.parametrize("name", TABLE_MIGRATIONS)
def test_table_migration_fails_fast_on_locks_and_leaves_articles_alone(name):
    sql = _sql_without_comments(name)
    lock = re.search(r"SET lock_timeout = '\d+s';", sql)
    assert lock is not None
    assert lock.start() < sql.index("CREATE")
    assert not re.search(r"ALTER\s+TABLE\s+(IF\s+EXISTS\s+)?articles\b", sql, re.IGNORECASE)
    assert not re.search(r"CREATE\s+INDEX[^;]*\bON\s+articles\b", sql, re.IGNORECASE)
    # A foreign key to articles would lock it while the migration runs and fire
    # a trigger for every article the purge deletes.
    assert not re.search(r"REFERENCES\s+articles\b", sql, re.IGNORECASE)
