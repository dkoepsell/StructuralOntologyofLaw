#!/usr/bin/env python3
"""
SOoL MLC Annotation Pipeline
==============================
SEAL Lab, Texas A&M University
David R. Koepsell, A Structural Ontology of the Law (Palgrave, forthcoming)

Sends each collected case opinion to the Claude API for first-pass
MLC structural annotation, validates the output, and writes results
to a SQLite annotations database and per-domain JSONL files.

Human review queue: cases flagged low-confidence or validation-failed
are written to review_queue.jsonl for manual correction.

Usage:
    python3 annotate_pipeline.py --domain 1 --limit 20   # pilot run
    python3 annotate_pipeline.py --domain all             # full corpus
    python3 annotate_pipeline.py --review                 # show review queue
    python3 annotate_pipeline.py --stats                  # annotation stats
    python3 annotate_pipeline.py --to-turtle --domain 1  # export OWL triples

Requirements:
    pip install requests tqdm
    (Uses the Claude API via the claude.ai proxy — no separate API key needed)
"""

import os
import sys
import json
import time
import sqlite3
import argparse
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

# ── import validation logic from annotate.py ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from annotate import (
    compute_cd_upstream, normalize_contradictions,
    validate, compute_cd, compute_structural_signature,
    to_turtle, CONTRADICTION_TYPES, CHAIN_OUTCOMES,
    DOCTRINAL_DOMAINS, MLC_NODES, NODE_CLOSURE_VALUES,
)

# ── optional equipoise pass-3 adversarial check ───────────────────────────────
try:
    from annotate_equipoise import (
        call_claude as eq_call_claude,
        parse_json  as eq_parse_json,
        SYSTEM_PASS3,
    )
    EQUIPOISE_AVAILABLE = True
except ImportError:
    EQUIPOISE_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-5"
CLAUDE_API_KEY = ""   # set via --api-key or ANTHROPIC_API_KEY env var
MAX_TOKENS     = 3000   # headroom: Sonnet 5's tokenizer emits ~30% more tokens
                        # for the same text than the retired Sonnet 4
OPINION_CHARS  = 12000   # truncate opinion text to this length for the prompt
                          # ~3,000 tokens — enough for the structural analysis
RATE_LIMIT     = 3.0     # seconds between API calls
# ─────────────────────────────────────────────────────────────────────────────
# DISPOSITION MASKING (equipoise / blind annotation)
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that signal dispositional outcome — visible in the opinion tail
_DISP_PATTERNS = [
    # Explicit holding phrases
    r"we\s+(?:therefore\s+)?affirm(?:ed|s)?\b",
    r"we\s+(?:therefore\s+)?revers(?:e|ed|es)\b",
    r"we\s+(?:therefore\s+)?remand\b",
    r"judgment\s+(?:of\s+the\s+district\s+court\s+)?(?:is\s+)?affirmed\b",
    r"judgment\s+(?:is\s+)?reversed\b",
    r"(?:is\s+)?reversed\s+and\s+remanded\b",
    r"\bAFFIRMED\b",
    r"\bREVERSED\b",
    r"\bREMANDED\b",
    r"(?:petition|appeal)\s+(?:is\s+)?(?:granted|denied)\b",
    r"\bprotection\s+(?:granted|denied)\b",
    # Outcome-signalling conclusion phrases
    r"for\s+the\s+(?:foregoing\s+)?reasons[,.]?\s+we\s+(?:affirm|reverse|remand)",
    r"the\s+(?:district\s+court['\u2019]?s?\s+)?(?:judgment|order)\s+is",
    r"we\s+(?:vacate|set\s+aside|dismiss|grant|deny)",
]

_DISP_RE = re.compile(
    "|".join(_DISP_PATTERNS),
    re.IGNORECASE,
)

# How many chars from the tail to mask
MASK_TAIL_CHARS = 2000

# Replacement text shown to annotator
MASK_PLACEHOLDER = (
    "\n\n[DISPOSITION REDACTED — annotate the structural chain from the "
    "opinion reasoning only. Do not infer the outcome from any redacted text.]"
)


def strip_disposition(text: str, tail_chars: int = MASK_TAIL_CHARS) -> tuple[str, bool]:
    """
    Remove dispositional language from opinion text for blind annotation.

    Strategy:
      1. Search the final `tail_chars` of the text for known outcome phrases.
      2. If found, truncate the text at the earliest match in that window
         and append MASK_PLACEHOLDER.
      3. Also remove any all-caps AFFIRMED / REVERSED / REMANDED tokens
         anywhere in the text (they often appear in headers too).
      4. Returns (masked_text, was_masked: bool).

    The function is conservative: it only removes text from the tail,
    leaving the opinion's structural reasoning intact.
    """
    if not text:
        return text, False

    tail_start = max(0, len(text) - tail_chars)
    tail       = text[tail_start:]

    # Find earliest disposition signal in tail
    earliest_match = None
    for m in _DISP_RE.finditer(tail):
        if earliest_match is None or m.start() < earliest_match.start():
            earliest_match = m

    was_masked = False
    if earliest_match:
        # Truncate at the sentence boundary before the match if possible
        cut = tail_start + earliest_match.start()
        # Back up to last sentence end before cut
        preceding = text[:cut]
        last_period = max(
            preceding.rfind(". "),
            preceding.rfind(".\n"),
            preceding.rfind("\n\n"),
        )
        if last_period > 0 and (cut - last_period) < 400:
            cut = last_period + 1
        text = text[:cut] + MASK_PLACEHOLDER
        was_masked = True

    # Secondary pass: remove all-caps outcome tokens anywhere
    # (they appear in headers like "AFFIRMED IN PART, REVERSED IN PART")
    cleaned = re.sub(
        r"\b(AFFIRMED|REVERSED|REMANDED|VACATED|DISMISSED)\b(?:[^.\n]{0,60})?",
        "[REDACTED]",
        text,
    )
    if cleaned != text:
        was_masked = True
        text = cleaned

    return text, was_masked



CORPUS_DIR     = "./corpus"
ANNOTATIONS_DB = "./sool_annotations.db"
REVIEW_QUEUE   = "./review_queue.jsonl"

