#!/usr/bin/env python3
"""
annotate_masked.py — Masked (blind) annotation pipeline — Migration B
=======================================================================
SEAL Lab, Texas A&M University

Re-annotates the full corpus with disposition language stripped,
writing results to `annotations_masked`. When ready, --swap-tables
renames annotations → annotations_unmasked and annotations_masked → annotations,
making the blind corpus the live corpus.

Workflow:
  Step 1 — Sample validation (domain 1, 200 cases):
    python3 annotate_masked.py --domain 1 --limit 200 --api-key $SOOL_ANTHROPIC_KEY
    python3 compare_masked_cd.py --domain 1

  Step 2 — Full corpus re-annotation (overnight, ~5 hours):
    python3 annotate_masked.py --domain all --api-key $SOOL_ANTHROPIC_KEY

  Step 3 — Validate full results:
    python3 annotate_masked.py --stats
    python3 compare_masked_cd.py

  Step 4 — Migrate (once satisfied):
    python3 annotate_masked.py --swap-tables --db ./sool_annotations.db
    # Old table preserved as annotations_unmasked
    # Masked table becomes the live annotations table
"""

import os, sys, re, json, time, sqlite3, argparse, logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from annotate import (
    validate, compute_cd, compute_structural_signature,
    normalize_contradictions,
    CONTRADICTION_TYPES, CHAIN_OUTCOMES,
    DOCTRINAL_DOMAINS, MLC_NODES, NODE_CLOSURE_VALUES,
)
from annotate_pipeline import (
    CLAUDE_API_URL, CLAUDE_MODEL, MAX_TOKENS, OPINION_CHARS,
    RATE_LIMIT, CORPUS_DIR, ANNOTATIONS_DB, DOMAIN_FILES,
    get_system_prompt, build_user_prompt, call_claude,
    parse_claude_response, sanitize_text,
    SYSTEM_PROMPT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

MASKED_TABLE = "annotations_masked"

# ── DISPOSITION MASKING ───────────────────────────────────────────────────────
# Patterns that signal dispositional outcome — appear in opinion tail
_DISP_PATTERNS = [
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
    r"for\s+the\s+(?:foregoing\s+)?reasons[,.]?\s+we\s+(?:affirm|reverse|remand)",
    r"the\s+(?:district\s+court['']?s?\s+)?(?:judgment|order)\s+is",
    r"we\s+(?:vacate|set\s+aside|dismiss|grant|deny)",
]

_DISP_RE = re.compile("|".join(_DISP_PATTERNS), re.IGNORECASE)

MASK_TAIL_CHARS  = 2000
MASK_PLACEHOLDER = (
    "\n\n[DISPOSITION REDACTED — annotate the structural chain from the "
    "opinion reasoning only. Do not infer the outcome from any redacted text.]"
)


def strip_disposition(text: str) -> tuple[str, bool]:
    """Strip dispositional language from opinion tail."""
    if not text:
        return text, False

    tail_start = max(0, len(text) - MASK_TAIL_CHARS)
    tail       = text[tail_start:]
    earliest   = None

    for m in _DISP_RE.finditer(tail):
        if earliest is None or m.start() < earliest.start():
            earliest = m

    was_masked = False
    if earliest:
        cut = tail_start + earliest.start()
        # Back up to last sentence boundary
        preceding   = text[:cut]
        last_period = max(
            preceding.rfind(". "),
            preceding.rfind(".\n"),
            preceding.rfind("\n\n"),
        )
        if last_period > 0 and (cut - last_period) < 400:
            cut = last_period + 1
        text = text[:cut] + MASK_PLACEHOLDER
        was_masked = True

    # Remove all-caps outcome tokens anywhere (headers etc.)
    cleaned = re.sub(
        r"\b(AFFIRMED|REVERSED|REMANDED|VACATED|DISMISSED)\b(?:[^.\n]{0,60})?",
        "[REDACTED]",
        text,
    )
    if cleaned != text:
        was_masked = True
        text = cleaned

    return text, was_masked


def build_masked_prompt(case: dict, domain_id: int) -> tuple[str, bool]:
    """Build user prompt with disposition stripped. Returns (prompt, was_masked)."""
    domain_name = DOCTRINAL_DOMAINS.get(domain_id, "unknown")

    text = ""
    for op in case.get("opinions", []):
        t = op.get("plain_text", "") or op.get("html_text", "") or ""
        if len(t) > len(text):
            text = t

    text = re.sub(r'<[^>]+>', ' ', text)
    text = sanitize_text(text)

    if len(text) > OPINION_CHARS:
        text = text[:OPINION_CHARS] + "\n\n[... opinion truncated for length ...]"

    text, was_masked = strip_disposition(text)

    case_name  = sanitize_text(case.get("case_name", "Unknown"))
    citation   = case.get("citations", [""])[0] if case.get("citations") else ""
    court      = case.get("court_id", "")
    date_filed = case.get("date_filed", "")

    prompt = f"""CASE: {case_name}
CITATION: {citation}
COURT: {court}  |  DATE: {date_filed}
DOCTRINAL DOMAIN: {domain_name}
OPINION TEXT:
{text if text else "[No opinion text available — annotate from case name and citation only; set confidence to low]"}
---
Annotate this case using the SOoL Minimum Legal Chain framework.
Return ONLY the JSON object described in your instructions."""

    return prompt, was_masked


# ── DATABASE ──────────────────────────────────────────────────────────────────

def init_masked_table(conn: sqlite3.Connection):
    """Create annotations_masked table if not present."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {MASKED_TABLE} (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id          TEXT NOT NULL,
            case_name        TEXT,
            domain_id        INTEGER,
            was_masked       INTEGER DEFAULT 1,
            node1_closure    TEXT, node2_closure TEXT, node3_closure TEXT,
            node4_closure    TEXT, node5_closure TEXT, node6_closure TEXT,
            node7_closure    TEXT, node8_closure TEXT,
            node1_entity     TEXT, node2_entity  TEXT, node3_entity  TEXT,
            node4_entity     TEXT, node5_entity  TEXT, node6_entity  TEXT,
            node7_entity     TEXT, node8_entity  TEXT,
            active_contradictions TEXT,
            contradiction_debt    REAL,
            chain_outcome         TEXT,
            confidence            TEXT,
            structural_signature  TEXT,
            annotation_date       TEXT,
            raw_response          TEXT,
            UNIQUE(case_id)
        )
    """)
    conn.commit()


