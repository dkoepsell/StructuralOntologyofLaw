#!/usr/bin/env python3
"""
daily_scotus.py — SOoL SCOTUS Daily Update
==========================================
SEAL Lab, Texas A&M University

Incremental daily runner for SCOTUS cases:
  1. Collect new cases from CourtListener (current SCOTUS term)
  2. Sync outcomes via fetch_outcomes.py
  3. Annotate unannotated cases (includes Pass 4 dissent analysis)
  4. Run backtest report and export JSON
  5. Upload scotus_backtest_results.json to Turbify FTP

Cron (run at 6am daily, after civil/criminal/case-of-day):
    0 6 * * * /bin/bash -c 'source ~/.sool_env && cd ~/CaseLaw && \
      source venv/bin/activate && python3 daily_scotus.py' \
      >> ~/CaseLaw/logs/scotus_daily_$(date +%%Y%%m%%d).log 2>&1

Environment variables (same ~/.sool_env as other pipelines):
    SOOL_CL_KEY          CourtListener API token
    SOOL_ANTHROPIC_KEY   Anthropic API key
    TURBIFY_FTP_USER     FTP username
    TURBIFY_FTP_PASS     FTP password
    TURBIFY_FTP_HOST     FTP hostname
"""

import argparse
import datetime
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

CASELAW_DIR  = Path(__file__).parent
SCOTUS_DB    = CASELAW_DIR / 'scotus_backtest.db'
EXPORT_JSON  = CASELAW_DIR / 'scotus_backtest_results.json'
LOG_DIR      = CASELAW_DIR / 'logs'
VENV_PYTHON  = CASELAW_DIR / 'venv/bin/python3'

# Annotate at most this many cases per daily run (controls API cost)
DAILY_ANNOTATE_LIMIT = 15

# Collect at most this many new cases per term per daily run
DAILY_COLLECT_LIMIT  = 30

# ── LOGGING ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger('daily_scotus')


def get_python():
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


# ── HELPERS ───────────────────────────────────────────────────────────────────

def current_scotus_term() -> int:
    """Return the current SCOTUS term year. Term opens first Monday of October."""
    today = datetime.date.today()
    return today.year if today.month >= 10 else today.year - 1


