#!/usr/bin/env python3
"""
annotate_criminal.py -- SOoL Criminal Ontology Annotation Pipeline
===================================================================
SEAL Lab, Texas A&M University

Annotates criminal law opinions using the MLC framework from the
STATE'S PERSPECTIVE as claimant.

KEY DIFFERENCE FROM CIVIL/ADMINISTRATIVE CORPUS:
    Civil corpus:    Claimant = individual asserting a right
    Criminal corpus: Claimant = STATE asserting criminal liability

    protection_granted = STATE PREVAILS (conviction upheld or elements proved)
    protection_denied  = DEFENDANT PREVAILS (acquittal, dismissal, reversal)

The MLC maps to the criminal chain as follows:
    N1 = Criminal statute (legislature's authority to prohibit)
    N2 = Elements of offense (determinate behavioral standard)
    N3 = Defendant as criminal actor (capacity, mens rea as role condition)
    N4 = Actus reus circumstances (triggering facts)
    N5 = The prohibited act (conduct element, including mental state)
    N6 = The state / people as institutional target of obligation
    N7 = Criminal liability (does guilt attach?)
    N8 = Sentence (punishment as repair mechanism)

Usage:
    python3 annotate_criminal.py --api-key KEY --category all
    python3 annotate_criminal.py --api-key KEY --category 1,6
    python3 annotate_criminal.py --api-key KEY --reannotate-errors
"""

import argparse, json, logging, os, re, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

# ── CD WEIGHTS (identical to civil corpus) ───────────────────────────────────
CD_WEIGHTS = {
    'CF':0.15, 'AINF':0.12, 'JC':0.10, 'RC3':0.14, 'PC':0.09, 'TC':0.08,
    'FM':0.11, 'NI':0.07, 'RF':0.11, 'RCL':0.18, 'CC':0.14, 'SE':0.10,
    'RPF':0.13
}

CRIMINAL_CATEGORIES = {
    1: "homicide_violence",
    2: "inchoate_offenses",
    3: "property_fraud",
    4: "status_regulatory",
    5: "strict_liability",
    6: "affirmative_defenses",
}

# ── CRIMINAL MLC SYSTEM PROMPT ────────────────────────────────────────────────

