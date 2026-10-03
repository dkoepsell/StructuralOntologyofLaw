#!/usr/bin/env python3
"""
SOoL MLC Annotation Schema and Validator
=========================================
SEAL Lab, Texas A&M University

Defines the structured annotation schema for MLC case encoding.
Each annotated case produces a JSON record that maps directly to
OWL/Turtle triples for the triple store.

Annotation format: JSON per case
Validation: schema check + cross-field consistency rules
Output: JSONL annotation records + Turtle triples

Usage:
    python annotate.py --validate annotation.json
    python annotate.py --to-turtle annotation.json > case.ttl
    python annotate.py --template   > blank_template.json
"""

import json
import sys
import argparse
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# MLC CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

MLC_NODES = {
    1: "SourceOfAuthority",
    2: "Norm",
    3: "ActorInRole",
    4: "TriggeringFacts",
    5: "LegalAct",
    6: "Target",
    7: "LegalEffect",
    8: "Remedy",
}

NODE_CLOSURE_VALUES = ["closed", "failed", "partial", "indeterminate"]

CONTRADICTION_TYPES = {
    "CF":  ("Conferral Failure",            "1→3",   0.15),
    "AI":  ("Authority Inflation",           "1→2",   0.12),
    "JC":  ("Jurisdictional Contradiction",  "2→6",   0.10),
    "RC3": ("Role Contradiction",            "N.3",   0.14),
    "PC":  ("Procedural Contradiction",      "2→5",   0.09),
    "TC":  ("Temporal Contradiction",        "2↔4",   0.08),
    "FM":  ("Fact Manipulation",             "N.4",   0.11),
    "NI":  ("Norm Indeterminacy",            "N.2",   0.07),
    "RF":  ("Recognition Failure",           "6/7",   0.11),
    "RCL": ("Recognition Collapse",          "6→8",   0.18),
    "CC":  ("Correlativity Contradiction",   "N.7",   0.14),
    "SE":  ("Self-Undermining Effect",       "N.7",   0.10),
    "RPF": ("Repair Failure",                "N.8",   0.13),
}

CHAIN_OUTCOMES = [
    "protection_granted",
    "protection_denied",
    "partial",
    "remanded",
    "dismissed",
    "moot",
]

DOCTRINAL_DOMAINS = {
    1: "first_amendment",
    2: "employment_discrimination",
    3: "administrative_law",
    4: "criminal_procedure",
    5: "immigration",
    6: "civil_rights_1983",
    7: "contract",
    8: "family_law",
    9: "habeas_corpus",
    10: "patent_ip",
    11: "securities_regulation",
}

# ─────────────────────────────────────────────────────────────────────────────
# ANNOTATION SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

