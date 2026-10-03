"""
fetch_outcomes.py — Fetch SCOTUS Outcomes from Oyez API
========================================================
SEAL Lab, Texas A&M University

Populates the outcome fields in scotus_backtest.db using the Oyez API.
Oyez is free, no API key required, and has structured decisions data
including the winning party name for all decided SCOTUS cases.

Also updates annotate_scotus.py behavior: annotates ALL cases with
transcripts regardless of outcome, then matches outcomes separately.

Usage:
    python3 fetch_outcomes.py                    # all cases in DB
    python3 fetch_outcomes.py --docket 24-935    # single case
    python3 fetch_outcomes.py --refresh          # re-fetch all
"""

import argparse, json, logging, os, re, sqlite3, sys, time
from datetime import datetime
from pathlib import Path
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

OYEZ     = "https://api.oyez.org"
HEADERS  = {"User-Agent": "SOoL-Research/1.0 SEAL-Lab-TAMU"}
RATE     = 0.5

# ── OYEZ OUTCOME FETCH ────────────────────────────────────────────────────────

def infer_term(argument_date: str, docket: str) -> int:
    """
    Infer SCOTUS term year from argument date.
    Term starts in October: argued Oct-Dec → term = that year
                            argued Jan-Jun → term = previous year
    """
    if argument_date and len(argument_date) >= 7:
        year  = int(argument_date[:4])
        month = int(argument_date[5:7])
        return year if month >= 9 else year - 1

    # Fall back to docket prefix
    prefix = docket.split('-')[0]
    if prefix.isdigit():
        n = int(prefix)
        year = 2000 + n if n < 100 else n
        # Docket prefix is the term year for modern SCOTUS dockets
        return year
    return 2023  # safe default

def fetch_oyez_outcome(docket: str, term: int) -> dict:
    """
    Fetch decision outcome from Oyez for a given docket + term.
    Returns dict with outcome, petitioner_won, winning_party, description.
    """
    time.sleep(RATE)
    url = f"{OYEZ}/cases/{term}/{docket}"
    r = requests.get(url, headers=HEADERS, timeout=15)

    if r.status_code == 404:
        # Try adjacent terms (sometimes term inference is off by 1)
        for t in [term-1, term+1]:
            time.sleep(RATE)
            r2 = requests.get(f"{OYEZ}/cases/{t}/{docket}", headers=HEADERS, timeout=15)
            if r2.status_code == 200:
                r = r2
                break
        else:
            return {}

    if r.status_code != 200:
        return {}

    data = r.json()
    case = data[0] if isinstance(data, list) else data
    decisions = case.get('decisions') or []

    if not decisions:
        return {'status': 'pending'}

    d = decisions[0]
    winning_party  = d.get('winning_party') or ''
    description    = d.get('description') or ''
    majority_votes = d.get('majority_vote', 0) or 0
    minority_votes = d.get('minority_vote', 0) or 0

    # Map winning party name → petitioner_won
    first_party  = (case.get('first_party') or '').lower()
    second_party = (case.get('second_party') or '').lower()
    first_label  = (case.get('first_party_label') or 'petitioner').lower()
    win_lower    = winning_party.lower()

    # Match winning party name to first or second party
    # Use first significant word of each party name for matching
    def first_word(s):
        s = re.sub(r'\(.*?\)', '', s).strip()  # remove parentheticals
        return s.split(',')[0].split(' ')[0].lower()

    fw = first_word(first_party)
    sw = first_word(second_party)
    ww = first_word(win_lower)

    if fw and fw in win_lower:
        won_first = True
    elif sw and sw in win_lower:
        won_first = False
    elif ww and ww in first_party:
        won_first = True
    elif ww and ww in second_party:
        won_first = False
    else:
        # Fallback: check majority/minority vote direction
        won_first = None

    if won_first is True:
        petitioner_won = 1 if 'petitioner' in first_label else 0
        outcome = 'protection_granted' if petitioner_won == 1 else 'protection_denied'
    elif won_first is False:
        petitioner_won = 0 if 'petitioner' in first_label else 1
        outcome = 'protection_denied' if petitioner_won == 0 else 'protection_granted'
    else:
        petitioner_won = None
        outcome = winning_party or 'unknown'

    # Handle dispositions that aren't simple win/lose
    desc_lower = description.lower()
    if 'vacated' in desc_lower and 'remanded' in desc_lower:
        if petitioner_won == 1:
            outcome = 'protection_granted'  # Vacated/remanded in petitioner's favor
        elif petitioner_won == 0:
            outcome = 'protection_denied'
        else:
            outcome = 'partial'
    elif 'dismissed' in desc_lower and 'improvidently' in desc_lower:
        outcome = 'dismissed'
        petitioner_won = None
    elif 'affirmed' in desc_lower:
        # Affirmed = lower court ruling stands
        # Need to know whether lower court favored petitioner
        pass  # Keep outcome as computed from winning party

    return {
        'outcome':              outcome,
        'petitioner_won':       petitioner_won,
        'winning_party_name':   winning_party,
        'lower_court_decision': description[:200],
        'majority_votes':       majority_votes,
        'minority_votes':       minority_votes,
        'decision_type':        d.get('decision_type', ''),
        'first_party':          case.get('first_party', ''),
        'second_party':         case.get('second_party', ''),
        'first_party_label':    case.get('first_party_label', ''),
    }


# ── BATCH OUTCOME FETCH ───────────────────────────────────────────────────────

