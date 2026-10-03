#!/bin/bash
# ============================================================
# SOoL Corpus Monthly Update Script
# SEAL Lab, Texas A&M University
# David R. Koepsell — A Structural Ontology of the Law
# ============================================================
# Usage:
#   chmod +x update_corpus.sh
#   ./update_corpus.sh
#
# For scheduled monthly runs, add to crontab:
#   0 2 1 * * /home/drkoe/CaseLaw/update_corpus.sh >> /home/drkoe/CaseLaw/logs/update.log 2>&1
#
# Required environment variables (set in ~/.sool_env or export directly):
#   SOOL_CL_KEY       — CourtListener API token
#   SOOL_ANTHROPIC_KEY — Anthropic API key
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── LOAD KEYS ────────────────────────────────────────────────
if [ -f "$HOME/.sool_env" ]; then
    source "$HOME/.sool_env"
fi

if [ -z "$SOOL_CL_KEY" ] || [ -z "$SOOL_ANTHROPIC_KEY" ]; then
    echo "ERROR: SOOL_CL_KEY and SOOL_ANTHROPIC_KEY must be set."
    echo "Create ~/.sool_env with:"
    echo "  export SOOL_CL_KEY=your-courtlistener-token"
    echo "  export SOOL_ANTHROPIC_KEY=sk-ant-api03-..."
    exit 1
fi

# ── ACTIVATE VENV ────────────────────────────────────────────
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
else
    echo "WARNING: No venv found. Using system Python."
fi

PYTHON=$(which python3 2>/dev/null || which python)
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/update_$(date +%Y%m%d_%H%M%S).log"

# ── HEADER ───────────────────────────────────────────────────
echo "============================================================" | tee -a "$LOGFILE"
echo "SOoL Corpus Update — $(date)"                                 | tee -a "$LOGFILE"
echo "============================================================" | tee -a "$LOGFILE"

