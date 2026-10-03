#!/usr/bin/env python3
"""
daily_criminal.py — SOoL Criminal Corpus Daily Update
======================================================
SEAL Lab, Texas A&M University

Mirrors daily_update.py for the criminal corpus:
  1. Collect new criminal cases from CourtListener (top-up to target)
  2. Annotate any unannotated cases
  3. Export sool_criminal_data.json
  4. Upload to Turbify FTP

Cron (run at 4am daily, 1hr after civil update):
    0 4 * * * /bin/bash -c 'source ~/.sool_env && cd ~/CaseLaw && \
      source venv/bin/activate && python3 daily_criminal.py' \
      >> ~/CaseLaw/logs/criminal_daily_$(date +%%Y%%m%%d).log 2>&1

Environment variables (same ~/.sool_env as civil pipeline):
    SOOL_CL_KEY          CourtListener API token
    SOOL_ANTHROPIC_KEY   Anthropic API key
    TURBIFY_FTP_USER     FTP username
    TURBIFY_FTP_PASS     FTP password
    TURBIFY_FTP_HOST     FTP hostname
"""

import argparse, datetime, json, logging, os, sqlite3, subprocess, sys, time
from pathlib import Path

import requests

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

CASELAW_DIR  = Path(__file__).parent
CRIMINAL_DB  = CASELAW_DIR / 'sool_criminal.db'
ANN_DB       = CASELAW_DIR / 'sool_criminal_annotations.db'
EXPORT_JSON  = CASELAW_DIR / 'sool_criminal_data.json'
LOG_DIR      = CASELAW_DIR / 'logs'
VENV_PYTHON  = CASELAW_DIR / 'venv/bin/python3'

# Daily top-up: collect up to this many new cases per category per run
DAILY_PER_CATEGORY = 25

# Wall-clock cap for the collection subprocess. The fixed query list is largely
# saturated, so most of this time yields nothing new; exceeding it is expected
# and non-fatal. Override with SOOL_COLLECT_TIMEOUT (seconds).
COLLECT_TIMEOUT_SEC = int(os.environ.get('SOOL_COLLECT_TIMEOUT', 3600))

# ── LOGGING ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger('daily_criminal')


def get_python():
    """Use venv python if available, else sys.executable."""
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


# ── STEP 1: COLLECT ──────────────────────────────────────────────────────────

def run_collection(cl_key: str, dry_run: bool = False) -> int:
    """Top up each category by DAILY_PER_CATEGORY cases. Returns new cases found."""
    if dry_run:
        log.info("[DRY RUN] Skipping collection")
        return 0

    log.info("── Step 1: Collect new criminal cases ──")
    # Key goes through the environment, never argv: argv is visible in `ps`
    # and subprocess tracebacks echo the whole command into the daily log.
    cmd = [
        get_python(), str(CASELAW_DIR / 'collect_criminal.py'),
        '--courts', 'both',
        '--limit', str(DAILY_PER_CATEGORY),
        '--db',    str(CRIMINAL_DB),
    ]
    child_env = {**os.environ, 'SOOL_CL_KEY': cl_key}
    # The collector commits each case as it goes, so a timeout is not data loss —
    # it just truncates this run. Never let it abort the whole daily job:
    # annotation, export and upload (Steps 2-4) must still run.
    try:
        result = subprocess.run(cmd, capture_output=False,
                                timeout=COLLECT_TIMEOUT_SEC, env=child_env)
    except subprocess.TimeoutExpired:
        log.warning(
            f"Collection exceeded {COLLECT_TIMEOUT_SEC}s and was stopped; "
            f"continuing with the rest of the daily run. "
            f"(Cases collected before the cutoff are already committed.)"
        )
        return 0
    if result.returncode != 0:
        log.warning(f"Collection exited with code {result.returncode}")
        return 0

    # Count new cases since we started
    try:
        conn = sqlite3.connect(str(CRIMINAL_DB))
        today = datetime.date.today().isoformat()
        n = conn.execute(
            "SELECT COUNT(*) FROM criminal_cases WHERE collected_at >= ?",
            (today,)
        ).fetchone()[0]
        conn.close()
        log.info(f"Collection complete — {n} new cases today")
        return n
    except Exception as e:
        log.warning(f"Could not count new cases: {e}")
        return 0