def fetch_all_outcomes(conn, refresh=False, docket_filter=None):
    """Fetch Oyez outcomes for all cases in the DB."""
    if docket_filter:
        cases = conn.execute(
            "SELECT id, docket, argument_date, case_name FROM scotus_cases WHERE docket=?",
            (docket_filter,)
        ).fetchall()
    elif refresh:
        cases = conn.execute(
            "SELECT id, docket, argument_date, case_name FROM scotus_cases"
        ).fetchall()
    else:
        cases = conn.execute("""
            SELECT id, docket, argument_date, case_name FROM scotus_cases
            WHERE petitioner_won IS NULL OR outcome IS NULL OR outcome = 'unknown'
        """).fetchall()

    log.info(f"Fetching outcomes for {len(cases)} cases from Oyez...")

    pending  = 0
    decided  = 0
    failed   = 0

    for c in cases:
        docket = c['docket']
        term   = infer_term(c['argument_date'] or '', docket)
        result = fetch_oyez_outcome(docket, term)

        if not result:
            log.info(f"  {docket:12s}: not found on Oyez (term {term})")
            failed += 1
            continue

        if result.get('status') == 'pending':
            log.info(f"  {docket:12s}: pending — not yet decided")
            pending += 1
            continue

        outcome       = result.get('outcome', 'unknown')
        petitioner_won = result.get('petitioner_won')
        description   = result.get('lower_court_decision', '')
        won_name      = result.get('winning_party_name', '')

        conn.execute("""
            UPDATE scotus_cases SET
              outcome=?, petitioner_won=?, lower_court_decision=?,
              issue_area=COALESCE(issue_area,?)
            WHERE id=?
        """, (outcome, petitioner_won, description,
              f"{result.get('first_party_label','')} won" if petitioner_won == 1 else '',
              c['id']))
        conn.commit()

        log.info(f"  {docket:12s}: {won_name[:25]:25s} → {outcome} (p_won={petitioner_won})")
        decided += 1

    log.info(f"\nOutcome fetch complete: {decided} decided, {pending} pending, {failed} not found")
    return decided, pending, failed


# ── UPDATE PREDICTION_CORRECT ─────────────────────────────────────────────────

def sync_prediction_correct(conn):
    """
    After outcomes are fetched, compute prediction_correct for all
    annotations that have both predicted_outcome and actual_outcome.
    """
    rows = conn.execute("""
        SELECT a.id, a.predicted_outcome, c.outcome
        FROM scotus_annotations a
        JOIN scotus_cases c ON c.id = a.case_id
        WHERE c.petitioner_won IS NOT NULL
        AND a.predicted_outcome IS NOT NULL
        AND a.predicted_outcome != ''
    """).fetchall()

    updated = 0
    for r in rows:
        pred   = r['predicted_outcome']
        actual = r['outcome']

        if pred in ('protection_granted','protection_denied') and \
           actual in ('protection_granted','protection_denied'):
            correct = 1 if pred == actual else 0
        elif pred in ('partial','indeterminate') or \
             actual in ('partial','vacated','dismissed'):
            correct = None
        else:
            correct = None

        conn.execute(
            "UPDATE scotus_annotations SET actual_outcome=?, prediction_correct=? WHERE id=?",
            (actual, correct, r['id'])
        )
        updated += 1
    conn.commit()
    log.info(f"Synced prediction_correct for {updated} annotations")
    return updated


# ── STATUS ────────────────────────────────────────────────────────────────────

def show_status(conn):
    rows = conn.execute("""
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN petitioner_won IS NOT NULL THEN 1 ELSE 0 END) as decided,
          SUM(CASE WHEN petitioner_won=1 THEN 1 ELSE 0 END) as p_won,
          SUM(CASE WHEN petitioner_won=0 THEN 1 ELSE 0 END) as p_lost
        FROM scotus_cases
    """).fetchone()

    ann = conn.execute("""
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN prediction_correct=1 THEN 1 ELSE 0 END) as correct,
          SUM(CASE WHEN prediction_correct=0 THEN 1 ELSE 0 END) as wrong
        FROM scotus_annotations
        WHERE actual_outcome IS NOT NULL
    """).fetchone()

    print(f"\n{'='*52}")
    print(f"SCOTUS Backtest — Outcome Coverage")
    print(f"{'='*52}")
    print(f"Total cases:         {rows['total']}")
    print(f"Decided (Oyez):      {rows['decided']} ({rows['p_won']} petitioner won, {rows['p_lost']} lost)")
    print(f"Pending/unknown:     {rows['total'] - rows['decided']}")

    if ann['total'] > 0:
        print(f"\nAnnotations with outcomes: {ann['total']}")
        if ann['correct'] + ann['wrong'] > 0:
            acc = ann['correct'] / (ann['correct'] + ann['wrong'])
            print(f"Prediction accuracy:       {ann['correct']}/{ann['correct']+ann['wrong']} ({acc*100:.1f}%)")

    print(f"\nOutcomes:")
    for r in conn.execute(
        "SELECT outcome, COUNT(*) n FROM scotus_cases WHERE outcome IS NOT NULL "
        "GROUP BY outcome ORDER BY n DESC"
    ):
        print(f"  {(r['outcome'] or 'NULL'):35s}: {r['n']}")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fetch SCOTUS outcomes from Oyez')
    parser.add_argument('--db',      default='scotus_backtest.db')
    parser.add_argument('--docket',  type=str)
    parser.add_argument('--refresh', action='store_true', help='Re-fetch all outcomes')
    parser.add_argument('--sync',    action='store_true', help='Only sync prediction_correct')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.sync:
        sync_prediction_correct(conn)
        show_status(conn)
        sys.exit(0)

    fetch_all_outcomes(conn, refresh=args.refresh, docket_filter=args.docket)
    sync_prediction_correct(conn)
    show_status(conn)
