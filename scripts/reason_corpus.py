#!/usr/bin/env python3
"""
reason_corpus.py — SOoL OWL Reasoner Integration
=================================================
SEAL Lab, Texas A&M University
David R. Koepsell

Loads the SOoL schema TTL files and corpus TTL exports into an OWL
reasoner (HermiT via Owlready2) and performs:

  1. Classification  — infer OWL types for each case individual
  2. Consistency     — detect structurally impossible annotations
  3. Novel inference — surface interesting class combinations
  4. Quality flags   — cases where reasoner disagrees with annotator

Produces: sool_inferences.json  (per-case inference results)

Usage:
    pip install owlready2
    python3 reason_corpus.py
    python3 reason_corpus.py --schema-dir ./ttl --corpus-dir .
    python3 reason_corpus.py --no-hermit   (use Pellet instead)
    python3 reason_corpus.py --quick       (classification only, skip full reasoning)

Requirements:
    pip install owlready2
    Java 8+ (for HermiT reasoner, bundled with owlready2)
"""

import argparse, json, sqlite3, sys, time
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

try:
    import owlready2
    from owlready2 import get_ontology, sync_reasoner_hermit, sync_reasoner_pellet
    OWLREADY = True
except ImportError:
    OWLREADY = False
    print("owlready2 not installed. Run: pip install owlready2")
    print("Also requires Java: sudo apt install default-jre")

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

SOOL_BASE   = "http://ontologyoflaw.org/structural#"
CRIM_BASE   = "http://ontologyoflaw.org/criminal#"
CORPUS_BASE = "http://ontologyoflaw.org/corpus/"

# Expected primary failure nodes per criminal category
EXPECTED_PRIMARY_NODES = {
    1: {5},          # Homicide — N5
    2: {4, 5},       # Inchoate — N4/N5
    3: {2},          # Property/Fraud — N2
    4: {3},          # Status — N3
    5: {5},          # Strict liability — N5
    6: {7},          # Affirmative defenses — N7
}

# CTs expected to dominate each defense type
EXPECTED_DEFENSE_CTS = {
    'justification': {'JC'},
    'excuse':        {'CF'},
    'procedural':    {'CF', 'TC'},
    'capacity':      {'CF'},
}

# Structural impossibilities — annotation errors if present
STRUCTURAL_IMPOSSIBILITIES = [
    # RPF requires some structural basis — N7 or N8 must not be fully closed
    # RPF is valid when N8=partial (blocked remedy) or N7=partial (incomplete recognition)
    # Only flag as impossible if RPF fires with BOTH N7 and N8 fully closed AND N8=closed
    # (already caught by the inline check below — remove from lambda list)
    # lambda removed: RPF+N7closed+N8failed — see inline check
    lambda r: False,  # placeholder — RPF consistency handled inline
    # protection_granted but N7 failed
    lambda r: r['outcome'] == 'protection_granted' and r['node7'] == 'failed',
    # protection_denied but all nodes closed
    lambda r: r['outcome'] == 'protection_denied' and
              all(r[f'node{n}'] == 'closed' for n in range(1,9)),
    # CD = 0 but active contradictions present
    lambda r: r['cd'] == 0 and len(r['cts']) > 0,
    # CD > 0 but no contradictions recorded
    lambda r: r['cd'] > 0 and len(r['cts']) == 0,
]


# ── RULE-BASED INFERENCE (fallback without OWL reasoner) ─────────────────────

