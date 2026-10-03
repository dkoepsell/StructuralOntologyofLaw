#!/usr/bin/env python3
"""
daily_update.py — SOoL Corpus Daily Update via CourtListener RSS
SEAL Lab, Texas A&M University

Fetches newly published federal appellate opinions from CourtListener RSS feeds,
collects full opinion text, annotates with Claude API, exports updated corpus JSON,
and uploads to Turbify FTP.

Usage:
    python3 daily_update.py                    # full update
    python3 daily_update.py --dry-run          # show what would be fetched
    python3 daily_update.py --rss-only         # fetch + store, skip annotation
    python3 daily_update.py --annotate-only    # annotate pending, skip fetch
    python3 daily_update.py --domains 1,3,6   # specific domains only

Cron (run at 3am daily):
    0 3 * * * /bin/bash -c 'source ~/.sool_env && cd ~/CaseLaw && \
      source venv/bin/activate && python3 daily_update.py' \
      >> ~/CaseLaw/logs/daily_$(date +%%Y%%m%%d).log 2>&1

Environment variables (set in ~/.sool_env):
    SOOL_CL_KEY          CourtListener API token
    SOOL_ANTHROPIC_KEY   Anthropic API key
    TURBIFY_FTP_USER     FTP username
    TURBIFY_FTP_PASS     FTP password
    TURBIFY_FTP_HOST     FTP hostname
    TURBIFY_FTP_PATH     Remote path for corpus JSON
"""

import argparse
import datetime
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

CORPUS_DIR   = './corpus'
ANNOT_DB     = './sool_annotations.db'
CORPUS_DB    = './sool_corpus.db'
LOG_DIR      = './logs'
EXPORT_JSON  = './sool_corpus_data.json'

# CourtListener RSS feeds — one per circuit, updated continuously
# Each feed returns the 20 most recent precedential opinions
CL_RSS_BASE = "https://www.courtlistener.com/feed/search/?" \
              "q=&type=o&order_by=dateFiled+desc&stat_Precedential=on&court="

# All 13 federal appellate courts
CIRCUITS = [
    'ca1','ca2','ca3','ca4','ca5','ca6','ca7',
    'ca8','ca9','ca10','ca11','cadc','cafc'
]

# Domain keyword signatures for auto-classification
# Cases matching these patterns get assigned to the domain
DOMAIN_KEYWORDS = {
    1: ['first amendment','free speech','garcetti','pickering','compelled speech',
        'viewpoint discrimination','public employee speech','retaliation speech'],
    2: ['title vii','discrimination','hostile work environment','mcdonnell douglas',
        'adverse employment','disparate treatment','adea','age discrimination'],
    3: ['administrative','agency action','arbitrary capricious','chevron',
        'loper bright','apa','rulemaking','major questions','deference'],
    4: ['fourth amendment','search seizure','fifth amendment','sixth amendment',
        'miranda','brady','probable cause','exclusionary rule','criminal'],
    5: ['immigration','removal','deportation','asylum','ina','iirira',
        'alien','undocumented','refugee','withholding removal'],
    6: ['section 1983','qualified immunity','civil rights','constitutional violation',
        'excessive force','deliberate indifference','monell','color of law'],
    7: ['contract','breach','ucc','consideration','promissory estoppel',
        'damages contract','formation','offer acceptance'],
    8: ['parental rights','custody','termination','best interests child',
        'family law','adoption','child welfare','foster care'],
    9: ['habeas','2254','2255','ineffective assistance','strickland',
        'actual innocence','aedpa','procedural default'],
    10:['patent','copyright','trademark','infringement','obviousness',
        'claim construction','fair use','trade secret','intellectual property'],
    11:['securities','10b-5','insider trading','sec enforcement','fraud securities',
        'materiality','scienter','investment adviser','dodd-frank'],
}

# ── LOGGING ───────────────────────────────────────────────────────────────────

Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('daily_update')


# ── DATABASE HELPERS ──────────────────────────────────────────────────────────

