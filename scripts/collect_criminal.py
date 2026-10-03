#!/usr/bin/env python3
"""
collect_criminal.py -- SOoL Criminal Ontology Corpus Collection
================================================================
SEAL Lab, Texas A&M University
David R. Koepsell

Collects a stratified corpus of state and federal criminal law opinions
for the Structural Ontology of Criminal Norms project.

This corpus is DISTINCT from the civil/administrative SOoL corpus.
It uses a separate database (sool_criminal.db) and annotation pipeline
(annotate_criminal.py) because the MLC perspective is INVERTED:
    - Claimant = THE STATE asserting criminal liability
    - protection_granted = CONVICTION / state prevails
    - protection_denied = ACQUITTAL / defense prevails / dismissal

Six offense categories x 500 cases = 3,000 target

Category design rationale (maps to primary MLC failure nodes):
    C1 Homicide/Violence    -- N5 primary (act classification: murder vs manslaughter)
    C2 Inchoate Offenses    -- N4/N5 primary (incomplete chain: attempt, conspiracy)
    C3 Property/Fraud       -- N2 primary (norm indeterminacy: element ambiguity)
    C4 Status Offenses      -- N3 primary (role is the prohibition: felon-in-possession)
    C5 Strict Liability     -- N5 thin (no mens rea node: regulatory, traffic, public welfare)
    C6 Defenses (All types) -- N7 primary (affirmative defenses defeat legal effect)

Usage:
    python3 collect_criminal.py --api-key YOUR_CL_KEY [--category all|1-6]
                                [--limit 500] [--courts state|federal|all]
"""

import os, sys, time, json, sqlite3, argparse, logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

# ── CRIMINAL ONTOLOGY CORPUS DESIGN ─────────────────────────────────────────
# Each category maps to a primary MLC node and expected CT profile.
# The annotator will analyze from the STATE's perspective as claimant.

