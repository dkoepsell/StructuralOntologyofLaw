#!/usr/bin/env python3
"""
migrate_outcome_split.py — schema remediation per SOoL_remediation_spec_v1 §3.1/§3.2.

Adds, idempotently:
  * derived_outcome    — mirror of chain_outcome under an honest name. The old
                         column is retained so existing scripts keep working;
                         a trigger keeps the two in sync.
  * court_disposition  — the court's actual holding, extracted independently.
                         NULL until the independent extraction pass populates it.
  * court_prevailing_party
  * cd_upstream        — Contradiction Debt over N1-N6 only (annotate.compute_cd_upstream),
                         i.e. the component NOT downstream of the Pass-2 rule.

Backfills cd_upstream and derived_outcome from existing rows.

Usage:
    ./venv/bin/python3 migrate_outcome_split.py [--dry-run]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from annotate import CONTRADICTION_TYPES, UPSTREAM_CTS  # noqa: E402

BASE = Path(__file__).parent

TARGETS = [
    ("sool_annotations.db",          "annotations"),
    ("sool_criminal_annotations.db", "criminal_annotations"),
]

NEW_COLS = [
    ("derived_outcome",        "TEXT"),
    ("court_disposition",      "TEXT"),
    ("court_prevailing_party", "TEXT"),
    ("cd_upstream",            "REAL"),
]


def cols(conn, table):
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def upstream_cd(raw):
    """Recompute upstream CD from a stored active_contradictions value."""
    if not raw:
        return 0.0
    try:
        cts = json.loads(raw) if raw.strip().startswith("[") else \
              [c.strip() for c in raw.split(",")]
    except Exception:
        cts = [c.strip() for c in str(raw).split(",")]
    return round(sum(CONTRADICTION_TYPES[c][2]
                     for c in cts
                     if c in UPSTREAM_CTS), 4)


def migrate(db, table, dry_run):
    path = BASE / db
    if not path.exists():
        print(f"  {db}: not found, skipping")
        return
    conn = sqlite3.connect(path)
    existing = cols(conn, table)
    if not existing:
        print(f"  {db}: table {table} not found, skipping")
        conn.close()
        return

    added = []
    for name, typ in NEW_COLS:
        if name not in existing:
            added.append(name)
            if not dry_run:
                conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {typ}')
    print(f"  {db}/{table}: columns added -> {added or 'none (already present)'}")

    if dry_run:
        conn.close()
        return

    # derived_outcome mirrors chain_outcome (the honest name for a derived value)
    if "chain_outcome" in existing:
        conn.execute(f'UPDATE "{table}" SET derived_outcome = chain_outcome '
                     f'WHERE derived_outcome IS NULL')

    # backfill cd_upstream
    rows = conn.execute(
        f'SELECT id, active_contradictions FROM "{table}" WHERE cd_upstream IS NULL'
    ).fetchall()
    for rid, raw in rows:
        conn.execute(f'UPDATE "{table}" SET cd_upstream=? WHERE id=?',
                     (upstream_cd(raw), rid))
    conn.commit()

    n = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    filled = conn.execute(
        f'SELECT COUNT(*) FROM "{table}" WHERE cd_upstream IS NOT NULL').fetchone()[0]
    avg_full = conn.execute(
        f'SELECT ROUND(AVG(contradiction_debt),4) FROM "{table}"').fetchone()[0]
    avg_up = conn.execute(
        f'SELECT ROUND(AVG(cd_upstream),4) FROM "{table}"').fetchone()[0]
    print(f"     rows={n:,}  cd_upstream filled={filled:,}  "
          f"mean CD={avg_full}  mean CD_upstream={avg_up}")
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("Outcome-variable split migration (spec §3.1, §3.2)")
    print("=" * 60)
    for db, table in TARGETS:
        migrate(db, table, args.dry_run)
    print("=" * 60)
    print("court_disposition is intentionally left NULL — it must be populated "
          "by an independent extraction pass that never sees the node annotation.")


if __name__ == "__main__":
    main()