def get_corpus_conn():
    conn = sqlite3.connect(CORPUS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_annot_conn():
    conn = sqlite3.connect(ANNOT_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_rss_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS rss_seen (
        cluster_id   INTEGER PRIMARY KEY,
        case_name    TEXT,
        court        TEXT,
        date_filed   TEXT,
        url          TEXT,
        first_seen   TEXT,
        domain_id    INTEGER,
        processed    INTEGER DEFAULT 0
    )""")
    conn.commit()


def ensure_daily_log_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_update_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date        TEXT,
        circuits_checked INTEGER,
        new_cases_found  INTEGER,
        annotated        INTEGER,
        corpus_total     INTEGER,
        cd_ratio         REAL,
        errors           INTEGER
    )""")
    conn.commit()


# ── RSS FETCH ─────────────────────────────────────────────────────────────────

def fetch_rss_feed(circuit, session, timeout=20):
    """Fetch CourtListener RSS for one circuit and return list of entries."""
    url = CL_RSS_BASE + circuit
    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        ns   = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = []
        # Try Atom format first
        for entry in root.findall('.//atom:entry', ns):
            title   = (entry.findtext('atom:title', '', ns) or '').strip()
            link_el = entry.find('atom:link', ns)
            link    = link_el.get('href', '') if link_el is not None else ''
            updated = entry.findtext('atom:updated', '', ns) or ''
            entries.append({'title': title, 'link': link, 'date': updated})

        # Fall back to RSS 2.0 format
        if not entries:
            for item in root.findall('.//item'):
                title = (item.findtext('title') or '').strip()
                link  = (item.findtext('link') or '').strip()
                date  = (item.findtext('pubDate') or '').strip()
                entries.append({'title': title, 'link': link, 'date': date})

        return entries

    except Exception as e:
        log.warning(f"RSS fetch failed for {circuit}: {e}")
        return []


def extract_cluster_id(url):
    """Extract CourtListener cluster ID from opinion URL."""
    m = re.search(r'/opinion/(\d+)/', url)
    return int(m.group(1)) if m else None


def classify_domain(case_name, text=''):
    """Auto-classify a case into a domain based on keyword matching."""
    haystack = (case_name + ' ' + text[:2000]).lower()
    scores   = {}
    for domain_id, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in haystack)
        if score > 0:
            scores[domain_id] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


# ── OPINION TEXT FETCH ────────────────────────────────────────────────────────

def fetch_opinion_text(cluster_id, session, cl_api_key=None):
    """Fetch full opinion text for a cluster."""
    headers = {}
    if cl_api_key:
        headers['Authorization'] = f'Token {cl_api_key}'

    try:
        r = session.get(
            f'https://www.courtlistener.com/api/rest/v4/opinions/'
            f'?cluster={cluster_id}&page_size=5',
            headers=headers, timeout=30
        )
        r.raise_for_status()
        text = ''
        for op in r.json().get('results', []):
            t = op.get('plain_text', '') or ''
            if len(t) > len(text):
                text = t
        return text
    except Exception as e:
        log.warning(f"  Opinion fetch failed for cluster {cluster_id}: {e}")
        return ''


def fetch_cluster_meta(cluster_id, session, cl_api_key=None):
    """Fetch cluster metadata (case_name, date_filed, etc.)."""
    headers = {}
    if cl_api_key:
        headers['Authorization'] = f'Token {cl_api_key}'
    try:
        r = session.get(
            f'https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/',
            headers=headers, timeout=20
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"  Metadata fetch failed for {cluster_id}: {e}")
        return {}


# ── ANNOTATION ────────────────────────────────────────────────────────────────

def annotate_case(cluster_id, case_name, domain_id, text, anthropic_key,
                  domain_names):
    """Annotate a single case via annotate_pipeline.py logic."""
    # Write case to a temp JSONL file and run the pipeline on it
    domain_name = domain_names.get(domain_id, 'unknown')
    tmp_file    = f'/tmp/sool_rss_{cluster_id}.jsonl'

    case_obj = {
        'id':          cluster_id,
        'case_name':   case_name,
        'domain_id':   domain_id,
        'domain_name': domain_name,
        'court_id':    '',
        'date_filed':  datetime.date.today().isoformat(),
        'opinions':    [{'plain_text': text}],
        'citations':   [],
        'absolute_url':'',
    }

    with open(tmp_file, 'w') as f:
        f.write(json.dumps(case_obj) + '\n')

    # Run annotate_pipeline on just this file
    # Pass the key through the environment, never argv: argv shows up in
    # `ps`, and subprocess tracebacks echo the full command into the logs.
    result = subprocess.run(
        [sys.executable, 'annotate_pipeline.py',
         '--domain',  str(domain_id),
         '--corpus-dir', '/tmp',
         '--limit',   '1'],
        capture_output=True, text=True, timeout=120,
        env={**os.environ,
             'ANTHROPIC_API_KEY': anthropic_key,
             f'SOOL_RSS_{cluster_id}': '1'}
    )
    os.unlink(tmp_file)
    return result.returncode == 0


