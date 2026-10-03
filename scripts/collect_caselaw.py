#!/usr/bin/env python3
"""
SOoL Precedent Mapping — Caselaw Collection Pipeline
=====================================================
SEAL Lab, Texas A&M University
David R. Koepsell, A Structural Ontology of the Law (Palgrave, forthcoming)

Collects a scientifically stratified corpus of federal appellate opinions
from CourtListener for MLC structural validation.

Usage:
    python collect_caselaw.py --api-key YOUR_KEY [--domain all|1|2|...|8]
                              [--limit 500] [--output ./corpus]

Requirements:
    pip install requests tqdm

CourtListener API key: https://www.courtlistener.com/sign-in/ (free account)
"""

import os
import sys
import time
import json
import sqlite3
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

# ─────────────────────────────────────────────────────────────────────────────
# CORPUS DESIGN — 8 DOMAINS × 500 CASES = 4,000 TARGET
# Each domain maps to expected primary MLC failure modes.
# Queries are additive: each string in 'queries' is run independently,
# results are deduplicated by opinion_id before storage.
# ─────────────────────────────────────────────────────────────────────────────

DOMAINS = {
    1: {
        "name": "First Amendment / Public Employee Speech",
        "short": "first_amendment",
        "primary_failures": ["Role Contradiction N.3", "Norm Indeterminacy N.2",
                             "Jurisdictional Contradiction N.2->6"],
        "target": 625,
        "queries": [
            "official duties first amendment public employee retaliation",
            "Garcetti Ceballos official speech first amendment",
            "Pickering balance public employee speech interest",
            "Connick Myers matters of public concern employee speech",
            "academic freedom first amendment professor classroom university",
            "government employee first amendment protected speech discipline",
            "compelled speech viewpoint discrimination public employee",
            "whistleblower retaliation first amendment government worker",
            "first amendment retaliation adverse action state employee",
            "public school teacher first amendment termination speech",
            "police officer first amendment speech retaliation termination",
            "firefighter municipal employee first amendment protected speech",
            "university professor tenure first amendment speech",
            "Lane v. Franks first amendment official duty testimony",
            "nurse doctor public hospital first amendment speech discipline",
            "social worker state employee first amendment reporting",
            "school principal first amendment speech discipline",
            "first amendment retaliation causation protected speech government",
            "public defender attorney first amendment employer retaliation",
        ],
    },
    2: {
        "name": "Employment Discrimination (Title VII)",
        "short": "employment_discrimination",
        "primary_failures": ["Recognition Failure N.6/7",
                             "Correlativity Contradiction N.7",
                             "Conferral Failure N.1->3"],
        "target": 625,
        "queries": [
            "title VII discrimination disparate treatment adverse employment action",
            "hostile work environment harassment protected class title VII",
            "retaliation title VII protected activity opposition",
            "section 1981 race discrimination employment contract",
            "McDonnell Douglas burden shifting pretext discrimination",
            "ADEA age discrimination employment act disparate treatment",
            "pregnancy discrimination act PDA title VII leave",
            "disparate impact title VII neutral policy workforce",
            "constructive discharge hostile environment title VII",
            "sex discrimination title VII gender pay wage gap",
            "national origin discrimination title VII workplace",
            "religious discrimination title VII accommodation failure",
            "disability discrimination ADA reasonable accommodation employment",
            "race discrimination promotion demotion title VII",
            "mixed motive discrimination title VII motivating factor",
            "cat paw discrimination subordinate bias employer",
            "supervisor harassment tangible employment action title VII",
            "same-sex harassment title VII workplace",
            "FMLA interference retaliation employer leave",
            "after-acquired evidence wrongful discharge title VII",
        ],
    },
    3: {
        "name": "Administrative Law / Agency Action",
        "short": "administrative_law",
        "primary_failures": ["Authority Inflation N.1->2",
                             "Procedural Contradiction N.2->5",
                             "Conferral Failure N.1->3"],
        "target": 625,
        "queries": [
            "arbitrary capricious agency action APA administrative review",
            "Chevron deference agency statutory interpretation step two",
            "ultra vires agency rulemaking exceeds statutory authority",
            "major questions doctrine agency regulatory power Congress",
            "notice and comment rulemaking APA procedural requirements",
            "agency final rule arbitrary capricious reviewable APA",
            "Skidmore deference Auer agency regulation interpretation",
            "nondelegation doctrine intelligible principle Congress agency",
            "administrative exhaustion agency final order review court",
            "Loper Bright Chevron overruled agency deference 2024",
            "SEC enforcement action administrative law judge APA",
            "EPA regulatory authority Clean Air Act rulemaking review",
            "NLRB unfair labor practice administrative review",
            "FDA agency action denial APA arbitrary capricious",
            "agency enforcement discretion judicial review APA",
            "FCC agency rulemaking arbitrary capricious review",
            "OSHA workplace safety rule arbitrary capricious review",
            "social security disability ALJ credibility substantial evidence",
            "agency statutory interpretation plain meaning Chevron step one",
            "standing administrative review APA final agency action",
        ],
    },
    4: {
        "name": "Criminal Procedure (4th/5th Amendment)",
        "short": "criminal_procedure",
        "primary_failures": ["Fact Manipulation N.4",
                             "Conferral Failure N.1->3",
                             "Procedural Contradiction N.2->5"],
        "target": 625,
        "queries": [
            "fourth amendment suppression motion warrant probable cause",
            "fruit poisonous tree exclusionary rule suppression",
            "Franks hearing false affidavit warrant probable cause",
            "Terry stop investigatory detention reasonable suspicion",
            "fifth amendment Miranda warning custodial interrogation",
            "good faith exception exclusionary rule Leon warrant",
            "warrantless search exigent circumstances emergency exception",
            "attenuation doctrine inevitable discovery independent source",
            "search and seizure consent voluntary fourth amendment",
            "automobile exception search vehicle fourth amendment",
            "GPS tracking electronic surveillance fourth amendment Carpenter",
            "plain view doctrine seizure fourth amendment",
            "knock and announce fourth amendment search warrant",
            "cell phone search warrant fourth amendment Riley",
            "protective sweep fourth amendment search home",
            "Brady violation prosecutorial disclosure exculpatory evidence",
            "plea guilty involuntary fifth amendment due process",
            "double jeopardy fifth amendment retrial prosecution",
            "Sixth amendment right to counsel interrogation denial",
            "grand jury indictment fifth amendment due process",
        ],
    },
    5: {
        "name": "Immigration / Status Recognition",
        "short": "immigration",
        "primary_failures": ["Recognition Collapse N.6->8",
                             "Jurisdictional Contradiction N.2->6",
                             "Recognition Failure N.6/7"],
        "target": 625,
        "queries": [
            "removal order asylum withholding of removal immigration",
            "INA immigration nationality act adjustment of status",
            "convention against torture withholding removal CAT claim",
            "lawful permanent resident LPR deportation removal order",
            "immigration judge adverse credibility asylum applicant",
            "cancellation of removal continuous physical presence",
            "expedited removal due process immigration proceedings",
            "Zadvydas indefinite detention post-removal immigration",
            "board of immigration appeals BIA removal proceedings",
            "refugee asylum well-founded fear persecution immigration",
            "particular social group asylum persecution immigration court",
            "political opinion asylum nexus persecution immigration",
            "voluntary departure order immigration removal proceedings",
            "DACA deferred action immigration enforcement challenge",
            "immigration detention bond hearing due process",
            "naturalization denial citizenship immigration requirements",
            "aggravated felony immigration removal consequence",
            "immigration court jurisdiction due process notice hearing",
            "temporary protected status TPS removal challenge",
            "asylum one year bar filing deadline exception",
        ],
    },
    6: {
        "name": "Civil Rights (1983) / Qualified Immunity",
        "short": "civil_rights_1983",
        "primary_failures": ["Correlativity Contradiction N.7",
                             "Repair Failure N.8",
                             "Conferral Failure N.1->3"],
        "target": 625,
        "queries": [
            "section 1983 civil rights constitutional deprivation color of law",
            "qualified immunity clearly established constitutional right",
            "Monell municipal liability policy custom section 1983",
            "excessive force objective reasonableness fourth amendment section 1983",
            "deliberate indifference serious medical need eighth amendment",
            "due process liberty interest deprivation fourteenth amendment",
            "color of state law state actor section 1983",
            "supervisory liability section 1983 personal involvement",
            "failure to train deliberate indifference municipal policy",
            "police excessive force shooting section 1983 qualified immunity",
            "pretrial detainee conditions confinement fourteenth amendment",
            "prison conditions Eighth Amendment deliberate indifference",
            "false arrest section 1983 Fourth Amendment",
            "malicious prosecution section 1983 Fourth Amendment",
            "substantive due process state-created danger section 1983",
            "equal protection class of one section 1983",
            "strip search Fourth Amendment section 1983 jail",
            "wrongful conviction section 1983 Brady fabrication evidence",
            "absolute immunity prosecutorial judicial section 1983",
            "taser excessive force Fourth Amendment section 1983",
        ],
    },
    7: {
        "name": "Contract / Commercial Obligation",
        "short": "contract",
        "primary_failures": ["Temporal Contradiction N.2<>4",
                             "Correlativity Contradiction N.7",
                             "Repair Failure N.8"],
        "target": 625,
        "queries": [
            "breach of contract damages expectation reliance benefit of bargain",
            "promissory estoppel detrimental reliance promise enforcement",
            "frustration purpose commercial impracticability impossibility",
            "anticipatory repudiation breach contract before performance due",
            "specific performance equitable remedy breach contract",
            "implied covenant good faith fair dealing breach obligation",
            "condition precedent failure excuse performance contract",
            "statute of frauds written contract enforceability",
            "offer acceptance consideration contract formation",
            "liquidated damages penalty clause contract breach remedy",
            "arbitration clause enforcement contract FAA",
            "unconscionability contract defense enforcement",
            "insurance coverage bad faith breach contract",
            "employment contract wrongful termination at-will",
            "non-compete agreement enforcement restraint of trade",
            "commercial lease breach landlord tenant remedy",
            "UCC warranty breach sale goods commercial",
            "contract interpretation ambiguity parol evidence rule",
            "unjust enrichment quasi-contract restitution remedy",
            "settlement agreement enforcement breach contract terms",
        ],
    },
    8: {
        "name": "Family Law / Parental Rights",
        "short": "family_law",
        "primary_failures": ["Jurisdictional Contradiction N.2->6",
                             "Recognition Failure N.6/7",
                             "Correlativity Contradiction N.7"],
        "target": 625,
        "queries": [
            "termination parental rights due process constitutional",
            "parental rights custody fourteenth amendment liberty interest",
            "ICWA Indian Child Welfare Act parental rights tribe",
            "Troxel grandparent visitation parental rights constitution",
            "Santosky clear convincing evidence parental termination",
            "foster care placement parental rights reunification",
            "adoption consent biological parent parental rights involuntary",
            "child welfare removal parental rights substantive due process",
            "parental liberty interest childrearing Meyer Pierce",
            "involuntary termination parental rights state intervention",
            "UCCJEA jurisdiction custody interstate parental",
            "Stanley v. Illinois unwed father parental rights",
            "grandparent visitation constitutional parental rights",
            "putative father parental rights biological paternity",
            "parental fitness standard termination constitutional",
            "dependency proceeding parental rights due process",
            "foster parent adoption parental rights biological parent",
            "parental rights disability ADA discrimination child welfare",
            "emergency removal parental rights due process notice",
            "parental rights incarcerated parent termination",
        ],
    },
    9: {
        "name": "Habeas Corpus / Post-Conviction Relief",
        "short": "habeas_corpus",
        "primary_failures": ["Repair Failure N.8",
                             "Procedural Contradiction N.2->5",
                             "Recognition Failure N.6/7"],
        "target": 600,
        "queries": [
            "habeas corpus 2254 ineffective assistance counsel Strickland",
            "habeas corpus AEDPA unreasonable application clearly established",
            "actual innocence gateway habeas corpus procedural default",
            "Brady violation habeas corpus post-conviction suppression",
            "habeas corpus exhaustion procedural default state court",
            "habeas corpus second successive petition abuse writ",
            "coerced confession due process habeas corpus",
            "habeas corpus jury instruction constitutional error",
            "Batson challenge habeas corpus racial jury selection",
            "habeas corpus prosecutorial misconduct closing argument",
            "Napue false testimony habeas corpus due process",
            "habeas corpus cumulative error constitutional prejudice",
            "section 2241 federal prisoner habeas corpus conditions",
            "habeas corpus sentence enhancement constitutional challenge",
            "Martinez v. Ryan habeas corpus ineffective post-conviction counsel",
            "habeas corpus confrontation clause Crawford testimonial",
            "Apprendi Blakely habeas corpus sentence beyond maximum",
            "habeas corpus retroactivity Teague new constitutional rule",
            "habeas corpus mental retardation Atkins execution",
            "federal habeas corpus state evidentiary hearing 2254(e)",
        ],
    },
    10: {
        "name": "Patent / Intellectual Property",
        "short": "patent_ip",
        "primary_failures": ["Norm Indeterminacy N.2",
                             "Jurisdictional Contradiction N.2->6",
                             "Correlativity Contradiction N.7"],
        "target": 400,
        "queries": [
            "patent infringement claim construction Markman Philips",
            "patent invalidity anticipation obviousness prior art",
            "patent eligibility abstract idea Alice Mayo section 101",
            "patent willful infringement enhanced damages Halo",
            "patent prosecution history estoppel doctrine equivalents",
            "copyright infringement substantial similarity fair use",
            "trademark likelihood confusion Lanham Act infringement",
            "trade secret misappropriation inevitable disclosure DTSA",
            "patent enablement written description section 112",
            "patent inequitable conduct prosecution unenforceability",
            "copyright fair use transformative purpose market harm",
            "patent obviousness Graham factors secondary considerations",
            "inter partes review IPR patent validity challenge PTAB",
            "copyright DMCA safe harbor takedown notice",
            "patent exhaustion first sale doctrine Quanta",
            "trademark dilution famous mark Lanham Act",
            "copyright registration deposit requirement infringement",
            "patent joint inventorship conception reduction practice",
            "design patent ornamental appearance infringement",
            "patent damages reasonable royalty lost profits Georgia-Pacific",
        ],
    },
    11: {
        "name": "Securities Regulation / Financial Fraud",
        "short": "securities_regulation",
        "primary_failures": ["Authority Inflation N.1->2",
                             "Norm Indeterminacy N.2",
                             "Fact Manipulation N.4"],
        "target": 600,
        "queries": [
            "securities fraud rule 10b-5 material misrepresentation reliance",
            "SEC enforcement insider trading section 10b material nonpublic",
            "securities class action PSLRA pleading scienter fraud",
            "Janus Capital misstatement maker securities fraud liability",
            "Halliburton fraud on market presumption reliance securities",
            "securities fraud loss causation economic loss rule",
            "Dodd-Frank whistleblower SEC anti-retaliation protection",
            "investment advisor fiduciary duty breach securities",
            "securities broker dealer FINRA arbitration fraud claim",
            "Ponzi scheme securities fraud disgorgement SEC enforcement",
            "initial public offering IPO securities registration fraud",
            "securities short selling manipulation market fraud",
            "investment contract Howey test securities definition",
            "securities offering exemption Regulation D private placement",
            "accounting fraud securities misstatement restatement",
            "SEC disgorgement Liu civil penalty enforcement",
            "securities tender offer disclosure Williams Act",
            "mutual fund excessive fees investment adviser 36(b)",
            "cryptocurrency token securities regulation Howey digital asset",
            "securities fraud scheme liability primary secondary aiding",
        ],
    },
}


