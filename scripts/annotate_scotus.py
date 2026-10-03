"""
annotate_scotus.py — SOoL MLC Annotation of SCOTUS Transcripts
===============================================================
SEAL Lab, Texas A&M University

Key design: Pass 1 does NOT ask the model to output CT codes. It outputs
plain-English descriptions of structural failures at each node. A Python
function then maps those descriptions to CT codes deterministically.
This prevents the model from hallucinating immigration/asylum context
when it sees abbreviated CT codes like NI, CC, RF, SE.

Usage:
    python3 annotate_scotus.py                   # annotate all unannotated
    python3 annotate_scotus.py --docket 24-1021  # single case
    python3 annotate_scotus.py --limit 20
    python3 annotate_scotus.py --reannotate
"""

import argparse, json, logging, os, re, sqlite3, sys, time
from datetime import datetime
from pathlib import Path
import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path("logs") / f"scotus_ann_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
log = logging.getLogger(__name__)
Path("logs").mkdir(exist_ok=True)

# Annotation regime for rows written by this script. Rows produced before 2026-08-06
# carry a code-level cascade that forced RF on 99.5% of cases; they are backfilled as
# scotus-v1-cascade so the two are never pooled. See typology/AMENDMENTS.md §3.5.
SCOTUS_REGIME  = "scotus-v2"

MODEL           = "claude-opus-4-5"
TRANSCRIPT_CHARS = 12000
RATE_LIMIT      = 0.5

# ── CT WEIGHTS ────────────────────────────────────────────────────────────────
CT_WEIGHTS = {
    "CF":0.15,"AI":0.12,"JC":0.10,"RC3":0.14,"PC":0.09,"TC":0.08,
    "FM":0.11,"NI":0.07,"RF":0.11,"RCL":0.18,"CC":0.14,"SE":0.10,"RPF":0.13
}

# ── PASS 1 SYSTEM PROMPT — NO CT CODES ────────────────────────────────────────
# The model describes structural failures in plain English.
# Python maps descriptions to CT codes. The model never sees abbreviations.

SYSTEM_PASS1 = """You are a formal legal ontologist. Analyze oral argument transcripts using the Minimum Legal Chain (MLC).

THE MLC — eight structural nodes that must all close for a valid legal outcome:

N1 - Source of Authority: Does a valid legal authority (constitution, statute, precedent) ground this claim?
N2 - Norm: Is the specific legal rule clear and determinate enough to apply to these facts?
N3 - Actor in Role: Is the party properly situated in their legal role to bear this obligation/right?
N4 - Triggering Facts: Are the facts that activate the norm established and undisputed?
N5 - Legal Act: Did the relevant legal act or omission occur?
N6 - Target: Is the party against whom the legal effect runs properly identified and situated?
N7 - Legal Effect (PIVOTAL): Does the asserted legal consequence actually attach?
N8 - Remedy: Is a remedy available and accessible if the effect attaches?

NODE CLOSURE VALUES:
"closed"        = node fully satisfied, chain continues
"failed"        = node not satisfied, chain breaks
"partial"       = node partially satisfied, structural stress present
"indeterminate" = cannot be determined from the transcript

TRANSCRIPT ANALYSIS GUIDANCE:
You are reading an oral argument. Assess nodes based on structural stress revealed in the arguments:
- Which nodes do Justices probe most skeptically? (likely partial or failed)
- Where is the petitioner's argument strong? (likely closed)
- Intense questioning about a node's merits = that node is contested = partial or failed
N7 in particular: skeptical Justice questioning about whether the claimed right actually attaches = N7 partial or failed.

IMPORTANT:
- Do NOT state who will win
- Do NOT use any abbreviated codes in your response
- For each node, describe in plain English what structural condition it represents and whether it is satisfied
- For failed/partial nodes, describe the structural failure in one plain sentence

Return ONLY valid JSON:
{
  "legal_domain": "one sentence: what area of law, what is the exact question, who wants what",
  "claimant": "name of petitioner",
  "respondent": "name of respondent",
  "nodes": {
    "1": {"closure": "closed|failed|partial|indeterminate", "entity": "what authority", "justification": "why this closure"},
    "2": {"closure": "...", "entity": "what rule", "justification": "..."},
    "3": {"closure": "...", "entity": "who is the actor", "justification": "..."},
    "4": {"closure": "...", "entity": "what facts", "justification": "..."},
    "5": {"closure": "...", "entity": "what act", "justification": "..."},
    "6": {"closure": "...", "entity": "who is the target", "justification": "..."},
    "7": {"closure": "...", "entity": "what legal effect", "justification": "..."},
    "8": {"closure": "...", "entity": "what remedy", "justification": "..."}
  },
  "structural_failures": [
    "plain English description of each structural failure at each failed/partial node"
  ],
  "confidence": "high|medium|low"
}"""

