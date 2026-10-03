#!/bin/bash
# setup_cron.sh — Install SOoL cron jobs with reboot persistence
# SEAL Lab, Texas A&M University
# Run once: bash setup_cron.sh

set -e

CASEDIR="$HOME/CaseLaw"
LOGDIR="$CASEDIR/logs"
mkdir -p "$LOGDIR"

echo "Setting up SOoL cron jobs..."

# ── Write the complete crontab ────────────────────────────────────────────────
# We write the full crontab rather than appending to avoid duplicates.
# Read existing crontab, strip any old SOoL lines, add fresh ones.

# Save current non-SOoL crontab lines
EXISTING=$(crontab -l 2>/dev/null | grep -v "daily_update\|daily_criminal\|daily_case\|sool_cron" || true)

cat > /tmp/sool_crontab << 'CRON'
# ── SOoL Research Pipeline ────────────────────────────────────────────────────
# Civil corpus daily update — 3am
0 3 * * * /bin/bash -c 'source $HOME/.sool_env && source $HOME/.bashrc && cd $HOME/CaseLaw && source venv/bin/activate && python3 daily_update.py' >> $HOME/CaseLaw/logs/daily_$(date +\%Y\%m\%d).log 2>&1

# Criminal corpus daily update — 4am (1hr after civil)
0 4 * * * /bin/bash -c 'source $HOME/.sool_env && source $HOME/.bashrc && cd $HOME/CaseLaw && source venv/bin/activate && python3 daily_criminal.py' >> $HOME/CaseLaw/logs/criminal_daily_$(date +\%Y\%m\%d).log 2>&1

# Case of the Day — 5am (after civil + criminal pipelines finish)
0 5 * * * /bin/bash -c 'source $HOME/.sool_env && source $HOME/.bashrc && cd $HOME/CaseLaw && source venv/bin/activate && python3 daily_case.py' >> $HOME/CaseLaw/logs/daily_case_$(date +\%Y\%m\%d).log 2>&1

# SCOTUS daily update — 6am (after civil/criminal/case-of-day)
0 6 * * * /bin/bash -c 'source $HOME/.sool_env && source $HOME/.bashrc && cd $HOME/CaseLaw && source venv/bin/activate && python3 daily_scotus.py' >> $HOME/CaseLaw/logs/scotus_daily_$(date +\%Y\%m\%d).log 2>&1

# Reboot: restart civil daily update (runs once at boot, then cron takes over)
@reboot sleep 120 && /bin/bash -c 'source $HOME/.sool_env && source $HOME/.bashrc && cd $HOME/CaseLaw && source venv/bin/activate && python3 daily_update.py --annotate-only' >> $HOME/CaseLaw/logs/reboot_civil_$(date +\%Y\%m\%d).log 2>&1

# Reboot: restart criminal annotation if pending cases exist
@reboot sleep 180 && /bin/bash -c 'source $HOME/.sool_env && source $HOME/.bashrc && cd $HOME/CaseLaw && source venv/bin/activate && python3 daily_criminal.py --annotate-only' >> $HOME/CaseLaw/logs/reboot_criminal_$(date +\%Y\%m\%d).log 2>&1
# ── End SOoL ──────────────────────────────────────────────────────────────────
CRON

# Combine existing (non-SOoL) lines with new SOoL lines
{
  echo "$EXISTING"
  echo ""
  cat /tmp/sool_crontab
} | crontab -

echo ""
echo "Crontab installed. Verifying..."
echo ""
crontab -l
echo ""

# ── Verify environment file exists ────────────────────────────────────────────
if [ ! -f "$HOME/.sool_env" ]; then
    echo "WARNING: ~/.sool_env not found. Create it with:"
    echo ""
    echo "  cat > ~/.sool_env << 'EOF'"
    echo "  export SOOL_CL_KEY=your_courtlistener_key"
    echo "  export SOOL_ANTHROPIC_KEY=your_anthropic_key"
    echo "  export TURBIFY_FTP_USER=your_ftp_user"
    echo "  export TURBIFY_FTP_PASS=your_ftp_pass"
    echo "  export TURBIFY_FTP_HOST=<ftp-host>"
    echo "  export TURBIFY_FTP_PATH=/sool_corpus_data.json"
    echo "  EOF"
    echo ""
else
    echo "~/.sool_env found OK"
    # Check all required keys are present
    source "$HOME/.sool_env"
    for var in SOOL_CL_KEY SOOL_ANTHROPIC_KEY TURBIFY_FTP_USER TURBIFY_FTP_PASS TURBIFY_FTP_HOST; do
        if [ -z "${!var}" ]; then
            echo "  WARNING: $var not set in ~/.sool_env"
        else
            echo "  OK: $var is set"
        fi
    done
fi

# ── Verify all pipeline scripts exist ─────────────────────────────────────────
echo ""
echo "Pipeline scripts:"
for script in daily_update.py daily_criminal.py daily_scotus.py collect_criminal.py annotate_criminal.py export_criminal.py; do
    if [ -f "$CASEDIR/$script" ]; then
        echo "  OK: $script"
    else
        echo "  MISSING: $CASEDIR/$script"
    fi
done

# ── Verify venv ───────────────────────────────────────────────────────────────
echo ""
echo "Python environment:"
if [ -f "$CASEDIR/venv/bin/python3" ]; then
    echo "  OK: venv/bin/python3"
    "$CASEDIR/venv/bin/python3" -c "import anthropic, requests, sklearn; print('  OK: anthropic, requests, sklearn installed')" 2>/dev/null || \
    echo "  WARNING: some packages may be missing — run: pip install anthropic requests scikit-learn"
else
    echo "  WARNING: venv not found at $CASEDIR/venv"
fi

# ── Test that cron can source .sool_env ───────────────────────────────────────
echo ""
echo "Environment test (simulating cron invocation):"
/bin/bash -c 'source $HOME/.sool_env 2>/dev/null && echo "  OK: .sool_env sources cleanly in /bin/bash"' || \
    echo "  WARNING: .sool_env failed to source"

echo ""
echo "Done. Cron jobs are active."
echo ""
echo "The @reboot entries ensure annotation resumes automatically if the machine restarts."
echo "Civil update: 3am daily  |  Criminal update: 4am daily"
echo ""
echo "Monitor with:"
echo "  tail -f ~/CaseLaw/logs/daily_\$(date +%Y%m%d).log"
echo "  tail -f ~/CaseLaw/logs/criminal_daily_\$(date +%Y%m%d).log"
echo "  python3 ~/CaseLaw/daily_criminal.py --status"