# ── EXPORT & UPLOAD ───────────────────────────────────────────────────────────

def run_export():
    """Run export_corpus.py to rebuild the JSON."""
    result = subprocess.run(
        [sys.executable, 'export_corpus.py'],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        log.error(f"export_corpus.py failed: {result.stderr[:200]}")
        return False
    log.info("Corpus JSON exported successfully")
    return True


def upload_to_turbify():
    """Upload sool_corpus_data.json to Turbify via FTP."""
    user = os.environ.get('TURBIFY_FTP_USER', '')
    pw   = os.environ.get('TURBIFY_FTP_PASS', '')
    host = os.environ.get('TURBIFY_FTP_HOST', '')
    path = os.environ.get('TURBIFY_FTP_PATH', '/sool_corpus_data.json')

    if not all([user, pw, host]):
        log.warning("Turbify FTP credentials not set — skipping upload")
        return False

    result = subprocess.run(
        ['curl', '--retry', '3', '--silent', '--show-error',
         '--user', f'{user}:{pw}',
         '-T', EXPORT_JSON,
         f'ftp://{host}{path}'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        log.info(f"Uploaded to ftp://{host}{path}")
        return True
    else:
        log.error(f"FTP upload failed: {result.stderr[:200]}")
        return False


# ── STATS ─────────────────────────────────────────────────────────────────────

def compute_stats(conn):
    """Compute current corpus stats for the daily log."""
    total = conn.execute(
        "SELECT COUNT(*) FROM annotations WHERE NOT needs_review"
    ).fetchone()[0]

    denied  = conn.execute(
        "SELECT AVG(contradiction_debt) FROM annotations "
        "WHERE chain_outcome='protection_denied' AND NOT needs_review"
    ).fetchone()[0] or 0

    granted = conn.execute(
        "SELECT AVG(contradiction_debt) FROM annotations "
        "WHERE chain_outcome='protection_granted' AND NOT needs_review"
    ).fetchone()[0] or 0.001

    ratio = round(denied / granted, 2) if granted > 0 else None
    return total, ratio


# ── COURTLISTENER API SUPPLEMENT ─────────────────────────────────────────────

CL_API_SEARCH = "https://www.courtlistener.com/api/rest/v4/search/"
CL_API_COURTS = ['ca1','ca2','ca3','ca4','ca5','ca6',
                 'ca7','ca8','ca9','ca10','ca11','cadc','cafc']

# Short focused queries per domain used for the API supplement search
API_DOMAIN_QUERIES = {
    1:  "first amendment public employee speech retaliation viewpoint",
    2:  "title VII discrimination employment adverse action disparate",
    3:  "arbitrary capricious agency APA rulemaking Chevron Loper",
    4:  "fourth amendment search seizure fifth amendment Miranda Brady",
    5:  "immigration removal deportation asylum INA withholding",
    6:  "section 1983 qualified immunity excessive force civil rights",
    7:  "contract breach damages promissory estoppel consideration",
    8:  "parental rights custody termination best interests child",
    9:  "habeas corpus 2254 2255 ineffective assistance Strickland AEDPA",
    10: "patent copyright trademark infringement claim construction fair use",
    11: "securities fraud 10b-5 insider trading SEC enforcement materiality",
}


def fetch_recent_via_api(corpus_conn, session, cl_api_key, target_domains,
                         date_after, date_before):
    """
    Supplement RSS by querying CourtListener search API for recent opinions
    in each domain, filed between date_after and date_before.
    Inserts newly discovered cases into rss_seen with processed=0 so they
    flow into the existing annotation pipeline.
    Returns the count of newly queued cases.
    """
    new_found = 0
    headers = {'Authorization': f'Token {cl_api_key}'} if cl_api_key else {}

    log.info(f"\n── Step 1b: API supplement ({date_after} → {date_before}) ──")

    for domain_id in target_domains:
        query = API_DOMAIN_QUERIES.get(domain_id)
        if not query:
            continue

        page = 1
        domain_new = 0
        while True:
            params = {
                'q': query,
                'type': 'o',
                'court': ' '.join(CL_API_COURTS),
                'filed_after': date_after,
                'filed_before': date_before,
                'stat_Precedential': 'on',
                'order_by': 'dateFiled desc',
                'page': page,
                'page_size': 20,
            }
            try:
                r = session.get(CL_API_SEARCH, params=params,
                                headers=headers, timeout=30)
                if r.status_code == 429:
                    wait = int(r.headers.get('Retry-After', 60))
                    log.warning(f"Rate limited — sleeping {wait}s")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning(f"API query failed for D{domain_id} p{page}: {e}")
                break

            results = data.get('results', [])
            if not results:
                break

            for hit in results:
                cluster_id = hit.get('cluster_id') or hit.get('id')
                if not cluster_id:
                    continue
                existing = corpus_conn.execute(
                    "SELECT 1 FROM rss_seen WHERE cluster_id=?",
                    (cluster_id,)
                ).fetchone()
                if existing:
                    continue
                case_name  = hit.get('caseName', f'Case {cluster_id}')
                date_filed = (hit.get('dateFiled') or '')[:10]
                court_id   = hit.get('court_id', '')
                abs_url    = hit.get('absolute_url', '')
                url        = f"https://www.courtlistener.com{abs_url}" if abs_url else ''
                corpus_conn.execute("""
                    INSERT OR IGNORE INTO rss_seen
                        (cluster_id, case_name, court, date_filed, url,
                         first_seen, domain_id, processed)
                    VALUES (?,?,?,?,?,?,?,0)
                """, (cluster_id, case_name, court_id, date_filed, url,
                      datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      domain_id))
                corpus_conn.commit()
                new_found  += 1
                domain_new += 1
                log.info(f"  API [{court_id}] D{domain_id} — {case_name[:60]}")

            if len(results) < 20:
                break
            page += 1
            time.sleep(1.0)

        if domain_new:
            log.info(f"  D{domain_id}: {domain_new} new via API")
        time.sleep(0.5)

    return new_found


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='SOoL Daily Corpus Update')
    parser.add_argument('--dry-run',        action='store_true',
                        help='Fetch RSS but do not annotate or upload')
    parser.add_argument('--rss-only',       action='store_true',
                        help='Fetch and store new cases, skip annotation')
    parser.add_argument('--annotate-only',  action='store_true',
                        help='Annotate pending cases only, skip RSS fetch')
    parser.add_argument('--upload-only',    action='store_true',
                        help='Export and upload only, skip fetch/annotate')
    parser.add_argument('--domains',        default=None,
                        help='Comma-separated domain IDs to process (default: all)')
    parser.add_argument('--circuits',       default=None,
                        help='Comma-separated circuits (default: all 13)')
    parser.add_argument('--max-per-run',    type=int, default=50,
                        help='Max new cases to annotate per run (default: 50)')
    args = parser.parse_args()

    # ── ENV ───────────────────────────────────────────────────────────────────
    cl_key       = os.environ.get('SOOL_CL_KEY', '')
    anthropic_key= os.environ.get('SOOL_ANTHROPIC_KEY', '')

    if not cl_key and not args.annotate_only and not args.upload_only:
        log.error("SOOL_CL_KEY not set. Run: source ~/.sool_env")
        sys.exit(1)

    if not anthropic_key and not args.rss_only and not args.upload_only and not args.dry_run:
        log.error("SOOL_ANTHROPIC_KEY not set. Run: source ~/.sool_env")
        sys.exit(1)

    DOMAIN_NAMES = {
        1:'first_amendment', 2:'employment_discrimination',
        3:'administrative_law', 4:'criminal_procedure', 5:'immigration',
        6:'civil_rights_1983', 7:'contract', 8:'family_law',
        9:'habeas_corpus', 10:'patent_ip', 11:'securities_regulation',
    }

    target_domains  = ([int(d) for d in args.domains.split(',')]
                       if args.domains else list(DOMAIN_NAMES.keys()))
    target_circuits = (args.circuits.split(',')
                       if args.circuits else CIRCUITS)

    run_date   = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_found  = 0
    queued     = 0   # cases prepared into domain JSONL for the pipeline
    annotated  = 0   # annotation rows actually written to the DB this run
    errors     = 0

    log.info("="*60)
    log.info(f"SOoL Daily Update — {run_date[:10]}")
    log.info(f"Circuits: {len(target_circuits)}  Domains: {target_domains}")
    log.info("="*60)

    # ── CORPUS DB SETUP ───────────────────────────────────────────────────────
    corpus_conn = get_corpus_conn()
    ensure_rss_table(corpus_conn)

    # ── STEP 1: RSS FETCH ─────────────────────────────────────────────────────
    if not args.annotate_only and not args.upload_only:
        log.info(f"\n── Step 1: Checking RSS feeds ({len(target_circuits)} circuits) ──")

        session = requests.Session()
        session.headers['User-Agent'] = (
            'SOoL-Research-Bot/2.0 (SEAL Lab, Texas A&M; '
            'contact: drkoepsell@tamu.edu; '
            'research corpus for A Structural Ontology of the Law)'
        )

        for circuit in target_circuits:
            entries = fetch_rss_feed(circuit, session)
            for entry in entries:
                cluster_id = extract_cluster_id(entry.get('link', ''))
                if not cluster_id:
                    continue

                # Already seen?
                existing = corpus_conn.execute(
                    "SELECT cluster_id FROM rss_seen WHERE cluster_id=?",
                    (cluster_id,)
                ).fetchone()
                if existing:
                    continue

                case_name  = entry.get('title', f'Case {cluster_id}')
                date_filed = entry.get('date', '')[:10]

                # Auto-classify domain
                domain_id = classify_domain(case_name)
                if domain_id not in target_domains:
                    continue  # not in a domain we track

                corpus_conn.execute("""
                    INSERT OR IGNORE INTO rss_seen
                    (cluster_id, case_name, court, date_filed, url, first_seen,
                     domain_id, processed)
                    VALUES (?,?,?,?,?,?,?,0)
                """, (cluster_id, case_name, circuit, date_filed,
                      entry.get('link',''),
                      datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      domain_id))
                corpus_conn.commit()
                new_found += 1
                log.info(f"  NEW [{circuit}] D{domain_id} — {case_name[:60]}")

            time.sleep(0.5)  # be kind to CourtListener

        log.info(f"Found {new_found} new cases across {len(target_circuits)} circuits")

        # Supplement RSS with direct API queries for recent opinions
        if not args.rss_only:
            meta_row = corpus_conn.execute(
                "SELECT value FROM corpus_meta WHERE key='last_api_fetch'"
            ).fetchone()
            api_date_after  = meta_row[0] if meta_row else '2025-01-01'
            api_date_before = datetime.date.today().isoformat()

            api_new = fetch_recent_via_api(
                corpus_conn, session, cl_key, target_domains,
                api_date_after, api_date_before,
            )
            new_found += api_new

            corpus_conn.execute(
                "INSERT OR REPLACE INTO corpus_meta (key, value) VALUES (?,?)",
                ('last_api_fetch', api_date_before)
            )
            corpus_conn.commit()
            log.info(f"API supplement: {api_new} new cases queued")

    if args.dry_run:
        log.info("Dry run — stopping here")
        pending = corpus_conn.execute(
            "SELECT COUNT(*) FROM rss_seen WHERE processed=0"
        ).fetchone()[0]
        log.info(f"Pending annotation queue: {pending} cases")
        return

    if args.rss_only:
        log.info("RSS-only mode — skipping annotation")
        return

    # ── STEP 2: FETCH TEXTS + ANNOTATE ───────────────────────────────────────
    if not args.upload_only:
        log.info(f"\n── Step 2: Annotating new cases (max {args.max_per_run}) ──")

        annot_conn = get_annot_conn()
        ensure_daily_log_table(annot_conn)

        # Get cases pending annotation
        pending = corpus_conn.execute("""
            SELECT cluster_id, case_name, court, date_filed, url, domain_id
            FROM rss_seen
            WHERE processed = 0
            ORDER BY first_seen ASC
            LIMIT ?
        """, (args.max_per_run,)).fetchall()

        log.info(f"  {len(pending)} cases in annotation queue")

        session = requests.Session()

        for row in pending:
            cluster_id = row['cluster_id']
            case_name  = row['case_name']
            domain_id  = row['domain_id']

            log.info(f"  Annotating: {case_name[:55]}  (D{domain_id})")

            # Check not already annotated
            already = annot_conn.execute(
                "SELECT case_id FROM annotations WHERE case_id=?",
                (cluster_id,)
            ).fetchone()
            if already:
                corpus_conn.execute(
                    "UPDATE rss_seen SET processed=1 WHERE cluster_id=?",
                    (cluster_id,)
                )
                corpus_conn.commit()
                continue

            # Fetch opinion text
            text = fetch_opinion_text(cluster_id, session, cl_key)
            if not text or len(text) < 200:
                log.warning(f"  No text for {cluster_id} — will retry tomorrow")
                errors += 1
                continue

            # Re-classify with full text available
            better_domain = classify_domain(case_name, text)
            if better_domain and better_domain in target_domains:
                domain_id = better_domain
                corpus_conn.execute(
                    "UPDATE rss_seen SET domain_id=? WHERE cluster_id=?",
                    (domain_id, cluster_id)
                )

            # Store in corpus DB for annotation pipeline
            try:
                corpus_conn.execute("""
                    INSERT OR IGNORE INTO cases
                    (id, domain_id, domain_name, case_name, court_id,
                     date_filed, query_matched, status)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (cluster_id, domain_id,
                      DOMAIN_NAMES.get(domain_id,'unknown'),
                      case_name, row['court'], row['date_filed'],
                      f'rss:{row["court"]}:{datetime.date.today()}',
                      'published'))
                corpus_conn.execute("""
                    INSERT OR IGNORE INTO opinions (case_id, plain_text)
                    VALUES (?,?)
                """, (cluster_id, text))
                corpus_conn.commit()
            except Exception as e:
                log.warning(f"  DB insert failed: {e}")
                errors += 1
                continue

            # Run annotation via annotate_pipeline
            try:
                # Write temp JSONL for the pipeline
                tmp = f'/tmp/sool_rss_{cluster_id}.jsonl'
                with open(tmp, 'w') as f:
                    f.write(json.dumps({
                        'id': cluster_id, 'case_name': case_name,
                        'domain_id': domain_id,
                        'domain_name': DOMAIN_NAMES.get(domain_id,'unknown'),
                        'court_id': row['court'],
                        'date_filed': row['date_filed'],
                        'citations': [], 'absolute_url': row['url'],
                        'opinions': [{'plain_text': text}],
                    }) + '\n')

                # Re-export JSONL for this domain so pipeline sees the new case
                domain_name = DOMAIN_NAMES.get(domain_id, 'unknown')
                domain_jsonl = f'{CORPUS_DIR}/domain_{domain_id}_{domain_name}.jsonl'
                Path(CORPUS_DIR).mkdir(exist_ok=True)

                # Append to domain JSONL (pipeline will deduplicate via already_annotated check)
                with open(domain_jsonl, 'a') as f:
                    f.write(json.dumps({
                        'id': cluster_id, 'case_name': case_name,
                        'domain_id': domain_id,
                        'domain_name': domain_name,
                        'court_id': row['court'],
                        'date_filed': row['date_filed'],
                        'citations': [], 'absolute_url': row['url'],
                        'opinions': [{'plain_text': text}],
                    }) + '\n')

                if os.path.exists(tmp):
                    os.unlink(tmp)

            except Exception as e:
                log.error(f"  JSONL prep failed for {cluster_id}: {e}")
                errors += 1
                continue

            # Mark as processed (annotation will happen in next step)
            corpus_conn.execute(
                "UPDATE rss_seen SET processed=1 WHERE cluster_id=?",
                (cluster_id,)
            )
            corpus_conn.commit()
            queued += 1
            time.sleep(1)

        # Cases already in the domain JSONLs but never successfully annotated —
        # e.g. everything queued while the API was returning 404. Without this
        # the pipeline only ever runs on same-day RSS hits, so a backlog that
        # built up during an outage would sit there forever.
        backlog = 0
        try:
            _cc = get_corpus_conn()
            _ac = get_annot_conn()
            backlog = max(0,
                          _cc.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
                          - _ac.execute("SELECT COUNT(*) FROM annotations").fetchone()[0])
            _cc.close(); _ac.close()
        except Exception as e:
            log.warning(f"  Could not measure annotation backlog: {e}")

        if backlog > 0 and queued == 0:
            log.info(f"\n  No new cases, but {backlog:,} case(s) remain "
                     f"unannotated — draining backlog.")

        # Run annotation pipeline on all pending domains
        if queued > 0 or backlog > 0:
            if queued > 0:
                log.info(f"\n  Running annotation pipeline on {queued} new cases...")
            domains_to_annotate = list(set(
                row['domain_id'] for row in pending
                if row['domain_id'] in target_domains
            ))
            # Backlog cases may sit in domains with no RSS hit today, so fall
            # back to sweeping every targeted domain.
            if not domains_to_annotate:
                domains_to_annotate = list(target_domains)
            domain_str = ','.join(str(d) for d in domains_to_annotate)

            def _annot_rowcount():
                """Rows currently in the annotations table (0 if unreadable)."""
                try:
                    c = get_annot_conn()
                    n = c.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
                    c.close()
                    return n
                except Exception as e:
                    log.warning(f"  Could not read annotation count: {e}")
                    return 0

            rows_before = _annot_rowcount()

            # Cap work per domain per run so a large backlog drains over
            # several nights instead of blowing the 1-hour timeout.
            per_domain_cap = int(os.environ.get('SOOL_ANNOTATE_LIMIT', 60))

            result = subprocess.run(
                [sys.executable, 'annotate_pipeline.py',
                 '--domain',  domain_str,
                 '--limit',   str(per_domain_cap)],
                capture_output=False,
                timeout=3600,  # 1 hour max
                env={**os.environ, 'ANTHROPIC_API_KEY': anthropic_key}
            )
            if result.returncode != 0:
                log.error("Annotation pipeline returned non-zero exit code")
                errors += 1

            # Ground the reported figure in rows actually persisted, not in how
            # many cases we handed to the pipeline.
            annotated = max(0, _annot_rowcount() - rows_before)
            if queued > 0 and annotated == 0:
                log.error(f"  Queued {queued} case(s) but wrote 0 annotations — "
                          f"annotation is not working.")
                errors += 1
            elif annotated < queued:
                log.warning(f"  Queued {queued} case(s) but only {annotated} "
                            f"annotation(s) were written.")

            # Fix mixed-perspective errors
            subprocess.run(
                [sys.executable, 'annotate_pipeline.py',
                 '--reannotate-mixed'],
                capture_output=False, timeout=600,
                env={**os.environ, 'ANTHROPIC_API_KEY': anthropic_key}
            )

    # ── STEP 3: EXPORT + UPLOAD ───────────────────────────────────────────────
    log.info("\n── Step 3: Export and upload ──")

    if run_export():
        upload_to_turbify()

    # ── CRIMINAL CORPUS EXPORT + UPLOAD ─────────────────────────────────────
    _crim_ann = Path(__file__).parent / 'sool_criminal_annotations.db'
    _crim_out = Path(__file__).parent / 'sool_criminal_data.json'
    if _crim_ann.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / 'export_criminal.py'),
                 '--ann-db', str(_crim_ann), '--out', str(_crim_out)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                log.info("Criminal corpus exported to sool_criminal_data.json")
                # Upload to Turbify alongside civil corpus
                user = os.environ.get('TURBIFY_FTP_USER','')
                pw   = os.environ.get('TURBIFY_FTP_PASS','')
                host = os.environ.get('TURBIFY_FTP_HOST','')
                if all([user, pw, host]):
                    subprocess.run(
                        ['curl','--retry','3','--silent','--show-error',
                         '--user', f'{user}:{pw}',
                         '-T', str(_crim_out),
                         f'ftp://{host}/sool_criminal_data.json'],
                        capture_output=True, text=True, timeout=120
                    )
                    log.info("Criminal corpus uploaded to Turbify")
            else:
                log.warning(f"Criminal export failed: {result.stderr[:100]}")
        except Exception as _e:
            log.warning(f"Criminal export error: {_e}")
    else:
        log.info("No criminal annotations DB found — skipping criminal export")

    # ── RDF/TTL EXPORT (civil + criminal) ────────────────────────────────────
    _rdf_script = Path(__file__).parent / 'export_rdf.py'
    if _rdf_script.exists():
        try:
            _rdf_result = subprocess.run(
                [sys.executable, str(_rdf_script),
                 '--civil-ann-db',    str(Path(__file__).parent / 'sool_annotations.db'),
                 '--criminal-ann-db', str(Path(__file__).parent / 'sool_criminal_annotations.db'),
                 '--out-dir',         str(Path(__file__).parent)],
                capture_output=True, text=True, timeout=300
            )
            if _rdf_result.returncode == 0:
                log.info("RDF/TTL exported: sool_corpus.ttl + sool_criminal.ttl")
                # Upload TTL files to Turbify
                _user = os.environ.get('TURBIFY_FTP_USER','')
                _pw   = os.environ.get('TURBIFY_FTP_PASS','')
                _host = os.environ.get('TURBIFY_FTP_HOST','')
                if all([_user, _pw, _host]):
                    for _ttl_name in ['sool_bfo_mlc_core.ttl', 'sool_criminal_norms.ttl',
                                  'sool_corpus.ttl', 'sool_criminal.ttl']:
                        _ttl_path = Path(__file__).parent / _ttl_name
                        if _ttl_path.exists():
                            _up = subprocess.run(
                                ['curl','--retry','3','--silent','--show-error',
                                 '--user', f'{_user}:{_pw}',
                                 '-T', str(_ttl_path),
                                 f'ftp://{_host}/{_ttl_name}'],
                                capture_output=True, text=True, timeout=180
                            )
                            if _up.returncode == 0:
                                log.info(f"Uploaded: {_ttl_name}")
                            else:
                                log.warning(f"TTL upload failed ({_ttl_name}): {_up.stderr[:80]}")

                # Run inference engine and upload inferences JSON
                _reason = Path(__file__).parent / 'reason_corpus.py'
                _inf_out = Path(__file__).parent / 'sool_inferences.json'
                if _reason.exists():
                    _ri = subprocess.run(
                        [sys.executable, str(_reason),
                         '--criminal-ann-db',
                         str(Path(__file__).parent / 'sool_criminal_annotations.db'),
                         '--out', str(_inf_out)],
                        capture_output=True, text=True, timeout=300
                    )
                    if _ri.returncode == 0 and _inf_out.exists():
                        log.info("Inference engine complete")
                        if all([_user, _pw, _host]):
                            subprocess.run(
                                ['curl','--retry','2','--silent',
                                 '--user', f'{_user}:{_pw}',
                                 '-T', str(_inf_out),
                                 f'ftp://{_host}/sool_inferences.json'],
                                capture_output=True, text=True, timeout=120
                            )
                            log.info("Uploaded: sool_inferences.json")
            else:
                log.warning(f"RDF export failed: {_rdf_result.stderr[:100]}")
        except Exception as _rdf_e:
            log.warning(f"RDF export error: {_rdf_e}")
    else:
        log.info("export_rdf.py not found — skipping TTL export")

    # ── HTML UPLOAD ───────────────────────────────────────────────────────────
    _html_src  = Path(__file__).parent / 'SOoL_QueryTool.html'
    _html_user = os.environ.get('TURBIFY_FTP_USER', '')
    _html_pw   = os.environ.get('TURBIFY_FTP_PASS', '')
    _html_host = os.environ.get('TURBIFY_FTP_HOST', '')
    if _html_src.exists() and all([_html_user, _html_pw, _html_host]):
        _hu = subprocess.run(
            ['curl', '--retry', '3', '--silent', '--show-error',
             '--user', f'{_html_user}:{_html_pw}',
             '-T', str(_html_src),
             f'ftp://{_html_host}/SOoL_QueryTool.html'],
            capture_output=True, text=True, timeout=120
        )
        if _hu.returncode == 0:
            log.info("Uploaded: SOoL_QueryTool.html")
        else:
            log.error(f"HTML upload FAILED: {_hu.stderr[:200]}")
            errors += 1
    else:
        # A skipped publish is a failure, not a routine info message: the live
        # site silently keeps serving the previous version.
        _missing = []
        if not _html_src.exists():
            _missing.append('SOoL_QueryTool.html missing')
        for _n, _v in (('TURBIFY_FTP_USER', _html_user),
                       ('TURBIFY_FTP_PASS', _html_pw),
                       ('TURBIFY_FTP_HOST', _html_host)):
            if not _v:
                _missing.append(f'{_n} unset')
        log.error("HTML NOT PUBLISHED — live site still serving the previous "
                  f"version. Cause: {'; '.join(_missing)}. "
                  "Run: source ~/.sool_env && python3 daily_update.py --upload-only")
        errors += 1

    # ── STEP 4: LOG SUMMARY ───────────────────────────────────────────────────
    annot_conn = get_annot_conn()
    ensure_daily_log_table(annot_conn)
    total, ratio = compute_stats(annot_conn)

    annot_conn.execute("""
        INSERT INTO daily_update_log
        (run_date, circuits_checked, new_cases_found, annotated,
         corpus_total, cd_ratio, errors)
        VALUES (?,?,?,?,?,?,?)
    """, (run_date, len(target_circuits), new_found,
          annotated, total, ratio, errors))
    annot_conn.commit()

    log.info("\n" + "="*60)
    log.info(f"Daily update complete — {datetime.date.today()}")
    log.info(f"  New cases found:    {new_found}")
    log.info(f"  Queued:             {queued}")
    log.info(f"  Annotated (saved):  {annotated}")
    log.info(f"  Corpus total:       {total:,}")
    log.info(f"  CD ratio:           {ratio}:1")
    log.info(f"  Errors:             {errors}")
    log.info("="*60)


DOMAIN_NAMES = {
    1:'first_amendment', 2:'employment_discrimination',
    3:'administrative_law', 4:'criminal_procedure', 5:'immigration',
    6:'civil_rights_1983', 7:'contract', 8:'family_law',
    9:'habeas_corpus', 10:'patent_ip', 11:'securities_regulation',
}

if __name__ == '__main__':
    main()
