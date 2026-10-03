#!/bin/bash
# finalize_v2.sh — chain the residual top-up pass onto the running rebuild.
#
# The current run converts each domain's rows to v2, but the masked-regime rows in
# D1-D7 (annotated 2026-04-05/06) were not picked up during their domains' passes;
# only D8's are converting because the job is inside D8 now. After it exits, ~205
# masked + 8 v1 cases in scope will still have no v2 annotation, which blocks a clean
# 2.0.0 release.
#
# Re-running the same command processes ONLY those: under --reannotate-v1 a case counts
# as done when its annotator is claude-pipeline-v2, so every v2 row is skipped.
#
# Waits for the in-flight job to exit, runs the top-up, then writes VERSION.json.
# Deliberately does NOT deploy — the release is checked by hand before publishing.

set -uo pipefail
cd "$HOME/CaseLaw" || exit 1
set -a; . "$HOME/.sool_env"; set +a

LOG="logs/finalize_v2_$(date +%Y%m%d_%H%M%S).log"
exec >>"$LOG" 2>&1

echo "=== finalize_v2 started $(date -Is) ==="

# 1. wait for the running rebuild to exit
while pgrep -f "annotate_pipeline.py --domain all" >/dev/null; do
  echo "$(date -Is)  rebuild still running; waiting"
  sleep 120
done
echo "$(date -Is)  rebuild process has exited"

residual() {
  sqlite3 sool_annotations.db \
    "select count(*) from annotations where annotator!='claude-pipeline-v2' and domain_id<=8;"
}

echo "$(date -Is)  residual non-v2 rows in scope: $(residual)"

# 2. top-up pass over whatever is left
if [ "$(residual)" -gt 0 ]; then
  echo "$(date -Is)  starting residual top-up pass"
  venv/bin/python3 annotate_pipeline.py --domain all --reannotate-v1
  echo "$(date -Is)  top-up exited rc=$?; residual now: $(residual)"
else
  echo "$(date -Is)  nothing to top up"
fi

# 3. record the version state (does not publish)
python3 typology/corpus_version.py --json VERSION.json
python3 typology/corpus_version.py

echo "=== finalize_v2 finished $(date -Is) ==="