# Federal circuit courts of appeals (CourtListener court IDs)
TARGET_COURTS = [
    "ca1", "ca2", "ca3", "ca4", "ca5", "ca6",
    "ca7", "ca8", "ca9", "ca10", "ca11", "cadc",
    "scotus",  # Supreme Court
]

DATE_RANGE = ("1990-01-01", "2024-12-31")

API_BASE   = "https://www.courtlistener.com/api/rest/v4"
RATE_LIMIT = 2.0   # seconds between requests — CourtListener free tier is ~100 req/min sustained; 2s is safe
MAX_RETRIES = 4

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS corpus_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS cases (
    id                  INTEGER PRIMARY KEY,  -- CourtListener cluster ID
    domain_id           INTEGER NOT NULL,
    domain_name         TEXT NOT NULL,
    case_name           TEXT,
    docket_number       TEXT,
    court_id            TEXT,
    date_filed          TEXT,
    date_argued         TEXT,
    citations           TEXT,  -- JSON array
    westlaw_cite        TEXT,
    lexis_cite          TEXT,
    url                 TEXT,
    cluster_url         TEXT,
    absolute_url        TEXT,
    status              TEXT,  -- Published/Unpublished/etc
    collected_at        TEXT,
    query_matched       TEXT,  -- which query found this case
    UNIQUE(id, domain_id)
);