CRIMINAL_CATEGORIES = {
    1: {
        "name": "Homicide and Violent Offenses",
        "short": "homicide_violence",
        "primary_node": "N5",
        "primary_failures": [
            "Recognition Failure N.7 (jury finds insufficient proof of element)",
            "Norm Indeterminacy N.2 (degree distinction: murder vs manslaughter)",
            "Fact Manipulation N.4 (self-defense / provocation disputing facts)",
        ],
        "ontological_note": (
            "The central structural question is act classification at N5: "
            "did the act constitute the specific prohibited conduct (premeditated "
            "murder vs heat-of-passion manslaughter vs negligent homicide)? "
            "The mental state (mens rea) is constitutive of the role at N3, "
            "not merely a triggering fact -- malice aforethought is a role "
            "condition, not an actus reus element."
        ),
        "target": 500,
        "queries": [
            "murder first degree premeditation deliberation appeal conviction",
            "manslaughter heat of passion provocation malice aforethought",
            "felony murder rule underlying felony merger doctrine",
            "murder second degree implied malice depraved heart recklessness",
            "homicide causation but-for proximate cause intervening superseding",
            "self-defense imperfect self-defense honest but unreasonable belief",
            "assault battery serious bodily harm aggravated assault conviction",
            "domestic violence intimate partner abuse criminal conviction appeal",
            "murder intent specific malice aforethought criminal appeal reversal",
            "robbery force intimidation taking criminal conviction elements",
            "rape sexual assault consent force criminal conviction appeal",
            "kidnapping false imprisonment asportation criminal conviction",
            "arson malice burning dwelling criminal conviction elements",
            "attempted murder intent specific purpose criminal elements",
            "murder conspiracy premeditation criminal conviction appeal",
            "homicide causation year-and-a-day rule criminal conviction",
            "voluntary manslaughter heat passion adequate provocation elements",
            "reckless homicide vehicular manslaughter criminal conviction",
            "felony murder causation co-felon killing criminal appeal",
            "murder lesser included offense jury instruction criminal appeal",
        ],
    },
    2: {
        "name": "Inchoate Offenses",
        "short": "inchoate_offenses",
        "primary_node": "N4/N5",
        "primary_failures": [
            "Norm Indeterminacy N.2 (how far is substantial step?)",
            "Fact Manipulation N.4 (acts not yet completed)",
            "Procedural Contradiction N.2->5 (chain attempts to close before completion)",
        ],
        "ontological_note": (
            "Inchoate offenses are the most structurally interesting category "
            "because the criminal chain never fully closes at N4/N5 -- the "
            "triggering facts and legal act are incomplete by definition. "
            "Attempt, conspiracy, and solicitation criminalize the chain "
            "formation process itself rather than its completion. "
            "This generates persistent NI at N2 (how much completion is required?) "
            "and TC at N2<->N4 (the norm applies before the facts it governs exist). "
            "Abandonment defenses are structural interventions that sever the "
            "chain before it closes sufficiently to generate criminal liability."
        ),
        "target": 500,
        "queries": [
            "criminal attempt substantial step beyond mere preparation conviction",
            "conspiracy agreement overt act scope liability criminal appeal",
            "solicitation criminal inchoate offense entrapment",
            "criminal attempt impossibility factual legal impossibility defense",
            "withdrawal abandonment renunciation conspiracy criminal defense",
            "RICO conspiracy enterprise pattern racketeering criminal conviction",
            "attempt specific intent mens rea inchoate criminal conviction",
            "conspiracy Wharton rule bilateral agreement criminal law",
            "solicitation attempt merger criminal inchoate completed offense",
            "criminal conspiracy scope Pinkerton liability co-conspirator acts",
            "attempt proximity test dangerous proximity criminal conviction",
            "conspiracy withdrawal termination criminal liability limit",
            "felon in possession firearm 922g completed attempt inchoate",
            "drug conspiracy distribution attempt criminal conviction elements",
            "terrorism attempt plot substantial step criminal conviction",
            "conspiracy venue jurisdiction overt act criminal conviction",
            "attempt abandonment voluntary complete defense criminal",
            "conspiracy single multiple agreement criminal conviction appeal",
            "criminal solicitation attempt merger completed offense",
            "inchoate liability innocent intermediary criminal conviction",
        ],
    },
    3: {
        "name": "Property Crimes and Fraud",
        "short": "property_fraud",
        "primary_node": "N2",
        "primary_failures": [
            "Norm Indeterminacy N.2 (element ambiguity: what counts as fraud?)",
            "Fact Manipulation N.4 (materiality, reliance, victim loss contested)",
            "Recognition Failure N.7 (element not proved beyond reasonable doubt)",
        ],
        "ontological_note": (
            "Property crimes and fraud exhibit the highest N2 stress of any "
            "offense category because the governing norms are structurally "
            "open-textured -- what constitutes 'fraud', 'deception', 'property', "
            "'taking', or 'material misrepresentation' is perpetually contested. "
            "This generates systematic NI at N2. The materiality standard in fraud "
            "is a paradigmatic N2/N4 intersection: the norm requires a fact to be "
            "material, but materiality is itself a normative judgment about facts. "
            "Theft offenses exhibit JC where property, contract, and criminal "
            "regimes generate competing norms over the same transaction."
        ),
        "target": 500,
        "queries": [
            "theft larceny taking carrying away intent to permanently deprive",
            "fraud misrepresentation material false statement intent criminal",
            "wire fraud mail fraud scheme artifice defraud criminal conviction",
            "robbery theft force intimidation asportation criminal elements",
            "burglary breaking entering dwelling intent criminal conviction",
            "embezzlement conversion fraudulent appropriation criminal conviction",
            "false pretenses misrepresentation title transfer criminal conviction",
            "extortion blackmail Hobbs Act threat criminal conviction elements",
            "receiving stolen property knowledge criminal conviction appeal",
            "identity theft computer fraud unauthorized access criminal",
            "forgery uttering false document criminal conviction elements",
            "money laundering proceeds specified unlawful activity criminal",
            "bribery corrupt payment official act criminal conviction Hobbs Act",
            "fraud materiality reasonable person standard criminal conviction",
            "theft by deception criminal fraud elements intent",
            "property crime value amount threshold criminal conviction",
            "criminal conversion civil property criminal distinction",
            "fraud scheme continuing offense criminal conviction appeal",
            "cybercrime computer fraud access criminal conviction elements",
            "tax fraud evasion willfulness criminal conviction elements",
        ],
    },
    4: {
        "name": "Status Offenses and Regulatory Crimes",
        "short": "status_regulatory",
        "primary_node": "N3",
        "primary_failures": [
            "Conferral Failure N.3 (actor cannot bear criminal role: capacity, status)",
            "Recognition Collapse N.6->8 (status persists despite full discharge)",
            "Authority Inflation N.1->2 (regulatory criminalization overreach)",
        ],
        "ontological_note": (
            "Status offenses are the purest N3 cases in criminal law: the "
            "prohibition attaches to the role itself rather than to any act. "
            "Felon-in-possession, sex offender registration, and professional "
            "license violations criminalize role-bearing rather than conduct. "
            "This generates the most severe RCL (Recognition Collapse) pattern "
            "in criminal law: the actor has discharged their sentence (N8 closed) "
            "but continues to bear criminal obligations derived from the status. "
            "The status creates a permanent specifically-dependent-continuant that "
            "generates new criminal chains without new harmful acts. "
            "Regulatory crimes (strict liability with regulatory context) show "
            "AI at N1->N2 where agency rulemaking effectively defines criminal "
            "conduct without the norm-setting authority of the legislature."
        ),
        "target": 500,
        "queries": [
            "felon in possession firearm 922g status prior conviction criminal",
            "sex offender registration SORNA failure to register criminal",
            "career offender recidivist enhancement status criminal sentencing",
            "illegal alien immigration status crime criminal conviction",
            "regulatory offense strict liability public welfare criminal",
            "professional license criminal violation status offense",
            "drug addict prohibited person firearms status criminal conviction",
            "domestic violence misdemeanant firearm prohibition Lautenberg",
            "registered sex offender residency restriction criminal violation",
            "mental defective adjudication firearm prohibition criminal",
            "status offense juvenile delinquency criminal adult",
            "recidivism three strikes habitual offender criminal status",
            "civil commitment sex offender criminal status continuing",
            "undocumented alien status criminal reentry deportation",
            "occupational debarment criminal regulatory status offense",
            "conditional release supervision violation criminal status",
            "probationer parolee status criminal fourth amendment",
            "corporate officer responsible corporate officer criminal liability",
            "strict liability food drug safety regulatory criminal conviction",
            "environmental criminal strict liability responsible party",
        ],
    },
    5: {
        "name": "Strict Liability and Public Welfare Offenses",
        "short": "strict_liability",
        "primary_node": "N5",
        "primary_failures": [
            "Procedural Contradiction N.2->5 (norm requires act without mens rea component)",
            "Norm Indeterminacy N.2 (scope of strict liability unclear)",
            "Conferral Failure N.3 (actor capacity irrelevant to prohibition)",
        ],
        "ontological_note": (
            "Strict liability offenses have a structurally thin N5: the legal act "
            "is the physical conduct alone, without any mental state component. "
            "This generates PC (Procedural Contradiction) at N2->N5 because the "
            "norm prohibits conduct that the actor may have had no rational "
            "capacity to avoid. The structural stress of strict liability is not "
            "that it is unjust (CD is not a moral measure) but that it severs "
            "the constitutive connection between role-bearing capacity (N3) and "
            "act (N5) that normally grounds criminal liability. "
            "The public welfare offense doctrine is a structural accommodation: "
            "it acknowledges the PC but justifies it by reference to regulatory "
            "necessity and reduced penalty. This is a managed structural "
            "incoherence -- the system acknowledges the contradiction and "
            "contains it rather than resolving it."
        ),
        "target": 500,
        "queries": [
            "strict liability criminal offense knowledge intent not required",
            "public welfare offense regulatory crime mens rea presumption",
            "statutory rape strict liability age consent criminal conviction",
            "drug possession strict liability knowledge presence constructive",
            "food safety drug adulteration strict liability criminal conviction",
            "environmental criminal strict liability discharge release",
            "traffic offense strict liability criminal civil infraction",
            "firearm registration strict liability National Firearms Act",
            "public welfare offense Morissette Staples criminal strict liability",
            "OSHA safety violation strict liability criminal conviction",
            "alcohol license dram shop strict liability criminal",
            "child pornography strict liability age knowledge criminal conviction",
            "corporate strict liability respondeat superior criminal conviction",
            "strict liability crime constitutional due process vagueness",
            "regulatory crime strict liability penalty proportionality",
            "food drug cosmetic act criminal strict liability conviction",
            "hazardous waste disposal RCRA criminal strict liability",
            "securities violation strict liability criminal conviction",
            "strict liability criminal defense good faith mistake of fact",
            "public welfare offense sentence imprisonment proportionality",
        ],
    },
    6: {
        "name": "Affirmative Defenses",
        "short": "affirmative_defenses",
        "primary_node": "N7",
        "primary_failures": [
            "Jurisdictional Contradiction N.2->6 (justification: competing norms)",
            "Conferral Failure N.3 (excuse: actor cannot bear criminal role)",
            "Correlativity Contradiction N.7 (elements proved but effect denied)",
        ],
        "ontological_note": (
            "Affirmative defenses are the primary N7 intervention category in "
            "criminal law. They operate AFTER the state's chain closes at N1-N6 "
            "and contest whether the legal effect (criminal liability) should "
            "attach. This makes them structurally different from denials of "
            "elements (which contest N2-N5) and procedural defenses (which "
            "contest N1 or N6). "
            "Justifications (self-defense, necessity, consent) generate JC at "
            "N2->N6: the state's norm prohibits the act, but a competing norm "
            "permits or requires it. The two norms cannot both govern the same "
            "act. Resolution requires determining which norm is lexically prior. "
            "Excuses (insanity, duress, infancy, intoxication) generate CF at N3: "
            "the actor could not structurally bear the criminal role because the "
            "institutional conditions for role-bearing were absent. "
            "The distinction matters structurally: justification means the state's "
            "chain was defective (the act was not wrongful); excuse means the "
            "chain was valid but the legal effect cannot attach to this actor."
        ),
        "target": 500,
        "queries": [
            "self-defense justified use force castle doctrine stand your ground",
            "insanity defense M'Naghten irresistible impulse ALI test criminal",
            "necessity justification lesser evil defense criminal conviction",
            "duress coercion criminal defense threat imminent harm",
            "entrapment predisposition government inducement criminal defense",
            "consent affirmative defense assault battery criminal conviction",
            "mistake of fact defense negates mens rea criminal conviction",
            "defense of others reasonable belief use of force criminal",
            "defense of property reasonable force criminal conviction",
            "diminished capacity partial defense mens rea criminal conviction",
            "voluntary intoxication specific intent general intent criminal",
            "infancy juvenile criminal responsibility age defense",
            "law enforcement justification crime prevention arrest use force",
            "automatism unconsciousness involuntary act criminal defense",
            "alibi mistaken identity criminal defense conviction reversal",
            "statute of limitations affirmative defense criminal prosecution bar",
            "double jeopardy collateral estoppel criminal defense bar",
            "immunized testimony use derivative use criminal prosecution bar",
            "outrageous government conduct due process criminal defense",
            "battered woman syndrome self-defense criminal conviction reversal",
        ],
    },
}

