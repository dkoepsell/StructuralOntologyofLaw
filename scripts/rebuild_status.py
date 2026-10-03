#!/usr/bin/env python3
"""
rebuild_status.py — publish v1→v2 re-annotation progress to the live site.

Writes `rebuild_status.json` (a few hundred bytes) describing how far the
re-annotation has got, optionally re-exports the corpus JSON so the served data
keeps pace with the rebuild, and FTPs both to Turbify.

Designed to run hourly from cron while the rebuild is in flight:

    python3 rebuild_status.py --export --upload

It is safe to run when no rebuild is going: the status reports `complete: true`
once every row is v2, which the query tool renders as a completion notice, and
`stalled: true` when work remains but nothing is running.

Throughput and ETA are derived from the `annotation_date` of rows already
written in the recent past, so no state file is needed and a stalled worker
shows up as a rate of zero rather than a stale extrapolation.
"""
import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE          = Path(__file__).resolve().parent
ANNOTATIONS   = HERE / "sool_annotations.db"
STATUS_JSON   = HERE / "rebuild_status.json"
CORPUS_JSON   = HERE / "sool_corpus_data.json"
EXPORTER      = HERE / "export_corpus.py"

TARGET_ANNOTATOR = "claude-pipeline-v2"
RATE_WINDOW_H    = 3.0          # look back this far to measure throughput

# Names come from annotate.py so this file cannot drift from the schema when a
# domain is added. The overrides are only for display.
try:
    from annotate import DOCTRINAL_DOMAINS
except Exception:                                    # pragma: no cover
    DOCTRINAL_DOMAINS = {}

_PRETTY = {"civil_rights_1983": "Civil Rights §1983", "patent_ip": "Patent / IP"}
DOMAIN_NAMES = {
    did: _PRETTY.get(slug, slug.replace("_", " ").title())
    for did, slug in DOCTRINAL_DOMAINS.items()
}

log = logging.getLogger("rebuild_status")