# Count before
BEFORE=$($PYTHON -c "
import sqlite3, os
db = 'sool_annotations.db'
if os.path.exists(db):
    print(sqlite3.connect(db).execute('SELECT COUNT(*) FROM annotations').fetchone()[0])
else:
    print(0)
" 2>/dev/null || echo 0)
echo "Annotations before: $BEFORE" | tee -a "$LOGFILE"

# ── STEP 1: COLLECT NEW CASES ────────────────────────────────
echo "" | tee -a "$LOGFILE"
echo "── Step 1: Collecting new cases ────────────────────────" | tee -a "$LOGFILE"

$PYTHON collect_caselaw.py \
    --api-key "$SOOL_CL_KEY" \
    --domain all \
    --limit 999 \
    --texts \
    2>&1 | tee -a "$LOGFILE"

# ── STEP 2: EXPORT JSONL ─────────────────────────────────────
echo "" | tee -a "$LOGFILE"
echo "── Step 2: Exporting JSONL corpus files ────────────────" | tee -a "$LOGFILE"

$PYTHON collect_caselaw.py \
    --api-key "$SOOL_CL_KEY" \
    --export \
    2>&1 | tee -a "$LOGFILE"

# ── STEP 3: ANNOTATE NEW CASES ───────────────────────────────
echo "" | tee -a "$LOGFILE"
echo "── Step 3: Annotating new cases ────────────────────────" | tee -a "$LOGFILE"

$PYTHON annotate_pipeline.py \
    --api-key "$SOOL_ANTHROPIC_KEY" \
    --domain all \
    2>&1 | tee -a "$LOGFILE"

# ── STEP 4: REANNOTATE MIXED-PERSPECTIVE ─────────────────────
echo "" | tee -a "$LOGFILE"
echo "── Step 4: Fixing mixed-perspective errors ─────────────" | tee -a "$LOGFILE"

$PYTHON annotate_pipeline.py \
    --api-key "$SOOL_ANTHROPIC_KEY" \
    --reannotate-mixed \
    2>&1 | tee -a "$LOGFILE"

# ── STEP 5: EXPORT CORPUS JSON ───────────────────────────────
echo "" | tee -a "$LOGFILE"
echo "── Step 5: Exporting corpus JSON for Query Tool ────────" | tee -a "$LOGFILE"

$PYTHON export_corpus.py \
    2>&1 | tee -a "$LOGFILE"

# ── STEP 6: RUN ANALYSIS SCRIPTS ─────────────────────────────
echo "" | tee -a "$LOGFILE"
echo "── Step 6: Running analysis scripts ────────────────────" | tee -a "$LOGFILE"

$PYTHON temporal_cd.py 2>&1 | tee -a "$LOGFILE" || echo "temporal_cd.py skipped (matplotlib not installed)" | tee -a "$LOGFILE"
$PYTHON node_topology.py 2>&1 | tee -a "$LOGFILE" || echo "node_topology.py skipped" | tee -a "$LOGFILE"

# ── SUMMARY ──────────────────────────────────────────────────
AFTER=$($PYTHON -c "
import sqlite3
n = sqlite3.connect('sool_annotations.db').execute('SELECT COUNT(*) FROM annotations').fetchone()[0]
print(n)
" 2>/dev/null || echo "?")

NEW=$((AFTER - BEFORE))

echo "" | tee -a "$LOGFILE"
echo "============================================================" | tee -a "$LOGFILE"
echo "Update complete — $(date)"                                     | tee -a "$LOGFILE"
echo "  Annotations before: $BEFORE"                                 | tee -a "$LOGFILE"
echo "  Annotations after:  $AFTER"                                  | tee -a "$LOGFILE"
echo "  New this run:       $NEW"                                     | tee -a "$LOGFILE"
echo "  Log: $LOGFILE"                                                | tee -a "$LOGFILE"
echo "============================================================" | tee -a "$LOGFILE"

# Record to update log in DB
$PYTHON -c "
import sqlite3, datetime, json, os

db_path = 'sool_annotations.db'
if not os.path.exists(db_path):
    exit()

conn = sqlite3.connect(db_path)
conn.execute('''CREATE TABLE IF NOT EXISTS update_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT,
    new_cases       INTEGER,
    corpus_total    INTEGER,
    cd_ratio        REAL
)''')

total = conn.execute('SELECT COUNT(*) FROM annotations').fetchone()[0]

# Compute CD ratio
try:
    denied  = conn.execute(\"SELECT AVG(contradiction_debt) FROM annotations WHERE chain_outcome='protection_denied' AND NOT needs_review\").fetchone()[0] or 0
    granted = conn.execute(\"SELECT AVG(contradiction_debt) FROM annotations WHERE chain_outcome='protection_granted' AND NOT needs_review\").fetchone()[0] or 0.001
    ratio = round(denied / granted, 2) if granted > 0 else None
except:
    ratio = None

conn.execute('INSERT INTO update_log (run_date, new_cases, corpus_total, cd_ratio) VALUES (?,?,?,?)',
    (datetime.datetime.utcnow().isoformat(), $NEW, total, ratio))
conn.commit()
print(f'Update logged: n={total}, CD ratio={ratio}')
" 2>&1 | tee -a "$LOGFILE"
# ── STEP 7: UPLOAD TO TURBIFY ────────────────────────────────
echo "" | tee -a "$LOGFILE"
echo "── Step 7: Uploading to Turbify ────────────────────────" | tee -a "$LOGFILE"

curl --ftp-create-dirs --retry 3 \
     -T ~/CaseLaw/sool_corpus_data.json \
     "ftp://$TURBIFY_FTP_USER:$TURBIFY_FTP_PASS@$TURBIFY_FTP_HOST$TURBIFY_FTP_PATH" \
     2>&1 | tee -a "$LOGFILE"

echo "Upload complete." | tee -a "$LOGFILE"