CRIMINAL_SYSTEM_PROMPT = """You are a legal ontologist trained in the Structural Ontology of the Law (SOoL), specializing in criminal law.

CRITICAL PERSPECTIVE RULE: In criminal law annotation, the CLAIMANT is THE STATE (the People, the Government). The state asserts criminal liability against the defendant.

    protection_granted = STATE PREVAILS (conviction upheld, elements proved, defense rejected)
    protection_denied  = DEFENDANT PREVAILS (acquittal, reversal, dismissal, defense succeeds)

THE CRIMINAL MLC -- 8 NODES:
  N1 Source of Authority: The criminal statute and legislature's authority to prohibit this conduct.
     CF fires when the statute is void for vagueness, retroactive, or exceeds legislative authority.
  N2 Norm: The elements of the offense as a determinate behavioral standard.
     NI fires when elements are genuinely ambiguous (what counts as fraud? what is 'material'?).
  N3 Actor in Role: The defendant as the bearer of criminal obligation.
     The mens rea requirement is a ROLE-CONSTITUTING CONDITION at N3, not merely a fact.
     CF fires for incapacity defenses (insanity, infancy) -- actor cannot structurally bear criminal role.
     RC3 fires when the same act is simultaneously required and prohibited by competing roles.
  N4 Triggering Facts: The actus reus circumstances -- the factual predicate for criminal liability.
     FM fires for entrapment (state manufactured facts), Brady violations, planted evidence.
  N5 Legal Act: The prohibited conduct including the mental state component.
     PC fires for strict liability offenses (norm requires act without the mens rea role condition).
     For inchoate offenses: N5 is partial or indeterminate (chain never completed).
  N6 Target: The state/people as institutional target bearing the enforcement obligation.
     Usually closed. JC fires when federal and state criminal regimes conflict over same conduct.
  N7 Legal Effect: Does CRIMINAL LIABILITY attach to this defendant for this act?
     THIS IS THE PIVOTAL NODE. Affirmative defenses operate here:
       - Justifications (self-defense, necessity): JC at N2->N6 -- competing norm permits the act
       - Excuses (insanity, duress): CF at N3 -- actor cannot bear the criminal role
       - Correlativity (CC): elements proved but legal effect refused (selective prosecution?)
     RF fires when the state fails to prove an element beyond reasonable doubt.
  N8 Remedy: The sentence. This is the REPAIR mechanism for the criminal breach.
     RPF fires when sentence is unconstitutionally disproportionate (8th Amendment).
     RPF also fires independently (not as RF cascade) when sentencing procedure is defective.

MANDATORY CASCADE RULES:
  1. If N7=failed (defendant prevails) AND N8=failed: RPF MUST be in active_contradictions
  2. If N7=failed because element not proved: RF MUST fire
  3. If justification defense succeeds: JC fires (competing norms); N7=failed
  4. If excuse defense succeeds: CF fires at N3; N7=failed
  5. For inchoate offenses: N5=partial is expected; NI at N2 is expected
  6. For strict liability (C5): PC fires at N2->N5; N3 closure is partial

STRUCTURAL TYPOLOGY OF DEFENSES (key to accurate annotation):
  Self-defense, necessity, consent  --> JC at N2->N6 (competing norm permits act)
  Insanity, infancy, automatism      --> CF at N3 (actor cannot bear criminal role)
  Duress, coercion                   --> CC at N7 (liability proved but effect denied -- impossible compliance)
  Entrapment                         --> FM at N4 (state manufactured triggering facts)
  Mistake of fact                    --> NI at N2 (norm scope unclear) or N5=partial
  Alibi, mistaken identity           --> FM at N4 (triggering facts not proved)
  Double jeopardy                    --> CF at N1 (authority to prosecute exhausted)
  Statute of limitations             --> TC at N2<->N4 (temporal misalignment)

CHAIN OUTCOMES:
  protection_granted = state prevails (conviction upheld, appeal denied)
  protection_denied  = defendant prevails (reversal, acquittal, dismissal, defense succeeds)
  partial            = mixed (some counts upheld, some reversed; partial defense success)
  remanded           = sent back for further proceedings
  dismissed          = case dismissed without merits ruling

Return ONLY valid JSON, no preamble:
{
  "nodes": {
    "1": {"closure": "closed|failed|partial|indeterminate", "entity": "..."},
    "2": {"closure": "...", "entity": "...", "elements": ["element1", "element2"]},
    "3": {"closure": "...", "entity": "...", "mens_rea": "...", "capacity": "..."},
    "4": {"closure": "...", "entity": "..."},
    "5": {"closure": "...", "entity": "...", "act_type": "commission|omission|possession|status"},
    "6": {"closure": "...", "entity": "..."},
    "7": {"closure": "...", "entity": "..."},
    "8": {"closure": "...", "entity": "..."}
  },
  "active_contradictions": [],
  "contradiction_debt": 0.0,
  "chain_outcome": "...",
  "defense_type": "none|justification|excuse|procedural|capacity|proof",
  "offense_category": "homicide|inchoate|property_fraud|status|strict_liability|other",
  "mens_rea_type": "purposely|knowingly|recklessly|negligently|strict_liability|none",
  "confidence": "high|medium|low",
  "outcome_notes": "..."
}"""


# ── CATEGORY-SPECIFIC SUPPLEMENTS ────────────────────────────────────────────