BLANK_TEMPLATE = {
    # ── CASE METADATA ──────────────────────────────────────────────────────
    "case_id":          None,      # CourtListener cluster ID (integer)
    "case_name":        "",        # e.g. "Garcetti v. Ceballos"
    "citation":         "",        # e.g. "547 U.S. 410 (2006)"
    "court":            "",        # e.g. "scotus", "ca9"
    "date_decided":     "",        # ISO format YYYY-MM-DD
    "domain_id":        None,      # 1–8 (see DOCTRINAL_DOMAINS)
    "annotator":        "",        # annotator ID/name
    "annotation_date":  "",        # ISO format

    # ── MLC NODE ANALYSIS ─────────────────────────────────────────────────
    # For each node: closure status + free-text justification
    "nodes": {
        "1": {
            "closure":       None,   # "closed" | "failed" | "partial" | "indeterminate"
            "entity":        "",     # What serves as source of authority?
            "justification": "",     # 1–3 sentences from opinion supporting assessment
        },
        "2": {
            "closure":       None,
            "entity":        "",     # What is the governing norm?
            "justification": "",
        },
        "3": {
            "closure":       None,
            "entity":        "",     # Who is the actor, in what role(s)?
            "roles_borne":   [],     # list of role names if multiple
            "justification": "",
        },
        "4": {
            "closure":       None,
            "entity":        "",     # What are the triggering facts?
            "justification": "",
        },
        "5": {
            "closure":       None,
            "entity":        "",     # What legal act/omission occurred?
            "justification": "",
        },
        "6": {
            "closure":       None,
            "entity":        "",     # Who is the target?
            "justification": "",
        },
        "7": {
            "closure":       None,
            "entity":        "",     # What legal effect is asserted/denied?
            "justification": "",
        },
        "8": {
            "closure":       None,
            "entity":        "",     # What remedy is/is not available?
            "justification": "",
        },
    },

    # ── CONTRADICTION INVENTORY ────────────────────────────────────────────
    # List of active contradiction type codes from CONTRADICTION_TYPES
    # e.g. ["RC3", "NI", "RPF"]
    "active_contradictions": [],

    # ── CHAIN OUTCOME ──────────────────────────────────────────────────────
    "chain_outcome":    None,      # see CHAIN_OUTCOMES
    "outcome_notes":    "",        # brief explanation

    # ── CONTRADICTION DEBT ─────────────────────────────────────────────────
    # Computed automatically from active_contradictions — do not fill in
    "contradiction_debt": None,

    # ── DOWNSTREAM PROPAGATION (optional, Phase 2) ────────────────────────
    # Does this case's unresolved contradiction recur in later cases?
    "deferred_contradictions": [],  # list of contradiction codes left unresolved
    "propagates_to":    [],         # list of CourtListener case IDs that inherit

    # ── CROSS-DOMAIN STRUCTURAL NOTE ──────────────────────────────────────
    # For the validation analysis: what structural type does this represent?
    # This is the cross-domain key that allows structural clustering.
    # Format: "NodeN:ContradictionType" e.g. "Node3:RC3"
    "structural_signature": [],

    # ── QUALITY FLAGS ─────────────────────────────────────────────────────
    "confidence":       None,       # "high" | "medium" | "low"
    "needs_review":     False,
    "review_note":      "",
}


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate(annotation: dict) -> list[str]:
    """
    Returns list of error strings. Empty list = valid.
    """
    errors = []

    # Required fields
    for field in ["case_id", "case_name", "domain_id", "annotator"]:
        if not annotation.get(field):
            errors.append(f"Missing required field: {field}")

    # Domain ID range
    if annotation.get("domain_id") and annotation["domain_id"] not in DOCTRINAL_DOMAINS:
        errors.append(f"Invalid domain_id: {annotation['domain_id']} (must be 1–11)")

    # Node closure values
    nodes = annotation.get("nodes", {})
    for node_num in [str(i) for i in range(1, 9)]:
        if node_num not in nodes:
            errors.append(f"Missing node {node_num} in nodes dict")
            continue
        closure = nodes[node_num].get("closure")
        if closure not in NODE_CLOSURE_VALUES:
            errors.append(f"Node {node_num}: invalid closure value '{closure}' "
                          f"(must be one of {NODE_CLOSURE_VALUES})")

    # Contradiction type codes
    # Checked against the raw field, so an entry that normalization has to
    # discard still surfaces as a review flag instead of vanishing. Shape
    # alone is not an error: a {"type": "RC3", ...} object carries the same
    # information as "RC3" and is accepted silently. Only entries from which
    # no valid code can be recovered are reported.
    for ct in _iter_raw_contradictions(annotation):
        if _extract_ct_code(ct) is None:
            errors.append(f"Unknown or malformed contradiction type: {ct!r} "
                          f"(valid: {list(CONTRADICTION_TYPES.keys())})")

    # Chain outcome
    if annotation.get("chain_outcome") not in CHAIN_OUTCOMES:
        errors.append(f"Invalid chain_outcome: '{annotation.get('chain_outcome')}' "
                      f"(must be one of {CHAIN_OUTCOMES})")

    # N7-failed / N8-closed is NOT an error. Per remediation spec §4.3 the old
    # prohibition foreclosed the analytically interesting case — a remedy that
    # is independently available or independently blocked. Divergence is a
    # finding, so it is recorded rather than rejected.
    n7 = nodes.get("7", {}).get("closure")
    n8 = nodes.get("8", {}).get("closure")
    if n7 == "failed" and n8 == "closed":
        annotation.setdefault("_divergences", []).append("N7_failed_N8_closed")

    # Consistency: if RPF in active_contradictions, Node 8 should not be closed
    if "RPF" in normalize_contradictions(annotation) and n8 == "closed":
        errors.append("Consistency: Repair Failure (RPF) asserted but "
                      "Node 8 closure is 'closed'. One of these must be revised.")

    # Confidence required
    if annotation.get("confidence") not in ["high", "medium", "low"]:
        errors.append("Missing or invalid 'confidence' field (high/medium/low)")

    return errors


def _iter_raw_contradictions(annotation: dict) -> list:
    """The model's `active_contradictions` as a list, whatever shape it came in."""
    raw = annotation.get("active_contradictions")
    if raw is None:
        return []
    if isinstance(raw, (str, dict)):
        return [raw]
    return list(raw) if isinstance(raw, (list, tuple)) else [raw]