DOMAIN_FILES = {
    1: "domain_1_first_amendment.jsonl",
    2: "domain_2_employment_discrimination.jsonl",
    3: "domain_3_administrative_law.jsonl",
    4: "domain_4_criminal_procedure.jsonl",
    5: "domain_5_immigration.jsonl",
    6: "domain_6_civil_rights_1983.jsonl",
    7: "domain_7_contract.jsonl",
    8: "domain_8_family_law.jsonl",
    # Phase IV
    9:  "domain_9_habeas_corpus.jsonl",
    10: "domain_10_patent_ip.jsonl",
    11: "domain_11_securities_regulation.jsonl",
}

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("annotation.log", mode="a"),
    ]
)
log = logging.getLogger("annotate_pipeline")

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS annotations (
    case_id             INTEGER PRIMARY KEY,
    case_name           TEXT,
    citation            TEXT,
    court               TEXT,
    date_decided        TEXT,
    domain_id           INTEGER,
    domain_name         TEXT,

    -- MLC node closure (1=closed, 0=failed, 0.5=partial, -1=indeterminate)
    node1_closure       TEXT,
    node2_closure       TEXT,
    node3_closure       TEXT,
    node4_closure       TEXT,
    node5_closure       TEXT,
    node6_closure       TEXT,
    node7_closure       TEXT,
    node8_closure       TEXT,

    -- Node entities (what fills each node)
    node1_entity        TEXT,
    node2_entity        TEXT,
    node3_entity        TEXT,
    node3_roles         TEXT,   -- JSON array
    node4_entity        TEXT,
    node5_entity        TEXT,
    node6_entity        TEXT,
    node7_entity        TEXT,
    node8_entity        TEXT,

    -- Contradiction analysis
    active_contradictions TEXT,  -- JSON array of codes
    contradiction_debt    REAL,
    chain_outcome         TEXT,
    outcome_notes         TEXT,
    structural_signature  TEXT,  -- JSON array

    -- Quality
    confidence            TEXT,
    needs_review          INTEGER,
    review_note           TEXT,

    -- Provenance
    annotator             TEXT,
    annotation_date       TEXT,
    raw_response          TEXT,   -- full Claude response for audit
    validation_errors     TEXT    -- JSON array; empty = passed
);

CREATE TABLE IF NOT EXISTS annotation_stats (
    domain_id     INTEGER PRIMARY KEY,
    total         INTEGER DEFAULT 0,
    passed        INTEGER DEFAULT 0,
    needs_review  INTEGER DEFAULT 0,
    failed        INTEGER DEFAULT 0,
    last_updated  TEXT
);

