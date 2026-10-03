#!/usr/bin/env python3
"""
scotus_oyez_pipeline.py — Full Oyez-based SCOTUS Backtest Pipeline
===================================================================
SEAL Lab, Texas A&M University

Runs the complete pipeline using Oyez transcripts for older terms:
  1. collect_scotus_oyez.py  — transcripts + outcomes from Oyez
  2. annotate_scotus.py      — SOoL MLC annotation
  3. fetch_outcomes.py       — sync / fill any missing outcomes
  4. backtest_scotus.py      — compute accuracy metrics

Designed for SCOTUS terms 2005-2019 where CourtListener stt coverage
is sparse. Oyez has structured transcripts back to the 1950s.

Usage:
    python3 scotus_oyez_pipeline.py --terms 2012 2013 2014 2015 2016 2017 2018
    python3 scotus_oyez_pipeline.py --terms 2005 2006 2007 2008 2009 --limit 40
    python3 scotus_oyez_pipeline.py --annotate-only   # skip collection
    python3 scotus_oyez_pipeline.py --report-only
"""

import argparse, logging, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path("logs") / f"oyez_pipeline_{datetime.now().strftime('%Y%m%d_%H%M')}.log")
    ]
)
log = logging.getLogger(__name__)
Path("logs").mkdir(exist_ok=True)

def run(cmd, check=True):
    log.info(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd)
    if check and r.returncode != 0:
        log.error(f"Command failed: {r.returncode}")
        sys.exit(r.returncode)
    return r.returncode

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Oyez SCOTUS Pipeline')
    parser.add_argument('--terms',         nargs='+', type=int,
                        default=[2012,2013,2014,2015,2016,2017,2018])
    parser.add_argument('--limit',         type=int, default=0)
    parser.add_argument('--db',            default='scotus_backtest.db')
    parser.add_argument('--annotate-only', action='store_true')
    parser.add_argument('--report-only',   action='store_true')
    parser.add_argument('--api-key',       default=None)
    parser.add_argument('--no-upload',     action='store_true')
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get('SOOL_ANTHROPIC_KEY', '')
    terms   = [str(t) for t in args.terms]
    start   = time.time()

    log.info(f"Oyez Pipeline — terms: {', '.join(terms)}")

    # ── Step 1: Collect from Oyez ─────────────────────────────────────────────
    if not args.annotate_only and not args.report_only:
        log.info("Step 1: Collecting from Oyez")
        cmd = [sys.executable, 'collect_scotus_oyez.py',
               '--terms', *terms, '--db', args.db]
        if args.limit:
            cmd += ['--limit', str(args.limit)]
        run(cmd)

    # ── Step 2: Fetch/sync outcomes ───────────────────────────────────────────
    if not args.report_only:
        log.info("Step 1b: Syncing outcomes from Oyez")
        run([sys.executable, 'fetch_outcomes.py', '--db', args.db, '--refresh'])

    # ── Step 3: Annotate ──────────────────────────────────────────────────────
    if not args.report_only:
        log.info("Step 2: Annotating with SOoL MLC")
        cmd = [sys.executable, 'annotate_scotus.py',
               '--db', args.db, '--api-key', api_key]
        if args.limit:
            cmd += ['--limit', str(args.limit)]
        run(cmd)

    # ── Step 4: Sync predictions ──────────────────────────────────────────────
    if not args.report_only:
        log.info("Step 2b: Syncing prediction outcomes")
        run([sys.executable, 'fetch_outcomes.py', '--db', args.db, '--sync'])

    # ── Step 4b: Apply SCOTUS calibration
    if not args.report_only:
        log.info('Step 4b: Applying SCOTUS calibration')
        run([sys.executable, 'apply_scotus_calibration.py', args.db])

    # ── Step 5: Backtest report ───────────────────────────────────────────────
    log.info("Step 3: Running backtest analysis")
    run([sys.executable, 'backtest_scotus.py', '--db', args.db,
         '--export', '--out', 'scotus_backtest_results.json'])

    # ── Step 6: Upload ────────────────────────────────────────────────────────
    if not args.no_upload and not args.report_only:
        ftp_user = os.environ.get('TURBIFY_FTP_USER', '')
        ftp_pass = os.environ.get('TURBIFY_FTP_PASS', '')
        ftp_host = os.environ.get('TURBIFY_FTP_HOST', '')
        if ftp_user and ftp_pass and ftp_host:
            log.info("Step 4: Uploading to Turbify")
            r = subprocess.run([
                'curl', '--retry', '3', '--silent', '--show-error',
                '--user', f"{ftp_user}:{ftp_pass}",
                '-T', 'scotus_backtest_results.json',
                f"ftp://{ftp_host}/scotus_backtest_results.json"
            ], capture_output=True, text=True)
            if r.returncode == 0:
                log.info("  Uploaded scotus_backtest_results.json")
            else:
                log.warning(f"  Upload failed: {r.stderr[:80]}")

    log.info(f"Pipeline complete in {time.time()-start:.0f}s")