CREATE TABLE IF NOT EXISTS opinions (
    id              INTEGER PRIMARY KEY,  -- CourtListener opinion ID
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    opinion_type    TEXT,   -- 010lead, 020concurrence, 030dissent, etc.
    author          TEXT,
    per_curiam      INTEGER,
    plain_text      TEXT,   -- full text (may be empty if only HTML available)
    html_text       TEXT,   -- HTML version
    word_count      INTEGER,
    char_count      INTEGER,
    collected_at    TEXT
);

CREATE TABLE IF NOT EXISTS citations (
    citing_case_id   INTEGER REFERENCES cases(id),
    cited_case_id    INTEGER,  -- CourtListener cluster ID (may not be in corpus)
    cited_case_name  TEXT,
    PRIMARY KEY (citing_case_id, cited_case_id)
);

CREATE TABLE IF NOT EXISTS collection_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id   INTEGER,
    query       TEXT,
    page        INTEGER,
    count       INTEGER,
    timestamp   TEXT
);

CREATE INDEX IF NOT EXISTS idx_cases_domain    ON cases(domain_id);
CREATE INDEX IF NOT EXISTS idx_cases_court     ON cases(court_id);
CREATE INDEX IF NOT EXISTS idx_cases_date      ON cases(date_filed);
CREATE INDEX IF NOT EXISTS idx_opinions_case   ON opinions(case_id);
"""

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("collection.log", mode="a"),
    ],
)
log = logging.getLogger("collect")

# ─────────────────────────────────────────────────────────────────────────────
# API CLIENT
# ─────────────────────────────────────────────────────────────────────────────

class CourtListenerClient:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {api_key}",
            "User-Agent": "SOoL-CorpusCollector/1.0 (SEAL Lab, Texas A&M; legal ontology research)",
        })
        self._last_request = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        self._last_request = time.time()

    def get(self, url: str, params: dict = None, retries: int = MAX_RETRIES):
        self._throttle()
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=30)
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", 60))
                    log.warning(f"Rate limited — waiting {wait}s")
                    time.sleep(wait)
                    continue
                if r.status_code == 503:
                    wait = 2 ** (attempt + 2)
                    log.warning(f"503 — retry in {wait}s (attempt {attempt+1})")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                if attempt == retries - 1:
                    log.error(f"Request failed after {retries} attempts: {e}")
                    return None
                wait = 2 ** (attempt + 1)
                log.warning(f"Request error ({e}) — retry in {wait}s")
                time.sleep(wait)
        return None

    def search_opinions(self, query: str, courts: list, date_after: str,
                        date_before: str, page: int = 1):
        """Search opinions endpoint — returns cluster-level results."""
        params = {
            "q":            query,
            "type":         "o",          # opinions
            "court":        " ".join(courts),
            "filed_after":  date_after,
            "filed_before": date_before,
            "order_by":     "score desc",
            "page":         page,
            "page_size":    20,
        }
        return self.get(f"{API_BASE}/search/", params=params)

    def browse_clusters(self, court: str, date_after: str,
                        date_before: str, page: int = 1):
        """Browse opinions by court + date range via the search endpoint.
        Uses 'v.' as a catch-all query — matches virtually every case name.
        The /clusters/ REST endpoint does not accept court+date filters;
        the search endpoint does."""
        params = {
            "q":           "v.",
            "type":        "o",
            "court":       court,
            "filed_after": date_after,
            "filed_before":date_before,
            "order_by":    "dateFiled asc",
            "page":        page,
            "page_size":   20,
        }
        return self.get(f"{API_BASE}/search/", params=params)

    def get_cluster(self, cluster_id: int):
        """Fetch full cluster (case) metadata including citations."""
        return self.get(f"{API_BASE}/clusters/{cluster_id}/")

    def get_opinion(self, opinion_id: int):
        """Fetch a single opinion with full text."""
        return self.get(f"{API_BASE}/opinions/{opinion_id}/")

    def get_opinions_for_cluster(self, cluster_id: int):
        """Fetch all opinions belonging to a cluster."""
        return self.get(f"{API_BASE}/opinions/",
                        params={"cluster": cluster_id, "page_size": 10})

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def _first_citation(citation_field) -> str:
    """Extract first citation string regardless of whether field is
    a list of strings, list of dicts, or a bare string."""
    if not citation_field:
        return ""
    if isinstance(citation_field, str):
        return citation_field
    if isinstance(citation_field, list) and citation_field:
        first = citation_field[0]
        if isinstance(first, dict):
            return first.get("cite", first.get("citation", str(first)))
        return str(first)
    return ""


class CorpusDB:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def case_exists(self, case_id: int, domain_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM cases WHERE id=? AND domain_id=?",
            (case_id, domain_id)
        ).fetchone()
        return row is not None

    def insert_case(self, domain_id: int, cluster: dict, query: str):
        now = datetime.now(timezone.utc).isoformat()
        citations_raw = cluster.get("citations", [])
        citations_json = json.dumps([c.get("cite", c) if isinstance(c, dict)
                                     else c for c in citations_raw])
        self.conn.execute("""
            INSERT OR IGNORE INTO cases
              (id, domain_id, domain_name, case_name, docket_number, court_id,
               date_filed, date_argued, citations, westlaw_cite, lexis_cite,
               url, cluster_url, absolute_url, status, collected_at, query_matched)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            cluster["id"],
            domain_id,
            DOMAINS[domain_id]["name"],
            cluster.get("case_name") or cluster.get("caseName", ""),
            cluster.get("docket_number", ""),
            cluster.get("court_id") or cluster.get("court", ""),
            cluster.get("date_filed") or cluster.get("dateFiled", ""),
            cluster.get("date_argued", ""),
            citations_json,
            _first_citation(cluster.get("citation")),
            "",
            f"https://www.courtlistener.com{cluster.get('absolute_url', '')}",
            f"{API_BASE}/clusters/{cluster['id']}/",
            cluster.get("absolute_url", ""),
            cluster.get("precedential_status", ""),
            now,
            query,
        ))
        self.conn.commit()

    def insert_opinion(self, case_id: int, opinion: dict):
        now = datetime.now(timezone.utc).isoformat()
        plain = opinion.get("plain_text", "") or ""
        html  = opinion.get("html_with_citations", "") or opinion.get("html", "") or ""
        author_info = opinion.get("author", "") or ""
        if isinstance(author_info, dict):
            author_info = author_info.get("name_full", str(author_info))
        self.conn.execute("""
            INSERT OR IGNORE INTO opinions
              (id, case_id, opinion_type, author, per_curiam,
               plain_text, html_text, word_count, char_count, collected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            opinion["id"],
            case_id,
            opinion.get("type", ""),
            author_info,
            1 if opinion.get("per_curiam") else 0,
            plain,
            html,
            len(plain.split()) if plain else 0,
            len(plain) if plain else 0,
            now,
        ))
        self.conn.commit()

    def log_page(self, domain_id: int, query: str, page: int, count: int):
        self.conn.execute("""
            INSERT INTO collection_log (domain_id, query, page, count, timestamp)
            VALUES (?,?,?,?,?)
        """, (domain_id, query, page, count, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def count_cases(self, domain_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM cases WHERE domain_id=?", (domain_id,)
        ).fetchone()
        return row[0] if row else 0

    def already_collected_pages(self, domain_id: int, query: str) -> set:
        rows = self.conn.execute(
            "SELECT page FROM collection_log WHERE domain_id=? AND query=?",
            (domain_id, query)
        ).fetchall()
        return {r[0] for r in rows}

    def get_cases_without_opinions(self, domain_id: int, limit: int = 200):
        return self.conn.execute("""
            SELECT c.id FROM cases c
            WHERE c.domain_id = ?
              AND NOT EXISTS (SELECT 1 FROM opinions o WHERE o.case_id = c.id)
            LIMIT ?
        """, (domain_id, limit)).fetchall()

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO corpus_meta (key,value) VALUES (?,?)",
            (key, value))
        self.conn.commit()

    def get_meta(self, key: str) -> str:
        row = self.conn.execute(
            "SELECT value FROM corpus_meta WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def export_jsonl(self, domain_id: int, output_path: str):
        """Export a domain's cases+opinions as JSONL for annotation pipeline."""
        cases = self.conn.execute("""
            SELECT c.*, GROUP_CONCAT(o.id) as opinion_ids
            FROM cases c
            LEFT JOIN opinions o ON o.case_id = c.id
            WHERE c.domain_id = ?
            GROUP BY c.id
        """, (domain_id,)).fetchall()

        with open(output_path, "w", encoding="utf-8") as f:
            for case in cases:
                row = dict(case)
                opinion_ids = row.pop("opinion_ids", "") or ""
                opinions = []
                for oid in (opinion_ids.split(",") if opinion_ids else []):
                    op = self.conn.execute(
                        "SELECT * FROM opinions WHERE id=?", (oid,)
                    ).fetchone()
                    if op:
                        opinions.append(dict(op))
                row["opinions"] = opinions
                row["citations"] = json.loads(row.get("citations") or "[]")
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        log.info(f"Exported {len(cases)} cases to {output_path}")

# ─────────────────────────────────────────────────────────────────────────────
# COLLECTION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def collect_domain(client: CourtListenerClient, db: CorpusDB,
                   domain_id: int, target: int = None):
    """
    Collect up to `target` cases for a domain by running all its queries
    against the CourtListener search API, paginating until target reached
    or results exhausted.
    """
    domain   = DOMAINS[domain_id]
    target   = target or domain["target"]
    existing = db.count_cases(domain_id)

    log.info(f"\n{'='*60}")
    log.info(f"Domain {domain_id}: {domain['name']}")
    log.info(f"Target: {target}  |  Already collected: {existing}")
    log.info(f"Expected primary failures: {', '.join(domain['primary_failures'])}")

    if existing >= target:
        log.info(f"Domain {domain_id} already at target — skipping.")
        return

    courts_str = TARGET_COURTS
    date_after, date_before = DATE_RANGE

    for query in domain["queries"]:
        current = db.count_cases(domain_id)
        if current >= target:
            log.info(f"Reached target {target} — stopping.")
            break

        log.info(f"\n  Query: '{query}'")
        already_done = db.already_collected_pages(domain_id, query)
        page = 1
        no_new_streak = 0      # consecutive pages with zero new cases
        MAX_STREAK    = 3      # stop query after this many empty pages
        MAX_PAGES     = 50     # hard cap per query — CourtListener relevance
                               # drops sharply after ~page 10; beyond 50 is noise

        with tqdm(desc=f"  D{domain_id} '{query[:40]}'", unit="pg",
                  leave=False) as pbar:
            while True:
                current = db.count_cases(domain_id)
                if current >= target:
                    break

                if page > MAX_PAGES:
                    log.info(f"    Hit page cap ({MAX_PAGES}) — moving to next query.")
                    break

                if no_new_streak >= MAX_STREAK:
                    log.info(f"    {MAX_STREAK} consecutive pages with no new cases — "
                             f"moving to next query.")
                    break

                if page in already_done:
                    page += 1
                    pbar.update(1)
                    continue

                result = client.search_opinions(
                    query, courts_str, date_after, date_before, page)

                if result is None:
                    log.warning(f"    Page {page}: null result — stopping query.")
                    break

                hits        = result.get("results", [])
                total_count = result.get("count", 0)

                # CourtListener reports total hits — if fewer than page*20
                # there are no more real results even if API keeps responding
                if total_count and page * 20 > total_count + 20:
                    log.info(f"    Exhausted {total_count} total results at page {page}.")
                    break

                if not hits:
                    break

                new_on_page = 0
                for hit in hits:
                    cluster_id = hit.get("cluster_id") or hit.get("id")
                    if cluster_id is None:
                        continue

                    if db.case_exists(cluster_id, domain_id):
                        continue

                    db.insert_case(domain_id, {
                        "id":                cluster_id,
                        "case_name":         hit.get("caseName", ""),
                        "court_id":          hit.get("court_id", ""),
                        "date_filed":        hit.get("dateFiled", ""),
                        "absolute_url":      hit.get("absolute_url", ""),
                        "precedential_status": hit.get("status", ""),
                        "citation":          hit.get("citation", []),
                    }, query)
                    new_on_page += 1

                if new_on_page == 0:
                    no_new_streak += 1
                else:
                    no_new_streak = 0   # reset streak on any new case

                db.log_page(domain_id, query, page, new_on_page)
                pbar.update(1)
                pbar.set_postfix({"total": db.count_cases(domain_id),
                                  "page": page,
                                  "new": new_on_page})

                log.debug(f"    Page {page}: {new_on_page} new / {len(hits)} hits "
                          f"(corpus total: {db.count_cases(domain_id)})")

                if len(hits) < 20:
                    break  # last page

                page += 1

    final = db.count_cases(domain_id)
    log.info(f"  Domain {domain_id} collection complete: {final} cases")