def _extract_ct_code(item) -> str | None:
    """Recover a known contradiction code from a string or object, else None."""
    if isinstance(item, str):
        code = item
    elif isinstance(item, dict):
        code = next((item[k] for k in ("type", "code", "contradiction_type",
                                       "contradiction", "ct")
                     if isinstance(item.get(k), str)), None)
    else:
        code = None
    if isinstance(code, str):
        code = code.strip().upper()
        if code in CONTRADICTION_TYPES:
            return code
    return None


def normalize_contradictions(annotation: dict) -> list[str]:
    """
    Coerce `active_contradictions` into a flat list of bare type codes.

    The model is asked for a list of strings ("RC3", "FM", ...), but it
    intermittently returns richer objects instead, e.g.
        [{"type": "RC3", "node": 3, "rationale": "..."}]
    An unhashable dict reaching `ct in CONTRADICTION_TYPES` raises TypeError
    and — because CD is computed before validate() — killed the whole run
    rather than flagging the single case (2026-08-03 re-annotation crash).

    Anything that cannot be resolved to a known code is dropped here and left
    for validate() to report, so a bad row is a review flag, never a crash.
    """
    codes = [c for c in (_extract_ct_code(i)
                         for i in _iter_raw_contradictions(annotation))
             if c is not None]
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(codes))


def compute_cd(annotation: dict) -> float:
    """Compute Contradiction Debt from active contradiction types."""
    return round(sum(
        CONTRADICTION_TYPES[ct][2]
        for ct in normalize_contradictions(annotation)
    ), 4)


# Contradiction types whose node attachment touches N7 or N8. Because the
# Pass-2 rule derives N7/N8 (and in turn the outcome variable) from the court's
# disposition, any CD component drawn from these is definitionally entangled
# with the outcome. Excluding them yields the analytically honest measure.
DOWNSTREAM_CTS = {"RF", "RCL", "CC", "SE", "RPF"}
UPSTREAM_CTS = set(CONTRADICTION_TYPES) - DOWNSTREAM_CTS


def compute_cd_upstream(annotation: dict) -> float:
    """
    Contradiction Debt restricted to nodes N1-N6.

    This is the portion of structural stress that is NOT downstream of the
    annotation rule linking N7/N8 to the recorded disposition, and is therefore
    the only component of CD that can legitimately be tested against an
    independently coded outcome. Report this, not `contradiction_debt`, in any
    predictive analysis.
    """
    return round(sum(
        CONTRADICTION_TYPES[ct][2]
        for ct in normalize_contradictions(annotation)
        if ct in UPSTREAM_CTS
    ), 4)


def compute_structural_signature(annotation: dict) -> list[str]:
    """
    Derive the cross-domain structural signature from node closures
    and active contradictions. Format: "NodeN:CT_CODE"
    This is the key used for structural clustering across domains.
    """
    signatures = []
    ct_to_node = {
        "CF":  "Node1_3",
        "AI":  "Node1_2",
        "JC":  "Node2_6",
        "RC3": "Node3",
        "PC":  "Node2_5",
        "TC":  "Node2_4",
        "FM":  "Node4",
        "NI":  "Node2",
        "RF":  "Node6_7",
        "RCL": "Node6_8",
        "CC":  "Node7",
        "SE":  "Node7",
        "RPF": "Node8",
    }
    for ct in normalize_contradictions(annotation):
        if ct in ct_to_node:
            signatures.append(f"{ct_to_node[ct]}:{ct}")
    return signatures