CATEGORY_SUPPLEMENTS = {
    1: """
CATEGORY: HOMICIDE AND VIOLENT OFFENSES
Primary expected failure: N5 (act classification -- murder vs manslaughter)

Key structural issues:
- Degree distinction is a N2/N5 question: does the act meet the specific elements
  of first-degree (premeditation, deliberation) vs second-degree (implied malice)?
- Heat-of-passion manslaughter is a PARTIAL defense operating at N7: it acknowledges
  criminal liability but contests the degree. This is NOT a full N7 failure.
- Felony murder: the underlying felony is N4; the killing is N5; the merger question
  is NI at N2 (does the felony merge with the homicide?).
- Self-defense: JC at N2->N6 -- the norm permitting defense of life competes with
  the homicide prohibition. When self-defense succeeds, N7=failed (JC fires).
""",

    2: """
CATEGORY: INCHOATE OFFENSES
Primary expected failure: N4/N5 (incomplete chain)

Key structural issues:
- Attempt: N5=partial (the chain never completed). NI at N2 fires when the
  substantial step/dangerous proximity line is contested.
- Conspiracy: N4=closed at the agreement; N5=partial (the target offense not complete).
  Pinkerton liability extends N5 to acts of co-conspirators.
- Abandonment defense: severs the chain before N7 -- structural intervention
  that prevents the normative residue from attaching.
- Impossibility: factual impossibility = N4 contested (facts don't support completion);
  legal impossibility = N2 failed (no offense exists).
- TC fires when conspiracy is charged for acts that predate the agreement.
""",

    3: """
CATEGORY: PROPERTY CRIMES AND FRAUD
Primary expected failure: N2 (norm indeterminacy)

Key structural issues:
- Materiality in fraud: NI fires when reasonable person standard for materiality
  is genuinely contested. This is the paradigmatic N2 criminal stress case.
- Intent to permanently deprive: this is a N3 role condition in theft, not N4/N5.
  When contested, it generates NI at N2 (is this the right standard?) or
  CF at N3 (did actor bear the requisite mens rea role?).
- Robbery: N5 = taking by force. The force/intimidation element is a N5 question.
- Money laundering: JC fires when the predicate offense and laundering charges
  generate competing obligations over the same transaction.
- Fraud vs civil breach of contract: JC at N2 (criminal norm vs civil norm over
  same conduct) is a recurring structural tension.
""",

    4: """
CATEGORY: STATUS OFFENSES AND REGULATORY CRIMES
Primary expected failure: N3 (role as prohibition)

Key structural issues:
- Felon-in-possession: N3 is the heart of the offense. The prior conviction
  is a role condition that generates the prohibition. CF fires when the prior
  conviction is itself constitutionally infirm.
- Sex offender registration: RCL fires systematically -- the actor has discharged
  the sentence (N8 closed in the original case) but continues bearing obligations.
  This is the clearest RCL pattern in criminal law.
- Strict regulatory liability: AI fires when agency rulemaking (N1->N2) effectively
  defines criminal conduct without legislative authorization. Post-Loper Bright
  this is increasingly contestable.
- Responsible corporate officer: RC3 fires when the same person bears both the
  corporate officer role (obligating supervision) and the personal actor role
  (not directly involved in violation). Classic dual-role criminal structure.
""",

    5: """
CATEGORY: STRICT LIABILITY AND PUBLIC WELFARE OFFENSES
Primary expected failure: N5 thin / PC

Key structural issues:
- PC fires at N2->N5 in ALL strict liability cases: the norm requires the act
  without the mens rea role condition that normally constitutes the criminal act.
  This is a managed structural contradiction -- the system acknowledges it.
- N3 closure is PARTIAL for strict liability: the actor capacity condition
  (rational agency, ability to conform conduct to norm) is severed from liability.
- The public welfare doctrine is an explicit structural accommodation: it acknowledges
  the PC and justifies it by reduced penalty and regulatory necessity.
- Constitutional challenge to strict liability: NI at N2 + CF at N3 together
  generate the due process vagueness argument.
- Statutory rape: N3=partial (age is a role condition that the actor may not have
  known about). The strict liability element generates PC at N2->N5.
""",

    6: """
CATEGORY: AFFIRMATIVE DEFENSES
Primary expected failure: N7 (legal effect contested despite proved elements)

Key structural issues:
- This category ALWAYS has N1-N6 substantially closed. The analytical focus is N7.
- Justification defenses (self-defense, necessity, consent): JC at N2->N6.
  Two norms compete -- the prohibition and the permission. When justification
  succeeds: N7=failed, JC fires, chain_outcome=protection_denied.
- Excuse defenses (insanity, duress, infancy, involuntary intoxication): CF at N3.
  The actor cannot structurally bear the criminal role. When excuse succeeds:
  N7=failed, CF fires, chain_outcome=protection_denied.
- Entrapment is an N4 defense (FM) but operates procedurally at N7: even with
  N4 contested, the court may find for state on predisposition.
- Diminished capacity is a PARTIAL excuse -- does not generate full CF but
  reduces the mens rea role condition, generating NI at N2 or partial N3.
- When defense FAILS (state prevails): protection_granted, N7=closed.
  Active contradictions reflect why the defense failed -- e.g., NI at N2 if
  the justification standard was genuinely contested but resolved for state.
""",
}


# ── ANNOTATION PIPELINE ───────────────────────────────────────────────────────

def compute_cd(cts: list) -> float:
    return round(sum(CD_WEIGHTS.get(ct, 0) for ct in cts), 4)