# Domain → courts most likely to have those cases
DOMAIN_COURTS = {
    1: ["ca1","ca4","ca6","ca7","ca9","ca10","ca11","cadc","scotus"],  # 1A
    2: ["ca2","ca3","ca4","ca5","ca7","ca8","ca11"],                   # Title VII
    3: ["cadc","ca9","ca5","ca1","ca3"],                               # Admin law
    4: ["ca5","ca8","ca9","ca11","ca6","ca2"],                         # Crim proc
    5: ["ca9","ca5","ca2","ca11","ca4","ca1"],                         # Immigration
    6: ["ca5","ca8","ca9","ca6","ca7","ca11"],                         # §1983
    7: ["ca2","ca3","ca5","ca7","ca8","ca9"],                          # Contract
    8: ["ca9","ca10","ca8","ca5","ca4","ca11"],                        # Family
}

def collect_by_browse(client: CourtListenerClient, db: CorpusDB,
                      domain_id: int, target: int = 625):
    """
    Secondary collection strategy: browse clusters by court + date range
    rather than keyword search. Finds cases the keyword queries missed.
    Samples 2-year windows across 1990-2024 for the domain's key courts.
    """
    domain    = DOMAINS[domain_id]
    current   = db.count_cases(domain_id)
    if current >= target:
        log.info(f"  Domain {domain_id} already at target — skipping browse.")
        return

    log.info(f"\n  Browse mode for D{domain_id} ({domain['name']})")
    log.info(f"  Need {target - current} more cases")

    courts = DOMAIN_COURTS.get(domain_id, TARGET_COURTS[:6])

    # 2-year windows across the date range — sample widely
    windows = [
        ("1990-01-01","1993-12-31"),
        ("1994-01-01","1997-12-31"),
        ("1998-01-01","2001-12-31"),
        ("2002-01-01","2005-12-31"),
        ("2006-01-01","2009-12-31"),
        ("2010-01-01","2013-12-31"),
        ("2014-01-01","2017-12-31"),
        ("2018-01-01","2021-12-31"),
        ("2022-01-01","2024-12-31"),
    ]

    for court in courts:
        for date_after, date_before in windows:
            current = db.count_cases(domain_id)
            if current >= target:
                log.info(f"  Reached target {target}.")
                return

            log_key = f"browse:{court}:{date_after[:4]}"
            already_done = db.already_collected_pages(domain_id, log_key)
            page = 1
            no_new_streak = 0

            with tqdm(desc=f"  D{domain_id} {court} {date_after[:4]}-{date_before[:4]}",
                      unit="pg", leave=False) as pbar:
                while True:
                    current = db.count_cases(domain_id)
                    if current >= target:
                        break
                    if no_new_streak >= 3:
                        break
                    if page > 30:
                        break
                    if page in already_done:
                        page += 1
                        pbar.update(1)
                        continue

                    result = client.browse_clusters(
                        court, date_after, date_before, page)

                    if result is None:
                        break

                    hits = result.get("results", [])
                    if not hits:
                        break

                    new_on_page = 0
                    for hit in hits:
                        # Search endpoint returns cluster_id; REST endpoint returns id
                        cluster_id = hit.get("cluster_id") or hit.get("id")
                        if cluster_id is None:
                            continue
                        if db.case_exists(cluster_id, domain_id):
                            continue
                        # Search endpoint field names differ from REST endpoint:
                        #   caseName vs case_name
                        #   dateFiled vs date_filed
                        #   citation (list of strings) vs citations
                        case_name = (hit.get("caseName") or
                                     hit.get("case_name") or "")
                        date_filed = (hit.get("dateFiled") or
                                      hit.get("date_filed") or "")
                        abs_url    = hit.get("absolute_url", "")
                        status     = hit.get("status") or hit.get("precedential_status","")
                        docket     = hit.get("docketNumber") or hit.get("docket_number","")
                        # citation field in search results is a list of strings
                        cites_raw  = hit.get("citation", []) or hit.get("citations", [])
                        if isinstance(cites_raw, list) and cites_raw:
                            if isinstance(cites_raw[0], str):
                                cites_raw = [{"cite": c} for c in cites_raw]
                        db.insert_case(domain_id, {
                            "id":                  cluster_id,
                            "case_name":           case_name,
                            "court_id":            court,
                            "court":               court,
                            "date_filed":          date_filed,
                            "absolute_url":        abs_url,
                            "precedential_status": status,
                            "citations":           cites_raw,
                            "citation":            cites_raw,
                            "docket_number":       docket,
                        }, log_key)
                        new_on_page += 1

                    if new_on_page == 0:
                        no_new_streak += 1
                    else:
                        no_new_streak = 0

                    db.log_page(domain_id, log_key, page, new_on_page)
                    pbar.update(1)
                    pbar.set_postfix({"total": db.count_cases(domain_id),
                                      "new": new_on_page})

                    if len(hits) < 20:
                        break
                    page += 1

    final = db.count_cases(domain_id)
    log.info(f"  Browse complete: {final} cases in D{domain_id}")