# ── STATE COURTS (CourtListener court IDs) ───────────────────────────────────
# State supreme courts -- highest authority on state criminal law
# CourtListener court IDs verified against:
# https://www.courtlistener.com/api/rest/v4/courts/?type=S&in_use=true
STATE_COURTS = [
    "cal",          # California Supreme Court
    "texcrimapp",   # Texas Court of Criminal Appeals
    "tex",          # Texas Supreme Court (civil — for some criminal)
    "ny",           # New York Court of Appeals
    "fla",          # Florida Supreme Court
    "ill",          # Illinois Supreme Court
    "pa",           # Pennsylvania Supreme Court
    "ohio",         # Ohio Supreme Court
    "mich",         # Michigan Supreme Court
    "ga",           # Georgia Supreme Court
    "nc",           # North Carolina Supreme Court
    "nj",           # New Jersey Supreme Court
    "va",           # Virginia Supreme Court
    "wash",         # Washington Supreme Court
    "ariz",         # Arizona Supreme Court
    "mass",         # Massachusetts Supreme Judicial Court
    "colo",         # Colorado Supreme Court
    "md",           # Maryland Court of Appeals
    "ind",          # Indiana Supreme Court
    "mo",           # Missouri Supreme Court
    "wis",          # Wisconsin Supreme Court
]

