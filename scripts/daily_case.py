#!/usr/bin/env python3
"""
daily_case.py — SOoL Case of the Day
=====================================
SEAL Lab, Texas A&M University

Fetches a randomly selected recent published circuit court opinion from
CourtListener, strips the disposition, annotates it with SOoL MLC via the
Anthropic API, and writes case_of_the_day.json for the Case Analyzer tab.

Runs daily via crontab. Add after existing pipelines:
    0 5 * * * /bin/bash -c 'source $HOME/.sool_env && cd $HOME/CaseLaw &&
        source venv/bin/activate &&
        python3 daily_case.py >> logs/daily_case_$(date +\\%Y%m%d).log 2>&1'

Then FTP case_of_the_day.json to Turbify automatically.

Usage:
    python3 daily_case.py
    python3 daily_case.py --dry-run     # fetch and annotate but don't upload
    python3 daily_case.py --force       # re-run even if today's file exists
"""

import os, re, json, time, random, argparse, logging, subprocess
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
CL_KEY        = os.environ.get("SOOL_CL_KEY", "")
ANTHROPIC_KEY = os.environ.get("SOOL_ANTHROPIC_KEY", "")
FTP_USER      = os.environ.get("TURBIFY_FTP_USER", "")
FTP_PASS      = os.environ.get("TURBIFY_FTP_PASS", "")
FTP_HOST      = os.environ.get("TURBIFY_FTP_HOST", "")

OUT_FILE      = "./case_of_the_day.json"
CLAUDE_MODEL  = "claude-sonnet-5"
OPINION_CHARS = 10000

# Circuit courts only — most structurally interesting
CIRCUIT_COURTS = ["ca1","ca2","ca3","ca4","ca5","ca6","ca7","ca8","ca9","ca10","ca11","cadc"]

# How many days back to search for recent opinions
LOOKBACK_DAYS = 14

# ── DISPOSITION MASKING ───────────────────────────────────────────────────────
_DISP_PATTERNS = [
    r"we\s+(?:therefore\s+)?affirm(?:ed|s)?\b",
    r"we\s+(?:therefore\s+)?revers(?:e|ed|es)\b",
    r"we\s+(?:therefore\s+)?remand\b",
    r"judgment\s+(?:of\s+the\s+district\s+court\s+)?(?:is\s+)?affirmed\b",
    r"judgment\s+(?:is\s+)?reversed\b",
    r"(?:is\s+)?reversed\s+and\s+remanded\b",
    r"\bAFFIRMED\b", r"\bREVERSED\b", r"\bREMANDED\b",
    r"for\s+the\s+(?:foregoing\s+)?reasons[,.]?\s+we\s+(?:affirm|reverse|remand)",
]
_DISP_RE = re.compile("|".join(_DISP_PATTERNS), re.IGNORECASE)

def strip_disposition(text: str) -> str:
    tail_start = max(0, len(text) - 2000)
    tail = text[tail_start:]
    earliest = None
    for m in _DISP_RE.finditer(tail):
        if earliest is None or m.start() < earliest.start():
            earliest = m
    if earliest:
        cut = tail_start + earliest.start()
        preceding = text[:cut]
        last_period = max(preceding.rfind(". "), preceding.rfind(".\n"), preceding.rfind("\n\n"))
        if last_period > 0 and (cut - last_period) < 400:
            cut = last_period + 1
        text = text[:cut] + "\n\n[DISPOSITION REDACTED]"
    text = re.sub(r"\b(AFFIRMED|REVERSED|REMANDED|VACATED)\b(?:[^.\n]{0,60})?", "[REDACTED]", text)
    return text


