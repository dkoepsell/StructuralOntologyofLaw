"""
annotate_equipoise.py — SOoL Equipoise Annotation Module
=========================================================
SEAL Lab, Texas A&M University
David R. Koepsell

Implements four methodological safeguards against annotation bias:

  Safeguard 1 — Party name masking
    Case names are stripped of party identifiers before the annotator
    sees the prompt. [CLAIMANT] and [RESPONDENT] replace actual names.
    Prevents case-name outcome signals from reaching the annotator.

  Safeguard 2 — Two-pass separation of node assessment from outcome
    Pass 1: Annotator assesses ONLY node closures and CTs from opinion
            text. The chain_outcome field is NOT requested in Pass 1.
    Pass 2: A second call receives the Pass 1 node/CT results and
            derives chain_outcome STRUCTURALLY from them, without
            re-reading the opinion text. Outcome cannot influence nodes.

  Safeguard 3 — Adversarial counterfactual check (Pass 3)
    Pass 3: Annotator receives the Pass 1/2 annotation and is asked
            explicitly: "What is the strongest structural case for the
            OPPOSITE outcome? Which nodes could plausibly be assessed
            differently?" Results are stored as adversarial_notes.
            Cases where the adversarial case is strong are flagged
            for human review.

  Safeguard 4 — Framework-neutral system prompt
    The author attribution ("developed by David R. Koepsell") is
    removed from the system prompt. The framework is described as a
    formal legal ontology without personal attribution, reducing the
    loyalty effect that named-author prompts create.

Usage:
    from annotate_equipoise import annotate_case_equipoise
    annotation = annotate_case_equipoise(case, api_key, domain_id)

    # Or run as standalone batch:
    python3 annotate_equipoise.py --civil-db sool_corpus.db --ann-db sool_annotations.db
    python3 annotate_equipoise.py --criminal
    python3 annotate_equipoise.py --audit   # re-run pass 3 on existing annotations
"""

import argparse, json, re, sqlite3, sys, time
from pathlib import Path
from typing import Optional
import anthropic

# ── PASS 1: NODE ASSESSMENT SYSTEM PROMPT ────────────────────────────────────
# Note: no author attribution (Safeguard 4); no chain_outcome field (Safeguard 2)