# Federal criminal courts (for federal offenses)
FEDERAL_CRIMINAL_COURTS = [
    "ca1", "ca2", "ca3", "ca4", "ca5", "ca6",
    "ca7", "ca8", "ca9", "ca10", "ca11", "cadc",
    "scotus",
]

DATE_RANGE = ("1985-01-01", "2024-12-31")


# ── DATABASE SETUP ────────────────────────────────────────────────────────────

def setup_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS criminal_cases (
        id              INTEGER PRIMARY KEY,
        category_id     INTEGER NOT NULL,
        category_name   TEXT,
        case_name       TEXT,
        docket_number   TEXT,
        court_id        TEXT,
        court_type      TEXT,    -- 'state' or 'federal'
        date_decided    TEXT,
        citation        TEXT,
        absolute_url    TEXT,
        query_matched   TEXT,
        status          TEXT DEFAULT 'collected',
        collected_at    TEXT
    );

    CREATE TABLE IF NOT EXISTS criminal_opinions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id         INTEGER REFERENCES criminal_cases(id),
        opinion_type    TEXT,
        plain_text      TEXT,
        html_text       TEXT,
        author          TEXT,
        per_curiam      INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS collection_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        court_id    TEXT,
        query       TEXT,
        page        INTEGER,
        count       INTEGER,
        timestamp   TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_criminal_cases_category
        ON criminal_cases(category_id);
    CREATE INDEX IF NOT EXISTS idx_criminal_cases_court
        ON criminal_cases(court_id);
    """)
    conn.commit()
    return conn


def case_exists(conn, case_id: int, category_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM criminal_cases WHERE id=? AND category_id=?",
        (case_id, category_id)
    ).fetchone() is not None


def count_cases(conn, category_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM criminal_cases WHERE category_id=?",
        (category_id,)
    ).fetchone()[0]


def insert_case(conn, category_id: int, cluster: dict, query: str,
                court_type: str = "federal"):
    # v4 search API returns camelCase field names
    cites = cluster.get("citation", []) or cluster.get("citations", [])
    citation = ""
    if isinstance(cites, list) and cites:
        first = cites[0]
        citation = first.get("cite", "") if isinstance(first, dict) else str(first)
    elif isinstance(cites, str):
        citation = cites

    # cluster_id is the numeric ID in v4 search; 'id' may be a URL
    case_id = (cluster.get("cluster_id") or cluster.get("id") or
               cluster.get("caseName", ""))

    conn.execute("""
        INSERT OR IGNORE INTO criminal_cases
        (id, category_id, category_name, case_name, docket_number, court_id,
         court_type, date_decided, citation, absolute_url, query_matched,
         status, collected_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        case_id,
        category_id,
        CRIMINAL_CATEGORIES[category_id]["name"],
        cluster.get("caseName") or cluster.get("case_name", ""),
        cluster.get("docketNumber") or cluster.get("docket_number", ""),
        cluster.get("court_id", ""),
        court_type,
        cluster.get("dateFiled") or cluster.get("date_filed", "") or
            cluster.get("date_decided", ""),
        citation,
        cluster.get("absolute_url", ""),
        query,
        "collected",
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()


# ── COLLECTION ─────────────────────────────────────────────────────────────

def collect_category(conn, category_id: int, api_key: str,
                     target: int, courts: list, court_type: str,
                     fetch_texts: bool = True, session=None):
    cat = CRIMINAL_CATEGORIES[category_id]
    log = logging.getLogger("collect_criminal")
    session = session or requests.Session()

    headers = {"Authorization": f"Token {api_key}"}

    existing = count_cases(conn, category_id)
    corpus_target = cat["target"]
    batch_goal = min(existing + target, corpus_target)
    log.info(f"C{category_id} {cat['name']}: {existing}/{corpus_target} already collected")

    if existing >= corpus_target:
        log.info(f"  Category {category_id} at target -- skipping")
        return

    for query in cat["queries"]:
        if count_cases(conn, category_id) >= batch_goal:
            break

        for page in range(1, 30):
            if count_cases(conn, category_id) >= batch_goal:
                break

            # Build params — court must be repeated for each value
            params = [
                ("q",                 query),
                ("type",              "o"),
                ("order_by",          "score desc"),
                ("stat_Precedential", "on"),
                ("filed_after",       DATE_RANGE[0]),
                ("filed_before",      DATE_RANGE[1]),
                ("page_size",         20),
                ("page",              page),
            ]
            for court_id in courts:
                params.append(("court", court_id))

            try:
                r = session.get(
                    "https://www.courtlistener.com/api/rest/v4/search/",
                    params=params, headers=headers, timeout=30
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning(f"  Search failed (q={query[:30]}, p={page}): {e}")
                time.sleep(5)
                break


            results = data.get("results", [])
            if page == 1:
                log.info(f"    p1: {len(results)} results "
                         f"(total={data.get('count','?')}) "
                         f"q='{query[:35]}'")
                if results:
                    log.info(f"    first result keys: {list(results[0].keys())}")
                    log.info(f"    first result id fields: "
                             f"id={results[0].get('id')} "
                             f"cluster_id={results[0].get('cluster_id')} "
                             f"case_name={results[0].get('case_name','')[:40]}")
            if not results:
                break

            new_on_page = 0
            for cluster in results:
                # v4 search API uses cluster_id (int); 'id' may be a URL string
                cid = cluster.get("cluster_id") or cluster.get("id")
                if not cid:
                    log.debug(f"    no id in result: {list(cluster.keys())}")
                    continue
                # Ensure integer
                try:
                    cid = int(cid)
                except (TypeError, ValueError):
                    log.debug(f"    non-integer id={cid!r} — skipping")
                    continue
                if case_exists(conn, cid, category_id):
                    continue

                insert_case(conn, category_id, cluster, query, court_type)
                new_on_page += 1

                # Fetch opinion text
                if fetch_texts:
                    try:
                        op_r = session.get(
                            "https://www.courtlistener.com/api/rest/v4/opinions/",
                            params={"cluster": cid, "page_size": 5},
                            headers=headers, timeout=25
                        )
                        op_r.raise_for_status()
                        for op in op_r.json().get("results", []):
                            text = op.get("plain_text", "") or op.get("html_text", "")
                            if text:
                                conn.execute("""
                                    INSERT OR IGNORE INTO criminal_opinions
                                    (case_id, opinion_type, plain_text, html_text,
                                     author, per_curiam)
                                    VALUES (?,?,?,?,?,?)
                                """, (
                                    cid,
                                    op.get("type", ""),
                                    op.get("plain_text", ""),
                                    op.get("html_text", ""),
                                    op.get("author_str", ""),
                                    1 if op.get("per_curiam") else 0,
                                ))
                                conn.commit()
                                break
                        time.sleep(0.3)
                    except Exception as e:
                        log.debug(f"  Opinion text fetch failed for {cid}: {e}")

            conn.execute(
                "INSERT INTO collection_log VALUES (NULL,?,?,?,?,?,?)",
                (category_id, court_type, query, page, new_on_page,
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()

            if new_on_page == 0 and page > 3:
                break

            time.sleep(1)

        n = count_cases(conn, category_id)
        log.info(f"  C{category_id} after '{query[:40]}': {n}/{target}")


def export_jsonl(conn, category_id: int, output_dir: str):
    rows = conn.execute("""
        SELECT c.id, c.case_name, c.category_id, c.category_name, c.court_id,
               c.court_type, c.date_decided, c.citation, c.absolute_url,
               o.plain_text
        FROM criminal_cases c
        LEFT JOIN criminal_opinions o ON o.case_id = c.id
        WHERE c.category_id = ?
    """, (category_id,)).fetchall()

    cat = CRIMINAL_CATEGORIES[category_id]
    path = Path(output_dir) / f"criminal_{category_id}_{cat['short']}.jsonl"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps({
                "id":            row[0],
                "case_name":     row[1],
                "category_id":   row[2],
                "category_name": row[3],
                "court_id":      row[4],
                "court_type":    row[5],
                "date_decided":  row[6],
                "citation":      row[7],
                "absolute_url":  row[8],
                "plain_text":    row[9] or "",
            }) + "\n")

    logging.getLogger("collect_criminal").info(
        f"Exported {len(rows)} cases to {path}"
    )
    return str(path)


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SOoL Criminal Ontology Corpus Collection"
    )
    parser.add_argument("--api-key",
                        default=os.environ.get("SOOL_CL_KEY", ""),
                        help="CourtListener API token (defaults to $SOOL_CL_KEY; "
                             "prefer the env var — argv is visible in `ps` and "
                             "is echoed into logs by subprocess tracebacks)")
    parser.add_argument("--db",       default="./sool_criminal.db")
    parser.add_argument("--output",   default="./criminal_corpus",
                        help="Output directory for JSONL files")
    parser.add_argument("--category", default="all",
                        help="Category ID(s) to collect: all | 1 | 1,2,3")
    parser.add_argument("--courts",   default="both",
                        choices=["state", "federal", "both"],
                        help="Which courts to collect from")
    parser.add_argument("--limit",    type=int, default=None,
                        help="Override target per category")
    parser.add_argument("--export",   action="store_true",
                        help="Export collected cases to JSONL and exit")
    parser.add_argument("--no-texts", action="store_true",
                        help="Skip fetching opinion text (faster, less useful)")
    parser.add_argument("--status",   action="store_true",
                        help="Print collection status and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[logging.StreamHandler()]
    )
    log = logging.getLogger("collect_criminal")

    conn = setup_db(args.db)

    if not args.api_key and not args.status:
        log.error("No CourtListener API token. Set SOOL_CL_KEY "
                  "(source ~/.sool_env) or pass --api-key.")
        sys.exit(1)

    if args.status:
        print("\nSOoL Criminal Corpus Status")
        print("=" * 50)
        total = 0
        for cat_id, cat in CRIMINAL_CATEGORIES.items():
            n = count_cases(conn, cat_id)
            total += n
            pct = n / cat["target"] * 100
            bar = "█" * (n * 20 // cat["target"]) + "░" * (20 - n * 20 // cat["target"])
            print(f"  C{cat_id} {cat['name'][:35]:<35} "
                  f"[{bar}] {n:>4}/{cat['target']}  {pct:.0f}%")
        print(f"\n  TOTAL: {total:,} / {sum(c['target'] for c in CRIMINAL_CATEGORIES.values()):,}")
        return

    if args.export:
        for cat_id in CRIMINAL_CATEGORIES:
            export_jsonl(conn, cat_id, args.output)
        return

    # Determine categories
    if args.category == "all":
        cat_ids = list(CRIMINAL_CATEGORIES.keys())
    else:
        cat_ids = [int(c) for c in args.category.split(",")]

    # Determine courts
    if args.courts == "state":
        courts_to_use = [("state", STATE_COURTS)]
    elif args.courts == "federal":
        courts_to_use = [("federal", FEDERAL_CRIMINAL_COURTS)]
    else:
        courts_to_use = [
            ("state",   STATE_COURTS),
            ("federal", FEDERAL_CRIMINAL_COURTS),
        ]

    log.info("=" * 60)
    log.info("SOoL Criminal Ontology Corpus Collection")
    log.info(f"Categories: {cat_ids}")
    log.info(f"Courts: {[ct for ct, _ in courts_to_use]}")
    log.info("=" * 60)

    session = requests.Session()
    session.headers["User-Agent"] = (
        "SOoL-Criminal-Research/1.0 (SEAL Lab, Texas A&M; "
        "drkoepsell@tamu.edu; Structural Ontology of Criminal Norms)"
    )

    for cat_id in cat_ids:
        cat = CRIMINAL_CATEGORIES[cat_id]
        target = args.limit or cat["target"]

        for court_type, court_list in courts_to_use:
            log.info(f"\nCollecting C{cat_id} from {court_type} courts...")
            collect_category(
                conn=conn,
                category_id=cat_id,
                api_key=args.api_key,
                target=target // len(courts_to_use),
                courts=court_list,
                court_type=court_type,
                fetch_texts=not args.no_texts,
                session=session,
            )

    log.info("\nExporting JSONL files...")
    for cat_id in cat_ids:
        export_jsonl(conn, cat_id, args.output)

    log.info("\nCollection complete.")
    log.info(f"Database: {args.db}")
    log.info(f"JSONL: {args.output}/")


if __name__ == "__main__":
    main()