# ─────────────────────────────────────────────────────────────────────────────
# OWL/TURTLE SERIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def to_turtle(annotation: dict) -> str:
    """
    Serialize an annotated case as OWL/Turtle triples for the triple store.
    """
    case_id   = annotation["case_id"]
    case_name = annotation["case_name"].replace('"', '\\"')
    domain    = DOCTRINAL_DOMAINS.get(annotation.get("domain_id"), "unknown")
    cite      = annotation.get("citation", "")
    court     = annotation.get("court", "")
    date      = annotation.get("date_decided", "")
    cd        = annotation.get("contradiction_debt") or compute_cd(annotation)
    outcome   = annotation.get("chain_outcome", "")
    sigs      = annotation.get("structural_signature") or \
                compute_structural_signature(annotation)

    prefix_block = f"""@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix law:  <http://seal.tamu.edu/legal-kernel/> .
@prefix case: <http://seal.tamu.edu/legal-kernel/cases/> .
@prefix mlc:  <http://seal.tamu.edu/legal-kernel/mlc/> .

"""

    # Case individual
    lines = [
        f'case:C{case_id} a mlc:CaseInstance ;',
        f'  rdfs:label "{case_name}" ;',
        f'  mlc:citation "{cite}" ;',
        f'  mlc:court "{court}" ;',
        f'  mlc:dateDecided "{date}"^^xsd:date ;' if date else '',
        f'  mlc:doctrinalDomain "{domain}" ;',
        f'  mlc:chainOutcome mlc:{outcome.replace("_","").title()} ;',
        f'  mlc:contradictionDebt "{cd}"^^xsd:decimal ;',
    ]

    # Active contradiction types
    for ct in normalize_contradictions(annotation):
        ct_name = CONTRADICTION_TYPES[ct][0].replace(" ", "").replace("/", "_")
        lines.append(f'  mlc:hasContradiction mlc:{ct_name} ;')

    # Structural signatures
    for sig in sigs:
        lines.append(f'  mlc:structuralSignature "{sig}" ;')

    # Node closure triples
    nodes = annotation.get("nodes", {})
    for n in range(1, 9):
        node_data = nodes.get(str(n), {})
        closure   = node_data.get("closure", "indeterminate")
        entity    = (node_data.get("entity") or "").replace('"', '\\"')
        node_name = MLC_NODES[n]
        lines.append(
            f'  mlc:node{n}Closure mlc:Closure_{closure.title()} ;'
        )
        if entity:
            lines.append(f'  mlc:node{n}Entity "{entity}" ;')

    # Close the individual
    lines = [l for l in lines if l]  # remove empty strings
    # Replace last ';' with '.'
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].rstrip().endswith(";"):
            lines[i] = lines[i].rstrip()[:-1] + "."
            break

    # Node details as sub-resources
    node_triples = []
    for n in range(1, 9):
        node_data = nodes.get(str(n), {})
        justif = (node_data.get("justification") or "").replace('"', '\\"')
        if justif:
            node_triples.append(
                f'\ncase:C{case_id}_N{n} a mlc:NodeInstance ;\n'
                f'  mlc:nodeNumber {n} ;\n'
                f'  mlc:justification "{justif}" .\n'
            )

    return prefix_block + "\n".join(lines) + "\n" + "".join(node_triples)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SOoL MLC Annotation Schema — validate, convert, template"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate",   metavar="FILE",
                       help="Validate a JSON annotation file")
    group.add_argument("--to-turtle",  metavar="FILE",
                       help="Convert annotation JSON to OWL/Turtle")
    group.add_argument("--template",   action="store_true",
                       help="Print blank annotation template as JSON")
    group.add_argument("--schema",     action="store_true",
                       help="Print schema documentation")
    args = parser.parse_args()

    if args.template:
        print(json.dumps(BLANK_TEMPLATE, indent=2))
        return

    if args.schema:
        print("\nMLC ANNOTATION SCHEMA\n" + "="*50)
        print(f"\nNode closure values: {NODE_CLOSURE_VALUES}")
        print(f"\nChain outcome values: {CHAIN_OUTCOMES}")
        print(f"\nDoctrinal domains:")
        for k, v in DOCTRINAL_DOMAINS.items():
            print(f"  {k}: {v}")
        print(f"\nContradiction type codes:")
        for code, (name, links, weight) in CONTRADICTION_TYPES.items():
            print(f"  {code:<5} {name:<35} Links: {links:<8} CD weight: {weight}")
        return

    if args.validate or args.to_turtle:
        fname = args.validate or args.to_turtle
        with open(fname, encoding="utf-8") as f:
            annotation = json.load(f)

        # Enrich with computed fields
        annotation["contradiction_debt"]   = compute_cd(annotation)
        annotation["structural_signature"] = compute_structural_signature(annotation)

        if args.validate:
            errors = validate(annotation)
            if errors:
                print(f"VALIDATION FAILED ({len(errors)} errors):")
                for e in errors:
                    print(f"  ✗  {e}")
                sys.exit(1)
            else:
                cd = annotation["contradiction_debt"]
                sigs = annotation["structural_signature"]
                print(f"✓  VALID")
                print(f"   Case: {annotation['case_name']}")
                print(f"   Domain: {DOCTRINAL_DOMAINS.get(annotation.get('domain_id'))}")
                print(f"   Active contradictions: "
                      f"{annotation.get('active_contradictions')}")
                print(f"   Contradiction Debt: {cd}")
                print(f"   Chain outcome: {annotation.get('chain_outcome')}")
                print(f"   Structural signatures: {sigs}")

        elif args.to_turtle:
            errors = validate(annotation)
            if errors:
                print("Cannot convert — validation errors:", file=sys.stderr)
                for e in errors:
                    print(f"  ✗ {e}", file=sys.stderr)
                sys.exit(1)
            print(to_turtle(annotation))


if __name__ == "__main__":
    main()
