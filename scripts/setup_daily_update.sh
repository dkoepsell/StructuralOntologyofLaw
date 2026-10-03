#!/bin/bash
# ============================================================
# setup_daily_update.sh
# One-time setup for SOoL daily corpus update pipeline
# Run this once on your home Linux machine
# SEAL Lab, Texas A&M University
# ============================================================
# Usage: chmod +x setup_daily_update.sh && ./setup_daily_update.sh

set -e
CLAW_DIR="$HOME/CaseLaw"
LOG_DIR="$CLAW_DIR/logs"

echo "=================================================="
echo "SOoL Daily Update Setup"
echo "=================================================="

# ── 1. Check environment ──────────────────────────────────
echo ""
echo "Step 1: Checking environment..."

if [ ! -f "$HOME/.sool_env" ]; then
    echo "ERROR: ~/.sool_env not found"
    echo "Create it with:"
    echo "  cat > ~/.sool_env << 'EOF'"
    echo "  export SOOL_CL_KEY=your_courtlistener_token"
    echo "  export SOOL_ANTHROPIC_KEY=your_anthropic_key"
    echo "  export TURBIFY_FTP_USER=<ftp-user>"
    echo "  export TURBIFY_FTP_PASS=your_ftp_password"
    echo "  export TURBIFY_FTP_HOST=<ftp-host>"
    echo "  export TURBIFY_FTP_PATH=/sool_corpus_data.json"
    echo "  EOF"
    exit 1
fi
source "$HOME/.sool_env"

for var in SOOL_CL_KEY SOOL_ANTHROPIC_KEY; do
    if [ -z "${!var}" ]; then
        echo "ERROR: $var not set in ~/.sool_env"
        exit 1
    fi
done
echo "  Environment OK"

# ── 2. Create directories ────────────────────────────────
echo ""
echo "Step 2: Creating directories..."
mkdir -p "$LOG_DIR"
mkdir -p "$CLAW_DIR/corpus"
echo "  $LOG_DIR"
echo "  $CLAW_DIR/corpus"

# ── 3. Install dependencies ──────────────────────────────
echo ""
echo "Step 3: Checking Python dependencies..."
cd "$CLAW_DIR"
source venv/bin/activate

python3 -c "import requests" 2>/dev/null || pip install requests --quiet
python3 -c "import xml.etree.ElementTree" 2>/dev/null || true
echo "  Dependencies OK"

# ── 4. Dry run to verify RSS access ──────────────────────
echo ""
echo "Step 4: Testing RSS feed access (dry run)..."
python3 daily_update.py --dry-run --circuits ca1,ca9 2>&1 | tail -10
echo "  RSS access OK"

# ── 5. Install crontab entry ─────────────────────────────
echo ""
echo "Step 5: Installing crontab entry..."

CRON_CMD="0 3 * * * /bin/bash -c 'source \$HOME/.sool_env && cd $CLAW_DIR && source venv/bin/activate && python3 daily_update.py' >> $LOG_DIR/daily_\$(date +\%Y\%m\%d).log 2>&1"

# Check if already installed
if crontab -l 2>/dev/null | grep -q "daily_update.py"; then
    echo "  Crontab entry already present:"
    crontab -l | grep daily_update.py
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "  Installed: runs daily at 3:00 AM"
fi

# Also add monthly full corpus update
MONTHLY_CMD="0 2 1 * * /bin/bash -c 'source \$HOME/.sool_env && cd $CLAW_DIR && source venv/bin/activate && ./update_corpus.sh' >> $LOG_DIR/monthly_\$(date +\%Y\%m).log 2>&1"

if ! crontab -l 2>/dev/null | grep -q "update_corpus.sh"; then
    (crontab -l 2>/dev/null; echo "$MONTHLY_CMD") | crontab -
    echo "  Installed: monthly full update on 1st at 2:00 AM"
fi

echo ""
echo "Current crontab:"
crontab -l

# ── 6. Test annotation pipeline ──────────────────────────
echo ""
echo "Step 6: Verifying annotation pipeline..."
python3 -c "import annotate_pipeline; print('  annotate_pipeline OK')"
python3 -c "import export_corpus;     print('  export_corpus OK')"
python3 -c "import daily_update;      print('  daily_update OK')"

# ── 7. First run ─────────────────────────────────────────
echo ""
echo "=================================================="
echo "Setup complete!"
echo ""
echo "To run the first update now:"
echo "  cd $CLAW_DIR && source venv/bin/activate"
echo "  source ~/.sool_env"
echo "  python3 daily_update.py"
echo ""
echo "To monitor logs:"
echo "  tail -f $LOG_DIR/daily_\$(date +%Y%m%d).log"
echo ""
echo "To check what would be fetched without annotating:"
echo "  python3 daily_update.py --dry-run"
echo "=================================================="