# ── CT MAPPING FROM PLAIN ENGLISH DESCRIPTIONS ───────────────────────────────
# Maps structural failure descriptions to CT codes using keyword matching.
# This is domain-neutral — no immigration associations possible.

CT_PATTERNS = [
    # Each entry: (CT_code, list of keyword patterns that indicate this CT)
    ("RCL", ["subjecthood", "strip", "personhood", "civil death", "status stripped",
             "obligations without rights", "enforced without standing"]),
    ("CF",  ["vest", "confer", "authority failed to grant", "not properly authorized",
             "lacks standing to bear", "role not conferred", "conferral"]),
    ("AI",  ["will displaces", "personal preference", "substitut", "no rule",
             "arbitrary", "authority inflation", "norm displaced by will"]),
    ("RC3", ["incompatible roles", "conflicting obligations", "same actor",
             "role contradiction", "dual role", "wearing two hats"]),
    ("JC",  ["competing regime", "two frameworks", "jurisdictional", "conflict of laws",
             "federal and state", "preemption", "two norms govern"]),
    ("PC",  ["procedure blocks", "cannot comply through", "procedural barrier",
             "norm's own procedure", "catch-22", "procedural contradiction"]),
    ("TC",  ["retroactive", "temporal", "timing", "before it existed",
             "anachronistic", "time mismatch", "applied retroactively"]),
    ("FM",  ["fabricated", "suppressed facts", "indeterminate facts", "manufactured",
             "contested facts", "disputed factual basis", "fact manipulation"]),
    ("NI",  ["vague rule", "indeterminate standard", "unclear test", "no clear rule",
             "contested legal standard", "unresolved legal question", "what test applies",
             "norm is unclear", "ambiguous standard", "norm indeterminacy"]),
    ("RF",  ["refuses to recognize", "denied recognition", "right not recognized",
             "court won't acknowledge", "recognition failure", "effect not recognized",
             "immunity bars", "not recognized as"]),
    ("CC",  ["right without duty", "duty not honored", "no correlative", "one-sided",
             "correlativity", "right claimed but", "asymmetric"]),
    ("SE",  ["self-defeating", "undermines itself", "destabilizes", "circular",
             "contradicts its own basis", "self-undermining", "validity depends on"]),
    ("RPF", ["remedy blocked", "no accessible remedy", "remedy unavailable",
             "cannot enforce", "repair impossible", "remedy fails", "inaccessible remedy"]),
]

# Also map from node closure patterns directly
NODE_CT_MAP = {
    # If N7 fails → RF must fire (court not recognizing the right)
    # If N8 fails after N7 fails → RPF must fire
    # If N2 is partial/failed → NI likely
    # If N6 is partial → RF or RCL
}

def map_failures_to_cts(structural_failures: list[str], nodes: dict) -> list[str]:
    """
    Map plain-English structural failure descriptions to CT codes.
    Uses keyword matching — completely domain-neutral.
    """
    failures_text = " ".join(structural_failures).lower()
    node_justifications = " ".join(
        n.get("justification", "") for n in nodes.values()
    ).lower()
    combined = failures_text + " " + node_justifications

    cts = set()

    # Pattern matching
    for ct_code, patterns in CT_PATTERNS:
        for pattern in patterns:
            if pattern.lower() in combined:
                cts.add(ct_code)
                break

    # ── CASCADE RULES REMOVED 2026-08-06 (v2 regime) ──────────────────────────
    #
    # This function used to derive contradiction types from node CLOSURE STATES as
    # well as from text:
    #
    #     if n7 in ("failed", "partial"):            cts.add("RF")
    #     if n7 == "failed" and n8 in (...):         cts.add("RPF")
    #     if n6 in ("partial", "failed"):            cts.add("RF")
    #     if not cts and n7 in ("failed","partial"): cts.add("RF")   # "at minimum"
    #
    # That is the v1 defect the civil pipeline was remediated to remove (annotation
    # RULE 1 / RULE 5), reimplemented here in code — which is worse, because a prompt
    # rule can be disregarded by the model whereas this rewrote its output
    # unconditionally. It also went further than v1 by firing on "partial" and by
    # adding an RF floor.
    #
    # Measured effect on the 1,023 rows produced under it: RF fired on 99.5% of cases,
    # against 2.8% in the corrected civil corpus — a ~35x inflation. Those rows record
    # rule compliance, not recognition failure, and any backtest over them is measuring
    # the rule. They are retained but must be treated as regime `scotus-v1-cascade`.
    #
    # Under v2, RF / CC / RPF are assigned on textual evidence only. The keyword
    # matching above is that evidence. Node closures are NOT evidence for a
    # contradiction type; they are a separate observation about the same case, and
    # letting one determine the other is what manufactured the original finding.
    #
    # Deliberately NOT replaced with a weaker rule. There is no closure-based rule that
    # is safe here: the whole point is that the two must be independently observed.
    # See typology/AMENDMENTS.md and the v2 prompt's "ASSIGNING RF, CC AND RPF" block.

    return sorted(cts)