def infer_case(row: dict) -> dict:
    """
    Apply SOoL structural inference rules to a single annotated case.
    Returns a dict of inferences. Works without owlready2.
    """
    inferences = {
        'case_id':          row['case_id'],
        'case_name':        row['case_name'],
        'inferred_classes': [],
        'inconsistencies':  [],
        'quality_flags':    [],
        'novel_findings':   [],
        'confidence':       'high',
    }

    cts     = set(row['cts'])
    outcome = row['outcome']
    cd      = row['cd']
    cat     = row.get('category_id', 0)
    defense = row.get('defense_type', 'none')
    nodes   = {n: row.get(f'node{n}', 'indeterminate') for n in range(1,9)}
    failed  = {n for n in range(1,9) if nodes[n] in ('failed','partial')}

    # ── CLASSIFICATION INFERENCES ────────────────────────────────────────────

    # Justification vs Excuse structural typing
    if defense == 'justification' and 'JC' in cts:
        inferences['inferred_classes'].append('crim:Justification')
    elif defense == 'excuse' and 'CF' in cts:
        inferences['inferred_classes'].append('crim:Excuse')
    elif defense == 'justification' and 'CF' in cts and 'JC' not in cts:
        inferences['inferred_classes'].append('crim:MisclassifiedExcuse')
        inferences['quality_flags'].append(
            "Defense labeled justification but CF fires without JC — "
            "may be an excuse misclassified as justification"
        )

    # Strict liability detection
    if 'PC' in cts and cat == 5:
        inferences['inferred_classes'].append('crim:StrictLiabilityOffense')
    elif 'PC' in cts and cat != 5:
        inferences['novel_findings'].append(
            f"PC fires in C{cat} case — strict liability element outside expected category"
        )

    # Status offense / RCL
    if 'RCL' in cts:
        inferences['inferred_classes'].append('crim:StatusOffenseWithCollapse')
        if cat != 4:
            inferences['novel_findings'].append(
                f"RCL fires in C{cat} — recognition collapse outside status offense category"
            )

    # Duress structural typing
    if defense in ('excuse', 'capacity') and 'CC' in cts and 'CF' not in cts:
        inferences['inferred_classes'].append('crim:DuressDefense')

    # Entrapment
    if 'FM' in cts and 4 in failed:
        inferences['inferred_classes'].append('crim:Entrapment')

    # High-confidence convictions (structurally clean chains)
    if outcome == 'protection_granted' and cd < 0.05 and len(cts) == 0:
        inferences['inferred_classes'].append('sool:StructurallyCleanChain')

    # High-stress reversals
    if outcome == 'protection_denied' and cd > 0.40:
        inferences['inferred_classes'].append('sool:HighContradictionDenial')

    # ── CONSISTENCY CHECKS ───────────────────────────────────────────────────

    # Cannot be granted if N7 fully failed
    # N7=partial is permissible for granted (right partially but sufficiently recognized)
    if outcome == 'protection_granted' and nodes[7] == 'failed':
        inferences['inconsistencies'].append(
            "INCONSISTENT: chain_outcome=protection_granted but N7=failed"
        )

    # Cannot be denied if all nodes closed
    if outcome == 'protection_denied' and all(
        nodes[n] == 'closed' for n in range(1, 9)
    ):
        inferences['inconsistencies'].append(
            "INCONSISTENT: chain_outcome=protection_denied but all nodes closed"
        )

    # RPF requires structural basis: N7 or N8 must show stress (failed or partial)
    # RPF with N7=closed AND N8=closed AND no active node stress = annotation error
    # RPF with N7=partial or N8=partial is valid (incomplete recognition/repair)
    if ('RPF' in cts
            and nodes[7] == 'closed'
            and nodes[8] == 'closed'
            and not any(nodes[n] in ('failed','partial') for n in range(1,7))):
        inferences['inconsistencies'].append(
            "INCONSISTENT: RPF fires but all nodes closed — "
            "RPF requires N7/N8 stress or upstream partial closure"
        )

    # CD=0 with CTs is impossible
    if cd == 0 and len(cts) > 0:
        inferences['inconsistencies'].append(
            f"INCONSISTENT: CD=0 but {len(cts)} active contradictions — "
            "CD should be > 0 whenever CTs fire"
        )

    # CD>0 with no CTs is suspicious
    if cd > 0.05 and len(cts) == 0:
        inferences['quality_flags'].append(
            f"CD={cd:.3f} but no contradiction types recorded — "
            "likely annotation gap"
        )

    # Primary node mismatch for criminal categories
    if cat in EXPECTED_PRIMARY_NODES and failed:
        expected = EXPECTED_PRIMARY_NODES[cat]
        actual   = failed & {2,3,4,5,7}  # structural nodes only
        if actual and not actual.intersection(expected):
            inferences['quality_flags'].append(
                f"Primary failure at N{sorted(actual)} but C{cat} predicts N{sorted(expected)} — "
                "verify category assignment"
            )

    # Defense CT mismatch
    if defense in EXPECTED_DEFENSE_CTS:
        expected_cts = EXPECTED_DEFENSE_CTS[defense]
        if not cts.intersection(expected_cts):
            inferences['quality_flags'].append(
                f"Defense={defense} but expected CTs {expected_cts} not present "
                f"(found: {cts}) — verify defense classification"
            )

    # ── NOVEL FINDINGS ───────────────────────────────────────────────────────

    # Successful excuse (state wins despite actor capacity argument)
    if defense == 'excuse' and outcome == 'protection_granted':
        inferences['novel_findings'].append(
            "Excuse defense failed — state prevailed despite actor capacity argument. "
            "CF fires but N7 closed. Examine why excuse was rejected."
        )

    # Entrapment claim with state win — predisposition found
    if 'FM' in cts and outcome == 'protection_granted':
        inferences['novel_findings'].append(
            "FM at N4 (potential entrapment) but state prevailed — "
            "predisposition likely found. FM fires but chain closed."
        )

    # Strict liability with reversal — high structural stress overcame
    if cat == 5 and outcome == 'protection_denied':
        inferences['novel_findings'].append(
            "Strict liability offense reversed — PC structural stress "
            "sufficient to generate reversal despite thin mens rea requirement."
        )

    # Multiple high-weight CTs (AI + RC3 + RCL = authoritarian pattern)
    authoritarian_cts = cts.intersection({'AINF', 'RC3', 'RCL', 'CC'})
    if len(authoritarian_cts) >= 2:
        inferences['novel_findings'].append(
            f"High-weight CT cluster: {authoritarian_cts} — "
            "compound authority/recognition failure pattern"
        )

    if inferences['inconsistencies']:
        inferences['confidence'] = 'low'
    elif inferences['quality_flags']:
        inferences['confidence'] = 'medium'

    return inferences


