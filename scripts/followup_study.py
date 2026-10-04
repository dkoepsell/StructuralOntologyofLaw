#!/usr/bin/env python3
"""
SOoL Follow-Up Automated Study
================================
SEAL Lab, Texas A&M University
David R. Koepsell, A Structural Ontology of the Law (Palgrave, forthcoming)

Three automated studies providing confirmatory/disconfirmatory evidence
for the structural universality hypothesis:

  Study A: CD Predictive Validity (citation network correlation)
  Study B: CC Rule 7 targeted re-annotation (qualified immunity fix)
  Study C: Repair Pattern Consistency (role-stripping vs. sub-role exception)

Usage:
    # Step 0: populate citation network first (required for Study A and C)
    python3 followup_study.py --fetch-citations --cl-api-key <COURTLISTENER_KEY>

    python3 followup_study.py --study A --corpus ./sool_corpus.db \
                               --annotations ./sool_annotations.db
    python3 followup_study.py --study B --api-key sk-ant-api03-...
    python3 followup_study.py --study C --api-key sk-ant-api03-...
    python3 followup_study.py --study all --api-key sk-ant-api03-...
    python3 followup_study.py --report   # print findings from completed studies
    python3 followup_study.py --export-turtle --annotations ./sool_annotations.db

Requirements:
    pip install requests tqdm scipy
"""

import os, sys, json, math, time, sqlite3, argparse, logging, re
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import requests
from tqdm import tqdm

try:
    from scipy import stats as scipy_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler("followup.log", mode="a")]
)
log = logging.getLogger("followup")

# ── CONFIG ───────────────────────────────────────────────────────────────────
CLAUDE_API_URL  = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL    = "claude-sonnet-5"
CLAUDE_API_KEY  = ""
CL_API_KEY      = ""   # CourtListener key for citation fetching
CL_BASE         = "https://www.courtlistener.com/api/rest/v4"
RATE_LIMIT      = 3.0
CL_RATE_LIMIT   = 2.0
CORPUS_DB       = "./sool_corpus.db"
ANNOTATIONS_DB  = "./sool_annotations.db"
RESULTS_DB      = "./sool_followup.db"
CORPUS_DIR      = "./corpus"

DOMAIN_NAMES = {
    1:"first_amendment", 2:"employment_discrimination", 3:"administrative_law",
    4:"criminal_procedure", 5:"immigration", 6:"civil_rights_1983",
    7:"contract", 8:"family_law"
}

DOMAIN_FILES = {
    1:"domain_1_first_amendment.jsonl",
    2:"domain_2_employment_discrimination.jsonl",
    3:"domain_3_administrative_law.jsonl",
    4:"domain_4_criminal_procedure.jsonl",
    5:"domain_5_immigration.jsonl",
    6:"domain_6_civil_rights_1983.jsonl",
    7:"domain_7_contract.jsonl",
    8:"domain_8_family_law.jsonl",
}

# ════════════════════════════════════════════════════════════════════════════
# RESULTS DATABASE
# ════════════════════════════════════════════════════════════════════════════
RESULTS_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS study_a_results (
    case_id             INTEGER PRIMARY KEY,
    case_name           TEXT,
    domain_id           INTEGER,
    date_decided        TEXT,
    contradiction_debt  REAL,
    chain_outcome       TEXT,
    citing_count_5yr    INTEGER,
    citing_count_10yr   INTEGER,
    citing_count_all    INTEGER,
    cd_quartile         INTEGER
);

CREATE TABLE IF NOT EXISTS study_b_annotations (
    case_id             INTEGER PRIMARY KEY,
    case_name           TEXT,
    domain_id           INTEGER,
    original_cts        TEXT,
    updated_cts         TEXT,
    cc_added            INTEGER,
    original_cd         REAL,
    updated_cd          REAL,
    cd_delta            REAL,
    raw_response        TEXT,
    annotation_date     TEXT
);

CREATE TABLE IF NOT EXISTS study_c_results (
    case_id             INTEGER PRIMARY KEY,
    case_name           TEXT,
    domain_id           INTEGER,
    resolution_method   TEXT,
    resolution_note     TEXT,
    subsequent_cd_mean  REAL,
    subsequent_cd_n     INTEGER,
    resolution_date     TEXT
);