# ── PASS 2 SYSTEM PROMPT ──────────────────────────────────────────────────────

SYSTEM_PASS2 = """Derive chain_outcome STRUCTURALLY from node closures only. No opinion text.

RULES:
1. N7=closed AND N8=closed → protection_granted
2. N7=failed → protection_denied
3. N7=partial AND N8=closed → partial
4. N7=partial AND N8=failed → protection_denied
5. N7=indeterminate → protection_denied (default)

Claimant = petitioner. protection_granted = petitioner wins.

Also write a structural_narrative: 2-3 sentences explaining the structural stress in this
specific case using the ACTUAL legal domain (sovereign immunity, First Amendment, etc).
Do NOT use immigration terminology unless this is actually an immigration case.

Return ONLY valid JSON:
{
  "chain_outcome": "protection_granted|protection_denied|partial|indeterminate",
  "outcome_derivation": "which node drove the outcome",
  "outcome_confidence": "high|medium|low",
  "structural_narrative": "plain English explanation of structural stress in this specific legal domain"
}"""

# ── PASS 3 SYSTEM PROMPT ──────────────────────────────────────────────────────

SYSTEM_PASS3 = """Devil's advocate for a legal structural analysis. Argue the STRONGEST case for the OPPOSITE outcome.

Identify the most contestable node closures. Explain what alternative readings would produce.
Assign adversarial_strength (0.0=no plausible alternative; 1.0=equally defensible).

Return ONLY valid JSON:
{
  "contestable_nodes": ["N2", "N7"],
  "alternative_assessment": "plain English alternative reading",
  "opposite_outcome_defensible": false,
  "adversarial_strength": 0.0,
  "adversarial_notes": "specific basis for alternative reading"
}"""

# ── PASS 4 SYSTEM PROMPT — DISSENT MLC ANALYSIS ──────────────────────────────

SYSTEM_PASS4 = """You are a formal legal ontologist. Analyze the DISSENTING opinion in this case using the Minimum Legal Chain (MLC).

THE MLC — eight structural nodes:
N1 - Source of Authority: Does a valid legal authority ground this claim?
N2 - Norm: Is the specific legal rule clear and determinate?
N3 - Actor in Role: Is the party properly situated in their legal role?
N4 - Triggering Facts: Are the activating facts established and undisputed?
N5 - Legal Act: Did the relevant legal act or omission occur?
N6 - Target: Is the opposing party properly identified and situated?
N7 - Legal Effect (PIVOTAL): Does the asserted legal consequence actually attach?
N8 - Remedy: Is a remedy available and accessible?

NODE CLOSURE VALUES: "closed" | "failed" | "partial" | "indeterminate"

Dissents typically argue that the majority misassessed one or more nodes:
- Substantive dissent: majority wrong on N7 (the right/effect claimed does/does not attach)
- Normative dissent: majority wrong on N2 (applied the wrong rule or applied it incorrectly)
- Factual dissent: majority wrong on N4 (triggering facts were wrongly assessed)
- Procedural dissent: majority wrong on N5 or N8 (wrong act identified or remedy improper)
- Jurisdictional dissent: majority wrong on N1 or N3 (authority or standing)

Analyze ONLY the dissent text. Assess each node AS THE DISSENTING JUDGE(S) WOULD SEE IT — their view of the structural chain, which may differ significantly from the majority.

IMPORTANT:
- Do NOT state who is correct — report the dissent's structural view neutrally
- Do NOT use any abbreviated codes in your response
- For each node, describe in plain English what the dissent argues

Return ONLY valid JSON:
{
  "dissent_nodes": {
    "1": {"closure": "closed|failed|partial|indeterminate", "entity": "what authority per dissent", "justification": "dissent's structural reasoning"},
    "2": {"closure": "...", "entity": "...", "justification": "..."},
    "3": {"closure": "...", "entity": "...", "justification": "..."},
    "4": {"closure": "...", "entity": "...", "justification": "..."},
    "5": {"closure": "...", "entity": "...", "justification": "..."},
    "6": {"closure": "...", "entity": "...", "justification": "..."},
    "7": {"closure": "...", "entity": "...", "justification": "..."},
    "8": {"closure": "...", "entity": "...", "justification": "..."}
  },
  "dissent_failures": [
    "plain English description of each structural failure the dissent identifies in the majority's chain"
  ],
  "key_divergence": "one sentence: which node(s) the dissent most forcefully contests and why",
  "dissent_confidence": "high|medium|low"
}"""