# Renamed from enforce_cascade_rules 2026-08-06. It no longer enforces a cascade —
# rules 1 and 2 (N7-failed -> RF/RPF, and overwriting the Node 8 closure) were removed
# as the v1 defect. What remains injects an expected contradiction type from the CRIME
# CATEGORY, which is a different and unresolved problem; the name should say so rather
# than advertise a cascade that is gone.
def apply_category_expectations(ann: dict, category_id: int) -> tuple:
    nodes = ann.get("nodes", {})
    cts   = set(ann.get("active_contradictions", []))
    fixes = []

    n7 = nodes.get("7", {}).get("closure", "")
    n8 = nodes.get("8", {}).get("closure", "")

    # ── RULES 1 AND 2 REMOVED 2026-08-06 (v2 regime) ─────────────────────────
    #
    # They read:
    #     if n7 in ("failed","partial"): cts.add("RF")
    #     if n7 == "failed":             cts.add("RPF")
    #                                    nodes["8"]["closure"] = "failed"
    #
    # This is the v1 defect (annotation RULE 1 / RULE 5) implemented in code, and it
    # went further than the prompt version by *overwriting* the annotator's Node 8
    # closure. On the civil corpus the same rules produced RF ~64%; removing them took
    # RF to 2.8%. On SCOTUS the equivalent code forced RF onto 99.5% of cases.
    #
    # Under v2, RF / CC / RPF are assigned on the court's own reasoning, and Node 8 is
    # assessed on its own evidence — divergence from Node 7 is a finding, not an error.
    # No closure-based replacement rule is safe here: the point is that the type and
    # the closure must be independently observed.

    # NOTE — RULES 3-5 BELOW ARE A SEPARATE, UNRESOLVED PROBLEM.
    #
    # They inject a contradiction type from the CRIME CATEGORY rather than from the
    # case: strict liability -> PC, inchoate + partial N5 -> NI, status offense -> RCL.
    # sool_criminal_norms.ttl declares an expected primary failure node per category,
    # and these rules then write that expectation into the data. Any subsequent finding
    # that criminal categories cluster by node would therefore be circular — the
    # clustering was inserted, not observed.
    #
    # Left in place deliberately: unlike rules 1-2 these are not the identified v1
    # defect, and removing them changes the criminal methodology, which is the PI's
    # call. But no criminal-domain structural claim should be published while they
    # stand. daily_criminal.py remains suspended in cron.

    # Rule 3: Strict liability (C5) -> PC expected
    if category_id == 5 and "PC" not in cts:
        cts.add("PC")
        fixes.append("Added PC: strict liability offense -> procedural contradiction expected")

    # Rule 4: Inchoate (C2) with partial N5 -> NI expected
    if category_id == 2:
        n5 = nodes.get("5", {}).get("closure", "")
        if n5 == "partial" and "NI" not in cts:
            cts.add("NI")
            fixes.append("Added NI: inchoate offense with partial N5")

    # Rule 5: Status offense (C4) with conviction -> check for RCL
    if category_id == 4 and ann.get("chain_outcome") == "protection_granted":
        offense_name = nodes.get("5", {}).get("entity", "").lower()
        if any(kw in offense_name for kw in ["registration", "status", "felon"]):
            if "RCL" not in cts:
                cts.add("RCL")
                fixes.append("Added RCL: status offense generates recognition collapse")

    ann["active_contradictions"] = sorted(cts)
    ann["contradiction_debt"] = compute_cd(list(cts))
    ann["nodes"] = nodes
    return ann, fixes


def build_prompt(case_name: str, category_id: int, text: str) -> str:
    supplement = CATEGORY_SUPPLEMENTS.get(category_id, "")
    return f"""{CRIMINAL_SYSTEM_PROMPT}{supplement}

CASE: {case_name}
OFFENSE CATEGORY: C{category_id} {CRIMINAL_CATEGORIES[category_id]}

OPINION TEXT:
{text[:5500]}"""