CREATE TABLE IF NOT EXISTS study_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    study       TEXT,
    status      TEXT,
    summary     TEXT,
    timestamp   TEXT
);
"""

class ResultsDB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(RESULTS_SCHEMA)
        self.conn.commit()

    def log(self, study, status, summary):
        self.conn.execute(
            "INSERT INTO study_log (study,status,summary,timestamp) VALUES (?,?,?,?)",
            (study, status, summary, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()


# ════════════════════════════════════════════════════════════════════════════
# STEP 0 — POPULATE CITATION NETWORK
# ════════════════════════════════════════════════════════════════════════════

def fetch_citations(corpus_db_path, cl_api_key, batch=50):
    """
    Populate the citations table in sool_corpus.db by fetching
    citation data from the CourtListener cluster endpoint.
    Required before running Study A or Study C.
    """
    log.info("\n" + "="*65)
    log.info("STEP 0: Populating Citation Network")
    log.info("="*65)

    conn = sqlite3.connect(corpus_db_path)
    conn.row_factory = sqlite3.Row

    total_cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    already_fetched = conn.execute(
        "SELECT COUNT(DISTINCT citing_case_id) FROM citations"
    ).fetchone()[0]

    log.info(f"Total cases in corpus: {total_cases}")
    log.info(f"Cases already with citations fetched: {already_fetched}")

    # Get cases not yet in citations table as citing_case_id
    pending_ids = conn.execute("""
        SELECT id, case_name, date_filed FROM cases
        WHERE id NOT IN (SELECT DISTINCT citing_case_id FROM citations)
        ORDER BY id
        LIMIT ?
    """, (batch,)).fetchall()

    log.info(f"Fetching citations for next {len(pending_ids)} cases...")

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {cl_api_key}",
        "User-Agent": "SOoL-CorpusCollector/1.0 (SEAL Lab, Texas A&M)"
    })

    fetched = errors = 0
    last_call = 0.0

    for row in tqdm(pending_ids, desc="Fetching citations", unit="case"):
        elapsed = time.time() - last_call
        if elapsed < CL_RATE_LIMIT:
            time.sleep(CL_RATE_LIMIT - elapsed)
        last_call = time.time()

        try:
            r = session.get(
                f"{CL_BASE}/clusters/{row['id']}/",
                timeout=20
            )
            if r.status_code == 404:
                # Mark as fetched with no citations
                conn.execute(
                    "INSERT OR IGNORE INTO citations (citing_case_id, cited_case_id) "
                    "VALUES (?, -1)", (row['id'],))
                conn.commit()
                fetched += 1
                continue
            r.raise_for_status()
            data = r.json()

            # CourtListener returns sub_opinions and citations_within
            # The 'sub_opinions' cluster may have citation relationships
            # Try 'citations' field — list of cluster URLs
            cite_urls = data.get("citations", [])

            # Also try 'opinions_cited' if present
            if not cite_urls:
                cite_urls = data.get("opinions_cited", [])

            cited_ids = []
            for cu in cite_urls:
                if isinstance(cu, dict):
                    # Extract ID from URL like /api/rest/v4/clusters/123/
                    url = cu.get("cluster", cu.get("url", ""))
                    match = re.search(r'/clusters/(\d+)/', str(url))
                    if match:
                        cited_ids.append(int(match.group(1)))
                elif isinstance(cu, str):
                    match = re.search(r'/clusters/(\d+)/', cu)
                    if match:
                        cited_ids.append(int(match.group(1)))

            if cited_ids:
                for cited_id in cited_ids:
                    conn.execute("""
                        INSERT OR IGNORE INTO citations
                        (citing_case_id, cited_case_id, cited_case_name)
                        VALUES (?,?,?)
                    """, (row['id'], cited_id, ""))
            else:
                # Mark as fetched with sentinel
                conn.execute(
                    "INSERT OR IGNORE INTO citations (citing_case_id, cited_case_id) "
                    "VALUES (?, -1)", (row['id'],))

            conn.commit()
            fetched += 1

        except Exception as e:
            log.warning(f"  Citation fetch error for {row['id']}: {e}")
            errors += 1

    total_cites = conn.execute(
        "SELECT COUNT(*) FROM citations WHERE cited_case_id != -1"
    ).fetchone()[0]
    log.info(f"\n  Fetched: {fetched}, Errors: {errors}")
    log.info(f"  Total citation relationships now in DB: {total_cites}")
    log.info(f"  Run --fetch-citations again to continue (processes {batch} per run)")


# ════════════════════════════════════════════════════════════════════════════
# CORPUS LOADER — shared by Studies B and C
# ════════════════════════════════════════════════════════════════════════════

def load_corpus_texts(corpus_dir):
    """Load all opinion texts from JSONL files into memory, keyed by case_id."""
    texts = {}
    import re as _re
    for domain_id, fname in DOMAIN_FILES.items():
        fpath = os.path.join(corpus_dir, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    case = json.loads(line)
                    cid = case.get("id") or case.get("case_id")
                    if not cid:
                        continue
                    # Extract best available text
                    best = ""
                    for op in case.get("opinions", []):
                        t = op.get("plain_text","") or op.get("html_text","") or ""
                        if len(t) > len(best):
                            best = t
                    # Strip HTML
                    best = _re.sub(r'<[^>]+>', ' ', best)
                    best = _re.sub(r'\s+', ' ', best).strip()
                    texts[cid] = best[:8000]  # 8k chars is plenty for Rule 7
                except Exception:
                    continue
    log.info(f"Loaded opinion texts for {len(texts)} cases from {corpus_dir}")
    return texts


# ════════════════════════════════════════════════════════════════════════════
# STUDY A — CD PREDICTIVE VALIDITY
# ════════════════════════════════════════════════════════════════════════════

def run_study_a(corpus_db_path, annotations_db_path, results_db):
    log.info("\n" + "="*65)
    log.info("STUDY A: CD Predictive Validity (Citation Network)")
    log.info("="*65)

    corpus = sqlite3.connect(corpus_db_path)
    corpus.row_factory = sqlite3.Row
    ann    = sqlite3.connect(annotations_db_path)
    ann.row_factory = sqlite3.Row

    # Check citation table population
    cite_count = corpus.execute(
        "SELECT COUNT(*) FROM citations WHERE cited_case_id != -1"
    ).fetchone()[0]

    if cite_count == 0:
        log.error("Citations table is empty.")
        log.error("Run: python3 followup_study.py --fetch-citations --cl-api-key <KEY>")
        log.error("(Run multiple times — processes 50 cases per run)")
        results_db.log("A", "blocked", "Citations table empty — run --fetch-citations first")
        return

    log.info(f"Citation relationships available: {cite_count}")

    # Load eligible annotations (pre-2014, clean)
    ann_rows = ann.execute("""
        SELECT case_id, case_name, domain_id, date_decided,
               contradiction_debt, chain_outcome
        FROM annotations
        WHERE date_decided != '' AND date_decided IS NOT NULL
          AND NOT needs_review
    """).fetchall()

    eligible = []
    for r in ann_rows:
        try:
            year = int(r["date_decided"][:4])
            if year < 2014:
                eligible.append(dict(r))
        except (ValueError, TypeError):
            continue

    log.info(f"Eligible pre-2014 cases: {len(eligible)}")

    # Build citation lookup: cited_id → [citing_case_ids with dates]
    case_dates = {r["id"]: r["date_filed"]
                  for r in corpus.execute("SELECT id, date_filed FROM cases")}

    cite_map = defaultdict(list)
    for cr in corpus.execute(
        "SELECT citing_case_id, cited_case_id FROM citations WHERE cited_case_id != -1"
    ):
        cited  = cr["cited_case_id"]
        citing = cr["citing_case_id"]
        d = case_dates.get(citing, "")
        if d:
            cite_map[cited].append(d)

    results = []
    for case in eligible:
        cid  = case["case_id"]
        base = case["date_decided"][:10]
        base_year = int(base[:4])
        cites_all = cite_map.get(cid, [])
        cites_5yr  = [d for d in cites_all
                      if d > base and d[:4] <= str(base_year + 5)]
        cites_10yr = [d for d in cites_all
                      if d > base and d[:4] <= str(base_year + 10)]

        results.append({**case,
                        "citing_count_all":  len(cites_all),
                        "citing_count_5yr":  len(cites_5yr),
                        "citing_count_10yr": len(cites_10yr)})

        results_db.conn.execute("""
            INSERT OR REPLACE INTO study_a_results VALUES (?,?,?,?,?,?,?,?,?,NULL)
        """, (cid, case["case_name"], case["domain_id"], case["date_decided"],
              case["contradiction_debt"], case["chain_outcome"],
              len(cites_5yr), len(cites_10yr), len(cites_all)))

    results_db.conn.commit()

    cd_vals   = [r["contradiction_debt"] or 0 for r in results]
    cite_10yr = [r["citing_count_10yr"] for r in results]

    print("\n" + "="*65)
    print("STUDY A RESULTS: CD vs. Citation Count")
    print("="*65)
    print(f"  n = {len(results)}, citation relationships = {cite_count}")

    # Check for constant array (no variation in citations)
    if len(set(cite_10yr)) <= 1:
        log.warning("  All citation counts are identical — "
                    "citation data may still be incomplete.")
        log.warning("  Run --fetch-citations more times to build the full network.")
        # Fall back to quartile analysis
        sorted_r = sorted(results, key=lambda x: x["contradiction_debt"] or 0)
        q = len(sorted_r) // 4
        if q > 0:
            print("\n  CD Quartile → Mean 10yr Citations:")
            for qi in range(4):
                qr = sorted_r[qi*q:(qi+1)*q]
                mc = sum(r["citing_count_10yr"] for r in qr)/len(qr)
                md = sum(r["contradiction_debt"] or 0 for r in qr)/len(qr)
                print(f"    Q{qi+1} avg_CD={md:.3f}  mean_10yr_cites={mc:.2f}")
        results_db.log("A", "partial",
            f"n={len(results)}, citations={cite_count} (incomplete)")
        return

    if HAS_SCIPY and len(results) >= 10:
        r_10yr, p_10yr = scipy_stats.pearsonr(cd_vals, cite_10yr)
        r_all,  p_all  = scipy_stats.pearsonr(
            cd_vals, [r["citing_count_all"] for r in results])

        print(f"\n  Pearson r (CD vs. 10yr citations):  "
              f"r = {r_10yr:+.4f}  p = {p_10yr:.4f}")
        print(f"  Pearson r (CD vs. all citations):   "
              f"r = {r_all:+.4f}  p = {p_all:.4f}")

        if r_10yr > 0 and p_10yr < 0.05:
            print(f"\n  ✓ CONFIRMS H1: r={r_10yr:.4f}, p={p_10yr:.4f}")
        elif r_10yr > 0 and p_10yr < 0.10:
            print(f"\n  ~ MARGINAL: r={r_10yr:.4f}, p={p_10yr:.4f}")
        else:
            print(f"\n  ✗ DOES NOT CONFIRM: r={r_10yr:.4f}, p={p_10yr:.4f}")

        print("\n  Per-domain (10yr):")
        for did in range(1, 9):
            dr = [r for r in results if r["domain_id"] == did]
            if len(dr) < 10:
                continue
            d_cd = [r["contradiction_debt"] or 0 for r in dr]
            d_ct = [r["citing_count_10yr"] for r in dr]
            if len(set(d_ct)) <= 1:
                print(f"    D{did} {DOMAIN_NAMES[did]:<30} "
                      f"n={len(dr):>3}  (uniform citation counts — incomplete)")
                continue
            corr, pval = scipy_stats.pearsonr(d_cd, d_ct)
            sig = "✓" if pval < 0.05 else ("~" if pval < 0.10 else "✗")
            print(f"    D{did} {DOMAIN_NAMES[did]:<30} n={len(dr):>3}"
                  f"  r={corr:+.3f}  p={pval:.3f}  {sig}")

        results_db.log("A", "complete",
            f"n={len(results)}, r_10yr={r_10yr:.4f}, p={p_10yr:.4f}")


# ════════════════════════════════════════════════════════════════════════════
# STUDY B — CC RULE 7
# ════════════════════════════════════════════════════════════════════════════

RULE7_SYSTEM = """You are an expert legal ontologist applying the SOoL framework.