SYSTEM_PASS1 = """You are an expert legal ontologist. Your task is to assess court opinions using the Minimum Legal Chain (MLC) — a formal structural framework for analyzing legal proceedings.

THE MINIMUM LEGAL CHAIN (MLC):
A legal effect is valid only if each of 8 structural nodes closes in sequence:
  Node 1 - Source of Authority: The constitutional/statutory/institutional ground of norm-issuance
  Node 2 - Norm: The specific rule or standard being applied
  Node 3 - Actor in Role: The agent bearing the norm-governed capacity
  Node 4 - Triggering Facts: The circumstances activating the norm
  Node 5 - Legal Act/Omission: The conduct that instantiates the trigger
  Node 6 - Target: The entity upon whom the legal effect is directed
  Node 7 - Legal Effect: The normative consequence (right, duty, power, liability)
  Node 8 - Remedy: The mechanism for restoring coherence on breach

NODE CLOSURE VALUES:
  "closed"        - node fully satisfied
  "failed"        - node not satisfied
  "partial"       - node partially satisfied, structural stress
  "indeterminate" - cannot be determined from the opinion text

CONTRADICTION TYPES — use these exact codes:
  CF   Conferral Failure         Authority fails to vest actor in role
  AI   Authority Inflation       Decision-maker's will displaces norm
  JC   Jurisdictional Contradiction  Competing normative regimes over same situation
  RC3  Role Contradiction        Same bearer holds roles generating incompatible obligations
  PC   Procedural Contradiction  Act required by norm cannot follow norm's own procedure
  TC   Temporal Contradiction    Norm and triggering facts in temporal misalignment
  FM   Fact Manipulation         Triggering facts fabricated, suppressed, or indeterminate
  NI   Norm Indeterminacy        Norm too vague to produce determinate closure
  RF   Recognition Failure       Target or legal effect denied required recognition
  RCL  Recognition Collapse      Subjecthood stripped while enforcement continues
  CC   Correlativity Contradiction  Rights claimed without correlative duties honored
  SE   Self-Undermining Effect   Legal effect destabilizes conditions for own persistence
  RPF  Repair Failure            Remedy structurally available but blocked

IMPORTANT: Your task in this pass is ONLY to assess node closures and contradiction types.
Do NOT infer or state the chain outcome. Do NOT speculate about who won.
Assess each node independently from the text.

CONTRADICTION ASSIGNMENT:
- Assign RF, CC and RPF only on their own textual evidence, never as an
  automatic consequence of a Node 7 or Node 8 failure:
    RF  — the court declines to recognise the asserted right at all.
    CC  — the right is recognised or assumed, but the correlative duty is refused
          (the qualified-immunity shape). CC is not a weaker RF; do not merge them.
    RPF — repair is specifically blocked or unavailable on the court's own reasoning.
  A Node 7 failure with no separate recognition/correlativity/repair reasoning may
  carry none of these.
- Assess Node 8 on its own evidence. It may diverge from Node 7 in either direction;
  note the divergence rather than suppressing it.
- Only assert contradictions derivable from the opinion text.
- Set confidence: "high" if text is clear; "medium" if inferring; "low" if text sparse.

OUTPUT FORMAT:
Return ONLY valid JSON — no preamble, no explanation, no markdown.

{
  "nodes": {
    "1": {"closure": "...", "entity": "...", "justification": "..."},
    "2": {"closure": "...", "entity": "...", "justification": "..."},
    "3": {"closure": "...", "entity": "...", "roles_borne": [], "justification": "..."},
    "4": {"closure": "...", "entity": "...", "justification": "..."},
    "5": {"closure": "...", "entity": "...", "justification": "..."},
    "6": {"closure": "...", "entity": "...", "justification": "..."},
    "7": {"closure": "...", "entity": "...", "justification": "..."},
    "8": {"closure": "...", "entity": "...", "justification": "..."}
  },
  "active_contradictions": [],
  "contradiction_notes": "...",
  "confidence": "high|medium|low"
}"""

# ── PASS 2: STRUCTURAL OUTCOME DERIVATION ────────────────────────────────────
# Receives node/CT results, no opinion text; derives outcome structurally.

SYSTEM_PASS2 = """You are a structural legal analyst. You will receive the node
closure assessment from a legal chain analysis and must compute the STRUCTURAL
PREDICTION that the Minimal Legal Chain model makes from those node closures alone.

IMPORTANT — what this value is and is not:
This is a PREDICTION generated by a stated function of the node closures. It is
NOT the court's holding and must never be reported as the case outcome. It is
recorded as `derived_outcome` so that it can be evaluated against
`court_disposition` — the court's actual holding, coded separately from the
opinion text by a pass that never sees these node closures. Any agreement
between this prediction and Contradiction Debt is definitional, since both are
functions of the same node closures; only agreement with `court_disposition`
is evidence of anything.

PREDICTION FUNCTION (apply in order):
1. If Node 7 = "closed" AND Node 8 = "closed": chain_outcome = "protection_granted"
2. If Node 7 = "failed": chain_outcome = "protection_denied"
3. If Node 7 = "partial" AND Node 8 = "closed": chain_outcome = "partial"
4. If Node 7 = "partial" AND Node 8 = "failed": chain_outcome = "protection_denied"
5. If Node 7 = "indeterminate": chain_outcome = "protection_denied" (default — indeterminate chains fail)
6. If any of Nodes 1-6 = "failed" with Node 7 = "indeterminate": chain_outcome = "protection_denied"

The claimant is the party whose chain you are assessing:
  protection_granted = claimant's right/protection recognized
  protection_denied  = claimant's right/protection denied
  partial            = mixed outcome

You must also compute the Contradiction Debt score:
CD weights: CF=0.15, AI=0.12, JC=0.10, RC3=0.14, PC=0.09, TC=0.08,
            FM=0.11, NI=0.07, RF=0.11, RCL=0.18, CC=0.14, SE=0.10, RPF=0.13
CD = sum of weights of all active contradiction types.

OUTPUT FORMAT — return ONLY valid JSON:
{
  "chain_outcome": "protection_granted|protection_denied|partial|remanded|dismissed|moot",
  "outcome_derivation": "which node(s) drove the prediction",
  "contradiction_debt": 0.00,
  "outcome_confidence": "high|medium|low"
}

NOTE: the `chain_outcome` key is retained for schema compatibility, but the value
is the model's PREDICTION, stored as `derived_outcome`. It is not the court's
holding."""