CREATE INDEX IF NOT EXISTS idx_ann_domain   ON annotations(domain_id);
CREATE INDEX IF NOT EXISTS idx_ann_outcome  ON annotations(chain_outcome);
CREATE INDEX IF NOT EXISTS idx_ann_cd       ON annotations(contradiction_debt);
"""

class AnnotationDB:
    def __init__(self, db_path: str):
        # A long re-annotation run overlaps the nightly cron jobs, so two
        # writers can hit this DB at once. WAL plus a generous busy timeout
        # makes them queue instead of raising "database is locked".
        self.conn = sqlite3.connect(db_path, check_same_thread=False,
                                    timeout=60.0)
        self.conn.execute("PRAGMA busy_timeout=60000")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def already_annotated(self, case_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM annotations WHERE case_id=?", (case_id,)
        ).fetchone()
        return row is not None

    def existing_mask_state(self, case_id: int) -> bool:
        """
        Was this case's current annotation produced with the disposition masked?

        Re-annotation must not silently convert the blind-annotated corpus
        (annotator='claude-masked', the bulk of the civil set) into unmasked
        rows. The v2 migration changes the *rules*, not the masking regime, so
        each row is redone under whichever regime produced it.
        """
        row = self.conn.execute(
            "SELECT was_masked, annotator FROM annotations WHERE case_id=?",
            (case_id,)
        ).fetchone()
        if not row:
            return False
        was_masked, annotator = row
        # The legacy blind-annotated corpus carries annotator='claude-masked'
        # but left was_masked at 0, so the annotator tag is authoritative for
        # those rows. Treat a case as masked if EITHER signal says so.
        if (annotator or "").strip() == "claude-masked":
            return True
        return bool(was_masked)

    def already_annotated_v2(self, case_id: int) -> bool:
        """
        True only if this case carries a POST-remediation annotation.

        Used by --reannotate-v1: rows written under the old regime
        (claude-pipeline-v1, which derived N7/N8 from the disposition) are
        treated as pending so they get redone under the v2 rules. Because
        save() is INSERT OR REPLACE and each row flips v1 -> v2 as it is
        rewritten, an interrupted run resumes exactly where it stopped.
        """
        row = self.conn.execute(
            "SELECT annotator FROM annotations WHERE case_id=?", (case_id,)
        ).fetchone()
        return row is not None and row[0] == "claude-pipeline-v2"

    def save(self, ann: dict, raw_response: str, errors: list,
             was_masked: bool = None):
        nodes = ann.get("nodes", {})
        now   = datetime.now(timezone.utc).isoformat()

        self.conn.execute("""
            INSERT OR REPLACE INTO annotations
                (case_id, case_name, citation, court, date_decided,
                 domain_id, domain_name,
                 node1_closure, node2_closure, node3_closure, node4_closure,
                 node5_closure, node6_closure, node7_closure, node8_closure,
                 node1_entity, node2_entity, node3_entity, node3_roles,
                 node4_entity, node5_entity, node6_entity,
                 node7_entity, node8_entity,
                 was_masked,
                 active_contradictions, contradiction_debt, cd_upstream,
                 chain_outcome, outcome_notes, structural_signature,
                 confidence, needs_review, review_note,
                 annotator, annotation_date, raw_response, validation_errors)
            VALUES (
                ?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,
                ?,?,?,
                ?,?,?,?
            )
        """, (
            ann["case_id"],
            ann.get("case_name", ""),
            ann.get("citation", ""),
            ann.get("court", ""),
            ann.get("date_decided", ""),
            ann.get("domain_id"),
            DOCTRINAL_DOMAINS.get(ann.get("domain_id"), ""),

            nodes.get("1", {}).get("closure"),
            nodes.get("2", {}).get("closure"),
            nodes.get("3", {}).get("closure"),
            nodes.get("4", {}).get("closure"),
            nodes.get("5", {}).get("closure"),
            nodes.get("6", {}).get("closure"),
            nodes.get("7", {}).get("closure"),
            nodes.get("8", {}).get("closure"),

            nodes.get("1", {}).get("entity", ""),
            nodes.get("2", {}).get("entity", ""),
            nodes.get("3", {}).get("entity", ""),
            json.dumps(nodes.get("3", {}).get("roles_borne", [])),
            nodes.get("4", {}).get("entity", ""),
            nodes.get("5", {}).get("entity", ""),
            nodes.get("6", {}).get("entity", ""),
            nodes.get("7", {}).get("entity", ""),
            nodes.get("8", {}).get("entity", ""),

            (1 if was_masked else 0) if was_masked is not None else None,
            json.dumps(ann.get("active_contradictions", [])),
            ann.get("contradiction_debt") or compute_cd(ann),
            # Structural stress over N1-N6 only — the component NOT downstream
            # of the Pass-2 derivation rule (remediation spec 3.2).
            compute_cd_upstream(ann),
            ann.get("chain_outcome", ""),
            ann.get("outcome_notes", ""),
            json.dumps(ann.get("structural_signature") or
                       compute_structural_signature(ann)),

            ann.get("confidence", "low"),
            1 if ann.get("needs_review") else 0,
            ann.get("review_note", ""),

            # v2 = post-remediation regime (spec §4.2/§4.3): RULE 1 and RULE 5
            # deleted, RULE 0 relaxed. Rows tagged v1 were produced under the
            # rules that derived N7/N8 from the disposition and must NOT be
            # pooled with v2 rows for any outcome analysis.
            "claude-pipeline-v2",
            now,
            raw_response[:4000] if raw_response else "",
            json.dumps(errors),
        ))
        self.conn.commit()

    def count(self, domain_id: int = None) -> int:
        if domain_id:
            return self.conn.execute(
                "SELECT COUNT(*) FROM annotations WHERE domain_id=?",
                (domain_id,)
            ).fetchone()[0]
        return self.conn.execute(
            "SELECT COUNT(*) FROM annotations"
        ).fetchone()[0]

    def count_needs_review(self, domain_id: int = None) -> int:
        if domain_id:
            return self.conn.execute(
                "SELECT COUNT(*) FROM annotations WHERE needs_review=1 AND domain_id=?",
                (domain_id,)
            ).fetchone()[0]
        return self.conn.execute(
            "SELECT COUNT(*) FROM annotations WHERE needs_review=1"
        ).fetchone()[0]

    def get_all(self, domain_id: int = None):
        if domain_id:
            return self.conn.execute(
                "SELECT * FROM annotations WHERE domain_id=? ORDER BY case_id",
                (domain_id,)
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM annotations ORDER BY domain_id, case_id"
        ).fetchall()

    def get_review_queue(self):
        return self.conn.execute(
            "SELECT * FROM annotations WHERE needs_review=1 ORDER BY domain_id"
        ).fetchall()

    def contradiction_distribution(self):
        """Returns cross-domain structural signature frequency — the key validation query."""
        rows = self.conn.execute(
            "SELECT domain_id, active_contradictions, chain_outcome, "
            "contradiction_debt FROM annotations"
        ).fetchall()

        dist = {}  # signature -> {domain -> count}
        for row in rows:
            try:
                cts = json.loads(row["active_contradictions"] or "[]")
            except Exception:
                continue
            for ct in cts:
                if ct not in dist:
                    dist[ct] = {}
                d = str(row["domain_id"])
                dist[ct][d] = dist[ct].get(d, 0) + 1
        return dist


# ─────────────────────────────────────────────────────────────────────────────
# THE MLC ANNOTATION PROMPT
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert legal ontologist trained in the Structural Ontology of the Law (SOoL) framework developed by David R. Koepsell. Your task is to annotate court opinions using the Minimum Legal Chain (MLC).

THE MINIMUM LEGAL CHAIN (MLC):
A legal effect is valid only if each of 8 nodes closes in sequence:
  Node 1 - Source of Authority: The constitutional/statutory/institutional ground of norm-issuance
  Node 2 - Norm: The specific rule or standard being applied
  Node 3 - Actor in Role: The agent bearing the norm-governed capacity (may bear multiple roles)
  Node 4 - Triggering Facts: The circumstances activating the norm
  Node 5 - Legal Act/Omission: The conduct that instantiates the trigger
  Node 6 - Target: The entity upon whom the legal effect is directed
  Node 7 - Legal Effect: The normative consequence (right, duty, power, liability)
  Node 8 - Remedy: The mechanism for restoring coherence on breach

NODE CLOSURE VALUES:
  "closed"        - node fully satisfied, chain continues
  "failed"        - node not satisfied, chain breaks here
  "partial"       - node partially satisfied, chain stressed
  "indeterminate" - cannot be determined from the opinion text

CONTRADICTION TYPES — use these exact codes:
  CF   Conferral Failure         (1→3)   Authority fails to vest actor in role properly
  AINF Authority Inflation       (1→2)   Decision-maker's will displaces norm; personal rule
  JC   Jurisdictional Contradiction (2→6) Competing normative regimes govern same situation
  RC3  Role Contradiction        (N.3)   Same bearer holds roles that generate incompatible obligations for the SAME act
  PC   Procedural Contradiction  (2→5)   Act required by norm cannot follow norm's own procedure
  TC   Temporal Contradiction    (2↔4)   Norm and triggering facts are in bidirectional temporal misalignment
  FM   Fact Manipulation         (N.4)   Triggering facts fabricated, suppressed, or made indeterminate
  NI   Norm Indeterminacy        (N.2)   Norm too vague to produce determinate closure; court cannot specify rule
  RF   Recognition Failure       (6/7)   Target or legal effect denied required recognition
  RCL  Recognition Collapse      (6→8)   Subjecthood stripped while enforcement of obligations continues
  CC   Correlativity Contradiction (N.7) Rights claimed without correlative duties honored
  SE   Self-Undermining Effect   (N.7)   Legal effect destabilizes conditions for system's own persistence
  RPF  Repair Failure            (N.8)   Remedy structurally available but blocked or inaccessible

MANDATORY INFERENCE RULES — you MUST apply these automatically:

RULE 0 — PERSPECTIVE (apply before everything else):
The MLC always traces THE CLAIMANT'S chain — the party asserting
the legal right or protection that the court is evaluating.

  chain_outcome "protection_granted" = THE CLAIMANT won.
  chain_outcome "protection_denied"  = THE CLAIMANT lost.
  Node 7 asks: does THE CLAIMANT'S asserted legal effect attach?
  Node 8 asks: does THE CLAIMANT have a remedy?

The government's enforcement authority, the agency's regulatory
power, and the prevailing party's legal mechanisms are IRRELEVANT
to Node 7 and Node 8.

Node 8 usually follows Node 7 — a claimant whose right did not attach
normally has no remedy. But assess Node 8 on its OWN evidence and let
it diverge when the text supports divergence. A remedy can be
independently available (an alternative statutory route, a
proportionality limit) or independently blocked (habeas gatekeeping,
a FRAND posture, procedurally inaccessible relief) regardless of
Node 7. When Node 8 diverges from Node 7, say so in outcome_notes.
Divergence is a finding, not an error.

RULE 2 — ROLE CONTRADICTION: If roles_borne contains 2+ roles AND the same triggering act (Node 4/5)
  produces incompatible effects through each role, then RC3 MUST appear in active_contradictions.
  Example: "public employee" + "citizen speaker" where official-duty rule defeats citizen speech = RC3.
  Example: "academic" + "state employee" where Garcetti defeats First Amendment = RC3.

RULE 3 — NORM INDETERMINACY: If the court explicitly reserves, defers, or declines to decide the
  scope of the governing norm, OR if the norm's application to these facts is genuinely contested,
  then NI MUST appear in active_contradictions.
  Example: Garcetti majority reserving the academic speech question = NI.

RULE 4 — JURISDICTIONAL CONTRADICTION: If Node 1 has TWO authority sources (e.g., constitutional
  AND institutional/statutory) that generate competing norms at Node 2 over the same conduct,
  then JC MUST appear in active_contradictions.

RULE 6 — CORRELATIVITY: If the claimant asserts a right (Node 7) but the opposing party refuses
  to honor the correlative duty, and the court sides with the refusal, then CC fires at Node 7.
  This is the qualified-immunity shape: the court may ASSUME or acknowledge the violation and
  still bar liability. That is CC — right acknowledged, correlative duty refused — and it is
  NOT the same as RF. Do not collapse it into RF.

ASSIGNING RF, CC AND RPF:
  Assign each on its own textual evidence, from what the court actually says.
  - RF  — the court declines to recognise the asserted right or legal effect at all.
  - CC  — the right is recognised or assumed, but the correlative duty is refused.
  - RPF — repair is specifically blocked or unavailable, on the court's own reasoning.
  Do NOT assign any of these merely because the claimant lost, and do not treat them as
  automatic consequences of a Node 7 or Node 8 failure. A denial with no separate
  recognition, correlativity or repair reasoning may carry none of them.

CHAIN OUTCOMES — use exactly one:
  protection_granted  - claimant's right/protection recognized
  protection_denied   - claimant's right/protection denied
  partial             - mixed outcome
  remanded            - sent back for further proceedings
  dismissed           - case dismissed on procedural grounds
  moot                - case rendered moot

STEP-BY-STEP ANNOTATION PROCEDURE:
1. Identify the legal claim and who is making it (Node 6 target).
2. Trace the authority chain: what constitutional/statutory source grounds this claim (Node 1)?
3. What norm does that authority issue (Node 2)? Is it determinate? Contested?
4. Who is the actor and what roles do they bear (Node 3)? List ALL roles explicitly.
5. What facts triggered the legal action (Node 4)? What act occurred (Node 5)?
6. Does the legal effect (Node 7) close? If not, why — which node caused the failure?
7. Is remedy available (Node 8)?
8. NOW APPLY THE MANDATORY INFERENCE RULES above to derive active_contradictions.
9. Assign confidence: "high" if opinion text is clear; "medium" if inferring; "low" if text absent.

CRITICAL RULES:
- Contradiction Debt is STRUCTURAL, not moral. A coherent chain can produce an unjust outcome.
- Only assert contradictions derivable from the opinion. Do not invent facts.
- If the case appears to be in the wrong doctrinal area (e.g., a labor preemption case in a
  First Amendment corpus), set needs_review=true and explain in review_note.
- After completing node assessment, always re-check: does your contradiction list match
  what your node closures imply? If N7=failed, you need RF or CC or both. If N8=failed, you need RPF.

OUTPUT FORMAT:
Return ONLY a valid JSON object — no preamble, no explanation, no markdown code fences.

{
  "nodes": {
    "1": {"closure": "...", "entity": "...", "justification": "..."},
    "2": {"closure": "...", "entity": "...", "justification": "..."},
    "3": {"closure": "...", "entity": "...", "roles_borne": [...], "justification": "..."},
    "4": {"closure": "...", "entity": "...", "justification": "..."},
    "5": {"closure": "...", "entity": "...", "justification": "..."},
    "6": {"closure": "...", "entity": "...", "justification": "..."},
    "7": {"closure": "...", "entity": "...", "justification": "..."},
    "8": {"closure": "...", "entity": "...", "justification": "..."}
  },
  "active_contradictions": [...],
  "chain_outcome": "...",
  "outcome_notes": "...",
  "confidence": "high|medium|low",
  "needs_review": false,
  "review_note": ""
}"""