# ── SOoL ANNOTATION SYSTEM PROMPT ─────────────────────────────────────────────
AZ_SYSTEM_PROMPT = """You are a legal ontologist applying the SOoL Minimum Legal Chain (MLC) framework.
Analyze the provided legal text and return a JSON annotation with this exact structure:

{
  "case_name": "string",
  "legal_claim": "string — one sentence describing the claimant's core legal claim",
  "claimant": "string — who is asserting the claim",
  "respondent": "string — who the claim is against",
  "nodes": {
    "1": {"closure": "closed|partial|failed", "entity": "string", "justification": "string"},
    "2": {"closure": "closed|partial|failed", "entity": "string", "justification": "string"},
    "3": {"closure": "closed|partial|failed", "entity": "string", "justification": "string"},
    "4": {"closure": "closed|partial|failed", "entity": "string", "justification": "string"},
    "5": {"closure": "closed|partial|failed", "entity": "string", "justification": "string"},
    "6": {"closure": "closed|partial|failed", "entity": "string", "justification": "string"},
    "7": {"closure": "closed|partial|failed", "entity": "string", "justification": "string"},
    "8": {"closure": "closed|partial|failed", "entity": "string", "justification": "string"}
  },
  "active_contradictions": ["CF","AI","JC","RC3","PC","TC","FM","NI","RF","RCL","CC","SE","RPF"],
  "chain_outcome": "protection_granted|protection_denied|partial|remanded|dismissed",
  "outcome_confidence": "high|medium|low",
  "structural_narrative": "2-3 sentence structural diagnosis explaining the chain outcome",
  "contradiction_debt": 0.000
}

MLC nodes:
N1 Source of Authority, N2 Norm, N3 Actor in Role, N4 Triggering Facts,
N5 Legal Act/Omission, N6 Target, N7 Legal Effect (PIVOTAL), N8 Remedy

Contradiction types (use only applicable):
CF Conferral Failure, AI Authority Inflation, JC Jurisdictional Contradiction,
RC3 Role Contradiction, PC Procedural Contradiction, TC Temporal Contradiction,
FM Fact Manipulation, NI Norm Indeterminacy, RF Recognition Failure,
RCL Recognition Collapse, CC Correlativity Contradiction,
SE Self-Undermining Effect, RPF Repair Procedure Failure

CD weights: RCL=0.18 CF=0.15 RC3=0.14 CC=0.14 RPF=0.13 AI=0.12 RF=0.11 FM=0.11 JC=0.10 SE=0.10 PC=0.09 TC=0.08 NI=0.07

Return ONLY the JSON object. No preamble, no markdown fences."""


# ── FETCH RANDOM RECENT OPINION ───────────────────────────────────────────────
def fetch_candidate_opinions():
    """Fetch recent published circuit court opinions from CL."""
    since = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    court = random.choice(CIRCUIT_COURTS)

    h = {"Authorization": f"Token {CL_KEY}", "User-Agent": "SOoL-Research/1.0"}
    r = requests.get(
        "https://www.courtlistener.com/api/rest/v4/opinions/",
        params={
            "cluster__docket__court": court,
            "cluster__precedential_status": "Published",
            "cluster__date_filed__gte": since,
            "page_size": 20,
            "order_by": "-cluster__date_filed",
        },
        headers=h, timeout=30,
    )
    if r.status_code != 200:
        log.warning(f"CL fetch failed: {r.status_code}")
        return []

    results = r.json().get("results", [])
    # Filter for opinions with substantial text
    candidates = [op for op in results if len(op.get("plain_text") or "") > 2000]
    return candidates, court


def fetch_opinion_text(op: dict) -> tuple[str, str, str]:
    """Extract text, case name, and CL URL from opinion record."""
    text = op.get("plain_text") or op.get("html_text") or ""
    # Strip HTML if needed
    text = re.sub(r'<[^>]+>', ' ', text)
    # Get cluster info for case name
    cluster_url = op.get("cluster", "")
    case_name = op.get("case_name", "Unknown v. Unknown")
    cl_url = ""
    if cluster_url:
        try:
            h = {"Authorization": f"Token {CL_KEY}", "User-Agent": "SOoL-Research/1.0"}
            r = requests.get(cluster_url, headers=h, timeout=10)
            if r.status_code == 200:
                c = r.json()
                case_name = c.get("case_name") or case_name
                # Get absolute URL
                docket_url = c.get("docket", "")
                if docket_url:
                    time.sleep(0.3)
                    rd = requests.get(docket_url, headers=h, timeout=10)
                    if rd.status_code == 200:
                        cl_url = "https://www.courtlistener.com" + (rd.json().get("absolute_url") or "")
        except Exception as e:
            log.warning(f"Cluster fetch failed: {e}")
    return text, case_name, cl_url