# ─────────────────────────────────────────────────────────────────────────────
# WORKER DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def worker_running() -> bool:
    """
    Is an annotate_pipeline.py worker actually alive?

    Matched on interpreter + argv[1] rather than a `pgrep -f` substring. A
    substring pattern also matches any shell whose own command line happens to
    contain it -- which is exactly how a dead run was reported as RUNNING for
    ~12 h on 2026-08-03.
    """
    try:
        pids = subprocess.run(["pgrep", "-f", "annotate_pipeline.py"],
                              capture_output=True, text=True, timeout=10).stdout.split()
    except Exception:
        return False
    me = {str(os.getpid()), str(os.getppid())}
    for pid in pids:
        if pid in me:
            continue
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            argv = [a.decode("utf-8", "replace") for a in argv if a]
            comm = Path(f"/proc/{pid}/comm").read_text().strip()
        except Exception:
            continue
        if comm.startswith("python") and len(argv) > 1 \
           and Path(argv[1]).name == "annotate_pipeline.py":
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ts(raw):
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def collect(conn) -> dict:
    now = datetime.now(timezone.utc)
    running = worker_running()

    total = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    done  = conn.execute("SELECT COUNT(*) FROM annotations WHERE annotator=?",
                         (TARGET_ANNOTATOR,)).fetchone()[0]
    remaining = total - done

    # Throughput from rows actually written in the recent window. Rows carry an
    # ISO timestamp, so this survives restarts and gaps without a state file.
    cutoff = now - timedelta(hours=RATE_WINDOW_H)
    window = []
    latest = None
    for (raw,) in conn.execute(
            "SELECT annotation_date FROM annotations WHERE annotator=?",
            (TARGET_ANNOTATOR,)):
        ts = _parse_ts(raw)
        if ts is None:
            continue
        if latest is None or ts > latest:
            latest = ts
        if ts >= cutoff:
            window.append(ts)

    # Rate over the span the rows actually cover, not over the nominal window.
    # Dividing by RATE_WINDOW_H flat would understate throughput for the first
    # few hours after a restart and inflate the ETA to match.
    rate = 0.0
    if len(window) >= 2:
        window.sort()
        span_h = (window[-1] - window[0]).total_seconds() / 3600.0
        if span_h > 0:
            rate = (len(window) - 1) / span_h

    # An ETA from a worker that is not running would be an extrapolation of work
    # that is not happening.
    eta = None
    if rate > 0 and remaining > 0 and running:
        eta = (now + timedelta(hours=remaining / rate)).isoformat()

    by_domain = []
    for did, dtotal, ddone in conn.execute(
            "SELECT domain_id, COUNT(*), "
            "       SUM(CASE WHEN annotator=? THEN 1 ELSE 0 END) "
            "FROM annotations GROUP BY domain_id ORDER BY domain_id",
            (TARGET_ANNOTATOR,)):
        ddone = ddone or 0
        by_domain.append({
            "domain_id": did,
            "name": DOMAIN_NAMES.get(did, f"Domain {did}"),
            "total": dtotal,
            "done": ddone,
            "pct": round(100.0 * ddone / dtotal, 1) if dtotal else 0.0,
        })

    complete = remaining == 0

    # "Stalled" is the state the 2026-08-03 crash sat in for 12 h: work left,
    # nothing running, nothing written recently. Name it explicitly so the page
    # can say so rather than showing a frozen percentage.
    stalled = (not complete) and (not running) and rate == 0.0

    return {
        "generated_utc": now.isoformat(),
        "schema": 1,
        "rebuild": {
            "label": "v1 → v2 re-annotation",
            "complete": complete,
            "worker_running": running,
            "stalled": stalled,
            "total": total,
            "done": done,
            "remaining": remaining,
            "pct": round(100.0 * done / total, 1) if total else 0.0,
            "rate_per_hour": round(rate, 1),
            "eta_utc": eta,
            "last_row_utc": latest.isoformat() if latest else None,
            "by_domain": by_domain,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUBLISH
# ─────────────────────────────────────────────────────────────────────────────

def ftp_put(local: Path, remote_name: str) -> bool:
    user = os.environ.get("TURBIFY_FTP_USER", "")
    pw   = os.environ.get("TURBIFY_FTP_PASS", "")
    host = os.environ.get("TURBIFY_FTP_HOST", "")
    if not all([user, pw, host]):
        log.error("TURBIFY_FTP_* not set — %s NOT published; the live site is "
                  "still serving the previous copy", remote_name)
        return False
    r = subprocess.run(
        ["curl", "--retry", "3", "--silent", "--show-error",
         "--user", f"{user}:{pw}", "-T", str(local),
         f"ftp://{host}/{remote_name}"],
        capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        log.error("Upload FAILED for %s: %s", remote_name, r.stderr[:200])
        return False
    log.info("Uploaded: %s (%d bytes)", remote_name, local.stat().st_size)
    return True


def export_corpus() -> bool:
    if not EXPORTER.exists():
        log.error("export_corpus.py not found — corpus JSON not refreshed")
        return False
    r = subprocess.run([sys.executable, str(EXPORTER),
                        "--db", str(ANNOTATIONS), "--out", str(CORPUS_JSON)],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        log.error("export_corpus.py failed: %s", (r.stderr or r.stdout)[:300])
        return False
    log.info("Corpus JSON re-exported (%d bytes)", CORPUS_JSON.stat().st_size)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", action="store_true",
                    help="re-export sool_corpus_data.json so served data keeps "
                         "pace with the rebuild")
    ap.add_argument("--upload", action="store_true",
                    help="FTP the status (and corpus JSON, with --export) to Turbify")
    ap.add_argument("--quiet", action="store_true", help="log warnings and above only")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s")

    if not ANNOTATIONS.exists():
        log.error("%s not found", ANNOTATIONS)
        return 1

    conn = sqlite3.connect(f"file:{ANNOTATIONS}?mode=ro", uri=True)
    try:
        status = collect(conn)
    finally:
        conn.close()

    STATUS_JSON.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    rb = status["rebuild"]
    log.info("%d/%d (%.1f%%) done, %d left, %.1f rows/h, worker=%s%s",
             rb["done"], rb["total"], rb["pct"], rb["remaining"],
             rb["rate_per_hour"], rb["worker_running"],
             " STALLED" if rb["stalled"] else "")

    errors = 0
    if args.export and not export_corpus():
        errors += 1
    if args.upload:
        if not ftp_put(STATUS_JSON, "rebuild_status.json"):
            errors += 1
        if args.export and CORPUS_JSON.exists() and not ftp_put(CORPUS_JSON,
                                                                "sool_corpus_data.json"):
            errors += 1

    # A stalled rebuild is reported but is not a failure of this script.
    if rb["stalled"]:
        log.warning("Re-annotation appears STALLED: %d rows left, no worker "
                    "running, nothing written in the last %.0f h.",
                    rb["remaining"], RATE_WINDOW_H)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
