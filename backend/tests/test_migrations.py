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
TABLE_MIGRATIONS = ["013_threads.sql", "015_thread_indexes.sql", "017_kg_entity_names.sql"]


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


# Migrations that build indexes on tables ingestion writes every cycle: each
# CONCURRENTLY, after dropping an INVALID leftover of a failed build, and with
# no lock_timeout (as 008 and 010, which tests/test_retrieval.py covers).
CONCURRENT_INDEX_MIGRATIONS = {"016_kg_entity_name_trgm.sql": ["idx_kg_nodes_entity_name_trgm"]}


def _sql_lines(name: str) -> list[str]:
    return [line.strip() for line in _sql_without_comments(name).splitlines() if line.strip()]


@pytest.mark.parametrize(
    ("name", "indexes"),
    CONCURRENT_INDEX_MIGRATIONS.items(),
    ids=list(CONCURRENT_INDEX_MIGRATIONS),
)
def test_concurrent_index_migration_never_blocks_ingestion(name, indexes):
    lines = _sql_lines(name)
    sql = "\n".join(lines)
    # A plain CREATE INDEX blocks writes for the whole build. CONCURRENTLY takes
    # SHARE UPDATE EXCLUSIVE only, and can't run in a transaction block.
    creates = [line for line in lines if line.startswith("CREATE")]
    assert creates
    assert all(line.startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS ") for line in creates)
    assert not re.search(r"\bBEGIN\b", sql, re.IGNORECASE)
    # A timeout mid-build would leave an INVALID index behind.
    assert "lock_timeout" not in sql
    assert not re.search(r"\barticles\b", sql, re.IGNORECASE)
    for index in indexes:
        # A rerun drops only a failed (INVALID) build, never a valid index.
        [check] = [i for i, line in enumerate(lines) if f"c.relname = '{index}'" in line]
        flag = re.fullmatch(r"\) AS (\w+) \\gset", lines[check + 1]).group(1)
        assert "AND NOT i.indisvalid" in lines[check]
        drop = lines.index(f"\\if :{flag}")
        assert lines[drop + 1 : drop + 3] == [f"DROP INDEX CONCURRENTLY {index};", "\\endif"]
        create = lines.index(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index}")
        assert check < drop < create
        assert [line for line in lines if index in line and line.startswith("DROP")] == [
            f"DROP INDEX CONCURRENTLY {index};"
        ]


# Migrations that only set a table's autovacuum parameters: SHARE UPDATE
# EXCLUSIVE (no conflict with reads or writes), no data change, no rewrite.
SETTINGS_MIGRATIONS = {"014_kg_edges_autovacuum.sql": "kg_edges"}


@pytest.mark.parametrize(
    ("name", "table"), SETTINGS_MIGRATIONS.items(), ids=list(SETTINGS_MIGRATIONS)
)
def test_settings_migration_only_sets_autovacuum_parameters(name, table):
    sql = _sql_without_comments(name)
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    assert re.fullmatch(r"SET lock_timeout = '\d+s'", statements[0])
    assert statements[1:]
    setting = r"autovacuum_\w+\s*=\s*\d+(?:\.\d+)?"
    for statement in statements[1:]:
        assert re.fullmatch(
            rf"ALTER TABLE {table} SET \(\s*{setting}(?:\s*,\s*{setting})*\s*\)", statement
        ), statement
    assert not re.search(r"\barticles\b", sql, re.IGNORECASE)
