#!/usr/bin/env python3
"""
check_pipeline.py — SOoL Pipeline Health Check
===============================================
SEAL Lab, Texas A&M University

Verifies that all collection, annotation, transport, and cron
components are active and healthy.

Usage:
    python3 check_pipeline.py
    python3 check_pipeline.py --verbose
"""

import os, sys, json, sqlite3, subprocess, datetime
from pathlib import Path

CASEDIR = Path(__file__).parent
VERBOSE = '--verbose' in sys.argv

# ANSI colors
G = '\033[92m'   # green
R = '\033[91m'   # red
Y = '\033[93m'   # yellow
B = '\033[94m'   # blue
W = '\033[97m'   # white bold
D = '\033[0m'    # reset

def ok(msg):   print(f"  {G}✓{D}  {msg}")
def warn(msg): print(f"  {Y}⚠{D}  {msg}")
def fail(msg): print(f"  {R}✗{D}  {msg}")
def info(msg): print(f"  {B}·{D}  {msg}")
def head(msg): print(f"\n{W}{msg}{D}")

errors = []
warnings = []

def check(label, ok_bool, ok_msg, fail_msg, warn_only=False):
    if ok_bool:
        ok(f"{label}: {ok_msg}")
    elif warn_only:
        warn(f"{label}: {fail_msg}")
        warnings.append(label)
    else:
        fail(f"{label}: {fail_msg}")
        errors.append(label)
    return ok_bool


# ── 1. ENVIRONMENT VARIABLES ──────────────────────────────────────────────────
head("1. Environment Variables")
env_vars = {
    'SOOL_CL_KEY':        'CourtListener API key',
    'SOOL_ANTHROPIC_KEY': 'Anthropic API key',
    'TURBIFY_FTP_USER':   'FTP username',
    'TURBIFY_FTP_PASS':   'FTP password',
    'TURBIFY_FTP_HOST':   'FTP hostname',
}
for var, label in env_vars.items():
    val = os.environ.get(var, '')
    check(var, bool(val), f"set ({label})", "NOT SET — source ~/.sool_env")


# ── 2. PIPELINE SCRIPTS ───────────────────────────────────────────────────────
head("2. Pipeline Scripts")
scripts = [
    'daily_update.py',
    'daily_criminal.py',
    'collect_criminal.py',
    'annotate_criminal.py',
    'export_criminal.py',
    'collect_caselaw.py',
    'annotate_pipeline.py',
    'export_corpus.py',
]
for s in scripts:
    p = CASEDIR / s
    check(s, p.exists(), "present", "MISSING")


# ── 3. CRONTAB ───────────────────────────────────────────────────────────────
head("3. Cron Jobs")
try:
    crontab = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    ct = crontab.stdout

    jobs = {
        'Civil daily (3am)':      '0 3 * * *' in ct and 'daily_update.py' in ct,
        'Criminal daily (4am)':   '0 4 * * *' in ct and 'daily_criminal.py' in ct,
        'Reboot civil':           '@reboot' in ct and 'daily_update.py' in ct,
        'Reboot criminal':        '@reboot' in ct and 'daily_criminal.py' in ct,
    }
    for job, present in jobs.items():
        check(job, present, "scheduled", "NOT IN CRONTAB")

    # Check cron daemon is running
    cron_running = subprocess.run(
        ['pgrep', '-x', 'cron'], capture_output=True
    ).returncode == 0
    check('cron daemon', cron_running, "running", "NOT RUNNING — sudo systemctl start cron")

except Exception as e:
    fail(f"crontab: {e}")
    errors.append('crontab')


# ── 4. DATABASES ─────────────────────────────────────────────────────────────
head("4. Databases")
dbs = {
    'sool_corpus.db':                 'Civil cases',
    'sool_annotations.db':            'Civil annotations',
    'sool_criminal.db':               'Criminal cases',
    'sool_criminal_annotations.db':   'Criminal annotations',
}
for dbfile, label in dbs.items():
    p = CASEDIR / dbfile
    if p.exists():
        size_mb = p.stat().st_size / 1024 / 1024
        ok(f"{dbfile}: {size_mb:.1f} MB ({label})")
    else:
        warn(f"{dbfile}: not yet created ({label})")
        warnings.append(dbfile)


# ── 5. CORPUS STATUS ─────────────────────────────────────────────────────────
head("5. Civil Corpus")
try:
    conn = sqlite3.connect(str(CASEDIR / 'sool_annotations.db'))
    total = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    recent = conn.execute("""
        SELECT COUNT(*) FROM annotations
        WHERE annotation_date >= date('now','-7 days')
    """).fetchone()[0]
    check('Civil corpus', total > 0, f"{total:,} cases annotated, {recent} in last 7 days",
          "no annotations found")
    conn.close()
except Exception as e:
    warn(f"Civil corpus: {e}")

