"""
collect_scotus_oyez.py — SCOTUS Collector via Oyez API
=======================================================
SEAL Lab, Texas A&M University

Collects oral argument transcripts from Oyez (api.oyez.org) for SCOTUS
terms where CourtListener stt_transcript coverage is sparse (pre-2019).
Oyez has structured transcripts going back to the 1950s.

Transcript structure:
  /cases?per_page=N&filter=term:YYYY  → case list
  case.oral_argument_audio[0].href    → OA detail endpoint
  oa_detail.transcript.sections[].turns[].text[].text  → speech text

Outcomes from:
  case.decisions[0].winning_party  → name of winning party
  case.first_party / second_party  → map name to petitioner/respondent

Usage:
    python3 collect_scotus_oyez.py --terms 2012 2013 2014 2015 2016 2017 2018
    python3 collect_scotus_oyez.py --terms 2005 2006 2007 2008 2009 --limit 40
    python3 collect_scotus_oyez.py --docket 14-556     # single case (Obergefell)
    python3 collect_scotus_oyez.py --status
"""

import argparse, json, logging, os, re, sqlite3, sys, time
from datetime import datetime
from pathlib import Path
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path("logs") / f"oyez_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
log = logging.getLogger(__name__)
Path("logs").mkdir(exist_ok=True)

OYEZ    = "https://api.oyez.org"
HEADERS = {"User-Agent": "SOoL-Research/1.0 SEAL-Lab-TAMU"}
RATE    = 0.5   # seconds between Oyez requests (polite)

# Re-use the existing scotus_backtest.db schema from collect_scotus.py
# Just import the get_db and save_case functions by re-creating what we need

SCHEMA = """
CREATE TABLE IF NOT EXISTS scotus_cases (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    docket           TEXT UNIQUE NOT NULL,
    case_name        TEXT,
    term             INTEGER,
    argument_date    TEXT,
    decision_date    TEXT,
    transcript_text  TEXT,
    transcript_chars INTEGER,
    cl_audio_id      TEXT,
    cl_cluster_id    TEXT,
    cl_docket_id     TEXT,
    decision_text    TEXT,
    outcome          TEXT,
    petitioner_won   INTEGER,
    lower_court_decision TEXT,
    issue_area       TEXT,
    collected_at     TEXT
);
CREATE TABLE IF NOT EXISTS scotus_annotations (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id              INTEGER REFERENCES scotus_cases(id),
    docket               TEXT,
    node1_closure TEXT, node1_entity TEXT, node1_justification TEXT,
    node2_closure TEXT, node2_entity TEXT, node2_justification TEXT,
    node3_closure TEXT, node3_entity TEXT, node3_justification TEXT,
    node4_closure TEXT, node4_entity TEXT, node4_justification TEXT,
    node5_closure TEXT, node5_entity TEXT, node5_justification TEXT,
    node6_closure TEXT, node6_entity TEXT, node6_justification TEXT,
    node7_closure TEXT, node7_entity TEXT, node7_justification TEXT,
    node8_closure TEXT, node8_entity TEXT, node8_justification TEXT,
    active_contradictions TEXT,
    contradiction_debt    REAL,
    predicted_outcome     TEXT,
    outcome_confidence    TEXT,
    structural_narrative  TEXT,
    adversarial_strength  REAL,
    adversarial_notes     TEXT,
    actual_outcome        TEXT,
    prediction_correct    INTEGER,
    annotated_at          TEXT,
    source_chars          INTEGER
);
CREATE TABLE IF NOT EXISTS scotus_backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT, n_cases INTEGER, n_correct INTEGER,
    n_wrong INTEGER, accuracy REAL, auc REAL, notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_sc_docket ON scotus_cases(docket);
CREATE INDEX IF NOT EXISTS idx_sc_term   ON scotus_cases(term);
CREATE INDEX IF NOT EXISTS idx_sa_case   ON scotus_annotations(case_id);
"""

