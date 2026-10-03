#!/usr/bin/env bash
# check_reannotation.sh — is the v1->v2 re-annotation still going, and how far along?
#   ./check_reannotation.sh
HOST="${SOOL_PROD_HOST:-$SOOL_PROD_HOST}"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" '
cd ~/CaseLaw || exit 1
PID=$(pgrep -f "annotate_pipeline.py --domain all" | head -1)

echo "=============================================="
echo " SOoL v1 -> v2 re-annotation"
echo "=============================================="
if [ -n "$PID" ]; then
  echo "  STATUS   : RUNNING (pid $PID, up $(ps -o etime= -p $PID | tr -d " "))"
else
  echo "  STATUS   : NOT RUNNING"
fi

venv/bin/python3 - <<PY
import sqlite3
c = sqlite3.connect("sool_annotations.db")
done  = c.execute("select count(*) from annotations where annotator=?", ("claude-pipeline-v2",)).fetchone()[0]
left  = c.execute("select count(*) from annotations where annotator!=?", ("claude-pipeline-v2",)).fetchone()[0]
total = done + left
pct   = (100.0 * done / total) if total else 0.0
hrs   = left * 29.0 / 3600.0
print("  PROGRESS : %d / %d  (%.1f%%)" % (done, total, pct))
print("  REMAINING: %d rows  (~%.1f h at 29 s/case)" % (left, hrs))
masked = c.execute("select count(*) from annotations where annotator=? and was_masked=1", ("claude-pipeline-v2",)).fetchone()[0]
print("  of which blind-annotated (masking preserved): %d" % masked)
nullcd = c.execute("select count(*) from annotations where cd_upstream is null").fetchone()[0]
if nullcd:
    print("  NOTE: %d rows still have cd_upstream NULL -> run migrate_outcome_split.py when done" % nullcd)
PY

echo "  LOG TAIL :"
tail -1 logs/reannotate_v2_20260803.log 2>/dev/null | cut -c1-90 | sed "s/^/    /"
echo "=============================================="
if [ -z "$PID" ]; then
  echo " If REMAINING > 0, it stopped early. Relaunch (safe, resumes):"
  echo "   ssh '"$HOST"' \"cd ~/CaseLaw && set -a && . ~/.sool_env && set +a && \\"
  echo "     nohup venv/bin/python3 annotate_pipeline.py --domain all --reannotate-v1 \\"
  echo "     > logs/reannotate_v2_20260803.log 2>&1 &\""
  echo " If REMAINING = 0, it is DONE -> see RESUME_HERE_20260803.md section 2."
fi
'