TASK: Determine whether CORRELATIVITY CONTRADICTION (CC) fires in this case.

CC vs. RF distinction — this is critical:
  RF (Recognition Failure): The court denies the right EXISTS.
  CC (Correlativity Contradiction): The court ACKNOWLEDGES the right exists
      but PERMITS the duty-bearer to REFUSE the correlative duty through
      immunity, privilege, or structural bar.

RULE 7 — IMMUNITY DOCTRINE:
If the opinion: (a) finds or assumes a constitutional violation occurred,
AND (b) nonetheless shields the defendant from liability via qualified
immunity, sovereign immunity, or absolute immunity —
THEN CC fires, because the right is acknowledged but the correlative duty
to provide a remedy is refused by operation of the immunity doctrine.

Examples where CC fires:
  "We assume a constitutional violation for purposes of the qualified
   immunity analysis, but find the right was not clearly established."
  — CC fires: violation acknowledged, duty to remedy refused.

Examples where CC does NOT fire (RF fires instead):
  "We find no constitutional violation occurred."
  — RF fires: right not established, not CC.

Return ONLY valid JSON:
{
  "cc_fires": true | false,
  "justification": "quote or paraphrase from the opinion (1-2 sentences)",
  "confidence": "high" | "medium" | "low"
}"""


def run_study_b(annotations_db_path, corpus_dir, results_db):
    log.info("\n" + "="*65)
    log.info("STUDY B: CC Rule 7 Targeted Re-Annotation")
    log.info("="*65)

    ann = sqlite3.connect(annotations_db_path)
    ann.row_factory = sqlite3.Row

    # Load opinion texts from JSONL corpus files
    opinion_texts = load_corpus_texts(corpus_dir)

    # Target D6 protection_denied + any immunity-related cases
    targets = ann.execute("""
        SELECT case_id, case_name, domain_id, active_contradictions,
               contradiction_debt, node7_entity, node7_closure, chain_outcome
        FROM annotations
        WHERE (domain_id = 6 AND chain_outcome = 'protection_denied')
           OR (node7_entity LIKE '%immunity%' AND chain_outcome = 'protection_denied')
        ORDER BY domain_id
    """).fetchall()

    log.info(f"Targets: {len(targets)}")
    texts_available = sum(1 for t in targets
                         if opinion_texts.get(t["case_id"]))
    log.info(f"With opinion text available: {texts_available}")

    cc_weights = {
        "CF":0.15,"AINF":0.12,"JC":0.10,"RC3":0.14,"PC":0.09,"TC":0.08,
        "FM":0.11,"NI":0.07,"RF":0.11,"RCL":0.18,"CC":0.14,"SE":0.10,"RPF":0.13
    }

    added = not_added = failed = skipped_no_text = 0
    last_call = 0.0

    for row in tqdm(targets, desc="Study B — Rule 7", unit="case"):
        case_id = row["case_id"]
        existing_cts = json.loads(row["active_contradictions"] or "[]")

        if "CC" in existing_cts:
            not_added += 1
            continue

        # Get opinion text
        opinion_text = opinion_texts.get(case_id, "")
        if not opinion_text:
            skipped_no_text += 1
            # Still attempt with just context — mark low confidence expected
            opinion_text = "[Opinion text not available in corpus]"

        user_prompt = f"""Case: {row['case_name']}