# ── OWLREADY2 INTEGRATION ─────────────────────────────────────────────────────

def run_owlready2_reasoner(schema_ttl: str, corpus_ttl: str,
                            use_hermit: bool = True) -> dict:
    """
    Load schema + corpus into Owlready2 and run HermiT reasoner.
    Returns dict of inferred individual types keyed by case URI.
    """
    if not OWLREADY:
        return {}

    print("Loading ontologies into Owlready2...")
    try:
        schema = get_ontology(f"file://{schema_ttl}").load()
        corpus = get_ontology(f"file://{corpus_ttl}").load()

        print("Running reasoner (this may take a few minutes)...")
        if use_hermit:
            sync_reasoner_hermit([schema, corpus], infer_property_values=True)
        else:
            sync_reasoner_pellet([schema, corpus], infer_property_values=True)

        # Extract inferred types
        results = {}
        for ind in corpus.individuals():
            types = [str(c) for c in ind.is_a]
            results[str(ind.iri)] = types

        print(f"Reasoner complete — {len(results)} individuals classified")
        return results

    except Exception as e:
        print(f"Reasoner error: {e}")
        print("Falling back to rule-based inference")
        return {}


# ── MAIN ANALYSIS ─────────────────────────────────────────────────────────────

def analyze_corpus(ann_db: str, corpus_type: str) -> list:
    """Run inference on all cases in an annotation DB."""
    conn = sqlite3.connect(ann_db)
    conn.row_factory = sqlite3.Row

    if corpus_type == 'civil':
        # Prefer annotations_unmasked if it exists (present when blind/equipoise
        # annotation has swapped the table — unmasked holds the verified originals)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        ann_table = 'annotations_unmasked' if 'annotations_unmasked' in tables else 'annotations'

        rows = conn.execute(f"""
            SELECT case_id, case_name, domain_id as category_id,
                   chain_outcome as outcome, contradiction_debt as cd,
                   active_contradictions, NULL as defense_type, confidence,
                   node1_closure as node1, node2_closure as node2,
                   node3_closure as node3, node4_closure as node4,
                   node5_closure as node5, node6_closure as node6,
                   node7_closure as node7, node8_closure as node8
            FROM {ann_table} WHERE confidence IN ('high','medium')
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT case_id, case_name, category_id,
                   chain_outcome as outcome, contradiction_debt as cd,
                   active_contradictions, NULL as defense_type, confidence,
                   node1_closure as node1, node2_closure as node2,
                   node3_closure as node3, node4_closure as node4,
                   node5_closure as node5, node6_closure as node6,
                   node7_closure as node7, node8_closure as node8
            FROM criminal_annotations WHERE confidence IN ('high','medium')
        """).fetchall()

    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        r['cts'] = json.loads(r.get('active_contradictions') or '[]')
        r['defense_type'] = r.get('defense_type') or 'none'
        result = infer_case(r)
        result['corpus'] = corpus_type
        results.append(result)

    return results


def summarize(results: list) -> dict:
    """Aggregate inference results into summary statistics."""
    total = len(results)
    inconsistent = [r for r in results if r['inconsistencies']]
    flagged      = [r for r in results if r['quality_flags']]
    novel        = [r for r in results if r['novel_findings']]

    # Class frequency
    class_counts = defaultdict(int)
    for r in results:
        for cls in r['inferred_classes']:
            class_counts[cls] += 1

    # Inconsistency types
    incon_types = defaultdict(int)
    for r in inconsistent:
        for msg in r['inconsistencies']:
            key = msg.split(':')[1].strip()[:60] if ':' in msg else msg[:60]
            incon_types[key] += 1

    return {
        'total':           total,
        'inconsistent':    len(inconsistent),
        'flagged':         len(flagged),
        'novel':           len(novel),
        'pct_clean':       round((total - len(inconsistent) - len(flagged)) / max(total,1) * 100, 1),
        'class_counts':    dict(sorted(class_counts.items(), key=lambda x:-x[1])),
        'inconsistency_types': dict(sorted(incon_types.items(), key=lambda x:-x[1])),
    }