head("6. Criminal Corpus")
try:
    cdb  = sqlite3.connect(str(CASEDIR / 'sool_criminal.db'))
    adb  = sqlite3.connect(str(CASEDIR / 'sool_criminal_annotations.db'))
    cats = cdb.execute("""
        SELECT category_id, COUNT(*) FROM criminal_cases GROUP BY category_id
    """).fetchall()
    total_c = cdb.execute("SELECT COUNT(*) FROM criminal_cases").fetchone()[0]
    total_a = adb.execute(
        "SELECT COUNT(DISTINCT case_id) FROM criminal_annotations"
    ).fetchone()[0]
    pending = total_c - total_a
    recent_a = adb.execute("""
        SELECT COUNT(*) FROM criminal_annotations
        WHERE annotation_date >= date('now','-1 days')
    """).fetchone()[0]

    check('Criminal collected', total_c > 0, f"{total_c:,} cases", "no cases collected")
    check('Criminal annotated', total_a > 0, f"{total_a:,} annotated ({pending} pending)",
          "no annotations found")
    check('Recent annotation', recent_a > 0, f"{recent_a} cases annotated in last 24h",
          "no annotation activity in 24h — may need to restart", warn_only=True)

    if VERBOSE:
        for cat_id, n in sorted(cats):
            pct = n * 20 // 500
            bar = '█' * pct + '░' * (20 - pct)
            info(f"  C{cat_id} [{bar}] {n:>4}/500")

    cdb.close(); adb.close()
except Exception as e:
    warn(f"Criminal corpus: {e}")


# ── 6. JSON EXPORTS ───────────────────────────────────────────────────────────
head("7. JSON Exports")
exports = {
    'sool_corpus_data.json':   'Civil corpus',
    'sool_criminal_data.json': 'Criminal corpus',
}
for fname, label in exports.items():
    p = CASEDIR / fname
    if p.exists():
        age_h  = (datetime.datetime.now().timestamp() - p.stat().st_mtime) / 3600
        size_k = p.stat().st_size // 1024
        age_ok = age_h < 48
        check(fname, age_ok,
              f"{size_k:,} KB, updated {age_h:.1f}h ago ({label})",
              f"STALE — {age_h:.0f}h old, run export script",
              warn_only=True)
    else:
        warn(f"{fname}: not found — run export script")
        warnings.append(fname)


# ── 7. FTP CONNECTIVITY ───────────────────────────────────────────────────────
head("8. FTP / Transport")
host = os.environ.get('TURBIFY_FTP_HOST', '')
user = os.environ.get('TURBIFY_FTP_USER', '')
pw   = os.environ.get('TURBIFY_FTP_PASS', '')

if host and user and pw:
    try:
        result = subprocess.run(
            ['curl', '--silent', '--show-error', '--max-time', '10',
             '--user', f'{user}:{pw}',
             f'ftp://{host}/'],
            capture_output=True, text=True, timeout=15
        )
        check('FTP connectivity', result.returncode == 0,
              f"connected to {host}",
              f"FAILED — {result.stderr[:80]}")

        # Check if both JSON files exist on FTP
        for fname in ['sool_corpus_data.json', 'sool_criminal_data.json']:
            r2 = subprocess.run(
                ['curl', '--silent', '--head', '--max-time', '10',
                 '--user', f'{user}:{pw}',
                 f'ftp://{host}/{fname}'],
                capture_output=True, text=True, timeout=15
            )
            check(f'FTP {fname}', r2.returncode == 0,
                  "present on server", "NOT FOUND on server", warn_only=True)
    except Exception as e:
        warn(f"FTP: {e}")
else:
    warn("FTP credentials not set — skipping connectivity test")


# ── 8. RUNNING PROCESSES ─────────────────────────────────────────────────────
head("9. Active Processes")
try:
    ps = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
    procs = {
        'collect_criminal.py':   'Criminal collection',
        'annotate_criminal.py':  'Criminal annotation',
        'daily_update.py':       'Civil daily update',
        'daily_criminal.py':     'Criminal daily update',
        'annotate_pipeline.py':  'Civil annotation',
    }
    any_running = False
    for script, label in procs.items():
        running = script in ps.stdout
        if running:
            ok(f"{label} ({script}) — RUNNING")
            any_running = True
        elif VERBOSE:
            info(f"{label} — not running (normal if outside scheduled time)")

    if not any_running:
        info("No pipeline processes currently running (normal outside 3-4am window)")
except Exception as e:
    warn(f"Process check: {e}")


# ── 9. RECENT LOG ACTIVITY ────────────────────────────────────────────────────
head("10. Recent Log Activity")
today = datetime.date.today().strftime('%Y%m%d')
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y%m%d')
log_checks = [
    (f'daily_{today}.log',          'Civil today'),
    (f'daily_{yesterday}.log',      'Civil yesterday'),
    (f'criminal_daily_{today}.log', 'Criminal today'),
    (f'criminal_daily_{yesterday}.log', 'Criminal yesterday'),
]
for logfile, label in log_checks:
    p = CASEDIR / 'logs' / logfile
    if p.exists():
        size = p.stat().st_size
        last_line = ''
        try:
            result = subprocess.run(['tail', '-1', str(p)], capture_output=True, text=True)
            last_line = result.stdout.strip()[-80:]
        except:
            pass
        ok(f"{label} ({logfile}): {size:,} bytes")
        if VERBOSE and last_line:
            info(f"    last: {last_line}")
    else:
        info(f"{label}: no log yet")


# ── SUMMARY ───────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
if not errors and not warnings:
    print(f"{G}All checks passed. Pipeline is fully operational.{D}")
elif not errors:
    print(f"{Y}{len(warnings)} warning(s), 0 errors. Pipeline is running.{D}")
    for w in warnings: print(f"  {Y}⚠{D}  {w}")
else:
    print(f"{R}{len(errors)} error(s), {len(warnings)} warning(s).{D}")
    for e in errors:   print(f"  {R}✗{D}  {e}")
    for w in warnings: print(f"  {Y}⚠{D}  {w}")
print(f"{'='*55}\n")