def already_masked(conn: sqlite3.Connection, case_id: str) -> bool:
    r = conn.execute(
        f"SELECT 1 FROM {MASKED_TABLE} WHERE case_id=?", (case_id,)
    ).fetchone()
    return r is not None


def write_masked(conn: sqlite3.Connection, case_id: str, case_name: str,
                 domain_id: int, was_masked: bool, ann: dict, raw: str):
    nodes = ann.get("nodes", {})

    def nc(n): return (nodes.get(str(n)) or {}).get("closure", "")
    def ne(n): return (nodes.get(str(n)) or {}).get("entity", "")

    # Canonical bare-code list — the model sometimes returns objects instead
    # of strings, and downstream readers assume codes.
    cts = json.dumps(normalize_contradictions(ann))
    sig_val = compute_structural_signature(ann) if hasattr(compute_structural_signature, '__call__') else ""
    sig = json.dumps(sig_val) if isinstance(sig_val, (list, dict)) else str(sig_val or "")
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(f"""
        INSERT OR REPLACE INTO {MASKED_TABLE}
        (case_id, case_name, domain_id, was_masked,
         node1_closure, node2_closure, node3_closure, node4_closure,
         node5_closure, node6_closure, node7_closure, node8_closure,
         node1_entity,  node2_entity,  node3_entity,  node4_entity,
         node5_entity,  node6_entity,  node7_entity,  node8_entity,
         active_contradictions, contradiction_debt, chain_outcome,
         confidence, structural_signature, annotation_date, raw_response)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        case_id, case_name, domain_id, int(was_masked),
        nc(1), nc(2), nc(3), nc(4), nc(5), nc(6), nc(7), nc(8),
        ne(1), ne(2), ne(3), ne(4), ne(5), ne(6), ne(7), ne(8),
        cts, ann.get("contradiction_debt", 0.0),
        ann.get("chain_outcome", ""), ann.get("confidence", ""),
        sig, now, raw[:4000],
    ))
    conn.commit()


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def annotate_domain_masked(conn: sqlite3.Connection, domain_id: int,
                           api_key: str, limit: int = None, dry_run: bool = False):
    fname = DOMAIN_FILES.get(domain_id)
    if not fname:
        log.error(f"Unknown domain: {domain_id}")
        return 0, 0

    fpath = os.path.join(CORPUS_DIR, fname)
    if not os.path.exists(fpath):
        log.error(f"Corpus file not found: {fpath}")
        return 0, 0

    cases = []
    with open(fpath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    cases.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Only cases not yet in masked table
    pending = [c for c in cases
               if not already_masked(conn, str(c.get("id") or c.get("case_id")))]
    if limit:
        pending = pending[:limit]

    domain_name = DOCTRINAL_DOMAINS.get(domain_id, "unknown")
    log.info(f"Domain {domain_id} ({domain_name}): {len(pending)} to re-annotate (masked)")

    if not pending:
        log.info("  All cases already in masked table.")
        return 0, 0

    if dry_run:
        log.info(f"  DRY RUN — would masked-annotate {len(pending)} cases.")
        return 0, 0

    import importlib
    ap = importlib.import_module("annotate_pipeline")
    ap.CLAUDE_API_KEY = api_key

    passed = failed = masked_count = 0
    last_call = 0.0

    for case in tqdm(pending, desc=f"D{domain_id} masked", unit="case"):
        case_id   = str(case.get("id") or case.get("case_id")).strip("'\"")
        case_name = case.get("case_name", "Unknown")

        elapsed = time.time() - last_call
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        last_call = time.time()

        prompt, was_masked = build_masked_prompt(case, domain_id)
        if was_masked:
            masked_count += 1

        raw, err = ap.call_claude(prompt, domain_id)
        if err:
            log.warning(f"  API error for {case_name[:50]}: {err}")
            failed += 1
            continue

        parsed, parse_err = ap.parse_claude_response(raw)
        if parse_err or not parsed:
            failed += 1
            continue

        # Compute CD — compute_cd expects the full annotation dict
        parsed["contradiction_debt"] = compute_cd(parsed)

        write_masked(conn, case_id, case_name, domain_id, was_masked, parsed, raw)
        passed += 1

    log.info(f"  Done: {passed} annotated, {failed} failed, "
             f"{masked_count}/{passed+failed} had disposition stripped")
    return passed, masked_count



def swap_tables(conn: sqlite3.Connection, db_path: str):
    """
    Migrate: annotations_masked → annotations (live corpus).
    Safety steps:
      1. Verify annotations_masked is populated (refuse if empty)
      2. Verify annotations_masked has >= 90% of annotations row count
      3. Rename annotations → annotations_unmasked
      4. Rename annotations_masked → annotations
      5. Print summary
    """
    n_main   = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    n_masked = conn.execute(f"SELECT COUNT(*) FROM {MASKED_TABLE}").fetchone()[0]

    log.info(f"annotations (current):        {n_main:,} rows")
    log.info(f"annotations_masked (new):     {n_masked:,} rows")

    if n_masked == 0:
        log.error("annotations_masked is empty — run full annotation first.")
        sys.exit(1)

    coverage = n_masked / max(n_main, 1)
    if coverage < 0.90:
        log.error(
            f"annotations_masked covers only {coverage:.0%} of current annotations. "
            f"Need ≥90% before swap. Run --domain all to complete."
        )
        sys.exit(1)

    log.info(f"Coverage: {coverage:.1%} — proceeding with swap...")

    # Confirm
    answer = input(
        f"\nThis will rename:\n"
        f"  annotations         → annotations_unmasked  (preserved)\n"
        f"  annotations_masked  → annotations           (becomes live)\n"
        f"\nType YES to proceed: "
    ).strip()
    if answer != "YES":
        log.info("Aborted.")
        sys.exit(0)

    # Execute swap inside a transaction
    conn.execute("BEGIN EXCLUSIVE")
    try:
        conn.execute("ALTER TABLE annotations RENAME TO annotations_unmasked")
        conn.execute(f"ALTER TABLE {MASKED_TABLE} RENAME TO annotations")
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        log.error(f"Swap failed — rolled back: {e}")
        sys.exit(1)

    log.info("\n✓ Swap complete.")
    log.info(f"  annotations         — {n_masked:,} masked annotations (now live)")
    log.info(f"  annotations_unmasked — {n_main:,} original annotations (preserved)")
    log.info("\nNext steps:")
    log.info("  python3 export_corpus.py          # regenerate JSON")
    log.info("  python3 daily_update.py --upload-only  # push to Turbify")


def print_stats(conn: sqlite3.Connection):
    print("\n" + "="*60)
    print("MASKED ANNOTATION STATS")
    print("="*60)
    for r in conn.execute(f"""
        SELECT domain_id, COUNT(*) n,
               SUM(was_masked) n_masked,
               AVG(contradiction_debt) avg_cd
        FROM {MASKED_TABLE}
        GROUP BY domain_id ORDER BY domain_id
    """).fetchall():
        print(f"  D{r[0]}: n={r[1]}  masked={r[2]}  avg_cd={r[3]:.3f}")
    total = conn.execute(f"SELECT COUNT(*) FROM {MASKED_TABLE}").fetchone()[0]
    print(f"\n  TOTAL: {total} masked annotations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SOoL blind re-annotation (equipoise study)")
    parser.add_argument("--api-key",  default=os.environ.get("SOOL_ANTHROPIC_KEY",""))
    parser.add_argument("--domain",   default="1",
                        help="Domain(s): 'all' or comma-separated e.g. '1,3'")
    parser.add_argument("--limit",    type=int, default=None,
                        help="Max cases per domain (default: all pending)")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--stats",    action="store_true")
    parser.add_argument("--db",       default=ANNOTATIONS_DB)
    parser.add_argument("--corpus-dir", default=CORPUS_DIR)
    parser.add_argument("--swap-tables", action="store_true",
                        help=(
                            "Rename annotations → annotations_unmasked and "
                            "annotations_masked → annotations. "
                            "Run only after full corpus annotation is complete. "
                            "Original data preserved as annotations_unmasked."
                        ))
    args = parser.parse_args()

    if not args.api_key and not args.stats:
        log.error("No API key. Use --api-key $SOOL_ANTHROPIC_KEY")
        sys.exit(1)

    import annotate_pipeline as _ap
    _ap.CORPUS_DIR = args.corpus_dir
    CORPUS_DIR = args.corpus_dir

    conn = sqlite3.connect(args.db)
    init_masked_table(conn)

    if args.swap_tables:
        swap_tables(conn, args.db)
        conn.close()
        sys.exit(0)

    if args.stats:
        print_stats(conn)
        sys.exit(0)

    domains = (
        list(DOMAIN_FILES.keys())
        if args.domain == "all"
        else [int(d) for d in args.domain.split(",")]
    )

    total_passed = total_masked = 0
    for did in domains:
        p, m = annotate_domain_masked(
            conn, did, args.api_key,
            limit=args.limit, dry_run=args.dry_run,
        )
        total_passed += p
        total_masked += m

    log.info(f"\nComplete: {total_passed} annotations, {total_masked} disposition-masked")
    log.info("Run: python3 compare_masked_cd.py")
    conn.close()