def annotate_case(case_id: int, case_name: str, category_id: int,
                  text: str, client: anthropic.Anthropic,
                  model: str = "claude-sonnet-5") -> dict:
    prompt = build_prompt(case_name, category_id, text)

    message = client.messages.create(
        model=model,
        max_tokens=2200,
        # Sonnet 5 thinks by default and max_tokens covers thinking + text;
        # disabling keeps the JSON-emitting behaviour this prompt expects.
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text

    # Parse JSON
    raw_clean = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.MULTILINE)
    raw_clean = re.sub(r'\s*```$', '', raw_clean, flags=re.MULTILINE)
    start = raw_clean.find('{')
    end   = raw_clean.rfind('}') + 1
    ann   = json.loads(raw_clean[start:end])

    # Apply cascade rules
    ann, fixes = apply_category_expectations(ann, category_id)

    ann["case_id"]        = case_id
    ann["case_name"]      = case_name
    ann["category_id"]    = category_id
    ann["annotation_date"] = datetime.now(timezone.utc).isoformat()
    ann["cascade_fixes"]  = fixes
    ann["raw_response"]   = raw[:2000]

    return ann


def setup_annotations_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS criminal_annotations (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id             INTEGER,
        case_name           TEXT,
        category_id         INTEGER,
        category_name       TEXT,
        court_id            TEXT,
        court_type          TEXT,
        date_decided        TEXT,

        node1_closure       TEXT, node1_entity    TEXT,
        node2_closure       TEXT, node2_entity    TEXT, node2_elements TEXT,
        node3_closure       TEXT, node3_entity    TEXT,
        node3_mens_rea      TEXT, node3_capacity  TEXT,
        node4_closure       TEXT, node4_entity    TEXT,
        node5_closure       TEXT, node5_entity    TEXT, node5_act_type TEXT,
        node6_closure       TEXT, node6_entity    TEXT,
        node7_closure       TEXT, node7_entity    TEXT,
        node8_closure       TEXT, node8_entity    TEXT,

        active_contradictions TEXT,
        contradiction_debt    REAL,
        chain_outcome         TEXT,
        defense_type          TEXT,
        offense_category      TEXT,
        mens_rea_type         TEXT,
        confidence            TEXT,
        outcome_notes         TEXT,

        needs_review          INTEGER DEFAULT 0,
        review_note           TEXT,
        annotator             TEXT,
        annotation_date       TEXT,
        raw_response          TEXT,
        cascade_fixes         TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_cann_category ON criminal_annotations(category_id);
    CREATE INDEX IF NOT EXISTS idx_cann_outcome ON criminal_annotations(chain_outcome);
    CREATE INDEX IF NOT EXISTS idx_cann_cd ON criminal_annotations(contradiction_debt);
    """)
    conn.commit()
    return conn


def save_annotation(ann_conn: sqlite3.Connection, ann: dict,
                    case_meta: dict):
    nodes = ann.get("nodes", {})
    ann_conn.execute("""
        INSERT OR REPLACE INTO criminal_annotations
        (case_id, case_name, category_id, category_name, court_id, court_type,
         date_decided,
         node1_closure, node1_entity,
         node2_closure, node2_entity, node2_elements,
         node3_closure, node3_entity, node3_mens_rea, node3_capacity,
         node4_closure, node4_entity,
         node5_closure, node5_entity, node5_act_type,
         node6_closure, node6_entity,
         node7_closure, node7_entity,
         node8_closure, node8_entity,
         active_contradictions, contradiction_debt, chain_outcome,
         defense_type, offense_category, mens_rea_type,
         confidence, outcome_notes,
         needs_review, annotator, annotation_date,
         raw_response, cascade_fixes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ann.get("case_id"),
        ann.get("case_name", ""),
        ann.get("category_id"),
        CRIMINAL_CATEGORIES.get(ann.get("category_id"), ""),
        case_meta.get("court_id", ""),
        case_meta.get("court_type", ""),
        case_meta.get("date_decided", ""),

        nodes.get("1", {}).get("closure"), nodes.get("1", {}).get("entity", ""),
        nodes.get("2", {}).get("closure"), nodes.get("2", {}).get("entity", ""),
        json.dumps(nodes.get("2", {}).get("elements", [])),
        nodes.get("3", {}).get("closure"), nodes.get("3", {}).get("entity", ""),
        nodes.get("3", {}).get("mens_rea", ""), nodes.get("3", {}).get("capacity", ""),
        nodes.get("4", {}).get("closure"), nodes.get("4", {}).get("entity", ""),
        nodes.get("5", {}).get("closure"), nodes.get("5", {}).get("entity", ""),
        nodes.get("5", {}).get("act_type", ""),
        nodes.get("6", {}).get("closure"), nodes.get("6", {}).get("entity", ""),
        nodes.get("7", {}).get("closure"), nodes.get("7", {}).get("entity", ""),
        nodes.get("8", {}).get("closure"), nodes.get("8", {}).get("entity", ""),

        json.dumps(ann.get("active_contradictions", [])),
        ann.get("contradiction_debt", 0),
        ann.get("chain_outcome", ""),
        ann.get("defense_type", "none"),
        ann.get("offense_category", ""),
        ann.get("mens_rea_type", ""),
        ann.get("confidence", "low"),
        ann.get("outcome_notes", ""),

        0,
        "claude-criminal-v1",
        ann.get("annotation_date", ""),
        ann.get("raw_response", "")[:2000],
        json.dumps(ann.get("cascade_fixes", [])),
    ))
    ann_conn.commit()