# ── API HELPER ────────────────────────────────────────────────────────────────

def call_api(client, system, user, max_tokens=2500, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=max_tokens,
                system=system, messages=[{"role":"user","content":user}]
            )
            return resp.content[0].text, None
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                return "", str(e)
    return "", "max retries"


def parse_json(raw):
    raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        return json.loads(raw.strip())
    except:
        return None


def migrate_schema(conn):
    """Add dissent columns to scotus_annotations if not present (backwards-compatible)."""
    for col, typ in [
        ("dissent_nodes",    "TEXT"),
        ("dissent_cd",       "REAL"),
        ("dissent_failures", "TEXT"),
        ("cd_divergence",    "REAL"),
        ("regime",           "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE scotus_annotations ADD COLUMN {col} {typ}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    # Every row written before the 2026-08-06 remediation was produced by a code-level
    # cascade that forced RF on 99.5% of cases. Tag them so they can never be pooled
    # with post-remediation rows; a NULL regime would silently read as comparable.
    n = conn.execute("SELECT COUNT(*) FROM scotus_annotations WHERE regime IS NULL").fetchone()[0]
    if n:
        conn.execute("UPDATE scotus_annotations SET regime='scotus-v1-cascade' WHERE regime IS NULL")
        conn.commit()
        log.warning("Tagged %d pre-remediation rows as scotus-v1-cascade "
                    "(RF was forced on 99.5%% of them; not comparable to scotus-v2).", n)


# ── MAIN ANNOTATION ───────────────────────────────────────────────────────────

def annotate_transcript(case: dict, client: anthropic.Anthropic,
                        run_adversarial: bool = True) -> dict | None:
    docket = case["docket"]
    name   = case.get("case_name", docket)
    text   = (case.get("transcript_text") or "")[:TRANSCRIPT_CHARS]

    if len(text) < 500:
        log.warning(f"{docket}: transcript too short, skipping")
        return None

    # ── Pass 1: Node assessment (plain English, no CT codes) ─────────────────
    user_p1 = (
        f"CASE: {name}\nDOCKET: {docket}\n\n"
        f"ORAL ARGUMENT TRANSCRIPT:\n{text}\n\n"
        f"---\nAssess the MLC node closures for this case. "
        f"Identify structural failures in plain English — do not use any abbreviations or codes. "
        f"Return JSON only."
    )
    raw1, err = call_api(client, SYSTEM_PASS1, user_p1, max_tokens=2500)
    if err:
        log.warning(f"{docket} Pass 1 error: {err}")
        return None
    p1 = parse_json(raw1)
    if not p1:
        log.warning(f"{docket} Pass 1 JSON parse failed: {raw1[:100]}")
        return None

    # Map structural failures to CT codes
    nodes     = p1.get("nodes", {})
    failures  = p1.get("structural_failures", [])
    cts       = map_failures_to_cts(failures, nodes)
    cd        = round(sum(CT_WEIGHTS.get(ct, 0) for ct in cts), 4)
    closures  = {n: nodes[n]["closure"] for n in nodes}

    log.info(f"  {docket} domain: {p1.get('legal_domain','?')[:80]}")
    log.info(f"  {docket} CTs mapped: {cts} | CD={cd}")

    # ── Pass 2: Structural outcome derivation ─────────────────────────────────
    user_p2 = (
        f"Legal domain: {p1.get('legal_domain','')}\n"
        f"Node closures: {json.dumps(closures)}\n"
        f"Structural failures: {failures}\n"
        f"Derive chain_outcome and write structural_narrative. Return JSON only."
    )
    raw2, err = call_api(client, SYSTEM_PASS2, user_p2, max_tokens=800)
    if err:
        log.warning(f"{docket} Pass 2 error: {err}")
        return None
    p2 = parse_json(raw2)
    if not p2:
        log.warning(f"{docket} Pass 2 JSON parse failed")
        return None

    # ── Pass 3: Adversarial ───────────────────────────────────────────────────
    p3 = {}
    if run_adversarial:
        user_p3 = (
            f"Legal domain: {p1.get('legal_domain','')}\n"
            f"Node closures: {json.dumps(closures)}\n"
            f"Outcome: {p2.get('chain_outcome')}\n"
            f"Argue strongest structural case for OPPOSITE outcome. Return JSON only."
        )
        raw3, err = call_api(client, SYSTEM_PASS3, user_p3, max_tokens=1000)
        if not err:
            p3 = parse_json(raw3) or {}

    time.sleep(RATE_LIMIT)

    # ── Pass 4: Dissent MLC analysis (optional — only if dissent_text present) ─
    p4 = {}
    dissent_text = (case.get("dissent_text") or "").strip()
    if dissent_text and len(dissent_text) >= 200:
        user_p4 = (
            f"CASE: {name}\nDOCKET: {docket}\n\n"
            f"DISSENTING OPINION TEXT:\n{dissent_text}\n\n"
            f"---\nAnalyze the dissent's MLC node assessments in plain English. "
            f"Do not use any abbreviations or codes. Return JSON only."
        )
        raw4, err = call_api(client, SYSTEM_PASS4, user_p4, max_tokens=2500)
        if not err:
            p4 = parse_json(raw4) or {}
            if p4:
                log.info(f"  {docket} dissent: {p4.get('key_divergence','?')[:80]}")

    # Compute dissent CD if Pass 4 succeeded
    dissent_nodes_data = p4.get("dissent_nodes", {})
    dissent_failures   = p4.get("dissent_failures", [])
    if dissent_nodes_data:
        d_cts = map_failures_to_cts(dissent_failures, dissent_nodes_data)
        d_cd  = round(sum(CT_WEIGHTS.get(c, 0) for c in d_cts), 4)
        cd_divergence = round(abs(d_cd - cd), 4)
        log.info(f"  {docket} dissent CD={d_cd:.3f} | divergence={cd_divergence:.3f}")
    else:
        d_cts = []
        d_cd  = None
        cd_divergence = None

    # ── Build annotation record ───────────────────────────────────────────────
    ann = {
        "docket":               docket,
        "active_contradictions": json.dumps(cts),
        "contradiction_debt":   cd,
        "predicted_outcome":    p2.get("chain_outcome", ""),
        "outcome_confidence":   p2.get("outcome_confidence", "medium"),
        "structural_narrative": p2.get("structural_narrative", ""),
        "adversarial_strength": p3.get("adversarial_strength", 0.0),
        "adversarial_notes":    p3.get("adversarial_notes", ""),
        "annotated_at":         datetime.now().isoformat(),
        "source_chars":         len(text),
        # Dissent fields (None if no dissent text was available)
        "dissent_nodes":    json.dumps(dissent_nodes_data) if dissent_nodes_data else None,
        "dissent_cd":       d_cd,
        "dissent_failures": json.dumps(d_cts) if d_cts else None,
        "cd_divergence":    cd_divergence,
    }
    for n in range(1, 9):
        nd = nodes.get(str(n), {})
        ann[f"node{n}_closure"]      = nd.get("closure", "indeterminate")
        ann[f"node{n}_entity"]       = nd.get("entity", "")
        ann[f"node{n}_justification"] = nd.get("justification", "")

    return ann


# ── SAVE ──────────────────────────────────────────────────────────────────────

def save_annotation(conn, case_id, ann, actual_outcome):
    pred   = ann.get("predicted_outcome", "")
    actual = actual_outcome or ""
    correct = None
    if pred in ("protection_granted","protection_denied") and \
       actual in ("protection_granted","protection_denied"):
        correct = 1 if pred == actual else 0

    ann["actual_outcome"]     = actual
    ann["prediction_correct"] = correct
    ann["case_id"]            = case_id
    # Rows written before 2026-08-06 were produced by a code-level cascade that forced
    # RF on 99.5% of cases; they are backfilled as scotus-v1-cascade. Anything written
    # from here carries scotus-v2 and is comparable to the civil v2 corpus.
    ann["regime"]             = SCOTUS_REGIME

    conn.execute("""
        INSERT OR REPLACE INTO scotus_annotations (
          case_id, docket,
          node1_closure, node1_entity, node1_justification,
          node2_closure, node2_entity, node2_justification,
          node3_closure, node3_entity, node3_justification,
          node4_closure, node4_entity, node4_justification,
          node5_closure, node5_entity, node5_justification,
          node6_closure, node6_entity, node6_justification,
          node7_closure, node7_entity, node7_justification,
          node8_closure, node8_entity, node8_justification,
          active_contradictions, contradiction_debt,
          predicted_outcome, outcome_confidence, structural_narrative,
          adversarial_strength, adversarial_notes,
          actual_outcome, prediction_correct, annotated_at, source_chars,
          dissent_nodes, dissent_cd, dissent_failures, cd_divergence, regime
        ) VALUES (
          :case_id, :docket,
          :node1_closure,:node1_entity,:node1_justification,
          :node2_closure,:node2_entity,:node2_justification,
          :node3_closure,:node3_entity,:node3_justification,
          :node4_closure,:node4_entity,:node4_justification,
          :node5_closure,:node5_entity,:node5_justification,
          :node6_closure,:node6_entity,:node6_justification,
          :node7_closure,:node7_entity,:node7_justification,
          :node8_closure,:node8_entity,:node8_justification,
          :active_contradictions,:contradiction_debt,
          :predicted_outcome,:outcome_confidence,:structural_narrative,
          :adversarial_strength,:adversarial_notes,
          :actual_outcome,:prediction_correct,:annotated_at,:source_chars,
          :dissent_nodes,:dissent_cd,:dissent_failures,:cd_divergence
        )
    """, ann)
    conn.commit()

    status = "correct" if correct==1 else "wrong" if correct==0 else "indeterminate"
    log.info(f"  {ann['docket']}: pred={pred} actual={actual} → {status} | CD={ann['contradiction_debt']:.3f}")


# ── BATCH ─────────────────────────────────────────────────────────────────────

def annotate_pending(conn, client, limit=0, reannotate=False):
    if reannotate:
        cases = conn.execute("""
            SELECT c.id, c.docket, c.case_name, c.transcript_text, c.outcome,
                   c.dissent_text
            FROM scotus_cases c
            WHERE LENGTH(c.transcript_text) > 500
            ORDER BY c.term DESC, c.argument_date
        """).fetchall()
    else:
        cases = conn.execute("""
            SELECT c.id, c.docket, c.case_name, c.transcript_text, c.outcome,
                   c.dissent_text
            FROM scotus_cases c
            LEFT JOIN scotus_annotations a ON a.case_id = c.id
            WHERE LENGTH(c.transcript_text) > 500
            AND a.id IS NULL
            ORDER BY c.term DESC, c.argument_date
        """).fetchall()

    if limit:
        cases = cases[:limit]

    log.info(f"Annotating {len(cases)} cases")
    for case in cases:
        ann = annotate_transcript(dict(case), client)
        if ann:
            save_annotation(conn, case["id"], ann, case["outcome"] or "")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",         default="scotus_backtest.db")
    parser.add_argument("--docket",     type=str)
    parser.add_argument("--limit",      type=int, default=0)
    parser.add_argument("--reannotate", action="store_true")
    parser.add_argument("--api-key",    default=None)
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("SOOL_ANTHROPIC_KEY")
    if not api_key:
        print("ERROR: No API key"); sys.exit(1)

    conn   = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    migrate_schema(conn)
    client = anthropic.Anthropic(api_key=api_key)

    if args.docket:
        case = conn.execute(
            "SELECT * FROM scotus_cases WHERE docket=?", (args.docket,)
        ).fetchone()
        if not case:
            print(f"{args.docket} not in DB"); sys.exit(1)
        conn.execute("DELETE FROM scotus_annotations WHERE docket=?", (args.docket,))
        conn.commit()
        ann = annotate_transcript(dict(case), client)
        if ann:
            save_annotation(conn, case["id"], ann, case["outcome"] or "")
    else:
        annotate_pending(conn, client, limit=args.limit, reannotate=args.reannotate)