def get_db(path="scotus_backtest.db"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

# ── HTTP ──────────────────────────────────────────────────────────────────────

_last = 0.0
def oyez_get(url, params=None):
    global _last
    elapsed = time.time() - _last
    if elapsed < RATE:
        time.sleep(RATE - elapsed)
    _last = time.time()
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        return r
    except Exception as e:
        log.warning(f"Request failed: {e}")
        return None

# ── TRANSCRIPT EXTRACTION ─────────────────────────────────────────────────────

def extract_transcript_text(oa_detail: dict) -> str:
    """
    Extract plain text from Oyez oral argument detail object.
    Structure: oa_detail.transcript.sections[].turns[].text[].text
    Also handles flat oa_detail.sections[] structure.
    """
    transcript_obj = oa_detail.get('transcript') or oa_detail
    sections = transcript_obj.get('sections') if isinstance(transcript_obj, dict) else []

    if not sections:
        # Try flat structure
        sections = oa_detail.get('sections') or []

    if not sections:
        return ''

    lines = []
    for section in sections:
        turns = section.get('turns') or []
        for turn in turns:
            speaker = ''
            if isinstance(turn.get('speaker'), dict):
                sp = turn['speaker']
                speaker = sp.get('name') or sp.get('last_name') or ''
            elif turn.get('speaker'):
                speaker = str(turn['speaker'])

            # Oyez uses 'text_blocks' field (not 'text')
            text_blocks = turn.get('text_blocks') or turn.get('text') or []
            for block in text_blocks:
                if isinstance(block, dict):
                    t = block.get('text', '') or block.get('start', '')
                    # text_blocks items have: start, stop, text
                    t = block.get('text', '')
                elif isinstance(block, str):
                    t = block
                else:
                    continue
                if t and t.strip():
                    if speaker:
                        lines.append(f"{speaker}: {t.strip()}")
                    else:
                        lines.append(t.strip())

    return '\n'.join(lines)

# ── OUTCOME MAPPING ───────────────────────────────────────────────────────────

def map_oyez_outcome(case_detail: dict) -> dict:
    """
    Extract outcome from Oyez case detail.
    Returns dict with outcome, petitioner_won, lower_court_decision.
    """
    decisions = case_detail.get('decisions') or []
    if not decisions:
        return {}

    d = decisions[0]
    winning_party = d.get('winning_party') or ''
    description   = d.get('description') or ''

    first_party  = (case_detail.get('first_party') or '').lower()
    second_party = (case_detail.get('second_party') or '').lower()
    first_label  = (case_detail.get('first_party_label') or 'petitioner').lower()
    win_lower    = winning_party.lower()

    def first_sig_word(s):
        s = re.sub(r'\(.*?\)', '', s).strip()
        words = s.split(',')[0].strip().split()
        return words[0].lower() if words else ''

    fw = first_sig_word(first_party)
    sw = first_sig_word(second_party)

    if fw and fw in win_lower:
        won_first = True
    elif sw and sw in win_lower:
        won_first = False
    elif win_lower and first_party and win_lower in first_party:
        won_first = True
    elif win_lower and second_party and win_lower in second_party:
        won_first = False
    else:
        won_first = None

    if won_first is True:
        petitioner_won = 1 if 'petitioner' in first_label else 0
    elif won_first is False:
        petitioner_won = 0 if 'petitioner' in first_label else 1
    else:
        petitioner_won = None

    if petitioner_won == 1:
        outcome = 'protection_granted'
    elif petitioner_won == 0:
        outcome = 'protection_denied'
    else:
        outcome = winning_party or 'unknown'

    return {
        'outcome':              outcome,
        'petitioner_won':       petitioner_won,
        'lower_court_decision': description[:300],
        'winning_party_name':   winning_party,
    }

# ── SAVE ──────────────────────────────────────────────────────────────────────

def save_case(conn, c: dict):
    existing = conn.execute(
        "SELECT id FROM scotus_cases WHERE docket=?", (c['docket'],)
    ).fetchone()

    fields = ['case_name','term','argument_date','decision_date',
              'transcript_text','transcript_chars','cl_audio_id',
              'cl_cluster_id','cl_docket_id','decision_text',
              'outcome','petitioner_won','lower_court_decision',
              'issue_area','collected_at']

    if existing:
        # Only update transcript if we got one and don't already have one
        sets = ', '.join(f"{f}=COALESCE(?,{f})" for f in fields)
        conn.execute(
            f"UPDATE scotus_cases SET {sets} WHERE docket=?",
            [c.get(f) for f in fields] + [c['docket']]
        )
    else:
        all_f = ['docket'] + fields
        placeholders = ','.join(['?'] * len(all_f))
        conn.execute(
            f"INSERT INTO scotus_cases ({','.join(all_f)}) VALUES ({placeholders})",
            [c.get(f) for f in all_f]
        )
    conn.commit()

# ── COLLECT ONE CASE ──────────────────────────────────────────────────────────

def collect_one(case_summary: dict, conn, term: int) -> bool:
    """
    Fetch transcript + outcome for one Oyez case summary.
    Returns True if case was collected with transcript.
    """
    docket    = (case_summary.get('docket_number') or '').strip()
    case_href = case_summary.get('href') or ''
    name      = case_summary.get('name') or docket

    if not docket:
        return False

    # Skip if already have transcript
    existing = conn.execute(
        "SELECT transcript_chars FROM scotus_cases WHERE docket=?", (docket,)
    ).fetchone()
    if existing and (existing['transcript_chars'] or 0) > 1000:
        log.debug(f"  {docket}: already collected, skipping")
        return True

    # Fetch full case detail for decisions + OA links
    if not case_href:
        case_href = f"{OYEZ}/cases/{term}/{docket}"

    r = oyez_get(case_href)
    if not r or r.status_code != 200:
        log.debug(f"  {docket}: case detail {r.status_code if r else 'failed'}")
        return False

    detail = r.json()
    detail = detail[0] if isinstance(detail, list) else detail

    # Extract outcome
    outcome_data = map_oyez_outcome(detail)

    # Extract oral argument transcript
    transcript_text = ''
    argument_date   = ''
    oa_list = detail.get('oral_argument_audio') or []

    for oa_entry in oa_list[:2]:  # try first 2 (some cases have multiple argument days)
        oa_href = oa_entry.get('href') or ''
        if not oa_href:
            continue
        r2 = oyez_get(oa_href)
        if not r2 or r2.status_code != 200:
            continue
        oa_detail = r2.json()

        # Extract argument date
        if not argument_date:
            arg_date = oa_detail.get('argument_date') or oa_detail.get('date') or ''
            if arg_date:
                # Oyez dates are sometimes epoch timestamps
                if isinstance(arg_date, (int, float)):
                    from datetime import datetime as dt
                    try:
                        argument_date = dt.fromtimestamp(arg_date).strftime('%Y-%m-%d')
                    except:
                        argument_date = str(arg_date)
                else:
                    argument_date = str(arg_date)

        text = extract_transcript_text(oa_detail)
        if text and len(text) > 500:
            transcript_text += text + '\n\n'

    if not transcript_text:
        log.debug(f"  {docket}: no transcript found")
        return False

    # Decision date
    timeline = detail.get('timeline') or []
    decision_date = ''
    for event in timeline:
        if isinstance(event, dict) and event.get('event') == 'Decided':
            ts = event.get('dates', [None])[0]
            if ts:
                try:
                    from datetime import datetime as dt
                    decision_date = dt.fromtimestamp(ts).strftime('%Y-%m-%d')
                except:
                    pass

    case = {
        'docket':          docket,
        'case_name':       name,
        'term':            term,
        'argument_date':   argument_date,
        'decision_date':   decision_date,
        'transcript_text': transcript_text.strip(),
        'transcript_chars': len(transcript_text.strip()),
        'collected_at':    datetime.now().isoformat(),
        **outcome_data,
    }

    save_case(conn, case)
    won = outcome_data.get('petitioner_won')
    outcome_str = outcome_data.get('outcome', '?')
    log.info(f"  {docket:12s} | {name[:38]:38s} | outcome={outcome_str:20s} | {len(transcript_text):,} chars")
    return True

# ── COLLECT TERM ──────────────────────────────────────────────────────────────

def collect_term(term: int, conn, limit: int = 0) -> int:
    """Collect all cases for a SCOTUS term from Oyez."""
    log.info(f"=== Collecting term {term} from Oyez ===")

    fetched = 0
    page = 0
    per_page = 20

    while True:
        r = oyez_get(f"{OYEZ}/cases", params={
            'per_page': per_page,
            'page':     page,
            'filter':   f"term:{term}",
        })
        if not r or r.status_code != 200:
            log.warning(f"Term {term} page {page}: {r.status_code if r else 'failed'}")
            break

        cases = r.json()
        if not cases:
            break

        for c in cases:
            success = collect_one(c, conn, term)
            if success:
                fetched += 1
                if limit and fetched >= limit:
                    log.info(f"Term {term}: limit {limit} reached")
                    return fetched

        if len(cases) < per_page:
            break  # last page
        page += 1

    log.info(f"Term {term}: {fetched} cases with transcripts")
    return fetched

# ── STATUS ────────────────────────────────────────────────────────────────────

def show_status(conn):
    total    = conn.execute("SELECT COUNT(*) FROM scotus_cases").fetchone()[0]
    w_trans  = conn.execute("SELECT COUNT(*) FROM scotus_cases WHERE transcript_chars > 1000").fetchone()[0]
    w_out    = conn.execute("SELECT COUNT(*) FROM scotus_cases WHERE petitioner_won IS NOT NULL").fetchone()[0]
    w_ann    = conn.execute("SELECT COUNT(*) FROM scotus_annotations").fetchone()[0]
    w_cor    = conn.execute("SELECT COUNT(*) FROM scotus_annotations WHERE prediction_correct=1").fetchone()[0]
    w_wr     = conn.execute("SELECT COUNT(*) FROM scotus_annotations WHERE prediction_correct=0").fetchone()[0]

    print(f"\nSCOTUS DB (Oyez+CL): {total} cases | {w_trans} transcripts | {w_out} outcomes | {w_ann} annotated")
    if w_cor + w_wr > 0:
        print(f"Accuracy: {w_cor}/{w_cor+w_wr} ({w_cor/(w_cor+w_wr)*100:.1f}%)")
    for r in conn.execute("SELECT term, COUNT(*) n, SUM(CASE WHEN transcript_chars>1000 THEN 1 ELSE 0 END) wt FROM scotus_cases GROUP BY term ORDER BY term"):
        print(f"  Term {r[0]}: {r[1]} cases ({r[2]} with transcript)")

# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SCOTUS Oyez Collector')
    parser.add_argument('--terms',  nargs='+', type=int)
    parser.add_argument('--docket', type=str)
    parser.add_argument('--limit',  type=int, default=0)
    parser.add_argument('--db',     default='scotus_backtest.db')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()

    conn = get_db(args.db)

    if args.status:
        show_status(conn); sys.exit(0)

    if args.docket:
        # Infer term from docket prefix
        prefix = args.docket.split('-')[0]
        year   = int(prefix) if prefix.isdigit() else 2015
        term   = (2000 + year if year < 100 else year) - 1  # docket year = term year + 1
        r = oyez_get(f"{OYEZ}/cases/{term}/{args.docket}")
        if r and r.status_code == 200:
            detail = r.json()
            detail = detail[0] if isinstance(detail, list) else detail
            # Create minimal summary
            summary = {
                'docket_number': args.docket,
                'name': detail.get('name', args.docket),
                'href': f"{OYEZ}/cases/{term}/{args.docket}",
            }
            collect_one(summary, conn, term)
        show_status(conn)
        sys.exit(0)

    if args.terms:
        total = 0
        for term in args.terms:
            total += collect_term(term, conn, limit=args.limit)
        log.info(f"Total collected: {total} cases across {len(args.terms)} terms")
        show_status(conn)
    else:
        parser.print_help()