Domain: {DOMAIN_NAMES.get(row['domain_id'], '?')}
Chain outcome: {row['chain_outcome']}
Node 7 entity: {row['node7_entity'] or 'N/A'}
Current contradiction types: {existing_cts}

OPINION TEXT (first 6000 chars):
{opinion_text[:6000]}

Does Rule 7 (Immunity Doctrine) apply? Should CC fire?"""

        elapsed = time.time() - last_call
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        last_call = time.time()

        try:
            resp = requests.post(
                CLAUDE_API_URL,
                headers={"Content-Type":"application/json",
                         "x-api-key":CLAUDE_API_KEY,
                         "anthropic-version":"2023-06-01"},
                json={"model":CLAUDE_MODEL, "max_tokens":600,
                      "thinking":{"type":"disabled"},
                      "system":RULE7_SYSTEM,
                      "messages":[{"role":"user","content":user_prompt}]},
                timeout=45
            )
            resp.raise_for_status()
            raw = ""
            for block in resp.json().get("content", []):
                if block.get("type") == "text":
                    raw += block.get("text", "")

            if not raw.strip():
                failed += 1
                continue

            clean = re.sub(r'```(?:json)?\s*', '', raw.strip())
            clean = re.sub(r'```', '', clean).strip()
            result = json.loads(clean)
            cc_fires = result.get("cc_fires", False)

        except Exception as e:
            log.warning(f"  Study B error for {row['case_name'][:40]}: {e}")
            failed += 1
            continue

        updated_cts = existing_cts[:]
        if cc_fires:
            updated_cts.append("CC")
            added += 1
        else:
            not_added += 1

        orig_cd    = row["contradiction_debt"] or 0
        updated_cd = round(sum(cc_weights.get(c, 0) for c in updated_cts), 4)

        results_db.conn.execute("""
            INSERT OR REPLACE INTO study_b_annotations VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (case_id, row["case_name"], row["domain_id"],
              json.dumps(existing_cts), json.dumps(updated_cts),
              1 if cc_fires else 0,
              orig_cd, updated_cd, round(updated_cd - orig_cd, 4),
              raw[:500], datetime.now(timezone.utc).isoformat()))
        results_db.conn.commit()

    print("\n" + "="*65)
    print("STUDY B RESULTS: CC Rule 7")
    print("="*65)
    print(f"  Targets:              {len(targets)}")
    print(f"  CC added:             {added}  ({added/max(1,len(targets))*100:.0f}%)")
    print(f"  CC not warranted:     {not_added}")
    print(f"  Skipped (no text):    {skipped_no_text}")
    print(f"  API/parse failures:   {failed}")

    if added > 0:
        d6_added = results_db.conn.execute(
            "SELECT COUNT(*) FROM study_b_annotations WHERE domain_id=6 AND cc_added=1"
        ).fetchone()[0]
        d6_total = results_db.conn.execute(
            "SELECT COUNT(*) FROM study_b_annotations WHERE domain_id=6"
        ).fetchone()[0]
        mean_delta = results_db.conn.execute(
            "SELECT AVG(cd_delta) FROM study_b_annotations WHERE cc_added=1"
        ).fetchone()[0] or 0
        print(f"\n  D6 CC rate after Rule 7: {d6_added}/{d6_total} "
              f"({d6_added/max(1,d6_total)*100:.0f}%)")
        print(f"  Mean CD increase when CC added: +{mean_delta:.3f}")
        if d6_added / max(1, d6_total) > 0.3:
            print("\n  ✓ CONFIRMS: CC rate >30% — QI is structurally CC, not merely RF.")
        else:
            print(f"\n  ✗ DOES NOT CONFIRM: CC rate "
                  f"{d6_added/max(1,d6_total)*100:.0f}% < 30%")
    else:
        print("\n  CC was never added. Possible causes:")
        print("  1. Most D6 cases deny the violation (RF), not assume-and-shield (CC)")
        print("  2. Opinion texts were unavailable for many cases")
        print("  3. The qualified immunity cases in this corpus are circuit-level,")
        print("     where courts often deny violation outright rather than assume-for-QI")

    results_db.log("B", "complete",
        f"n={len(targets)}, cc_added={added}, no_text={skipped_no_text}, failed={failed}")


