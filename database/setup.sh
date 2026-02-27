#!/usr/bin/env bash
# ============================================================
# Orbis Database Setup
# ============================================================
# This script applies all SQL migration files against a Supabase
# Postgres instance.  You can also run each file manually in the
# Supabase SQL Editor (Dashboard > SQL Editor > New query).
#
# Prerequisites:
#   - psql CLI installed  (brew install libpq / apt install postgresql-client)
#   - Extensions enabled in Supabase Dashboard:
#       * PostGIS          (Database > Extensions)
#       * pgvector         (Database > Extensions)
#       * uuid-ossp        (enabled by default)
#
# Usage:
#   export DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres"
#   bash database/setup.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="${SCRIPT_DIR}/migrations"
SEED_FILE="${SCRIPT_DIR}/seed.sql"

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "=============================================="
    echo "  Orbis Database Migration Instructions"
    echo "=============================================="
    echo ""
    echo "Option A: Run this script with DATABASE_URL set"
    echo ""
    echo "  export DATABASE_URL=\"postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres\""
    echo "  bash database/setup.sh"
    echo ""
    echo "Option B: Paste each file into the Supabase SQL Editor"
    echo ""
    echo "  1. Go to https://supabase.com/dashboard > your project > SQL Editor"
    echo "  2. Run each migration file in order:"
    echo ""
    for f in "${MIGRATIONS_DIR}"/*.sql; do
        echo "     - $(basename "$f")"
    done
    echo ""
    echo "  3. Then run the seed file:"
    echo "     - seed.sql"
    echo ""
    echo "Make sure PostGIS, pgvector, and uuid-ossp extensions are"
    echo "enabled under Database > Extensions before running migrations."
    echo ""
    exit 0
fi

echo "Applying migrations to: ${DATABASE_URL%%@*}@..."
echo ""

for migration in "${MIGRATIONS_DIR}"/*.sql; do
    echo ">> Running $(basename "$migration") ..."
    psql "${DATABASE_URL}" -f "$migration"
done

echo ""
echo ">> Running seed.sql ..."
psql "${DATABASE_URL}" -f "$SEED_FILE"

echo ""
echo "All migrations and seed data applied successfully."
