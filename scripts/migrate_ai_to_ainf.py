#!/usr/bin/env python3
"""
migrate_ai_to_ainf.py — amendment A2. Rename the contradiction code AI to AINF.

Reversible. Every value changed is recorded in a migration log table inside the
same database, so --rollback restores the exact prior strings rather than
guessing an inverse.

Why the rename, from typology/AMENDMENTS.md A2: David's research programme is AI
governance, so the token AI inside a SOoL artifact is permanently ambiguous in
this corpus specifically. Adjudicating between Authority Inflation and Authority
Incompleteness buys nothing when a third sense is unavoidable. AI becomes a
reserved code under R2: never reused, never re-minted.

What is migrated (code tokens only, inside JSON arrays):

    sool_annotations.db          annotations                   active_contradictions
                                                               structural_signature
                                 annotations_unmasked          both
                                 annotations_quarantine_d9_11  both
    sool_criminal_annotations.db criminal_annotations          active_contradictions
    scotus_backtest.db           scotus_annotations            active_contradictions

What is deliberately NOT migrated:

  * annotations.raw_response, and any other raw model output. That is the
    verbatim artifact the annotation was derived from. Rewriting it would
    falsify the record of what the model actually said. 255 rows contain the
    token and all are left alone.
  * free prose (review notes, comments), where "AI" may mean artificial
    intelligence. The census counted 80 such uses in this repo.

The alias map in vocab/registry.json keeps AI resolvable for published figures,
notably the administrative-law result that cites it, so the rename does not make
the prior record unreadable.

Usage:
    python3 migrate_ai_to_ainf.py --dry-run
    python3 migrate_ai_to_ainf.py --apply
    python3 migrate_ai_to_ainf.py --verify
    python3 migrate_ai_to_ainf.py --rollback
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKUPS = ROOT / "backups"

OLD, NEW = "AI", "AINF"
LOG_TABLE = "migration_log_ai_to_ainf"

TARGETS = {
    "sool_annotations.db": [
        ("annotations", ["active_contradictions", "structural_signature"]),
        ("annotations_unmasked", ["active_contradictions", "structural_signature"]),
        ("annotations_quarantine_d9_11",
         ["active_contradictions", "structural_signature"]),
    ],
    "sool_criminal_annotations.db": [
        ("criminal_annotations", ["active_contradictions"]),
    ],
    "scotus_backtest.db": [
        ("scotus_annotations", ["active_contradictions"]),
    ],
}

# A bare code token. Also matches the code after a node prefix, as in
# "Node1_2:AI", without touching words that merely contain the letters.
TOKEN = re.compile(rf"(?<![A-Za-z0-9_]){OLD}(?![A-Za-z0-9_])")


def convert(value: str) -> str | None:
    """Return the migrated string, or None if nothing changes.

    Values are JSON arrays. Parse and rewrite element-wise where possible, so a
    malformed string is never silently mangled by a blind regex.
    """
    if not value or not TOKEN.search(value):
        return None
    try:
        data = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        # Not JSON. Fall back to token substitution, which is still safe
        # because TOKEN only matches a standalone code.
        out = TOKEN.sub(NEW, value)
        return out if out != value else None

    def walk(x):
        if isinstance(x, str):
            return TOKEN.sub(NEW, x)
        if isinstance(x, list):
            return [walk(i) for i in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x

    new = walk(data)
    if new == data:
        return None
    # separators match the stored style: ["AI", "NI"]
    return json.dumps(new)


def ensure_log(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            applied_at TEXT NOT NULL,
            tbl        TEXT NOT NULL,
            col        TEXT NOT NULL,
            rowid_ref  INTEGER NOT NULL,
            old_value  TEXT NOT NULL,
            new_value  TEXT NOT NULL
        )""")


def tables_of(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def columns_of(conn: sqlite3.Connection, tab: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tab})")}


def plan(db: Path) -> list[tuple[str, str, int, str, str]]:
    out = []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tabs = tables_of(conn)
    for tab, cols in TARGETS[db.name]:
        if tab not in tabs:
            continue
        have = columns_of(conn, tab)
        for col in cols:
            if col not in have:
                continue
            for rid, val in conn.execute(
                    f"SELECT rowid,{col} FROM {tab} WHERE {col} IS NOT NULL"):
                new = convert(str(val))
                if new is not None:
                    out.append((tab, col, rid, str(val), new))
    conn.close()
    return out