# ════════════════════════════════════════════════════════════════════════════
# STUDY C — REPAIR PATTERN CONSISTENCY
# ════════════════════════════════════════════════════════════════════════════

REPAIR_PATTERN_SYSTEM = """You are a legal analyst applying the SOoL (Structural Ontology of Law) framework.

TASK: Classify how this court resolved a Node 3 Role Contradiction (RC3).

Two resolution methods:
  "role_stripping": The court eliminates one role from the bearer.
    The conflicting role is declared inapplicable or absorbed into the other.
    The chain closes but one role's normative space is foreclosed.
    Example: Garcetti — citizen-speaker role absorbed into official-duty role.

  "sub_role_exception": The court preserves both roles but carves a
    protected zone within one. Both roles remain but the court defines
    conditions where the protected role prevails.
    Example: Meriwether — academic speech may be protected within
    the public-employee role under specific academic conditions.

  "unclear": Cannot determine from available information.

Return ONLY valid JSON:
{
  "resolution_method": "role_stripping" | "sub_role_exception" | "unclear",
  "resolution_note": "1-2 sentences describing how court resolved the role tension",
  "confidence": "high" | "medium" | "low"
}"""


def run_study_c(annotations_db_path, corpus_db_path, corpus_dir, results_db):
    log.info("\n" + "="*65)
    log.info("STUDY C: Repair Pattern Consistency")
    log.info("="*65)

    ann    = sqlite3.connect(annotations_db_path)
    ann.row_factory = sqlite3.Row
    corpus = sqlite3.connect(corpus_db_path)
    corpus.row_factory = sqlite3.Row

    rc3_cases = ann.execute("""
        SELECT case_id, case_name, domain_id, date_decided,
               contradiction_debt, outcome_notes, chain_outcome,
               node3_entity, node3_roles
        FROM annotations
        WHERE active_contradictions LIKE '%RC3%'
        ORDER BY domain_id
    """).fetchall()

    log.info(f"RC3 cases: {len(rc3_cases)}")

    # Load opinion texts
    opinion_texts = load_corpus_texts(corpus_dir)

    # Load CD lookup and citation map
    all_ann = {r["case_id"]: r["contradiction_debt"] or 0
               for r in ann.execute(
                   "SELECT case_id, contradiction_debt FROM annotations")}

    cite_count = corpus.execute(
        "SELECT COUNT(*) FROM citations WHERE cited_case_id != -1"
    ).fetchone()[0]
    has_citations = cite_count > 0

    cite_map = defaultdict(list)
    if has_citations:
        for cr in corpus.execute(
            "SELECT citing_case_id, cited_case_id FROM citations WHERE cited_case_id != -1"
        ):
            cite_map[cr["cited_case_id"]].append(cr["citing_case_id"])

    failed = classified = 0
    last_call = 0.0

    for row in tqdm(rc3_cases, desc="Study C — repair pattern", unit="case"):
        case_id = row["case_id"]

        # Skip if already classified
        existing = results_db.conn.execute(
            "SELECT 1 FROM study_c_results WHERE case_id=?", (case_id,)
        ).fetchone()
        if existing:
            classified += 1
            continue

        roles = json.loads(row["node3_roles"] or "[]")
        opinion = opinion_texts.get(case_id, "")[:3000]

        user_prompt = f"""Case: {row['case_name']}
Domain: {DOMAIN_NAMES.get(row['domain_id'], '?')}
Chain outcome: {row['chain_outcome']}
Actor: {row['node3_entity'] or 'N/A'}
Roles borne: {roles}
Outcome notes: {row['outcome_notes'] or 'N/A'}
Opinion excerpt: {opinion or '[not available]'}

This case has a Role Contradiction. How did the court resolve it?"""

        elapsed = time.time() - last_call
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        last_call = time.time()

        try:
            resp = requests.post(
                CLAUDE_API_URL,
                headers={"Content-Type":"application/json",
                         "x-api-key":CLAUDE_API_KEY,
                         "anthropic-version":"2023-06-01"},
                json={"model":CLAUDE_MODEL, "max_tokens":450,
                      "thinking":{"type":"disabled"},
                      "system":REPAIR_PATTERN_SYSTEM,
                      "messages":[{"role":"user","content":user_prompt}]},
                timeout=30
            )
            resp.raise_for_status()
            raw = ""
            for block in resp.json().get("content", []):
                if block.get("type") == "text":
                    raw += block.get("text","")
            if not raw.strip():
                failed += 1
                continue
            clean = re.sub(r'```(?:json)?\s*', '', raw.strip())
            clean = re.sub(r'```', '', clean).strip()
            result = json.loads(clean)
            method = result.get("resolution_method", "unclear")
            note   = result.get("resolution_note", "")
        except Exception as e:
            log.warning(f"  Study C error for {row['case_name'][:40]}: {e}")
            failed += 1
            continue

        # Compute subsequent CD if citations available
        citing_ids  = cite_map.get(case_id, [])
        citing_cds  = [all_ann[c] for c in citing_ids if c in all_ann]
        subseq_mean = sum(citing_cds)/len(citing_cds) if citing_cds else None

        results_db.conn.execute("""
            INSERT OR REPLACE INTO study_c_results VALUES (?,?,?,?,?,?,?,?)
        """, (case_id, row["case_name"], row["domain_id"], method, note,
              subseq_mean, len(citing_cds),
              datetime.now(timezone.utc).isoformat()))
        results_db.conn.commit()
        classified += 1

    # Print results
    print("\n" + "="*65)
    print("STUDY C RESULTS: Repair Pattern Consistency")
    print("="*65)
    print(f"  RC3 cases classified: {classified}  |  Failed: {failed}")

    # Resolution method distribution
    method_rows = results_db.conn.execute("""
        SELECT resolution_method, COUNT(*) as n,
               COUNT(CASE WHEN subsequent_cd_n > 0 THEN 1 END) as with_cites
        FROM study_c_results
        GROUP BY resolution_method ORDER BY n DESC
    """).fetchall()

    print("\n  Resolution method distribution:")
    for m in method_rows:
        print(f"    {m['resolution_method']:<25} n={m['n']:>3}  "
              f"({m['with_cites']} have subsequent cases in corpus)")

    # Domain breakdown
    print("\n  By domain:")
    domain_rows = results_db.conn.execute("""
        SELECT domain_id,
               SUM(CASE WHEN resolution_method='role_stripping' THEN 1 ELSE 0 END) as rs,
               SUM(CASE WHEN resolution_method='sub_role_exception' THEN 1 ELSE 0 END) as sre,
               SUM(CASE WHEN resolution_method='unclear' THEN 1 ELSE 0 END) as unk,
               COUNT(*) as total
        FROM study_c_results GROUP BY domain_id ORDER BY domain_id
    """).fetchall()
    for r in domain_rows:
        print(f"    D{r['domain_id']} {DOMAIN_NAMES.get(r['domain_id'],'?'):<30}"
              f"  role_strip={r['rs']:>2}  sub_role={r['sre']:>2}  unclear={r['unk']:>2}")

    # CD comparison if citations available
    cd_rows = results_db.conn.execute("""
        SELECT resolution_method,
               COUNT(*) as n,
               AVG(subsequent_cd_mean) as avg_subseq_cd
        FROM study_c_results
        WHERE subsequent_cd_mean IS NOT NULL
        GROUP BY resolution_method
    """).fetchall()

    if cd_rows:
        print("\n  Subsequent CD by resolution method:")
        for r in cd_rows:
            print(f"    {r['resolution_method']:<25} n={r['n']:>3}  "
                  f"avg_subsequent_CD={r['avg_subseq_cd']:.3f}")
        rs = {r["resolution_method"]: r for r in cd_rows}
        if "role_stripping" in rs and "sub_role_exception" in rs:
            s_cd = rs["role_stripping"]["avg_subseq_cd"]
            e_cd = rs["sub_role_exception"]["avg_subseq_cd"]
            if s_cd < e_cd:
                print(f"\n  ✓ CONFIRMS: role_stripping ({s_cd:.3f}) < "
                      f"sub_role_exception ({e_cd:.3f})")
            else:
                print(f"\n  ✗ DOES NOT CONFIRM: role_stripping ({s_cd:.3f}) >= "
                      f"sub_role_exception ({e_cd:.3f})")
    else:
        print("\n  Subsequent CD comparison not yet available.")
        print("  Run --fetch-citations to build citation network, then re-run Study C.")

    results_db.log("C", "complete",
        f"classified={classified}, failed={failed}, "
        f"citations={'available' if has_citations else 'not yet fetched'}")