def sanitize_text(text: str) -> str:
    """Remove null bytes, control characters, and invalid sequences that cause 400 errors."""
    if not text:
        return ""
    # Remove null bytes and other control characters except newline/tab
    text = text.replace('\x00', '')
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Encode/decode to strip any invalid unicode sequences
    text = text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# PHASE IV DOMAIN-SPECIFIC ANNOTATION SUPPLEMENTS
# Plain ASCII only -- no Unicode special chars
# ---------------------------------------------------------------------------

_SUPP_9 = (
    "DOMAIN-SPECIFIC GUIDANCE: HABEAS CORPUS / POST-CONVICTION RELIEF\n"
    "Primary expected failure: Node 8 (Repair) -- the proceeding challenges\n"
    "adequacy of repair in a prior proceeding.\n\n"
    "NODE NOTES:\n"
    "N1: Authority = habeas statute (Art I Sec.9; 28 USC Sec.2254/Sec.2255).\n"
    "    AEDPA limits are a Node 2 issue, not Node 1.\n"
    "N2: AEDPA unreasonable-application standard is itself a source of NI.\n"
    "N3: Petitioner = convicted prisoner asserting constitutional right denied below.\n"
    "N8: PRIMARY BATTLEGROUND. Code RPF when prior remedy was constitutionally\n"
    "    inadequate. This is NOT a cascade from N7 -- it is an independent N8 challenge.\n\n"
    "COMMON PATTERNS:\n"
    "  Ineffective assistance (Strickland): RC3 at N3 of trial -> RPF at N8 of habeas.\n"
    "  Brady violation: FM at N4 of trial -> RPF at N8 of habeas.\n"
    "  Procedural default / AEDPA bar: NI at N2 + JC (state vs federal procedure).\n"
    "  Actual innocence: FM at N4 -> RCL (prisoner as object not subject).\n\n"
    "Perspective: claimant = habeas petitioner.\n"
    "  protection_granted = petition succeeded.\n"
    "  protection_denied  = petition dismissed or denied.\n"
)

_SUPP_10 = (
    "DOMAIN-SPECIFIC GUIDANCE: PATENT / INTELLECTUAL PROPERTY\n"
    "Primary expected failure: Node 1 (Source of Authority) -- the validity\n"
    "of the grant itself is the central question.\n\n"
    "NODE NOTES:\n"
    "N1: Authority = patent grant (USPTO), copyright registration, or trademark.\n"
    "    CF fires when patent is found INVALID (obviousness, anticipation,\n"
    "    Sec.101 ineligibility, inequitable conduct). N1 failure is common here.\n"
    "N2: Claim construction. NI fires for indefinite claims (Sec.112),\n"
    "    means-plus-function ambiguity, or abstract idea uncertainty (Alice/Mayo).\n"
    "N3: Patentee/licensor/assignee role. RC3 in joint inventorship disputes.\n"
    "    CF if chain of title is broken (no standing to sue).\n"
    "N4/5: Accused infringing act. Doctrine of equivalents = N5 question.\n"
    "N6: Accused infringer. JC fires in FRAND/SEP disputes.\n"
    "N7/8: RF when infringement not found. CC when FRAND blocks enforcement.\n\n"
    "COMMON PATTERNS:\n"
    "  Sec.101 ineligibility (Alice): NI at N2 + CF at N1.\n"
    "  Patent invalidity defense: CF at N1.\n"
    "  Copyright fair use: NI at N2 + RF at N7.\n"
    "  Trade secret: FM at N4 if secret improperly acquired.\n\n"
    "Perspective: claimant = IP rights-holder asserting infringement/validity.\n"
    "  protection_granted = infringement found / validity upheld.\n"
    "  protection_denied  = no infringement / IP right invalid / fair use found.\n"
)