def do_apply(db: Path, changes, note: str) -> int:
    conn = sqlite3.connect(db)
    try:
        ensure_log(conn)
        conn.execute("BEGIN")
        now = datetime.now().isoformat(timespec="seconds")
        for tab, col, rid, old, new in changes:
            conn.execute(f"UPDATE {tab} SET {col}=? WHERE rowid=?", (new, rid))
            conn.execute(
                f"INSERT INTO {LOG_TABLE}(applied_at,tbl,col,rowid_ref,"
                f"old_value,new_value) VALUES (?,?,?,?,?,?)",
                (now, tab, col, rid, old, new))
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        conn.close()
        raise RuntimeError(f"{db.name}: {e}") from e
    conn.close()
    return len(changes)


def do_rollback(db: Path) -> int:
    conn = sqlite3.connect(db)
    if LOG_TABLE not in tables_of(conn):
        conn.close()
        return 0
    rows = conn.execute(
        f"SELECT id,tbl,col,rowid_ref,old_value FROM {LOG_TABLE} "
        f"ORDER BY id DESC").fetchall()
    try:
        conn.execute("BEGIN")
        for _id, tab, col, rid, old in rows:
            conn.execute(f"UPDATE {tab} SET {col}=? WHERE rowid=?", (old, rid))
        conn.execute(f"DELETE FROM {LOG_TABLE}")
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK"); conn.close()
        raise RuntimeError(f"{db.name}: {e}") from e
    conn.close()
    return len(rows)


def verify(db: Path) -> tuple[int, int]:
    """Return (remaining AI tokens, AINF tokens) across the target columns."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tabs = tables_of(conn)
    old_n = new_n = 0
    newtok = re.compile(rf"(?<![A-Za-z0-9_]){NEW}(?![A-Za-z0-9_])")
    for tab, cols in TARGETS[db.name]:
        if tab not in tabs:
            continue
        have = columns_of(conn, tab)
        for col in cols:
            if col not in have:
                continue
            for (val,) in conn.execute(
                    f"SELECT {col} FROM {tab} WHERE {col} IS NOT NULL"):
                s = str(val)
                if TOKEN.search(s):
                    old_n += 1
                if newtok.search(s):
                    new_n += 1
    conn.close()
    return old_n, new_n


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    dbs = [ROOT / n for n in TARGETS if (ROOT / n).exists()]
    if not dbs:
        print("*** no target databases found", file=sys.stderr)
        return 1

    if args.verify:
        bad = 0
        for db in dbs:
            o, n = verify(db)
            flag = "OK" if o == 0 else "** AI REMAINS"
            print(f"  {db.name:<32} AI={o:<5} AINF={n:<5} {flag}")
            bad += o
        return 1 if bad else 0

    if args.rollback:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        d = BACKUPS / f"pre_ainf_rollback_{ts}"
        d.mkdir(parents=True, exist_ok=True)
        total = 0
        for db in dbs:
            shutil.copy2(db, d / db.name)
            n = do_rollback(db)
            print(f"  {db.name:<32} reverted {n}")
            total += n
        print(f"\nreverted {total} value(s). Backup: {d}")
        return 0

    plans = {db: plan(db) for db in dbs}
    total = sum(len(v) for v in plans.values())
    print(f"A2 migration: {OLD} -> {NEW}\n")
    for db, ch in plans.items():
        by: dict[tuple[str, str], int] = {}
        for tab, col, *_ in ch:
            by[(tab, col)] = by.get((tab, col), 0) + 1
        print(f"  {db.name}")
        if not ch:
            print("      (nothing to change)")
        for (tab, col), n in sorted(by.items()):
            print(f"      {tab}.{col:<26} {n}")
    print(f"\n  total values to change: {total}")

    if plans and total:
        db0, ch0 = next((d, c) for d, c in plans.items() if c)
        print(f"\n  example ({db0.name} {ch0[0][0]}.{ch0[0][1]} rowid {ch0[0][2]}):")
        print(f"      before: {ch0[0][3][:90]}")
        print(f"      after : {ch0[0][4][:90]}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = BACKUPS / f"pre_ainf_migration_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    for db in dbs:
        shutil.copy2(db, d / db.name)
    print(f"\nbackup: {d}")

    done = 0
    for db in dbs:
        if plans[db]:
            done += do_apply(db, plans[db], "A2")
            print(f"  {db.name}: {len(plans[db])} value(s) migrated")
    print(f"\nmigrated {done} value(s). Rollback with --rollback.")

    print("\nverify:")
    for db in dbs:
        o, n = verify(db)
        print(f"  {db.name:<32} AI={o:<5} AINF={n:<5} {'OK' if o==0 else '** FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