# ── PASS 3: ADVERSARIAL COUNTERFACTUAL ───────────────────────────────────────
# Explicitly argues the other side; flags cases with strong adversarial case.

SYSTEM_PASS3 = """You are playing devil's advocate for a legal structural analysis. You will receive a completed structural annotation of a legal proceeding and must argue the STRONGEST POSSIBLE CASE for the OPPOSITE outcome.

Your task:
1. Identify which node closure assessments are most contestable — where a reasonable annotator could plausibly reach a different conclusion.
2. Explain what alternative assessment of those nodes would produce for the overall chain.
3. Identify whether the opposite outcome is structurally defensible under any reasonable reading of the evidence.
4. Assign an adversarial_strength score (0.0 = no plausible alternative; 1.0 = opposite outcome equally defensible).

This is a methodological safeguard for annotation quality, not a critique of the annotation. Be rigorous and specific. Do not be charitable to the original annotation.

OUTPUT FORMAT — return ONLY valid JSON:
{
  "contestable_nodes": ["list of node numbers where alternative closure is plausible"],
  "alternative_assessment": "what would the chain look like under the most plausible alternative reading",
  "opposite_outcome_defensible": true|false,
  "adversarial_strength": 0.0,
  "adversarial_notes": "specific textual basis for alternative reading",
  "flag_for_review": false
}"""


# ── PARTY NAME MASKER (Safeguard 1) ──────────────────────────────────────────