# ── STEP 2: ANNOTATE ─────────────────────────────────────────────────────────

def run_annotation(anthropic_key: str, dry_run: bool = False) -> int:
    """Annotate all unannotated cases. Returns number annotated."""
    if dry_run:
        log.info("[DRY RUN] Skipping annotation")
        return 0

    log.info("── Step 2: Annotate unannotated cases ──")

    # Check how many need annotation
    try:
        crim_conn = sqlite3.connect(str(CRIMINAL_DB))
        ann_conn  = sqlite3.connect(str(ANN_DB))
        total_collected = crim_conn.execute(
            "SELECT COUNT(*) FROM criminal_cases"
        ).fetchone()[0]
        total_annotated = ann_conn.execute(
            "SELECT COUNT(DISTINCT case_id) FROM criminal_annotations"
        ).fetchone()[0]
        pending = total_collected - total_annotated
        crim_conn.close()
        ann_conn.close()
        log.info(f"Pending annotation: {pending} cases "
                 f"({total_collected} collected, {total_annotated} annotated)")
        if pending <= 0:
            log.info("Nothing to annotate")
            return 0
    except Exception as e:
        log.warning(f"Could not check pending: {e}")

    # Key via environment, not argv (see run_collection).
    cmd = [
        get_python(), str(CASELAW_DIR / 'annotate_criminal.py'),
        '--corpus-db', str(CRIMINAL_DB),
        '--ann-db',    str(ANN_DB),
    ]
    result = subprocess.run(cmd, capture_output=False, timeout=7200,
                            env={**os.environ,
                                 'ANTHROPIC_API_KEY': anthropic_key})
    if result.returncode != 0:
        log.warning(f"Annotation exited with code {result.returncode}")
        return 0

    try:
        ann_conn = sqlite3.connect(str(ANN_DB))
        today    = datetime.date.today().isoformat()
        n = ann_conn.execute(
            "SELECT COUNT(*) FROM criminal_annotations WHERE annotation_date >= ?",
            (today,)
        ).fetchone()[0]
        ann_conn.close()
        log.info(f"Annotation complete — {n} new annotations today")
        return n
    except Exception as e:
        log.warning(f"Could not count annotations: {e}")
        return 0


# ── STEP 3: EXPORT ───────────────────────────────────────────────────────────

def run_export(dry_run: bool = False) -> bool:
    """Export annotations to JSON. Returns True on success."""
    if dry_run:
        log.info("[DRY RUN] Skipping export")
        return False

    log.info("── Step 3: Export to JSON ──")
    cmd = [
        get_python(), str(CASELAW_DIR / 'export_criminal.py'),
        '--ann-db', str(ANN_DB),
        '--out',    str(EXPORT_JSON),
    ]
    result = subprocess.run(cmd, capture_output=False, timeout=120)
    if result.returncode == 0:
        size_kb = EXPORT_JSON.stat().st_size // 1024 if EXPORT_JSON.exists() else 0
        log.info(f"Exported {EXPORT_JSON.name} ({size_kb} KB)")
        return True
    else:
        log.error("Export failed")
        return False


# ── STEP 4: UPLOAD ───────────────────────────────────────────────────────────