def fetch_opinion_texts(client: CourtListenerClient, db: CorpusDB,
                        domain_id: int, batch: int = 100):
    """
    Second pass: for cases without opinion text, fetch full opinion text.
    Run this after collect_domain to fill in the full text.
    """
    log.info(f"\nFetching opinion texts for domain {domain_id}...")
    pending = db.get_cases_without_opinions(domain_id, limit=batch)
    log.info(f"  {len(pending)} cases need opinion text.")

    for row in tqdm(pending, desc=f"  D{domain_id} opinion texts", unit="case"):
        case_id = row[0]
        result = client.get_opinions_for_cluster(case_id)
        if result is None:
            continue
        opinions = result.get("results", [])
        for op in opinions:
            # If plain_text is missing, fetch full opinion
            if not op.get("plain_text") and op.get("id"):
                full = client.get_opinion(op["id"])
                if full:
                    op.update(full)
            db.insert_opinion(case_id, op)


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT — CORPUS STATISTICS
# ─────────────────────────────────────────────────────────────────────────────

def print_corpus_stats(db: CorpusDB):
    print("\n" + "="*60)
    print("CORPUS STATISTICS")
    print("="*60)
    total = 0
    for domain_id, domain in DOMAINS.items():
        count = db.count_cases(domain_id)
        total += count
        target = domain["target"]
        pct = count / target * 100
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"  D{domain_id} {domain['short']:<35} "
              f"{count:>4}/{target} [{bar}] {pct:.0f}%")
    print(f"\n  TOTAL: {total} / {sum(d['target'] for d in DOMAINS.values())}")

    # Court distribution
    conn = db.conn
    print("\nCourt distribution (top 10):")
    rows = conn.execute("""
        SELECT court_id, COUNT(*) as n FROM cases
        GROUP BY court_id ORDER BY n DESC LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"  {r['court_id']:<10} {r['n']}")

    # Year distribution
    print("\nYear distribution:")
    rows = conn.execute("""
        SELECT substr(date_filed,1,4) as yr, COUNT(*) as n
        FROM cases WHERE date_filed != ''
        GROUP BY yr ORDER BY yr
    """).fetchall()
    for r in rows:
        print(f"  {r['yr']}  {r['n']}")
    print("="*60 + "\n")


def export_all(db: CorpusDB, output_dir: str):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for domain_id, domain in DOMAINS.items():
        path = os.path.join(output_dir, f"domain_{domain_id}_{domain['short']}.jsonl")
        db.export_jsonl(domain_id, path)
    log.info(f"Exported all domains to {output_dir}/")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SOoL Caselaw Corpus Collector — CourtListener API"
    )
    parser.add_argument("--api-key",  required=True,
                        help="CourtListener API token (from your account page)")
    parser.add_argument("--domain",   default="all",
                        help="Domain(s) to collect: 'all' or comma-separated IDs e.g. '1,3,5'")
    parser.add_argument("--limit",    type=int, default=500,
                        help="Cases per domain (default 500)")
    parser.add_argument("--output",   default="./corpus",
                        help="Output directory for JSONL exports")
    parser.add_argument("--db",       default="./sool_corpus.db",
                        help="SQLite database path")
    parser.add_argument("--texts",    action="store_true",
                        help="Also fetch full opinion texts (slower)")
    parser.add_argument("--stats",    action="store_true",
                        help="Print corpus statistics and exit")
    parser.add_argument("--export",   action="store_true",
                        help="Export JSONL and exit (no new collection)")
    args = parser.parse_args()

    db = CorpusDB(args.db)
    db.set_meta("project", "SOoL Precedent Mapping Validation")
    db.set_meta("version", "1.0")
    db.set_meta("initiated", datetime.now(timezone.utc).isoformat())

    if args.stats:
        print_corpus_stats(db)
        return

    if args.export:
        export_all(db, args.output)
        return

    client = CourtListenerClient(args.api_key)

    # Verify API key works
    test = client.get(f"{API_BASE}/courts/?page_size=1")
    if test is None:
        log.error("API key verification failed. Check your key and try again.")
        sys.exit(1)
    log.info("API key verified. Starting collection.")

    # Domain selection
    if args.domain == "all":
        domain_ids = list(DOMAINS.keys())
    else:
        domain_ids = [int(x.strip()) for x in args.domain.split(",")]

    log.info(f"Collecting domains: {domain_ids}")
    log.info(f"Target per domain: {args.limit}")
    log.info(f"Date range: {DATE_RANGE[0]} → {DATE_RANGE[1]}")
    log.info(f"Courts: {', '.join(TARGET_COURTS)}")
    log.info(f"Database: {args.db}")

    # Phase 1: Collect case metadata (keyword search)
    for domain_id in domain_ids:
        collect_domain(client, db, domain_id, target=args.limit)

    # Phase 1b: Browse fallback for domains still short of target
    # Uses court+date browsing instead of keyword search — finds new cases
    for domain_id in domain_ids:
        current = db.count_cases(domain_id)
        if current < args.limit:
            log.info(f"\nD{domain_id} at {current}/{args.limit} — switching to browse mode")
            collect_by_browse(client, db, domain_id, target=args.limit)

    # Phase 2: Fetch opinion texts (optional — takes much longer)
    if args.texts:
        for domain_id in domain_ids:
            fetch_opinion_texts(client, db, domain_id, batch=args.limit)

    # Summary
    print_corpus_stats(db)
    export_all(db, args.output)
    log.info("Collection complete.")


if __name__ == "__main__":
    main()