def mask_party_names(case_name: str, opinion_text: str) -> tuple[str, str]:
    """
    Replace party names in case name and opinion text with [CLAIMANT]
    and [RESPONDENT] to prevent outcome signals from case-name recognition.

    Heuristic: split case name on ' v. ' or ' v ' and mask each side.
    Common government identifiers (United States, State, Commissioner, etc.)
    are replaced with [GOVERNMENT] rather than [RESPONDENT] when they appear
    as the respondent.
    """
    GOVERNMENT_TERMS = {
        'united states', 'u.s.', 'state', 'people', 'commonwealth',
        'government', 'commissioner', 'secretary', 'department', 'agency',
        'board', 'commission', 'administrator', 'director', 'attorney general',
        'district attorney', 'warden', 'superintendent', 'sheriff',
    }

    masked_name = case_name
    masked_text = opinion_text or ''

    # Split on v. pattern
    parts = re.split(r'\s+v\.\s+|\s+v\s+', case_name, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        claimant, respondent = parts[0].strip(), parts[1].strip()

        # Determine if respondent is government
        resp_lower = respondent.lower()
        is_govt = any(t in resp_lower for t in GOVERNMENT_TERMS)
        resp_label = '[GOVERNMENT]' if is_govt else '[RESPONDENT]'

        masked_name = f'[CLAIMANT] v. {resp_label}'

        # Mask in opinion text (limit substitutions to avoid over-masking)
        if len(claimant) > 3:
            masked_text = re.sub(
                re.escape(claimant), '[CLAIMANT]',
                masked_text, count=20, flags=re.IGNORECASE
            )
        if len(respondent) > 3:
            masked_text = re.sub(
                re.escape(respondent), resp_label,
                masked_text, count=20, flags=re.IGNORECASE
            )

    return masked_name, masked_text


# ── API CALL HELPER ───────────────────────────────────────────────────────────

def call_claude(client: anthropic.Anthropic, system: str, user: str,
                max_tokens: int = 2000, retries: int = 2) -> tuple[str, Optional[str]]:
    """Call Claude API with retry. Returns (response_text, error_or_None)."""
    for attempt in range(retries + 1):
        try:
            resp = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return resp.content[0].text, None
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                return "", str(e)
    return "", "max retries exceeded"


def parse_json(raw: str) -> Optional[dict]:
    """Strip markdown fences and parse JSON."""
    raw = re.sub(r'^```json\s*|^```\s*|```$', '', raw.strip(), flags=re.MULTILINE)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return None


# ── MAIN THREE-PASS ANNOTATOR ────────────────────────────────────────────────

CT_WEIGHTS = {
    'CF': 0.15, 'AI': 0.12, 'JC': 0.10, 'RC3': 0.14, 'PC': 0.09,
    'TC': 0.08, 'FM': 0.11, 'NI': 0.07, 'RF': 0.11, 'RCL': 0.18,
    'CC': 0.14, 'SE': 0.10, 'RPF': 0.13,
}


def annotate_case_equipoise(case: dict, client: anthropic.Anthropic,
                             domain_id: int = 0,
                             run_adversarial: bool = True,
                             opinion_chars: int = 12000) -> dict:
    """
    Run three-pass equipoise annotation on a single case.

    Returns annotation dict with all three passes merged.
    Adds equipoise_flags dict indicating which safeguards fired.
    """
    result = {
        'case_id':          case.get('id') or case.get('case_id'),
        'case_name':        case.get('case_name', ''),
        'equipoise_flags':  {},
        'pass1':            {},
        'pass2':            {},
        'pass3':            {},
        'annotation_error': None,
    }

    opinion_text = case.get('plain_text', '') or ''
    opinion_text = opinion_text[:opinion_chars]
    case_name    = case.get('case_name', 'Unknown')

    # ── SAFEGUARD 1: Mask party names ─────────────────────────────────────────
    masked_name, masked_text = mask_party_names(case_name, opinion_text)
    result['equipoise_flags']['name_masked'] = (masked_name != case_name)

    # ── PASS 1: Node closure and CT assessment ───────────────────────────────
    domain_name = case.get('domain_name', '') or case.get('category_name', '')
    user_p1 = (
        f"MASKED CASE: {masked_name}\n"
        f"COURT: {case.get('court_id', '') or case.get('court', '')}\n"
        f"DOMAIN: {domain_name}\n\n"
        f"OPINION TEXT:\n{masked_text or '[No opinion text available]'}\n\n"
        f"---\nAssess the Minimum Legal Chain node closures and contradiction types for this case.\n"
        f"Return ONLY the JSON object. Do NOT state or infer who won."
    )

    raw_p1, err = call_claude(client, SYSTEM_PASS1, user_p1, max_tokens=2500)
    if err:
        result['annotation_error'] = f"Pass 1 error: {err}"
        return result

    p1 = parse_json(raw_p1)
    if not p1:
        result['annotation_error'] = f"Pass 1 JSON parse failed: {raw_p1[:200]}"
        return result

    result['pass1'] = p1

    # ── PASS 2: Structural outcome derivation ────────────────────────────────
    nodes_summary = {
        n: p1['nodes'][n]['closure']
        for n in p1.get('nodes', {})
    }
    cts = p1.get('active_contradictions', [])
    cd  = round(sum(CT_WEIGHTS.get(ct, 0) for ct in cts), 4)

    user_p2 = (
        f"Node closure assessment:\n{json.dumps(nodes_summary, indent=2)}\n\n"
        f"Active contradictions: {cts}\n"
        f"Computed CD: {cd}\n\n"
        f"Derive the chain outcome structurally from the node closures above.\n"
        f"Return ONLY the JSON object."
    )

    raw_p2, err = call_claude(client, SYSTEM_PASS2, user_p2, max_tokens=800)
    if err:
        result['annotation_error'] = f"Pass 2 error: {err}"
        return result

    p2 = parse_json(raw_p2)
    if not p2:
        result['annotation_error'] = f"Pass 2 JSON parse failed: {raw_p2[:200]}"
        return result

    # Override computed CD with structured Pass 2 value
    p2['contradiction_debt'] = cd
    result['pass2'] = p2

    # Check if Pass 2 outcome matches Pass 1 node-implied outcome
    n7 = nodes_summary.get('7', 'indeterminate')
    n8 = nodes_summary.get('8', 'indeterminate')
    implied = ('protection_granted' if n7 == 'closed' and n8 == 'closed'
               else 'protection_denied' if n7 == 'failed'
               else 'partial')
    derived = p2.get('chain_outcome', '')
    result['equipoise_flags']['pass1_pass2_mismatch'] = (
        derived != implied and implied != 'partial'
    )

    # ── PASS 3: Adversarial counterfactual ───────────────────────────────────
    if run_adversarial:
        user_p3 = (
            f"Completed structural annotation:\n"
            f"Node closures: {json.dumps(nodes_summary, indent=2)}\n"
            f"Active CTs: {cts}\n"
            f"Derived outcome: {derived}\n"
            f"CD: {cd}\n\n"
            f"Argue the strongest structural case for the OPPOSITE outcome.\n"
            f"Return ONLY the JSON object."
        )

        raw_p3, err = call_claude(client, SYSTEM_PASS3, user_p3, max_tokens=1200)
        if not err:
            p3 = parse_json(raw_p3)
            if p3:
                result['pass3'] = p3
                adv_strength = p3.get('adversarial_strength', 0.0)
                result['equipoise_flags']['high_adversarial_strength'] = (
                    adv_strength >= 0.6
                )
                result['equipoise_flags']['flagged_for_review'] = (
                    p3.get('flag_for_review', False) or adv_strength >= 0.7
                )

    # ── MERGE into final annotation ──────────────────────────────────────────
    nodes_out = p1.get('nodes', {})
    final = {
        'case_id':              result['case_id'],
        'case_name':            case_name,
        'domain_id':            domain_id,
        'chain_outcome':        p2.get('chain_outcome', ''),
        'contradiction_debt':   cd,
        'active_contradictions': cts,
        'confidence':           p1.get('confidence', 'medium'),
        'outcome_notes':        p2.get('outcome_derivation', ''),
        'adversarial_notes':    result['pass3'].get('adversarial_notes', ''),
        'adversarial_strength': result['pass3'].get('adversarial_strength', 0.0),
        'needs_review':         result['equipoise_flags'].get('flagged_for_review', False),
        'equipoise_flags':      json.dumps(result['equipoise_flags']),
        'annotation_method':    'equipoise_3pass',
    }

    # Node closures
    for n in range(1, 9):
        node = nodes_out.get(str(n), {})
        final[f'node{n}_closure'] = node.get('closure', 'indeterminate')
        final[f'node{n}_entity']  = node.get('entity', '')

    return final


# ── EQUIPOISE AUDIT: re-run Pass 3 on existing annotations ───────────────────

def audit_existing_annotations(ann_db: str, client: anthropic.Anthropic,
                                limit: int = 100, min_cd: float = 0.15,
                                criminal: bool = False) -> dict:
    """
    Run adversarial Pass 3 on existing high-CD annotations.
    Returns summary of how many were flagged.
    """
    conn = sqlite3.connect(ann_db)
    conn.row_factory = sqlite3.Row

    try:
        table = 'criminal_annotations' if criminal else 'annotations'
        rows = conn.execute(f"""
            SELECT rowid as rid, case_name, chain_outcome, contradiction_debt,
                   active_contradictions,
                   node1_closure, node2_closure, node3_closure, node4_closure,
                   node5_closure, node6_closure, node7_closure, node8_closure
            FROM {table}
            WHERE contradiction_debt >= ?
            AND (adversarial_strength IS NULL OR adversarial_strength = 0)
            ORDER BY contradiction_debt DESC
            LIMIT ?
        """, (min_cd, limit)).fetchall()
    except Exception:
        rows = []

    flagged = 0
    for row in rows:
        nodes = {str(i+1): row[f'node{i+1}_closure'] for i in range(8)}
        cts   = json.loads(row['active_contradictions'] or '[]')
        cd    = row['contradiction_debt']
        outcome = row['chain_outcome']

        user_p3 = (
            f"Node closures: {json.dumps(nodes)}\n"
            f"Active CTs: {cts}\nOutcome: {outcome}\nCD: {cd}\n\n"
            f"Argue the strongest structural case for the OPPOSITE outcome."
        )
        raw, err = call_claude(client, SYSTEM_PASS3, user_p3, max_tokens=1000)
        if err: continue
        p3 = parse_json(raw)
        if not p3: continue

        strength = p3.get('adversarial_strength', 0.0)
        flag     = strength >= 0.7 or p3.get('flag_for_review', False)
        if flag: flagged += 1

        conn.execute(f"""
            UPDATE {table}
            SET adversarial_strength = ?,
                adversarial_notes = ?,
                needs_review = ?
            WHERE rowid = ?
        """, (strength, p3.get('adversarial_notes', ''), 1 if flag else 0, row['rid']))
        conn.commit()
        time.sleep(0.3)

    conn.close()
    return {'audited': len(rows), 'flagged': flagged}


# ── SCHEMA ADDITIONS ──────────────────────────────────────────────────────────

EQUIPOISE_SCHEMA_ADDITIONS = """
-- Add equipoise columns to existing annotation tables
-- Run once per DB before using equipoise annotation

ALTER TABLE annotations ADD COLUMN adversarial_strength REAL DEFAULT 0.0;
ALTER TABLE annotations ADD COLUMN adversarial_notes TEXT DEFAULT '';
ALTER TABLE annotations ADD COLUMN equipoise_flags TEXT DEFAULT '{}';
ALTER TABLE annotations ADD COLUMN annotation_method TEXT DEFAULT 'standard';

ALTER TABLE criminal_annotations ADD COLUMN adversarial_strength REAL DEFAULT 0.0;
ALTER TABLE criminal_annotations ADD COLUMN adversarial_notes TEXT DEFAULT '';
ALTER TABLE criminal_annotations ADD COLUMN equipoise_flags TEXT DEFAULT '{}';
ALTER TABLE criminal_annotations ADD COLUMN annotation_method TEXT DEFAULT 'standard';
"""


def add_equipoise_columns(db_path: str):
    """Add equipoise columns to annotation DB if not present."""
    conn = sqlite3.connect(db_path)
    table = 'criminal_annotations' if 'criminal' in db_path else 'annotations'
    existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    for col, typ in [
        ('adversarial_strength', 'REAL DEFAULT 0.0'),
        ('adversarial_notes',    'TEXT DEFAULT ""'),
        ('equipoise_flags',      'TEXT DEFAULT "{}"'),
        ('annotation_method',    'TEXT DEFAULT "standard"'),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            print(f"Added column: {col}")
    conn.commit()
    conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SOoL Equipoise Annotator')
    parser.add_argument('--civil-db',    default='./sool_corpus.db')
    parser.add_argument('--ann-db',      default='./sool_annotations.db')
    parser.add_argument('--criminal',    action='store_true')
    parser.add_argument('--audit',       action='store_true',
                        help='Run adversarial Pass 3 on existing high-CD annotations')
    parser.add_argument('--audit-limit', type=int, default=100)
    parser.add_argument('--audit-min-cd', type=float, default=0.15)
    parser.add_argument('--api-key',     default=None)
    parser.add_argument('--add-columns', action='store_true',
                        help='Add equipoise columns to annotation DB and exit')
    args = parser.parse_args()

    import os
    api_key = args.api_key or os.environ.get('SOOL_ANTHROPIC_KEY')
    if not api_key:
        print("ERROR: No API key. Set SOOL_ANTHROPIC_KEY or use --api-key")
        sys.exit(1)

    ann_db = args.ann_db
    if args.criminal:
        ann_db = ann_db.replace('sool_annotations', 'sool_criminal_annotations')

    if args.add_columns:
        add_equipoise_columns(ann_db)
        sys.exit(0)

    client = anthropic.Anthropic(api_key=api_key)

    if args.audit:
        print(f"Running adversarial audit on {ann_db}...")
        result = audit_existing_annotations(
            ann_db, client,
            limit=args.audit_limit,
            min_cd=args.audit_min_cd
        )
        print(f"Audited: {result['audited']}  Flagged for review: {result['flagged']}")
        sys.exit(0)

    print("Equipoise annotator ready.")
    print("Import annotate_case_equipoise() into your pipeline scripts.")
    print("Run with --audit to run adversarial check on existing annotations.")
    print("Run with --add-columns to add equipoise columns to annotation DB.")