# ── ANNOTATE VIA CLAUDE ───────────────────────────────────────────────────────
def annotate(text: str, case_name: str) -> dict:
    """Run SOoL MLC annotation via Claude API."""
    masked_text = strip_disposition(text)
    truncated   = masked_text[:OPINION_CHARS]

    user_msg = (
        f"CASE: {case_name}\n\n"
        f"LEGAL TEXT:\n{truncated}\n\n"
        "---\nAnalyze this text using the SOoL Minimum Legal Chain. Return only JSON."
    )

    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 3500,
            # See annotate_pipeline.call_claude: Sonnet 5 thinks by default and
            # max_tokens covers thinking + text, which truncates the JSON.
            "thinking": {"type": "disabled"},
            "system": AZ_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    raw = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            raw += block.get("text", "")

    # Parse JSON
    clean = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.MULTILINE)
    clean = re.sub(r'\s*```$', '', clean.strip(), flags=re.MULTILINE)
    return json.loads(clean.strip())


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SOoL Case of the Day")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force",   action="store_true", help="Re-run even if today's file exists")
    args = parser.parse_args()

    today = date.today().isoformat()

    # Check if already done today
    if not args.force and Path(OUT_FILE).exists():
        try:
            with open(OUT_FILE) as f:
                existing = json.load(f)
            if existing.get("date") == today:
                log.info(f"Case of the day already set for {today}: {existing.get('case_name','?')}")
                return
        except:
            pass

    if not CL_KEY:
        log.error("SOOL_CL_KEY not set")
        return
    if not ANTHROPIC_KEY:
        log.error("SOOL_ANTHROPIC_KEY not set")
        return

    # Fetch candidates — try up to 3 courts if first has no results
    candidates = []
    court = ""
    for attempt in range(3):
        result = fetch_candidate_opinions()
        if result and result[0]:
            candidates, court = result
            break
        time.sleep(1)

    if not candidates:
        log.error("No suitable opinions found")
        return

    # Pick random candidate
    op = random.choice(candidates)
    log.info(f"Selected opinion from {court}: {op.get('cluster','?')}")

    # Fetch full text and metadata
    text, case_name, cl_url = fetch_opinion_text(op)
    log.info(f"Case: {case_name} ({len(text):,} chars)")

    if len(text) < 500:
        log.error("Opinion text too short — skipping")
        return

    # Annotate
    log.info("Annotating via Claude...")
    try:
        annotation = annotate(text, case_name)
    except Exception as e:
        log.error(f"Annotation failed: {e}")
        return

    # Compute CD if not already set
    CT_WEIGHTS = {
        "RCL":0.18,"CF":0.15,"RC3":0.14,"CC":0.14,"RPF":0.13,
        "AI":0.12,"RF":0.11,"FM":0.11,"JC":0.10,"SE":0.10,
        "PC":0.09,"TC":0.08,"NI":0.07,
    }
    cts = annotation.get("active_contradictions", [])
    cd  = round(sum(CT_WEIGHTS.get(ct, 0) for ct in cts), 4)
    annotation["contradiction_debt"] = cd

    # Build output
    output = {
        "date":        today,
        "generated":   datetime.now(timezone.utc).isoformat(),
        "court":       court.upper(),
        "case_name":   case_name,
        "cl_url":      cl_url,
        "opinion_excerpt": text[:800].strip() + "…",
        "annotation":  annotation,
    }

    log.info(f"CD={cd}  outcome={annotation.get('chain_outcome')}  "
             f"CTs={cts}  confidence={annotation.get('outcome_confidence')}")

    if args.dry_run:
        log.info("DRY RUN — not writing file")
        print(json.dumps(output, indent=2)[:1000])
        return

    # Write JSON
    with open(OUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    log.info(f"Written: {OUT_FILE}")

    # Upload to Turbify
    if FTP_USER and FTP_PASS and FTP_HOST:
        r = subprocess.run([
            "curl", "--retry", "3", "--silent", "--show-error",
            "--user", f"{FTP_USER}:{FTP_PASS}",
            "-T", OUT_FILE,
            f"ftp://{FTP_HOST}/case_of_the_day.json",
        ], capture_output=True, text=True)
        if r.returncode == 0:
            log.info("Uploaded case_of_the_day.json to Turbify")
        else:
            log.warning(f"FTP upload failed: {r.stderr[:200]}")
    else:
        log.warning("FTP credentials not set — skipping upload")


if __name__ == "__main__":
    main()