_SUPP_11 = (
    "DOMAIN-SPECIFIC GUIDANCE: SECURITIES REGULATION\n"
    "Primary expected failure: Node 3 (Actor in Role) -- which institutional\n"
    "role the defendant bore and what obligations attached is the central question.\n\n"
    "NODE NOTES:\n"
    "N1: Authority = Securities Exchange Act (1934), Securities Act (1933),\n"
    "    Dodd-Frank, SEC rules. AI fires when SEC extends beyond statutory\n"
    "    authorization (increasingly common post-Loper Bright).\n"
    "N2: Rule 10b-5 (fraud), materiality standard, duty to disclose, Reg FD.\n"
    "    NI fires when materiality is genuinely contested or Janus creates ambiguity.\n"
    "N3: PRIMARY BATTLEGROUND. Insider vs outsider, tipper vs tippee, officer\n"
    "    vs employee, investment adviser vs broker, primary vs secondary actor.\n"
    "    RC3 fires when same actor bears incompatible roles:\n"
    "      Corporate officer (duty of loyalty) + personal investor = RC3.\n"
    "      Investment adviser (fiduciary) + broker (suitability only) = RC3.\n"
    "      Primary actor (Sec.10b liable) + secondary actor (not liable\n"
    "        under Central Bank) = RC3 in scheme liability cases.\n"
    "    CF fires when authority failed to vest obligation in the role\n"
    "      (Janus -- maker vs speaker distinction).\n"
    "N4/5: Triggering act = misstatement, omission, manipulative trading.\n"
    "    FM fires in market manipulation (wash trading, spoofing).\n"
    "N6: Investor/class as target. JC where SEC enforcement and private\n"
    "    class action operate under incompatible standards.\n"
    "N7/8: RF when scienter not found. CC when scheme liability acknowledged\n"
    "    but secondary actor immunity blocks enforcement of correlative duty.\n\n"
    "COMMON PATTERNS:\n"
    "  Insider trading (Dirks/misappropriation): RC3 at N3.\n"
    "  Rule 10b-5 class action: NI at N2 + RF at N7.\n"
    "  SEC enforcement post-Loper Bright: AI at N1/N2.\n"
    "  Ponzi/fraud: FM at N4 + RF at N7.\n"
    "  Dodd-Frank whistleblower retaliation: N5 primary + RF at N7.\n\n"
    "Perspective: investor/plaintiff in private actions; SEC in enforcement.\n"
    "  protection_granted = claimant prevails / violation found.\n"
    "  protection_denied  = claimant loses / no violation found.\n"
)

DOMAIN_SUPPLEMENTS = {9: _SUPP_9, 10: _SUPP_10, 11: _SUPP_11}


def get_system_prompt(domain_id):
    """Return SYSTEM_PROMPT with optional domain-specific supplement appended."""
    base = SYSTEM_PROMPT
    supplement = DOMAIN_SUPPLEMENTS.get(domain_id)
    if supplement:
        base = base + "\n\n" + supplement
    return base



def build_user_prompt(case: dict, domain_id: int, mask_disposition: bool = False) -> str:
    """Build the per-case user prompt from the case record."""
    domain_name = DOCTRINAL_DOMAINS.get(domain_id, "unknown")

    # Get best available opinion text
    text = ""
    for op in case.get("opinions", []):
        t = op.get("plain_text", "") or op.get("html_text", "") or ""
        if len(t) > len(text):
            text = t

    # Strip HTML tags if present
    text = re.sub(r'<[^>]+>', ' ', text)
    # Sanitize — remove null bytes, control chars, invalid UTF-8
    text = sanitize_text(text)

    # Truncate to budget
    if len(text) > OPINION_CHARS:
        text = text[:OPINION_CHARS] + "\n\n[... opinion truncated for length ...]"

    # ── Outcome masking (equipoise / blind annotation) ──────────────────
    masked_flag = False
    if mask_disposition:
        text, masked_flag = strip_disposition(text)
        if masked_flag:
            log.debug(f"  Masked disposition in {case.get('case_name', '?')[:40]}")

    case_name   = sanitize_text(case.get("case_name", "Unknown"))
    citation    = case.get("citations", [""])[0] if case.get("citations") else ""
    court       = case.get("court_id", "")
    date_filed  = case.get("date_filed", "")

    prompt = f"""CASE: {case_name}
CITATION: {citation}
COURT: {court}  |  DATE: {date_filed}
DOCTRINAL DOMAIN: {domain_name}

OPINION TEXT:
{text if text else "[No opinion text available — annotate from case name and citation only; set confidence to low]"}

---
Annotate this case using the SOoL Minimum Legal Chain framework.
Return ONLY the JSON object described in your instructions."""

    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# CLAUDE API CALL
# ─────────────────────────────────────────────────────────────────────────────

def call_claude(user_prompt: str, domain_id: int = 0) -> tuple[str, str]:
    """
    Call the Claude API. Returns (raw_response_text, error_string).
    error_string is empty on success.
    """
    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": MAX_TOKENS,
        # Sonnet 5 runs adaptive thinking when `thinking` is omitted, and
        # max_tokens caps thinking + response text together — which would eat
        # the budget and truncate the JSON these prompts are tuned to emit.
        # Keep the non-thinking behaviour the prompt set was built against.
        "thinking":   {"type": "disabled"},
        "system":     SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": user_prompt}],
    }

    try:
        r = requests.post(
            CLAUDE_API_URL,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json=payload,
            timeout=60,
        )
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 30))
            log.warning(f"Rate limited — waiting {wait}s")
            time.sleep(wait)
            return call_claude(user_prompt)  # one retry
        if r.status_code == 400:
            log.warning(f"400 Bad Request body: {r.text[:400]}")
            return "", f"400: {r.text[:200]}"
        r.raise_for_status()
        data = r.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
        return text.strip(), ""
    except requests.RequestException as e:
        return "", str(e)


def parse_claude_response(raw: str) -> tuple[dict, str]:
    """
    Parse Claude's JSON response. Returns (annotation_dict, error_string).
    Strips markdown fences if present.
    """
    if not raw:
        return {}, "Empty response"

    # Strip markdown code fences
    clean = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.MULTILINE)
    clean = re.sub(r'\s*```$', '', clean.strip(), flags=re.MULTILINE)
    clean = clean.strip()

    try:
        return json.loads(clean), ""
    except json.JSONDecodeError as e:
        # Try to find the first { ... } block
        match = re.search(r'\{[\s\S]+\}', clean)
        if match:
            try:
                return json.loads(match.group(0)), ""
            except Exception:
                pass
        return {}, f"JSON parse error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# CORE ANNOTATION LOOP
# ─────────────────────────────────────────────────────────────────────────────

