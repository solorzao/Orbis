"""A production-like knowledge graph and thread members for search's database tests.

Names are real given names and surnames combined (tests/realistic_names.py),
so they share word-start trigrams as GDELT's names do. kg_nodes rows are
written in ingestion's order: each cycle writes its articles' ARTICLE nodes
with the people and organisations first seen in it, so names sit thinly
among the headlines on the heap, as on production. Members name public
figures by weight and the other names at random.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone

from tests.realistic_names import (
    CITIES,
    CITY_ORG_SUFFIXES,
    GIVEN_NAMES,
    HEADLINE_WORDS,
    ORG_SUFFIXES,
    ORGANISATIONS,
    PUBLIC_FIGURES,
    SURNAMES,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def entity_names(people: int, seed: int = 7) -> list[tuple[str, str]]:
    """(type, name) for the public figures and organisations, then *people* combined
    names and the generated organisations, in a seeded order."""
    rng = random.Random(seed)
    combos = sorted({f"{g} {s}" for g in GIVEN_NAMES for s in SURNAMES})
    rng.shuffle(combos)
    named = {name for name, _ in PUBLIC_FIGURES}
    persons = [name for name in combos if name not in named][:people]
    orgs = sorted(
        {f"{s} {suffix}" for s in SURNAMES for suffix in ORG_SUFFIXES}
        | {f"{c} {suffix}" for c in CITIES for suffix in CITY_ORG_SUFFIXES}
    )
    rng.shuffle(orgs)
    rows = [("PERSON", n) for n, _ in PUBLIC_FIGURES] + [("ORG", n) for n, _ in ORGANISATIONS]
    known = set(rows)
    generated = [("PERSON", n) for n in persons] + [("ORG", n) for n in orgs]
    generated = [row for row in generated if row not in known]  # e.g. Wagner Group
    rng.shuffle(generated)
    return rows + generated


def _headline(rng: random.Random, i: int) -> str:
    words = rng.sample(HEADLINE_WORDS, rng.randint(6, 10))
    words.insert(rng.randrange(len(words)), rng.choice(SURNAMES))
    return " ".join(words).capitalize() + f" {i}"


async def build(
    conn,
    *,
    articles: int = 150_000,
    people: int = 50_000,
    members: int = 100_000,
    cycles: int = 150,
    seed: int = 7,
) -> list[tuple[str, str]]:
    """Write the graph and members on *conn* (inside the caller's transaction) and
    return the (type, name) of every person and organisation written."""
    rng = random.Random(seed)
    names = entity_names(people, seed)
    per_cycle = articles // cycles
    name_iter = iter(names)
    records = []
    for cycle in range(cycles):
        published = NOW - timedelta(hours=(cycles - cycle) * 7 * 24 / cycles)
        new_names = len(names) * (cycle + 1) // cycles - len(names) * cycle // cycles
        # Each article's node, then the names it is the first to mention.
        slots = sorted(rng.sample(range(per_cycle), min(new_names, per_cycle)))
        extra = max(0, new_names - per_cycle)
        for a in range(per_cycle):
            i = cycle * per_cycle + a
            title = _headline(rng, i)
            meta = {
                "url": f"https://news{i % 900}.example/{i}/{title[:30].replace(' ', '-')}",
                "lat": round(rng.uniform(-60, 70), 4),
                "lng": round(rng.uniform(-170, 170), 4),
                "published_at": str(published),
            }
            records.append((uuid.uuid4(), "ARTICLE", title, json.dumps(meta)))
            while slots and slots[0] == a:
                slots.pop(0)
                type_, name = next(name_iter)
                records.append((uuid.uuid4(), type_, name, "{}"))
        for _ in range(extra):
            type_, name = next(name_iter)
            records.append((uuid.uuid4(), type_, name, "{}"))
    await conn.copy_records_to_table(
        "kg_nodes", records=records, columns=["id", "type", "name", "metadata"]
    )

    # Members: a week of assigned articles. Public figures and named
    # organisations by weight, the generated names at random.
    weighted = [n for n, w in PUBLIC_FIGURES + ORGANISATIONS for _ in range(w)]
    generic = [n for _, n in names[len(PUBLIC_FIGURES) + len(ORGANISATIONS) :]]
    thread = await conn.fetchval(
        "INSERT INTO threads (centroid_sum, first_seen, last_seen)"
        " VALUES (array_fill(0.01, ARRAY[512])::vector, $1, $1) RETURNING id",
        NOW,
    )
    rows = []
    for m in range(members):
        named = {rng.choice(weighted) for _ in range(rng.choice((0, 1, 1, 2, 2, 3)))}
        others = {rng.choice(generic) for _ in range(rng.randint(2, 6))}
        rows.append(
            (
                uuid.uuid4(),
                thread,
                m // 2,  # pairs of copies
                f"outlet{m % 900}.example",
                NOW - timedelta(minutes=(members - m) * 7 * 24 * 60 / members),
                rng.uniform(-60, 70),
                rng.uniform(-170, 170),
                sorted(named | others)[:16],
                0.9,
            )
        )
    await conn.copy_records_to_table(
        "thread_members",
        records=rows,
        columns=[
            "article_id", "thread_id", "story_key", "source_name", "published_at",
            "latitude", "longitude", "entities", "similarity",
        ],
    )  # fmt: skip

    # As (auto)vacuum leaves production's: GIN pending lists merged, statistics fresh.
    gins = await conn.fetch(
        "SELECT indexrelid::regclass::text AS name FROM pg_index i"
        " JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_am am ON am.oid = c.relam"
        " WHERE am.amname = 'gin'"
        " AND i.indrelid IN ('kg_nodes'::regclass, 'thread_members'::regclass)"
    )
    for gin in gins:
        await conn.execute("SELECT gin_clean_pending_list($1::regclass)", gin["name"])
    await conn.execute("ANALYZE kg_nodes")
    await conn.execute("ANALYZE thread_members")
    return [(t, n) for t, n in names]
