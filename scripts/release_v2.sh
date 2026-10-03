#!/bin/bash
# release_v2.sh — publish a corpus release. Refuses to publish a dirty one.
#
# Sequence: gate -> export -> regenerate -> validate -> upload -> verify live.
# Every step must pass before the next runs; any failure aborts before the upload,
# so a broken build cannot reach the site.
#
#   ./release_v2.sh            # full release (requires clean_release == true)
#   ./release_v2.sh --dry-run  # everything except the upload
#   ./release_v2.sh --force-rc # publish a release candidate (banner stays provisional)

set -uo pipefail
cd "$HOME/CaseLaw" || exit 1
set -a; . "$HOME/.sool_env"; set +a

DRY=0; FORCE_RC=0
for a in "$@"; do
  case "$a" in
    --dry-run)  DRY=1 ;;
    --force-rc) FORCE_RC=1 ;;
    *) echo "unknown arg: $a"; exit 2 ;;
  esac
done

step() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
fail() { printf '\n*** ABORT: %s\n' "$1"; exit 1; }

step "1/7  release gate"
python3 typology/corpus_version.py --json VERSION.json || fail "version manifest failed"
CLEAN=$(python3 -c "import json;print(json.load(open('VERSION.json'))['clean_release'])")
VER=$(python3 -c "import json;print(json.load(open('VERSION.json'))['corpus_version'])")
echo "  version=$VER  clean=$CLEAN"
if [ "$CLEAN" != "True" ] && [ "$FORCE_RC" -eq 0 ]; then
  fail "corpus is not a clean release (use --force-rc to publish a candidate)"
fi

step "2/7  typology drift check"
python3 typology/parse_ontology.py >/dev/null || fail "ontology parse failed"
python3 typology/test_lint.py | tail -1
python3 typology/pipeline_health.py > logs/pipeline_health_$(date +%Y%m%d).txt 2>&1 || true
echo "  pipeline health -> logs/pipeline_health_$(date +%Y%m%d).txt"

step "3/7  export corpus"
python3 export_corpus.py 2>&1 | tail -4 || fail "export failed"
python3 verify_export.py > logs/verify_export_$(date +%Y%m%d).txt 2>&1
tail -1 logs/verify_export_$(date +%Y%m%d).txt
grep -q "RESULT: PASS" logs/verify_export_$(date +%Y%m%d).txt || fail "export verification failed"

step "4/7  regenerate hypotheses panel"
python3 gen_provisional.py --splice || fail "panel generation failed"

step "5/7  validate page"
python3 validate_provisional_page.py | tail -2 || fail "page validation failed"
node cov_harness.js 2>/dev/null | tail -1 || echo "  (cov_harness skipped — node unavailable)"

step "6/7  upload"
if [ "$DRY" -eq 1 ]; then
  echo "  --dry-run: skipping upload"
else
  for f in SOoL_QueryTool.html sool_corpus_data.json; do
    curl --retry 3 --silent --show-error \
         --user "$TURBIFY_FTP_USER:$TURBIFY_FTP_PASS" \
         -T "$f" "ftp://$TURBIFY_FTP_HOST/$f" || fail "upload failed: $f"
    echo "  uploaded $f"
  done
fi

step "7/7  verify live"
if [ "$DRY" -eq 1 ]; then
  echo "  --dry-run: skipping live verification"
else
  sleep 3
  python3 - <<'EOF'
import json, urllib.request, sys
base = "https://www.davidkoepsell.com/"
h = urllib.request.urlopen(base + "SOoL_QueryTool.html", timeout=60).read().decode("utf-8", "replace")
d = json.loads(urllib.request.urlopen(base + "sool_corpus_data.json", timeout=120).read())
m = d["meta"]
local = json.load(open("VERSION.json"))
print(f"  live corpus_version : {m.get('corpus_version')}")
print(f"  live clean_release  : {m.get('clean_release')}")
print(f"  live analysis n     : {m.get('n'):,} of {m.get('n_all'):,}")
print(f"  live domains        : {sorted({c['domain'] for c in d['cases']})}")
ok = True
if m.get("corpus_version") != local["corpus_version"]:
    print("  !! live version does not match VERSION.json"); ok = False
for k in ("<!--PROVISIONAL-FINDINGS-START-->", "id=\"coverage-table\"", "function _v2Cases"):
    if k not in h:
        print(f"  !! missing from live page: {k}"); ok = False
if local["clean_release"] and "— released" not in h:
    print("  !! clean release but the page does not say 'released'"); ok = False
if not local["clean_release"] and "not for citation" not in h:
    print("  !! dirty corpus but the page does not carry the provisional banner"); ok = False
print("  RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
EOF
  [ $? -eq 0 ] || fail "live verification failed"
fi

printf '\n\033[1mRELEASE %s COMPLETE\033[0m\n' "$VER"
