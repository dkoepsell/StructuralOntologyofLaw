#!/usr/bin/env python3
"""
scotus_pipeline.py — SCOTUS Backtest Pipeline Orchestrator
===========================================================
SEAL Lab, Texas A&M University

Runs the complete SCOTUS backtest pipeline:
  1. collect_scotus.py  — download transcripts + decisions
  2. annotate_scotus.py — SOoL MLC annotation of transcripts
  3. backtest_scotus.py — compute accuracy metrics
  4. FTP upload         — push results JSON to Turbify

Usage:
    python3 scotus_pipeline.py --terms 2020 2021 2022 2023 2024
    python3 scotus_pipeline.py --terms 2024 --limit 30 --dry-run
    python3 scotus_pipeline.py --annotate-only   # skip collection
    python3 scotus_pipeline.py --report-only     # just generate report
"""

import argparse, logging, os, sys, subprocess, time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path('logs') / f"scotus_pipeline_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
log = logging.getLogger(__name__)
Path('logs').mkdir(exist_ok=True)

def run(cmd, check=True):
    log.info(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=False)
    if check and r.returncode != 0:
        log.error(f"Command failed with code {r.returncode}")
        sys.exit(r.returncode)
    return r.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SCOTUS Backtest Pipeline')
    parser.add_argument('--terms',          nargs='+', type=int,
                        default=[2020,2021,2022,2023,2024])
    parser.add_argument('--limit',          type=int, default=0)
    parser.add_argument('--db',             default='scotus_backtest.db')
    parser.add_argument('--annotate-only',  action='store_true')
    parser.add_argument('--report-only',    action='store_true')
    parser.add_argument('--dry-run',        action='store_true')
    parser.add_argument('--no-upload',      action='store_true')
    parser.add_argument('--api-key',        default=None)
    parser.add_argument('--cl-key',         default=None)
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get('SOOL_ANTHROPIC_KEY', '')
    cl_key  = args.cl_key  or os.environ.get('SOOL_CL_KEY', '')
    terms   = [str(t) for t in args.terms]

    log.info(f"SCOTUS Pipeline — terms: {', '.join(terms)}")
    start = time.time()

    # ── Step 1: Collect ────────────────────────────────────────────────────────
    if not args.annotate_only and not args.report_only and not args.dry_run:
        log.info("Step 1: Collecting transcripts and decisions")
        cmd = [
            sys.executable, 'collect_scotus.py',
            '--terms', *terms,
            '--db', args.db,
        ]
        if args.limit:
            cmd += ['--limit', str(args.limit)]
        if cl_key:
            cmd += ['--cl-key', cl_key]
        run(cmd)
    else:
        log.info("Step 1: Skipped (--annotate-only or --report-only)")

    # ── Step 1b: Fetch outcomes from Oyez ────────────────────────────────────
    if not args.annotate_only and not args.report_only and not args.dry_run:
        log.info("Step 1b: Fetching outcomes from Oyez")
        run([sys.executable, 'fetch_outcomes.py', '--db', args.db])

    # ── Step 2: Annotate ───────────────────────────────────────────────────────
    if not args.report_only and not args.dry_run:
        log.info("Step 2: Annotating transcripts with SOoL MLC")
        cmd = [
            sys.executable, 'annotate_scotus.py',
            '--db', args.db,
            '--api-key', api_key,
        ]
        if args.limit:
            cmd += ['--limit', str(args.limit)]
        run(cmd)
    else:
        log.info("Step 2: Skipped (--report-only)")

    # ── Step 2b: Sync prediction_correct after annotation ───────────────────
    if not args.report_only and not args.dry_run:
        log.info("Step 2b: Syncing prediction outcomes")
        run([sys.executable, 'fetch_outcomes.py', '--db', args.db, '--sync'])

    # ── Step 3: Backtest report ────────────────────────────────────────────────
    log.info("Step 3: Running backtest analysis")
    cmd = [
        sys.executable, 'backtest_scotus.py',
        '--db', args.db,
        '--export',
        '--out', 'scotus_backtest_results.json',
    ]
    run(cmd)

    # ── Step 4: Upload ─────────────────────────────────────────────────────────
    if not args.no_upload and not args.dry_run:
        ftp_user = os.environ.get('TURBIFY_FTP_USER', '')
        ftp_pass = os.environ.get('TURBIFY_FTP_PASS', '')
        ftp_host = os.environ.get('TURBIFY_FTP_HOST', '')
        if ftp_user and ftp_pass and ftp_host:
            log.info("Step 4: Uploading to Turbify")
            import subprocess
            for fname in ['scotus_backtest_results.json']:
                r = subprocess.run([
                    'curl', '--retry', '3', '--silent', '--show-error',
                    '--user', f"{ftp_user}:{ftp_pass}",
                    '-T', fname,
                    f"ftp://{ftp_host}/{fname}"
                ], capture_output=True, text=True)
                if r.returncode == 0:
                    log.info(f"  Uploaded {fname}")
                else:
                    log.warning(f"  Upload failed: {r.stderr}")
        else:
            log.info("Step 4: Skipped (no FTP credentials)")

    elapsed = time.time() - start
    log.info(f"Pipeline complete in {elapsed:.0f}s")