# ════════════════════════════════════════════════════════════════════════════
# REPORT
# ════════════════════════════════════════════════════════════════════════════

def print_report(results_db):
    print("\n" + "="*65)
    print("SOoL FOLLOW-UP STUDIES — CONSOLIDATED FINDINGS")
    print("="*65)
    logs = results_db.conn.execute(
        "SELECT * FROM study_log ORDER BY timestamp"
    ).fetchall()
    if not logs:
        print("  No studies completed yet.")
        return
    for entry in logs:
        print(f"\n  Study {entry['study']} [{entry['status']}] "
              f"{entry['timestamp'][:10]}")
        print(f"    {entry['summary']}")


# ════════════════════════════════════════════════════════════════════════════
# TURTLE EXPORT
# ════════════════════════════════════════════════════════════════════════════

def export_turtle_standalone(annotations_db_path, output_dir="./turtle_export"):
    Path(output_dir).mkdir(exist_ok=True)
    conn = sqlite3.connect(annotations_db_path)
    conn.row_factory = sqlite3.Row

    PREFIXES = """@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix law:  <http://seal.tamu.edu/legal-kernel/> .
@prefix mlc:  <http://seal.tamu.edu/legal-kernel/mlc/> .
@prefix case: <http://seal.tamu.edu/legal-kernel/cases/> .

"""
    CT_NAMES = {
        "CF":"ConferralFailure","AINF":"AuthorityInflation",
        "JC":"JurisdictionalContradiction","RC3":"RoleContradiction",
        "PC":"ProceduralContradiction","TC":"TemporalContradiction",
        "FM":"FactManipulation","NI":"NormIndeterminacy",
        "RF":"RecognitionFailure","RCL":"RecognitionCollapse",
        "CC":"CorrelativiyContradiction","SE":"SelfUnderminingEffect",
        "RPF":"RepairFailure"
    }

    total = 0
    for domain_id, domain_name in DOMAIN_NAMES.items():
        rows = conn.execute(
            "SELECT * FROM annotations WHERE domain_id=? ORDER BY case_id",
            (domain_id,)
        ).fetchall()
        out_path = os.path.join(output_dir, f"domain_{domain_id}_{domain_name}.ttl")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(PREFIXES)
            f.write(f"# Domain {domain_id}: {domain_name}  n={len(rows)}\n")
            f.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}\n\n")
            for r in rows:
                cid  = r["case_id"]
                name = (r["case_name"] or "").replace('"', '\\"')
                cts  = json.loads(r["active_contradictions"] or "[]")
                sigs = json.loads(r["structural_signature"] or "[]")
                cd   = r["contradiction_debt"] or 0
                out  = r["chain_outcome"] or "unknown"
                lines = [
                    f'case:C{cid} a mlc:CaseInstance ;',
                    f'  rdfs:label "{name}" ;',
                    f'  mlc:court "{r["court"] or ""}" ;',
                    f'  mlc:doctrinalDomain "{domain_name}" ;',
                    f'  mlc:chainOutcome mlc:{out.replace("_","").title()} ;',
                    f'  mlc:contradictionDebt "{cd:.4f}"^^xsd:decimal ;',
                ]
                if r["date_decided"]:
                    lines.insert(3,
                        f'  mlc:dateDecided "{r["date_decided"][:10]}"^^xsd:date ;')
                for ct in cts:
                    lines.append(
                        f'  mlc:hasContradiction mlc:{CT_NAMES.get(ct,ct)} ;')
                for sig in sigs:
                    lines.append(f'  mlc:structuralSignature "{sig}" ;')
                for n in range(1, 9):
                    cl = r[f"node{n}_closure"] or "indeterminate"
                    en = (r[f"node{n}_entity"] or "").replace('"','\\"')[:200]
                    lines.append(
                        f'  mlc:node{n}Closure mlc:Closure_{cl.title()} ;')
                    if en:
                        lines.append(f'  mlc:node{n}Entity "{en}" ;')
                for i in range(len(lines)-1, -1, -1):
                    if lines[i].rstrip().endswith(";"):
                        lines[i] = lines[i].rstrip()[:-1] + " ."
                        break
                f.write("\n".join(lines) + "\n\n")
                total += 1
        log.info(f"Exported {len(rows)} → {out_path}")

    # Combined file
    combined = os.path.join(output_dir, "sool_corpus_all.ttl")
    with open(combined, "w", encoding="utf-8") as out:
        out.write(PREFIXES)
        out.write(f"# SOoL full corpus — {total} cases\n")
        out.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}\n\n")
        for did, dn in DOMAIN_NAMES.items():
            df = os.path.join(output_dir, f"domain_{did}_{dn}.ttl")
            if os.path.exists(df):
                with open(df, encoding="utf-8") as f:
                    content = f.read()
                    idx = content.find("\n# Domain")
                    out.write(content[idx:] if idx >= 0 else content)

    log.info(f"Combined: {combined} ({total} cases)")
    return total


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    global CLAUDE_API_KEY, CL_API_KEY, CORPUS_DB, ANNOTATIONS_DB, CORPUS_DIR

    parser = argparse.ArgumentParser(
        description="SOoL Follow-Up Studies"
    )
    parser.add_argument("--study", default="report")
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY",""),
                        help="Anthropic API key (Studies B and C)")
    parser.add_argument("--cl-api-key", default="",
                        help="CourtListener API key (--fetch-citations)")
    parser.add_argument("--fetch-citations", action="store_true",
                        help="Populate citation network (run before Study A/C)")
    parser.add_argument("--corpus",      default=CORPUS_DB)
    parser.add_argument("--annotations", default=ANNOTATIONS_DB)
    parser.add_argument("--corpus-dir",  default=CORPUS_DIR)
    parser.add_argument("--results",     default=RESULTS_DB)
    parser.add_argument("--export-turtle", action="store_true")
    parser.add_argument("--turtle-dir",  default="./turtle_export")
    args = parser.parse_args()

    CLAUDE_API_KEY = args.api_key
    CL_API_KEY     = args.cl_api_key
    CORPUS_DB      = args.corpus
    ANNOTATIONS_DB = args.annotations
    CORPUS_DIR     = args.corpus_dir

    if args.export_turtle:
        n = export_turtle_standalone(args.annotations, args.turtle_dir)
        print(f"\nExported {n} cases to {args.turtle_dir}/")
        return

    if args.fetch_citations:
        if not CL_API_KEY:
            log.error("--fetch-citations requires --cl-api-key <COURTLISTENER_KEY>")
            sys.exit(1)
        fetch_citations(args.corpus, CL_API_KEY)
        return

    rdb = ResultsDB(args.results)
    study = args.study.upper()

    if study in ("A", "ALL"):
        run_study_a(args.corpus, args.annotations, rdb)
    if study in ("B", "ALL"):
        if not CLAUDE_API_KEY:
            log.error("Study B requires --api-key")
        else:
            run_study_b(args.annotations, args.corpus_dir, rdb)
    if study in ("C", "ALL"):
        if not CLAUDE_API_KEY:
            log.error("Study C requires --api-key")
        else:
            run_study_c(args.annotations, args.corpus, args.corpus_dir, rdb)
    if study in ("REPORT", "ALL"):
        print_report(rdb)


if __name__ == "__main__":
    main()