def run_upload(dry_run: bool = False) -> bool:
    """Upload JSON to Turbify FTP. Returns True on success."""
    if dry_run:
        log.info("[DRY RUN] Skipping upload")
        return False

    user = os.environ.get('TURBIFY_FTP_USER', '')
    pw   = os.environ.get('TURBIFY_FTP_PASS', '')
    host = os.environ.get('TURBIFY_FTP_HOST', '')

    if not all([user, pw, host]):
        log.warning("Turbify FTP credentials not set — skipping upload")
        return False

    log.info("── Step 4: Upload to Turbify ──")
    result = subprocess.run(
        ['curl', '--retry', '3', '--silent', '--show-error',
         '--user', f'{user}:{pw}',
         '-T', str(EXPORT_JSON),
         f'ftp://{host}/sool_criminal_data.json'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        log.info(f"Uploaded to ftp://{host}/sool_criminal_data.json")
        return True
    else:
        log.error(f"FTP upload failed: {result.stderr[:200]}")
        return False


# ── STATUS ────────────────────────────────────────────────────────────────────

def print_status():
    try:
        crim_conn = sqlite3.connect(str(CRIMINAL_DB))
        ann_conn  = sqlite3.connect(str(ANN_DB))

        cats = crim_conn.execute("""
            SELECT category_id, COUNT(*) FROM criminal_cases GROUP BY category_id
        """).fetchall()
        total_c = crim_conn.execute("SELECT COUNT(*) FROM criminal_cases").fetchone()[0]
        total_a = ann_conn.execute(
            "SELECT COUNT(DISTINCT case_id) FROM criminal_annotations"
        ).fetchone()[0]

        print(f"\nCriminal Corpus Status — {datetime.date.today()}")
        print("=" * 50)
        for cat_id, n in sorted(cats):
            bar = '█' * (n * 20 // 500) + '░' * (20 - n * 20 // 500)
            print(f"  C{cat_id} [{bar}] {n:>4}/500")
        print(f"\n  Collected:  {total_c:,}")
        print(f"  Annotated:  {total_a:,}")
        print(f"  Pending:    {total_c - total_a:,}")
        if EXPORT_JSON.exists():
            mtime = datetime.datetime.fromtimestamp(EXPORT_JSON.stat().st_mtime)
            print(f"  JSON last:  {mtime.strftime('%Y-%m-%d %H:%M')}")
        crim_conn.close()
        ann_conn.close()
    except Exception as e:
        print(f"Status error: {e}")


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SOoL Criminal Corpus Daily Update"
    )
    parser.add_argument('--cl-key',        default=os.environ.get('SOOL_CL_KEY',''))
    parser.add_argument('--anthropic-key', default=os.environ.get('SOOL_ANTHROPIC_KEY',''))
    parser.add_argument('--dry-run',       action='store_true')
    parser.add_argument('--collect-only',  action='store_true')
    parser.add_argument('--annotate-only', action='store_true')
    parser.add_argument('--export-only',   action='store_true')
    parser.add_argument('--status',        action='store_true')
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    LOG_DIR.mkdir(exist_ok=True)

    log.info("=" * 60)
    log.info("SOoL Criminal Corpus Daily Update")
    log.info(f"Date: {datetime.date.today()}")
    log.info("=" * 60)

    run_date = datetime.date.today().isoformat()
    new_found  = 0
    annotated  = 0
    exported   = False
    uploaded   = False

    if not args.annotate_only and not args.export_only:
        if not args.cl_key:
            log.error("SOOL_CL_KEY not set — cannot collect")
        else:
            new_found = run_collection(args.cl_key, args.dry_run)

    if not args.collect_only and not args.export_only:
        if not args.anthropic_key:
            log.error("SOOL_ANTHROPIC_KEY not set — cannot annotate")
        else:
            annotated = run_annotation(args.anthropic_key, args.dry_run)

    if not args.collect_only and not args.annotate_only:
        exported = run_export(args.dry_run)
        if exported:
            uploaded = run_upload(args.dry_run)

    log.info("=" * 60)
    log.info(f"Daily criminal update complete — {run_date}")
    log.info(f"  New cases collected:  {new_found}")
    log.info(f"  New cases annotated:  {annotated}")
    log.info(f"  JSON exported:        {exported}")
    log.info(f"  Uploaded to Turbify:  {uploaded}")
    log.info("=" * 60)


if __name__ == '__main__':
    main()