def already_annotated(ann_conn: sqlite3.Connection,
                      case_id: int, category_id: int) -> bool:
    return ann_conn.execute(
        "SELECT 1 FROM criminal_annotations WHERE case_id=? AND category_id=?",
        (case_id, category_id)
    ).fetchone() is not None


def main():
    parser = argparse.ArgumentParser(
        description="SOoL Criminal Ontology Annotation Pipeline"
    )
    parser.add_argument("--api-key",
                        default=(os.environ.get("ANTHROPIC_API_KEY")
                                 or os.environ.get("SOOL_ANTHROPIC_KEY", "")),
                        help="Anthropic API key (defaults to $ANTHROPIC_API_KEY; "
                             "prefer the env var — argv is visible in `ps` and "
                             "is echoed into logs by subprocess tracebacks)")
    parser.add_argument("--corpus-db", default="./sool_criminal.db")
    parser.add_argument("--ann-db",    default="./sool_criminal_annotations.db")
    parser.add_argument("--category",  default="all",
                        help="Category IDs: all | 1 | 1,2,3")
    parser.add_argument("--limit",     type=int, default=None,
                        help="Max cases to annotate per category this run")
    parser.add_argument("--model",     default="claude-sonnet-5")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s"
    )
    log = logging.getLogger("annotate_criminal")

    corpus_conn = sqlite3.connect(args.corpus_db)
    corpus_conn.row_factory = sqlite3.Row
    ann_conn = setup_annotations_db(args.ann_db)

    client = anthropic.Anthropic(api_key=args.api_key)

    if args.category == "all":
        cat_ids = list(CRIMINAL_CATEGORIES.keys())
    else:
        cat_ids = [int(c) for c in args.category.split(",")]

    total_annotated = 0
    total_errors    = 0

    for cat_id in cat_ids:
        log.info(f"\n── Category C{cat_id}: {CRIMINAL_CATEGORIES[cat_id]} ──")

        cases = corpus_conn.execute("""
            SELECT c.id, c.case_name, c.category_id, c.court_id, c.court_type,
                   c.date_decided, o.plain_text
            FROM criminal_cases c
            LEFT JOIN criminal_opinions o ON o.case_id = c.id
            WHERE c.category_id = ?
            AND o.plain_text IS NOT NULL
            AND LENGTH(o.plain_text) > 300
            ORDER BY c.id
        """, (cat_id,)).fetchall()

        n_done = 0
        for row in cases:
            if args.limit and n_done >= args.limit:
                break

            if already_annotated(ann_conn, row["id"], cat_id):
                continue

            log.info(f"  [{n_done+1}] {row['case_name'][:55]}")

            try:
                ann = annotate_case(
                    case_id=row["id"],
                    case_name=row["case_name"],
                    category_id=cat_id,
                    text=row["plain_text"],
                    client=client,
                    model=args.model,
                )

                save_annotation(ann_conn, ann, dict(row))

                log.info(f"      outcome={ann['chain_outcome']}"
                         f"  CD={ann['contradiction_debt']:.3f}"
                         f"  CTs={ann['active_contradictions']}"
                         f"  defense={ann.get('defense_type','?')}")

                if ann.get("cascade_fixes"):
                    for fix in ann["cascade_fixes"]:
                        log.debug(f"      cascade: {fix}")

                n_done += 1
                total_annotated += 1
                time.sleep(0.5)

            except Exception as e:
                log.error(f"      ERROR: {e}")
                total_errors += 1
                time.sleep(2)

        log.info(f"  C{cat_id} done: {n_done} annotated")

    log.info(f"\nAnnotation complete: {total_annotated} cases, {total_errors} errors")
    log.info(f"Annotations: {args.ann_db}")


if __name__ == "__main__":
    main()
