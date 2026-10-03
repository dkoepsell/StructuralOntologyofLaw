#!/bin/bash
# release_when_ready.sh — wait for the in-scope top-up to drain, then publish.
#
# The rebuild finished domains 1-8 and then wandered into D9-11, which were dropped
# from the corpus (no opinion text was ever collected for them). That job is left alone;
# a second, domain-scoped pass is converting the residual masked/v1 rows in D1-8. The
# two touch disjoint rows, and the database is WAL with a 60s busy timeout, so they run
# safely in parallel.
#
# This waits for the in-scope residual to reach zero, then hands off to release_v2.sh,
# which has its own gate and will refuse to publish anything that is not a clean release.

set -uo pipefail
cd "$HOME/CaseLaw" || exit 1

LOG="logs/release_when_ready_$(date +%Y%m%d_%H%M%S).log"
exec >>"$LOG" 2>&1
echo "=== release_when_ready started $(date -Is) ==="

residual() {
  sqlite3 sool_annotations.db \
    "select count(*) from annotations where annotator!='claude-pipeline-v2' and domain_id<=8;"
}

STALL=0
LAST=$(residual)
while :; do
  R=$(residual)
  echo "$(date -Is)  in-scope residual: $R"
  [ "$R" -eq 0 ] && break

  # Stop waiting if the top-up has died and the count is no longer moving, rather than
  # looping forever against a job that will never finish.
  if ! pgrep -f "annotate_pipeline.py --domain 1,2,3" >/dev/null; then
    if [ "$R" -eq "$LAST" ]; then
      STALL=$((STALL+1))
    else
      STALL=0
    fi
    if [ "$STALL" -ge 3 ]; then
      echo "$(date -Is)  top-up is not running and residual is static at $R — giving up"
      echo "  (remaining rows likely failed to parse; inspect before releasing)"
      exit 2
    fi
  fi
  LAST=$R
  sleep 120
done

echo "$(date -Is)  in-scope residual reached 0"
python3 typology/corpus_version.py

echo "$(date -Is)  handing off to release_v2.sh"
./release_v2.sh
RC=$?
echo "$(date -Is)  release_v2.sh exited rc=$RC"
exit $RC