def annotate_domain(db: AnnotationDB, domain_id: int,
                    limit: int = None, dry_run: bool = False,
                    mask_disposition: bool = False,
                    reannotate_v1: bool = False):
    """Annotate all cases in a domain JSONL file."""
    fname = DOMAIN_FILES.get(domain_id)
    if not fname:
        log.error(f"Unknown domain: {domain_id}")
        return

    fpath = os.path.join(CORPUS_DIR, fname)
    if not os.path.exists(fpath):
        log.error(f"Corpus file not found: {fpath}")
        return

    # Load cases
    cases = []
    with open(fpath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    cases.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Filter already-annotated. Under --reannotate-v1 a case counts as done
    # only if it already carries a v2 annotation, so old-regime rows are
    # re-processed (and the run is resumable — see already_annotated_v2).
    _done = db.already_annotated_v2 if reannotate_v1 else db.already_annotated
    pending = [c for c in cases
               if not _done(c.get("id") or c.get("case_id"))]

    if limit:
        pending = pending[:limit]

    domain_name = DOCTRINAL_DOMAINS.get(domain_id, "unknown")
    log.info(f"\nDomain {domain_id} ({domain_name}): "
             f"{len(pending)} pending / {len(cases)} total")

    if not pending:
        log.info("  All cases already annotated.")
        return

    if dry_run:
        log.info(f"  DRY RUN — would annotate {len(pending)} cases.")
        for c in pending[:3]:
            log.info(f"    {c.get('case_name', '?')[:60]}")
        return

    review_writer = open(REVIEW_QUEUE, "a", encoding="utf-8")
    passed = failed_parse = failed_validation = flagged = 0
    last_call = 0.0

    for case in tqdm(pending, desc=f"D{domain_id} {domain_name[:20]}", unit="case"):
        case_id   = case.get("id") or case.get("case_id")
        case_name = case.get("case_name", "Unknown")

        # Rate limit
        elapsed = time.time() - last_call
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        last_call = time.time()

        # Build prompt and call API
        # Preserve each row's original masking regime when redoing the corpus
        # under the v2 rules; otherwise the blind-annotated set would silently
        # become unmasked.
        _mask = mask_disposition
        if reannotate_v1:
            _mask = db.existing_mask_state(case.get("id") or case.get("case_id"))
        user_prompt = build_user_prompt(case, domain_id, mask_disposition=_mask)
        raw, api_err = call_claude(user_prompt, domain_id)

        if api_err:
            log.warning(f"  API error for {case_name[:50]}: {api_err}")
            failed_parse += 1
            continue

        # Parse response
        parsed, parse_err = parse_claude_response(raw)
        if parse_err:
            log.warning(f"  Parse error for {case_name[:50]}: {parse_err}")
            failed_parse += 1
            continue

        # Build full annotation record
        citation = ""
        _cites = case.get("citations", []) or case.get("citation", [])
        if isinstance(_cites, list) and _cites:
            _first = _cites[0]
            citation = _first.get("cite","") if isinstance(_first,dict) else str(_first)
        elif isinstance(_cites, str):
            citation = _cites
        citation = citation.strip()

        annotation = {
            "case_id":        case_id,
            "case_name":      case_name,
            "citation":       citation,
            "court":          case.get("court_id", ""),
            "date_decided":   case.get("date_filed", ""),
            "domain_id":      domain_id,
            "annotator":      f"claude/{CLAUDE_MODEL}",
            "annotation_date": datetime.now(timezone.utc).isoformat(),
            **parsed,
        }

        # Compute derived fields
        annotation["contradiction_debt"]   = compute_cd(annotation)
        annotation["structural_signature"] = compute_structural_signature(annotation)

        # Validate. Runs against the model's raw `active_contradictions` so a
        # malformed entry is reported before normalization discards it.
        errors = validate(annotation)

        # Store the canonical bare-code list, whatever shape the model emitted.
        annotation["active_contradictions"] = normalize_contradictions(annotation)

        # Determine review status
        needs_review = (
            annotation.get("needs_review", False)
            or annotation.get("confidence") == "low"
            or len(errors) > 0
        )
        annotation["needs_review"] = needs_review
        if errors:
            annotation["review_note"] = (
                (annotation.get("review_note") or "") +
                " | VALIDATION: " + "; ".join(errors)
            ).strip(" | ")

        # Save to DB
        db.save(annotation, raw, errors, was_masked=_mask)

        # ── EQUIPOISE PASS 3: Adversarial check ──────────────────────────────
        if EQUIPOISE_AVAILABLE and not api_err and not parse_err:
            try:
                nodes_summary = {
                    str(n): annotation.get(f'node{n}_closure', 'indeterminate')
                    for n in range(1, 9)
                }
                cts     = annotation.get('active_contradictions', [])
                cd      = annotation.get('contradiction_debt', 0)
                outcome = annotation.get('chain_outcome', '')
                user_p3 = (
                    f"Node closures: {nodes_summary}\n"
                    f"Active CTs: {cts}\nOutcome: {outcome}\nCD: {cd}\n\n"
                    f"Argue the strongest structural case for the OPPOSITE outcome."
                )
                import anthropic as _ant
                _client = _ant.Anthropic(api_key=CLAUDE_API_KEY)
                raw_p3, _err = eq_call_claude(_client, SYSTEM_PASS3, user_p3,
                                              max_tokens=800)
                if not _err:
                    p3 = eq_parse_json(raw_p3)
                    if p3:
                        strength = float(p3.get('adversarial_strength', 0.0))
                        notes    = p3.get('adversarial_notes', '')
                        eq_flag  = strength >= 0.65 or p3.get('flag_for_review', False)
                        db.conn.execute("""
                            UPDATE annotations
                            SET adversarial_strength = ?,
                                adversarial_notes    = ?,
                                equipoise_flagged    = ?,
                                annotation_method    = 'equipoise_3pass'
                            WHERE case_id = ?
                        """, (strength, notes, 1 if eq_flag else 0, case_id))
                        db.conn.commit()
                        if eq_flag:
                            annotation['needs_review'] = True
            except Exception as _eq_err:
                log.debug(f"  Equipoise check failed: {_eq_err}")

        if errors:
            failed_validation += 1
        elif needs_review:
            flagged += 1
        else:
            passed += 1

        # Write to review queue if needed
        if needs_review:
            review_writer.write(json.dumps({
                "case_id":      case_id,
                "case_name":    case_name,
                "domain_id":    domain_id,
                "confidence":   annotation.get("confidence"),
                "errors":       errors,
                "review_note":  annotation.get("review_note", ""),
                "annotation":   annotation,
            }, ensure_ascii=False) + "\n")

    review_writer.close()

    total = passed + failed_parse + failed_validation + flagged
    log.info(f"\n  Domain {domain_id} annotation complete:")
    log.info(f"    Passed (high/medium confidence, no errors): {passed}")
    log.info(f"    Flagged for review (low confidence):        {flagged}")
    log.info(f"    Validation errors (saved, needs review):    {failed_validation}")
    log.info(f"    Parse/API failures (not saved):             {failed_parse}")
    log.info(f"    Total processed: {total}")

    return {
        "passed":            passed,
        "flagged":           flagged,
        "failed_validation": failed_validation,
        "failed_parse":      failed_parse,
        "total":             total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# STATISTICS AND VALIDATION QUERIES
# ─────────────────────────────────────────────────────────────────────────────

def reannotate_mixed_perspective(db: AnnotationDB, api_key: str):
    """
    Re-annotate only the cases with mixed-perspective errors:
    (protection_granted AND node7=failed) OR (protection_denied AND node7=closed).
    Uses the corrected prompt with Rule 0.
    """
    global CLAUDE_API_KEY
    CLAUDE_API_KEY = api_key

    rows = db.conn.execute("""
        SELECT case_id, case_name, domain_id
        FROM annotations
        WHERE (chain_outcome='protection_granted' AND node7_closure='failed')
           OR (chain_outcome='protection_denied'  AND node7_closure='closed')
        ORDER BY domain_id
    """).fetchall()

    log.info(f"\nRe-annotating {len(rows)} mixed-perspective cases...")

    # Load corpus files into memory for lookup
    corpus = {}
    for domain_id, fname in DOMAIN_FILES.items():
        fpath = os.path.join(CORPUS_DIR, fname)
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
                    if cid:
                        # Key as str. The annotations table declares case_id TEXT, so
                        # sqlite3 hands back '195132', while the corpus JSONL "id" is a
                        # JSON number and arrives as int 195132. Keying on the raw value
                        # made the membership test below always fail, so all 111
                        # mixed-perspective rows were reported "not found in corpus"
                        # on every nightly run since at least 2026-08-18.
                        corpus[str(cid)] = (case, domain_id)
                except json.JSONDecodeError:
                    continue

    fixed = failed = 0
    last_call = 0.0

    for row in tqdm(rows, desc="Re-annotating mixed-perspective", unit="case"):
        case_id   = str(row["case_id"])   # see the str() keying note above
        case_name = row["case_name"]
        domain_id = row["domain_id"]

        if case_id not in corpus:
            log.warning(f"  Case {case_id} ({case_name[:40]}) not found in corpus.")
            failed += 1
            continue

        case, _ = corpus[case_id]

        elapsed = time.time() - last_call
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        last_call = time.time()

        user_prompt = build_user_prompt(case, domain_id)
        raw, api_err = call_claude(user_prompt, domain_id)

        if api_err:
            log.warning(f"  API error for {case_name[:40]}: {api_err}")
            failed += 1
            continue

        parsed, parse_err = parse_claude_response(raw)
        if parse_err:
            log.warning(f"  Parse error for {case_name[:40]}: {parse_err}")
            failed += 1
            continue

        citation = ""
        if isinstance(case.get("citations"), list) and case["citations"]:
            citation = case["citations"][0]

        annotation = {
            "case_id":        case_id,
            "case_name":      case_name,
            "citation":       citation,
            "court":          case.get("court_id", ""),
            "date_decided":   case.get("date_filed", ""),
            "domain_id":      domain_id,
            "annotator":      f"claude/{CLAUDE_MODEL}/reannotated",
            "annotation_date": datetime.now(timezone.utc).isoformat(),
            **parsed,
        }

        annotation["contradiction_debt"]   = compute_cd(annotation)
        annotation["structural_signature"] = compute_structural_signature(annotation)

        errors = validate(annotation)
        annotation["needs_review"] = bool(errors or
            annotation.get("needs_review") or
            annotation.get("confidence") == "low")
        if errors:
            annotation["review_note"] = (
                (annotation.get("review_note") or "") +
                " | VALIDATION: " + "; ".join(errors)
            ).strip(" | ")

        # Check if perspective was fixed
        n7 = annotation.get("nodes", {}).get("7", {}).get("closure")
        outcome = annotation.get("chain_outcome", "")
        still_mixed = (
            (outcome == "protection_granted" and n7 == "failed") or
            (outcome == "protection_denied"  and n7 == "closed")
        )

        if still_mixed:
            log.warning(f"  Still mixed after re-annotation: {case_name[:50]}")
            annotation["needs_review"] = True
            annotation["review_note"] = (
                (annotation.get("review_note") or "") +
                " | STILL MIXED PERSPECTIVE AFTER RE-ANNOTATION"
            ).strip(" | ")

        db.save(annotation, raw, errors)
        fixed += 1

    log.info(f"\n  Re-annotation complete: {fixed} re-annotated, {failed} failed.")
    log.info(f"  Run --stats to see updated distribution.")

    # Health gate, mirroring the one at the end of the normal annotation path.
    # That gate exists because "the pipeline exits 0 on a dead model ID and the
    # caller reports '0 errors'". It was never extended to this branch, which is
    # the identical attempted>0 / saved==0 condition, so a 111-of-111 failure was
    # recorded as a clean run for weeks.
    attempted = fixed + failed
    if attempted and fixed == 0:
        log.error(f"  Attempted {attempted} re-annotation(s) and saved none. "
                  f"Treating as failure.")
        sys.exit(1)


def print_stats(db: AnnotationDB):
    print("\n" + "="*65)
    print("ANNOTATION STATISTICS")
    print("="*65)

    for domain_id, domain_name in DOCTRINAL_DOMAINS.items():
        total  = db.count(domain_id)
        review = db.count_needs_review(domain_id)
        print(f"  D{domain_id} {domain_name:<35} {total:>4} annotated  "
              f"({review} need review)")

    print(f"\n  TOTAL ANNOTATED: {db.count()}")
    print(f"  TOTAL NEEDS REVIEW: {db.count_needs_review()}")

    # Contradiction distribution across domains
    print("\n" + "-"*65)
    print("CONTRADICTION TYPE DISTRIBUTION ACROSS DOMAINS")
    print("(This is the primary validation query — cross-domain clustering)")
    print("-"*65)

    dist = db.contradiction_distribution()
    if not dist:
        print("  No annotations yet.")
    else:
        domain_ids = [str(i) for i in range(1, 9)]
        header = f"  {'CT':<6} {'Name':<32} " + " ".join(f"D{i}" for i in range(1, 9))
        print(header)
        print("  " + "-"*63)
        for ct, counts in sorted(dist.items(),
                                  key=lambda x: -sum(x[1].values())):
            name = CONTRADICTION_TYPES.get(ct, ("?",))[0][:30]
            row  = f"  {ct:<6} {name:<32} "
            row += " ".join(f"{counts.get(str(i), 0):>2}" for i in range(1, 9))
            print(row)
        print()
        print("  INTERPRETATION: If SOoL's structural universality hypothesis")
        print("  holds, contradiction types should cluster ACROSS domains")
        print("  (non-zero values in multiple D columns for the same CT row).")
        print("  Random distribution would show each CT concentrated in 1-2 domains.")

    # Chain outcome distribution
    print("\n" + "-"*65)
    print("CHAIN OUTCOME DISTRIBUTION")
    print("-"*65)
    rows = db.conn.execute("""
        SELECT chain_outcome, COUNT(*) as n,
               AVG(contradiction_debt) as avg_cd
        FROM annotations
        GROUP BY chain_outcome
        ORDER BY n DESC
    """).fetchall()
    for r in rows:
        print(f"  {r['chain_outcome']:<25} n={r['n']:>4}  "
              f"avg CD={r['avg_cd']:.3f}")

    # CD by domain
    print("\n" + "-"*65)
    print("MEAN CONTRADICTION DEBT BY DOMAIN")
    print("-"*65)
    rows = db.conn.execute("""
        SELECT domain_id, domain_name,
               COUNT(*) as n,
               AVG(contradiction_debt) as avg_cd,
               MAX(contradiction_debt) as max_cd
        FROM annotations
        GROUP BY domain_id
        ORDER BY avg_cd DESC
    """).fetchall()
    for r in rows:
        print(f"  D{r['domain_id']} {r['domain_name']:<35} "
              f"n={r['n']:>4}  avg CD={r['avg_cd']:.3f}  max={r['max_cd']:.3f}")

    print("="*65 + "\n")


def print_review_queue(db: AnnotationDB):
    queue = db.get_review_queue()
    print(f"\n{len(queue)} cases in review queue:\n")
    for row in queue:
        print(f"  [{row['domain_id']}] {row['case_name'][:55]:<55} "
              f"conf={row['confidence']:<6} "
              f"CD={row['contradiction_debt']:.2f}")
        if row['review_note']:
            print(f"       Note: {row['review_note'][:80]}")


def export_turtle(db: AnnotationDB, domain_id: int, output_path: str):
    """Export all annotations for a domain as OWL/Turtle."""
    rows = db.get_all(domain_id)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# SOoL MLC Annotations — Auto-generated\n")
        f.write(f"# Domain {domain_id}: {DOCTRINAL_DOMAINS.get(domain_id)}\n")
        f.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}\n\n")
        for row in rows:
            ann = {
                "case_id":    row["case_id"],
                "case_name":  row["case_name"],
                "citation":   row["citation"],
                "court":      row["court"],
                "date_decided": row["date_decided"],
                "domain_id":  row["domain_id"],
                "active_contradictions": json.loads(
                    row["active_contradictions"] or "[]"),
                "chain_outcome": row["chain_outcome"],
                "structural_signature": json.loads(
                    row["structural_signature"] or "[]"),
                "contradiction_debt": row["contradiction_debt"],
                "confidence": row["confidence"],
                "needs_review": bool(row["needs_review"]),
                "review_note": row["review_note"] or "",
                "nodes": {
                    str(n): {
                        "closure":      row[f"node{n}_closure"],
                        "entity":       row[f"node{n}_entity"] or "",
                        "justification": "",
                        **({"roles_borne": json.loads(
                                row["node3_roles"] or "[]")}
                           if n == 3 else {}),
                    }
                    for n in range(1, 9)
                },
            }
            try:
                f.write(to_turtle(ann) + "\n\n")
            except Exception as e:
                f.write(f"# ERROR for case {row['case_id']}: {e}\n\n")
    log.info(f"Exported {len(rows)} annotations to {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global CORPUS_DIR, CLAUDE_API_KEY
    parser = argparse.ArgumentParser(
        description="SOoL MLC Annotation Pipeline — Claude API"
    )
    # Accept either name: daily_update.py injects ANTHROPIC_API_KEY, while
    # ~/.sool_env (and therefore any standalone/cron invocation) sets
    # SOOL_ANTHROPIC_KEY. Honouring both keeps manual runs working.
    parser.add_argument("--api-key",
                        default=(os.environ.get("ANTHROPIC_API_KEY")
                                 or os.environ.get("SOOL_ANTHROPIC_KEY", "")),
                        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--domain", default="all",
                        help="Domain(s): 'all' or comma-separated e.g. '1,3'")
    parser.add_argument("--reannotate-v1", action="store_true",
                        help="Re-annotate rows written under the pre-remediation "
                             "regime (annotator=claude-pipeline-v1), which derived "
                             "N7/N8 from the disposition. Rows already at v2 are "
                             "skipped, so the run is resumable.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max cases to annotate per domain (default: all pending)")
    parser.add_argument("--reannotate-mixed", action="store_true",
                        help="Re-annotate mixed-perspective cases with corrected Rule 0 prompt")
    parser.add_argument("--stats", action="store_true",
                        help="Print annotation statistics and exit")
    parser.add_argument("--review", action="store_true",
                        help="Print review queue and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be annotated without calling API")
    parser.add_argument("--mask-disposition", action="store_true",
                        help=(
                            "Strip dispositional outcome language from opinion tail "
                            "before annotation (blind/equipoise mode). Enables "
                            "comparison study: run on a 200-case sample and compare "
                            "CD distributions against unmasked annotations. "
                            "Masked annotations are logged to masked_annotations.jsonl."
                        ))
    parser.add_argument("--to-turtle", action="store_true",
                        help="Export annotations as OWL/Turtle and exit")
    parser.add_argument("--corpus-dir", default=CORPUS_DIR,
                        help=f"Corpus JSONL directory (default: {CORPUS_DIR})")
    parser.add_argument("--db", default=ANNOTATIONS_DB,
                        help=f"Annotations database path (default: {ANNOTATIONS_DB})")
    args = parser.parse_args()

    CORPUS_DIR    = args.corpus_dir
    CLAUDE_API_KEY = args.api_key

    if not CLAUDE_API_KEY and not (args.stats or args.review or args.to_turtle or args.dry_run):
        log.error("No API key provided. Use --api-key YOUR_KEY or set ANTHROPIC_API_KEY env var.")
        sys.exit(1)

    db = AnnotationDB(args.db)

    if args.stats:
        print_stats(db)
        return

    if args.review:
        print_review_queue(db)
        return

    if args.reannotate_mixed:
        if not CLAUDE_API_KEY:
            log.error("--reannotate-mixed requires --api-key")
            sys.exit(1)
        reannotate_mixed_perspective(db, CLAUDE_API_KEY)
        # stats already printed inside reannotate_mixed_perspective
        return

    if args.to_turtle:
        domain_ids = ([1,2,3,4,5,6,7,8,9,10,11] if args.domain == "all"
                      else [int(x) for x in args.domain.split(",")])
        Path("./turtle_export").mkdir(exist_ok=True)
        for d in domain_ids:
            out = f"./turtle_export/domain_{d}_{DOCTRINAL_DOMAINS[d]}.ttl"
            export_turtle(db, d, out)
        return

    # Select domains
    if args.domain == "all":
        domain_ids = list(DOCTRINAL_DOMAINS.keys())
    else:
        domain_ids = [int(x.strip()) for x in args.domain.split(",")]

    log.info(f"Annotation pipeline starting")
    log.info(f"Model: {CLAUDE_MODEL}")
    log.info(f"Domains: {domain_ids}")
    log.info(f"Limit per domain: {args.limit or 'all pending'}")
    log.info(f"Corpus dir: {CORPUS_DIR}")
    log.info(f"Database: {args.db}")

    run_total = {"passed": 0, "flagged": 0, "failed_validation": 0,
                 "failed_parse": 0, "total": 0}
    for domain_id in domain_ids:
        counts = annotate_domain(db, domain_id, limit=args.limit,
                                 dry_run=args.dry_run,
                                 reannotate_v1=args.reannotate_v1)
        if counts:
            for k in run_total:
                run_total[k] += counts.get(k, 0)

    print_stats(db)
    log.info("Annotation pipeline complete.")

    if args.dry_run:
        return

    # Health gate: a run that attempted work but saved nothing (or lost the
    # majority to API/parse errors) is a failure, not a success. Without this
    # the pipeline exits 0 on a dead model ID and the caller reports "0 errors".
    attempted = run_total["total"]
    saved = (run_total["passed"] + run_total["flagged"]
             + run_total["failed_validation"])
    if attempted > 0 and saved == 0:
        log.error(f"Annotation FAILED: attempted {attempted} case(s), saved 0 "
                  f"({run_total['failed_parse']} API/parse failures). "
                  f"Check the model ID ({CLAUDE_MODEL}) and API key.")
        sys.exit(1)
    if attempted > 0 and run_total["failed_parse"] > attempted / 2:
        log.error(f"Annotation DEGRADED: {run_total['failed_parse']} of "
                  f"{attempted} case(s) failed on API/parse errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
