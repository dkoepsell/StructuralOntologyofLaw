"""
collect_scotus.py — SCOTUS Oral Argument + Decision Collector
=============================================================
Uses CourtListener stt_transcript for oral argument text.
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
        logging.FileHandler(Path("logs") / f"scotus_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
log = logging.getLogger(__name__)
Path("logs").mkdir(exist_ok=True)

CL_API     = "https://www.courtlistener.com/api/rest/v4"
RATE_LIMIT = 0.4

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
    collected_at     TEXT,
    dissent_text     TEXT,
    dissent_author   TEXT
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
    # Migrate: add dissent columns to existing DBs (safe if columns already exist)
    for col, typ in [("dissent_text", "TEXT"), ("dissent_author", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE scotus_cases ADD COLUMN {col} {typ}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn

_last = 0.0
def cl_get(url, params=None, key=""):
    global _last
    elapsed = time.time() - _last
    if elapsed < RATE_LIMIT:
        time.sleep(RATE_LIMIT - elapsed)
    _last = time.time()
    return requests.get(url, params=params,
        headers={"Authorization": f"Token {key}",
                 "User-Agent": "SOoL-Research/1.0"},
        timeout=20)

def map_disposition(disposition):
    d = (disposition or "").lower()
    if any(w in d for w in ["reversed", "vacated and remanded", "vacated, reversed"]):
        return "protection_granted", 1, "reversed"
    elif "affirmed" in d:
        return "protection_denied", 0, "affirmed"
    elif "vacated" in d:
        return "partial", None, "vacated"
    elif "dismissed" in d:
        return "dismissed", None, "dismissed"
    return disposition or "unknown", None, disposition or "unknown"

def fetch_decision(docket_num, cl_docket_id, key):
    r = cl_get(f"{CL_API}/clusters/",
               params={"docket": cl_docket_id, "page_size": 5}, key=key)
    results = r.json().get("results", []) if r.status_code == 200 else []
    if not results:
        r2 = cl_get(f"{CL_API}/clusters/",
                    params={"docket__docket_number": docket_num,
                            "docket__court": "scotus", "page_size": 5}, key=key)
        results = r2.json().get("results", []) if r2.status_code == 200 else []
    if not results:
        return {}
    cluster = results[0]
    outcome, petitioner_won, lower = map_disposition(cluster.get("disposition") or "")
    opinion_text   = ""
    dissent_text   = ""
    dissent_author = ""
    sub = cluster.get("sub_opinions") or []
    for item in sub:
        op_url = item if isinstance(item, str) else item.get("resource_uri", "")
        if not op_url:
            continue
        r3 = cl_get(op_url, key=key)
        if r3.status_code != 200:
            continue
        op      = r3.json()
        op_type = op.get("type", "")
        text    = (op.get("plain_text") or op.get("html_with_citations") or "")
        if op_type.startswith("030") and not dissent_text:
            dissent_text   = text[:12000]
            dissent_author = (op.get("author_str") or "").split(",")[0].strip() or None
        elif not opinion_text:
            opinion_text = text[:15000]
    return {
        "cl_cluster_id":      str(cluster.get("id", "")),
        "decision_date":      cluster.get("date_filed", ""),
        "outcome":            outcome,
        "petitioner_won":     petitioner_won,
        "lower_court_decision": lower,
        "issue_area":         cluster.get("scdb_id", ""),
        "decision_text":      opinion_text,
        "dissent_text":       dissent_text or None,
        "dissent_author":     dissent_author or None,
    }

def save_case(conn, c):
    existing = conn.execute(
        "SELECT id FROM scotus_cases WHERE docket=?", (c["docket"],)
    ).fetchone()
    fields = ["case_name","term","argument_date","decision_date",
              "transcript_text","transcript_chars","cl_audio_id",
              "cl_cluster_id","cl_docket_id","decision_text",
              "outcome","petitioner_won","lower_court_decision",
              "issue_area","collected_at","dissent_text","dissent_author"]
    if existing:
        sets = ", ".join(f"{f}=COALESCE(?,{f})" for f in fields)
        conn.execute(f"UPDATE scotus_cases SET {sets} WHERE docket=?",
                     [c.get(f) for f in fields] + [c["docket"]])
    else:
        all_f = ["docket"] + fields
        conn.execute(f"INSERT INTO scotus_cases ({','.join(all_f)}) VALUES ({','.join(['?']*len(all_f))})",
                     [c.get(f) for f in all_f])
    conn.commit()

def collect_term(term, conn, key, limit=0):
    log.info(f"=== Collecting term {term} ===")
    after  = f"{term}-09-01"
    before = f"{term+1}-08-31"
    params = {"docket__court__id": "scotus", "order_by": "date_argued", "page_size": 20}
    fetched = 0
    url = f"{CL_API}/audio/"
    while url:
        r = cl_get(url, params=params if "?" not in url else None, key=key)
        if r.status_code != 200:
            log.warning(f"Audio {r.status_code}")
            break
        data = r.json()
        for a in data.get("results", []):
            stt = a.get("stt_transcript") or ""
            if len(stt) < 1000:
                continue
            # Filter by date range in Python — skip if no date
            arg_date = a.get("date_argued") or ""
            if not arg_date:
                continue
            if arg_date < after or arg_date > before:
                continue
            dr = cl_get(a.get("docket", ""), key=key)
            if dr.status_code != 200:
                continue
            d = dr.json()
            docket_num = (d.get("docket_number") or "").strip()
            if not docket_num:
                continue
            existing = conn.execute(
                "SELECT id, outcome FROM scotus_cases WHERE docket=?", (docket_num,)
            ).fetchone()
            if existing and existing["outcome"] and existing["outcome"] not in ("unknown", ""):
                fetched += 1
                if limit and fetched >= limit:
                    return fetched
                continue
            case = {
                "docket": docket_num, "case_name": a.get("case_name", ""),
                "term": term, "argument_date": str(d.get("date_argued", "")),
                "transcript_text": stt, "transcript_chars": len(stt),
                "cl_audio_id": str(a.get("id", "")),
                "cl_docket_id": str(d.get("id", "")),
                "collected_at": datetime.utcnow().isoformat(),
            }
            dec = fetch_decision(docket_num, str(d.get("id", "")), key)
            case.update(dec)
            log.info(f"  {docket_num:12s} | {case['case_name'][:40]:40s} | outcome={case.get('outcome','?'):20s} | {len(stt):,} chars")
            save_case(conn, case)
            fetched += 1
            if limit and fetched >= limit:
                return fetched
        url = data.get("next")
        params = None
    log.info(f"Term {term}: {fetched} cases")
    return fetched

def show_status(conn):
    t  = conn.execute("SELECT COUNT(*) FROM scotus_cases").fetchone()[0]
    wt = conn.execute("SELECT COUNT(*) FROM scotus_cases WHERE transcript_chars > 1000").fetchone()[0]
    wo = conn.execute("SELECT COUNT(*) FROM scotus_cases WHERE outcome NOT IN ('unknown','') AND outcome IS NOT NULL").fetchone()[0]
    wa = conn.execute("SELECT COUNT(*) FROM scotus_annotations").fetchone()[0]
    wc = conn.execute("SELECT COUNT(*) FROM scotus_annotations WHERE prediction_correct=1").fetchone()[0]
    ww = conn.execute("SELECT COUNT(*) FROM scotus_annotations WHERE prediction_correct=0").fetchone()[0]
    print(f"\nSCOTUS DB: {t} cases | {wt} with transcript | {wo} with outcome | {wa} annotated")
    if wc + ww > 0:
        print(f"Accuracy: {wc}/{wc+ww} ({wc/(wc+ww)*100:.1f}%)")
    for row in conn.execute("SELECT term, COUNT(*) n FROM scotus_cases GROUP BY term ORDER BY term"):
        print(f"  Term {row['term']}: {row['n']}")
    for row in conn.execute("SELECT outcome, COUNT(*) n FROM scotus_cases WHERE outcome IS NOT NULL GROUP BY outcome ORDER BY n DESC"):
        print(f"  {(row['outcome'] or 'NULL'):30s}: {row['n']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms",  nargs="+", type=int)
    parser.add_argument("--docket", type=str)
    parser.add_argument("--limit",  type=int, default=0)
    parser.add_argument("--db",     default="scotus_backtest.db")
    parser.add_argument("--cl-key", default=None)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    key  = args.cl_key or os.environ.get("SOOL_CL_KEY", "")
    conn = get_db(args.db)

    if args.status:
        show_status(conn); sys.exit(0)

    if args.docket:
        r = cl_get(f"{CL_API}/audio/",
                   params={"docket__docket_number": args.docket,
                           "docket__court__id": "scotus", "page_size": 3}, key=key)
        if r.status_code == 200 and r.json().get("results"):
            a  = r.json()["results"][0]
            dr = cl_get(a.get("docket", ""), key=key)
            d  = dr.json() if dr.status_code == 200 else {}
            dn = (d.get("docket_number") or args.docket).strip()
            case = {"docket": dn, "case_name": a.get("case_name",""),
                    "transcript_text": a.get("stt_transcript",""),
                    "transcript_chars": len(a.get("stt_transcript") or ""),
                    "cl_audio_id": str(a.get("id","")),
                    "cl_docket_id": str(d.get("id","")),
                    "argument_date": str(d.get("date_argued","")),
                    "collected_at": datetime.utcnow().isoformat()}
            case.update(fetch_decision(dn, str(d.get("id","")), key))
            save_case(conn, case)
            log.info(f"Collected {dn}: {case['transcript_chars']:,} chars, outcome={case.get('outcome','?')}")
        show_status(conn); sys.exit(0)

    if args.terms:
        for term in args.terms:
            collect_term(term, conn, key, limit=args.limit)
        show_status(conn)
    else:
        parser.print_help()