def init_state(conn):
    """Ensure the state tracking table exists with exactly one row."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scotus_daily_state (
            id             INTEGER PRIMARY KEY CHECK (id = 1),
            last_collected TEXT,
            last_annotated TEXT,
            last_uploaded  TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO scotus_daily_state (id) VALUES (1)")
    conn.commit()


def get_state(conn) -> dict:
    row = conn.execute("SELECT * FROM scotus_daily_state WHERE id=1").fetchone()
    return dict(row) if row else {}


def set_state(conn, **kwargs):
    sets = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(f"UPDATE scotus_daily_state SET {sets} WHERE id=1",
                 list(kwargs.values()))
    conn.commit()


def count_pending_annotation(conn) -> int:
    return conn.execute("""
        SELECT COUNT(*) FROM scotus_cases c
        LEFT JOIN scotus_annotations a ON a.case_id = c.id
        WHERE LENGTH(c.transcript_text) > 500
        AND a.id IS NULL
    """).fetchone()[0]


def count_with_dissent(conn) -> int:
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM scotus_annotations WHERE dissent_cd IS NOT NULL"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        return 0


# ── STEP 1: COLLECT ───────────────────────────────────────────────────────────

def run_collection(cl_key: str, dry_run: bool = False) -> int:
    """
    Collect new SCOTUS cases for the current (and prior) term.
    Returns the number of cases collected today.
    """
    if dry_run:
        log.info("[DRY RUN] Would collect current SCOTUS term cases")
        return 0

    term = current_scotus_term()
    # Also scan the previous term — late decisions sometimes appear months after argument
    terms = [str(term - 1), str(term)]

    log.info(f"── Step 1: Collect SCOTUS cases (terms {', '.join(terms)}) ──")
    cmd = [
        get_python(), str(CASELAW_DIR / 'collect_scotus.py'),
        '--terms', *terms,
        '--db',    str(SCOTUS_DB),
        '--limit', str(DAILY_COLLECT_LIMIT),
    ]
    if cl_key:
        cmd += ['--cl-key', cl_key]

    result = subprocess.run(cmd, capture_output=False, timeout=3600)
    if result.returncode != 0:
        log.warning(f"Collection exited with code {result.returncode}")

    try:
        conn  = sqlite3.connect(str(SCOTUS_DB))
        today = datetime.date.today().isoformat()
        n = conn.execute(
            "SELECT COUNT(*) FROM scotus_cases WHERE collected_at >= ?", (today,)
        ).fetchone()[0]
        conn.close()
        log.info(f"Collection complete — {n} new cases today")
        return n
    except Exception as e:
        log.warning(f"Could not count new cases: {e}")
        return 0


# ── STEP 2: SYNC OUTCOMES ─────────────────────────────────────────────────────

def run_outcome_sync(dry_run: bool = False):
    """Sync known outcomes from Oyez for cases missing a decision."""
    if dry_run:
        log.info("[DRY RUN] Would sync outcomes via fetch_outcomes.py")
        return

    outcomes_script = CASELAW_DIR / 'fetch_outcomes.py'
    if not outcomes_script.exists():
        log.info("fetch_outcomes.py not found — skipping outcome sync")
        return

    log.info("── Step 2: Sync outcomes (fetch_outcomes.py --sync) ──")
    result = subprocess.run(
        [get_python(), str(outcomes_script), '--db', str(SCOTUS_DB), '--sync'],
        capture_output=False, timeout=600
    )
    if result.returncode != 0:
        log.warning(f"Outcome sync exited with code {result.returncode}")


# ── STEP 3: ANNOTATE ──────────────────────────────────────────────────────────

def run_annotation(anthropic_key: str, dry_run: bool = False) -> int:
    """
    Annotate unannotated SCOTUS cases (including Pass 4 dissent analysis
    for cases that have dissent_text). Returns number annotated today.
    """
    if dry_run:
        log.info("[DRY RUN] Would annotate pending SCOTUS cases")
        return 0

    conn = sqlite3.connect(str(SCOTUS_DB))
    conn.row_factory = sqlite3.Row
    pending = count_pending_annotation(conn)
    conn.close()

    if pending <= 0:
        log.info("── Step 3: No cases pending annotation ──")
        return 0

    log.info(f"── Step 3: Annotate {min(pending, DAILY_ANNOTATE_LIMIT)} of {pending} pending cases ──")
    cmd = [
        get_python(), str(CASELAW_DIR / 'annotate_scotus.py'),
        '--db',      str(SCOTUS_DB),
        '--api-key', anthropic_key,
        '--limit',   str(DAILY_ANNOTATE_LIMIT),
    ]
    result = subprocess.run(cmd, capture_output=False, timeout=7200)
    if result.returncode != 0:
        log.warning(f"Annotation exited with code {result.returncode}")

    try:
        conn  = sqlite3.connect(str(SCOTUS_DB))
        today = datetime.date.today().isoformat()
        n = conn.execute(
            "SELECT COUNT(*) FROM scotus_annotations WHERE annotated_at >= ?", (today,)
        ).fetchone()[0]
        conn.close()
        log.info(f"Annotation complete — {n} new annotations today")
        return n
    except Exception as e:
        log.warning(f"Could not count annotations: {e}")
        return 0


# ── STEP 4: BACKTEST + EXPORT ─────────────────────────────────────────────────

def run_backtest(dry_run: bool = False) -> bool:
    """Run backtest report and export JSON. Returns True on success."""
    if dry_run:
        log.info("[DRY RUN] Would run backtest and export JSON")
        return False

    log.info("── Step 4: Run backtest and export JSON ──")
    result = subprocess.run(
        [
            get_python(), str(CASELAW_DIR / 'backtest_scotus.py'),
            '--db',     str(SCOTUS_DB),
            '--export',
            '--out',    str(EXPORT_JSON),
        ],
        capture_output=False, timeout=300
    )
    if result.returncode == 0:
        size_kb = EXPORT_JSON.stat().st_size // 1024 if EXPORT_JSON.exists() else 0
        log.info(f"Exported {EXPORT_JSON.name} ({size_kb} KB)")
        return True
    else:
        log.error("Backtest/export failed")
        return False


# ── STEP 5: UPLOAD ────────────────────────────────────────────────────────────

def run_upload(dry_run: bool = False) -> bool:
    """Upload JSON to Turbify FTP. Returns True on success."""
    if dry_run:
        log.info("[DRY RUN] Would upload to Turbify FTP")
        return False

    user = os.environ.get('TURBIFY_FTP_USER', '')
    pw   = os.environ.get('TURBIFY_FTP_PASS', '')
    host = os.environ.get('TURBIFY_FTP_HOST', '')

    if not all([user, pw, host]):
        log.warning("Turbify FTP credentials not set — skipping upload")
        return False

    if not EXPORT_JSON.exists():
        log.warning("Export JSON not found — skipping upload")
        return False

    log.info("── Step 5: Upload to Turbify ──")
    result = subprocess.run(
        ['curl', '--retry', '3', '--silent', '--show-error',
         '--user', f'{user}:{pw}',
         '-T', str(EXPORT_JSON),
         f'ftp://{host}/scotus_backtest_results.json'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        log.info(f"Uploaded to ftp://{host}/scotus_backtest_results.json")
        return True
    else:
        log.error(f"FTP upload failed: {result.stderr[:200]}")
        return False


# ── STATUS ────────────────────────────────────────────────────────────────────

def print_status():
    try:
        conn = sqlite3.connect(str(SCOTUS_DB))
        conn.row_factory = sqlite3.Row
        init_state(conn)

        total_c = conn.execute("SELECT COUNT(*) FROM scotus_cases").fetchone()[0]
        total_a = conn.execute("SELECT COUNT(*) FROM scotus_annotations").fetchone()[0]
        with_d  = count_with_dissent(conn)
        pending = count_pending_annotation(conn)

        wc = conn.execute(
            "SELECT COUNT(*) FROM scotus_annotations WHERE prediction_correct=1"
        ).fetchone()[0]
        ww = conn.execute(
            "SELECT COUNT(*) FROM scotus_annotations WHERE prediction_correct=0"
        ).fetchone()[0]

        state = get_state(conn)
        conn.close()

        print(f"\nSCOTUS Daily Status — {datetime.date.today()}")
        print("=" * 50)
        print(f"  Collected:       {total_c:,}")
        print(f"  Annotated:       {total_a:,}")
        print(f"  With dissent:    {with_d:,}")
        print(f"  Pending annot.:  {pending:,}")
        if wc + ww > 0:
            print(f"  Accuracy:        {wc}/{wc+ww} ({wc/(wc+ww)*100:.1f}%)")
        print(f"  Last collected:  {state.get('last_collected','never')}")
        print(f"  Last annotated:  {state.get('last_annotated','never')}")
        print(f"  Last uploaded:   {state.get('last_uploaded','never')}")
        if EXPORT_JSON.exists():
            mtime = datetime.datetime.fromtimestamp(EXPORT_JSON.stat().st_mtime)
            print(f"  JSON last:       {mtime.strftime('%Y-%m-%d %H:%M')}")
    except Exception as e:
        print(f"Status error: {e}")


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SOoL SCOTUS Daily Update"
    )
    parser.add_argument('--cl-key',        default=os.environ.get('SOOL_CL_KEY', ''))
    parser.add_argument('--anthropic-key', default=os.environ.get('SOOL_ANTHROPIC_KEY', ''))
    parser.add_argument('--dry-run',       action='store_true')
    parser.add_argument('--collect-only',  action='store_true')
    parser.add_argument('--annotate-only', action='store_true')
    parser.add_argument('--no-upload',     action='store_true')
    parser.add_argument('--status',        action='store_true')
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    LOG_DIR.mkdir(exist_ok=True)

    # Open DB and ensure state table exists
    conn = sqlite3.connect(str(SCOTUS_DB))
    conn.row_factory = sqlite3.Row
    init_state(conn)
    conn.close()

    run_date   = datetime.date.today().isoformat()
    new_found  = 0
    annotated  = 0
    exported   = False
    uploaded   = False

    log.info("=" * 60)
    log.info("SOoL SCOTUS Daily Update")
    log.info(f"Date: {run_date}  |  Term: {current_scotus_term()}")
    log.info("=" * 60)

    # ── Collect ───────────────────────────────────────────────────────────────
    if not args.annotate_only:
        if not args.cl_key:
            log.error("SOOL_CL_KEY not set — cannot collect")
        else:
            new_found = run_collection(args.cl_key, args.dry_run)
            if not args.dry_run:
                conn = sqlite3.connect(str(SCOTUS_DB))
                conn.row_factory = sqlite3.Row
                set_state(conn, last_collected=datetime.datetime.now().isoformat())
                conn.close()

    # ── Sync outcomes ─────────────────────────────────────────────────────────
    if not args.collect_only and not args.annotate_only:
        run_outcome_sync(args.dry_run)

    # ── Annotate ──────────────────────────────────────────────────────────────
    if not args.collect_only:
        if not args.anthropic_key:
            log.error("SOOL_ANTHROPIC_KEY not set — cannot annotate")
        else:
            annotated = run_annotation(args.anthropic_key, args.dry_run)
            if not args.dry_run and annotated:
                conn = sqlite3.connect(str(SCOTUS_DB))
                conn.row_factory = sqlite3.Row
                set_state(conn, last_annotated=datetime.datetime.now().isoformat())
                conn.close()

    # ── Backtest + export ─────────────────────────────────────────────────────
    if not args.collect_only and not args.annotate_only:
        exported = run_backtest(args.dry_run)

    # ── Upload ────────────────────────────────────────────────────────────────
    if exported and not args.no_upload and not args.collect_only and not args.annotate_only:
        uploaded = run_upload(args.dry_run)
        if uploaded and not args.dry_run:
            conn = sqlite3.connect(str(SCOTUS_DB))
            conn.row_factory = sqlite3.Row
            set_state(conn, last_uploaded=datetime.datetime.now().isoformat())
            conn.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    conn = sqlite3.connect(str(SCOTUS_DB))
    conn.row_factory = sqlite3.Row
    with_d = count_with_dissent(conn)
    conn.close()

    log.info("=" * 60)
    log.info(f"SCOTUS daily update complete — {run_date}")
    log.info(f"  New cases collected:  {new_found}")
    log.info(f"  New cases annotated:  {annotated}")
    log.info(f"  Cases with dissent:   {with_d} total in DB")
    log.info(f"  JSON exported:        {exported}")
    log.info(f"  Uploaded to Turbify:  {uploaded}")
    log.info("=" * 60)


if __name__ == '__main__':
    main()