def main():
    parser = argparse.ArgumentParser(
        description="SOoL OWL Reasoner and Inference Engine"
    )
    parser.add_argument('--civil-ann-db',    default='./sool_annotations.db')
    parser.add_argument('--criminal-ann-db', default='./sool_criminal_annotations.db')
    parser.add_argument('--schema-dir',      default='.')
    parser.add_argument('--corpus-dir',      default='.')
    parser.add_argument('--out',             default='./sool_inferences.json')
    parser.add_argument('--civil-only',      action='store_true')
    parser.add_argument('--criminal-only',   action='store_true')
    parser.add_argument('--no-hermit',       action='store_true',
                        help='Use Pellet instead of HermiT')
    parser.add_argument('--owl-reasoning',   action='store_true',
                        help='Use Owlready2/HermiT (requires Java)')
    args = parser.parse_args()

    print("="*55)
    print("SOoL Inference Engine")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*55)

    all_results  = []
    all_summary  = {}

    if not args.criminal_only and Path(args.civil_ann_db).exists():
        print("\nAnalyzing civil corpus...")
        civil_results = analyze_corpus(args.civil_ann_db, 'civil')
        civil_summary = summarize(civil_results)
        all_results.extend(civil_results)
        all_summary['civil'] = civil_summary
        print(f"  {civil_summary['total']:,} cases analyzed")
        print(f"  {civil_summary['inconsistent']} inconsistencies")
        print(f"  {civil_summary['flagged']} quality flags")
        print(f"  {civil_summary['novel']} novel findings")
        print(f"  {civil_summary['pct_clean']}% structurally clean")

    if not args.civil_only and Path(args.criminal_ann_db).exists():
        print("\nAnalyzing criminal corpus...")
        crim_results = analyze_corpus(args.criminal_ann_db, 'criminal')
        crim_summary = summarize(crim_results)
        all_results.extend(crim_results)
        all_summary['criminal'] = crim_summary
        print(f"  {crim_summary['total']:,} cases analyzed")
        print(f"  {crim_summary['inconsistent']} inconsistencies")
        print(f"  {crim_summary['flagged']} quality flags")
        print(f"  {crim_summary['novel']} novel findings")
        print(f"  {crim_summary['pct_clean']}% structurally clean")
        print(f"\n  Inferred classes:")
        for cls, n in list(crim_summary['class_counts'].items())[:8]:
            print(f"    {cls:<40} {n}")

    # OWL reasoner (optional, requires Java)
    if args.owl_reasoning and OWLREADY:
        print("\nRunning OWL reasoner (requires Java)...")
        schema_path = str(Path(args.schema_dir) / 'sool_criminal_norms.ttl')
        corpus_path = str(Path(args.corpus_dir) / 'sool_criminal.ttl')
        if Path(schema_path).exists() and Path(corpus_path).exists():
            owl_types = run_owlready2_reasoner(
                schema_path, corpus_path,
                use_hermit=not args.no_hermit
            )
            # Merge OWL-inferred types into results
            for r in all_results:
                uri = f"http://ontologyoflaw.org/corpus/criminal/case_{r['case_id']}"
                if uri in owl_types:
                    r['owl_inferred_classes'] = owl_types[uri]
        else:
            print("  TTL files not found — run export_rdf.py first")

    # Write output
    output = {
        'meta': {
            'generated':    datetime.now(timezone.utc).isoformat(),
            'total_cases':  len(all_results),
            'summary':      all_summary,
        },
        'cases': all_results,
    }

    with open(args.out, 'w') as f:
        json.dump(output, f, separators=(',',':'))

    size_kb = Path(args.out).stat().st_size // 1024
    print(f"\nInferences written to {args.out} ({size_kb} KB)")

    # Print top inconsistencies
    if all_summary:
        print("\nTop inconsistency types across corpora:")
        all_incon = defaultdict(int)
        for s in all_summary.values():
            for k, v in s.get('inconsistency_types', {}).items():
                all_incon[k] += v
        for msg, n in sorted(all_incon.items(), key=lambda x:-x[1])[:5]:
            print(f"  [{n}] {msg}")

    print("="*55)


if __name__ == '__main__':
    main()
