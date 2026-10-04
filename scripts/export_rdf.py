#!/usr/bin/env python3
"""
export_rdf.py — SOoL Corpus RDF/OWL Export
==========================================
SEAL Lab, Texas A&M University
David R. Koepsell

Converts SQLite annotation databases to RDF/Turtle files conforming
to the SOoL and criminal norms OWL schemas.

Produces:
  sool_corpus.ttl       — civil corpus as RDF individuals
  sool_criminal.ttl     — criminal corpus as RDF individuals
  sool_combined.ttl     — both corpora merged with cross-references

Each annotated case becomes an OWL individual with:
  - rdf:type assertion to the appropriate sool:/crim: class
  - MLC node closure assertions (8 datatype properties)
  - Active contradiction type assertions (object properties)
  - Chain outcome, CD score, domain/category assertions
  - BFO-typed legal chain participation

Usage:
    python3 export_rdf.py
    python3 export_rdf.py --civil-only
    python3 export_rdf.py --criminal-only
    python3 export_rdf.py --out-dir ./rdf_output
    python3 export_rdf.py --validate    (check with rdflib)

Requirements:
    pip install rdflib
"""

import argparse, json, sqlite3, re, sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

try:
    from rdflib import Graph, Namespace, Literal, URIRef, BNode
    from rdflib.namespace import RDF, RDFS, OWL, XSD
    RDFLIB = True
except ImportError:
    RDFLIB = False

# ── NAMESPACES ────────────────────────────────────────────────────────────────

SOOL_NS  = "http://ontologyoflaw.org/structural#"
CRIM_NS  = "http://ontologyoflaw.org/criminal#"
CORPUS_NS = "http://ontologyoflaw.org/corpus/"
BFO_NS   = "http://purl.obolibrary.org/obo/BFO_"

# MLC node names
NODE_NAMES = {
    1: "SourceOfAuthority",
    2: "Norm",
    3: "ActorInRole",
    4: "TriggeringFacts",
    5: "LegalAct",
    6: "Target",
    7: "LegalEffect",
    8: "Remedy",
}

# Contradiction type → sool: class mapping, loaded from the registry.
#
# This was a hand-typed dict until 2026-10-03, and two of its thirteen values named
# classes that exist in no TTL: 'RC3' emitted sool:RoleContradictionTriad (the ontology
# has sool:RoleContradiction) and 'SE' emitted sool:SovereigntyException (the ontology
# has sool:SelfUnderminingEffect, a different concept). Both were written into every
# published graph as sool:hasContradictionType objects, so sool_corpus.ttl and
# sool_criminal.ttl carried dangling IRIs on every nightly export.
#
# Reading the registry makes that class of error unrepresentable: the local names come
# from the same parse of the ontology of record that produced vocab/registry.json.
# Deprecated codes are accepted so stored rows keyed on 'AINF' still resolve after the
# AI -> AINF rename (amendment A2).
def _load_ct_classes():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / "vocab" / "registry.json"
    try:
        reg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(
            f"*** ABORT: cannot load {path}: {e}\n"
            f"*** Run: python3 build_registry.py\n"
            f"*** Refusing to export with a guessed type vocabulary."
        )

    out = {}
    for code, entry in reg["types"].items():
        local = (entry.get("iri_operational") or "").split(":")[-1].split("#")[-1]
        if not local:
            sys.exit(f"*** ABORT: registry entry {code} has no usable IRI")
        out[code] = local
        for dep in entry.get("deprecatedCodes") or []:
            out.setdefault(dep, local)
    if len(out) < 13:
        sys.exit(f"*** ABORT: registry yielded only {len(out)} contradiction codes")
    return out


CT_CLASSES = _load_ct_classes()

# Criminal category → crim: class mapping
CRIM_CATEGORY_CLASSES = {
    1: 'HomicideOffense',
    2: 'InchoateOffense',
    3: 'PropertyFraudOffense',
    4: 'StatusOffense',
    5: 'StrictLiabilityOffense',
    6: 'AffirmativeDefenseCase',
}

# Civil domain → sool: class (approximate mapping)
CIVIL_DOMAIN_CLASSES = {
    1:  'FirstAmendmentClaim',
    2:  'FourthAmendmentClaim',
    3:  'EqualProtectionClaim',
    4:  'CriminalProcedureClaim',
    5:  'ImmigrationClaim',
    6:  'CivilRightsClaim',
    7:  'ContractClaim',
    8:  'FamilyLawClaim',
    9:  'HabeasClaim',
    10: 'PatentClaim',
    11: 'SecuritiesClaim',
}

# Defense type → crim: class
DEFENSE_CLASSES = {
    'justification': 'Justification',
    'excuse':        'Excuse',
    'procedural':    'ProceduralBarDefense',
    'capacity':      'Excuse',
    'proof':         'CriminalDefense',
}


# ── TURTLE WRITER (pure string, no rdflib dependency) ─────────────────────────

def safe_uri_fragment(s: str) -> str:
    """Make a string safe as a URI fragment."""
    s = str(s).strip()
    s = re.sub(r'[^\w\-]', '_', s)
    s = re.sub(r'_+', '_', s)
    return s[:80].strip('_')


def turtle_literal(s, datatype=None, lang=None):
    """Escape a string as a Turtle literal."""
    s = str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    if datatype:
        return f'"{s}"^^{datatype}'
    if lang:
        return f'"{s}"@{lang}'
    return f'"{s}"'


def write_prefixes(f):
    f.write("""@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix bfo:    <http://purl.obolibrary.org/obo/BFO_> .
@prefix sool:   <http://ontologyoflaw.org/structural#> .
@prefix crim:   <http://ontologyoflaw.org/criminal#> .
@prefix corpus: <http://ontologyoflaw.org/corpus/> .
@prefix civil:  <http://ontologyoflaw.org/corpus/civil/> .
@prefix crimcase: <http://ontologyoflaw.org/corpus/criminal/> .

""")


# ── CIVIL CORPUS EXPORT ───────────────────────────────────────────────────────

def export_civil(ann_db: str, out_path: str) -> int:
    conn = sqlite3.connect(ann_db)
    conn.row_factory = sqlite3.Row

    # Civil annotations columns: case_id, court, date_decided (hardcoded)




    rows = conn.execute("""
        SELECT a.case_id, a.case_name, a.domain_id, a.court, a.date_decided,
               a.chain_outcome, a.contradiction_debt,
               a.node1_closure, a.node2_closure, a.node3_closure,
               a.node4_closure, a.node5_closure, a.node6_closure,
               a.node7_closure, a.node8_closure,
               a.active_contradictions, a.confidence,
               NULL as primary_ct, a.outcome_notes
        FROM scope_highconf a
        ORDER BY a.domain_id, a.case_id
    """).fetchall()
    print(f"Exporting {len(rows):,} civil cases to RDF...")

    with open(out_path, 'w', encoding='utf-8') as f:
        write_prefixes(f)

        # Ontology header
        f.write(f"""<http://ontologyoflaw.org/corpus/civil> a owl:Ontology ;
    rdfs:label "SOoL Civil Corpus" ;
    rdfs:comment "RDF export of SOoL civil annotation corpus" ;
    owl:imports <http://ontologyoflaw.org/structural#> ;
    sool:caseCount "{len(rows)}"^^xsd:integer ;
    sool:generatedAt "{datetime.now(timezone.utc).isoformat()}"^^xsd:dateTime .

""")

        for row in rows:
            cid = row['case_id']
            uri = f"civil:case_{cid}"
            domain_id = row['domain_id'] or 0
            domain_class = CIVIL_DOMAIN_CLASSES.get(domain_id, 'LegalClaim')
            outcome = row['chain_outcome'] or ''
            cd = row['contradiction_debt'] or 0
            cts = json.loads(row['active_contradictions'] or '[]')
            node_closures = {
                n: row[f'node{n}_closure'] or 'indeterminate'
                for n in range(1, 9)
            }

            # Determine primary type
            if outcome == 'protection_granted':
                outcome_class = 'sool:ProtectionGrantedChain'
            elif outcome == 'protection_denied':
                outcome_class = 'sool:ProtectionDeniedChain'
            else:
                outcome_class = 'sool:LegalChain'

            # Write individual
            f.write(f"{uri}\n")
            f.write(f"    a sool:{domain_class}, {outcome_class}, owl:NamedIndividual ;\n")
            f.write(f"    rdfs:label {turtle_literal(row['case_name'] or '')} ;\n")
            f.write(f"    sool:caseId {turtle_literal(str(cid), 'xsd:integer')} ;\n")
            f.write(f"    sool:domainId {turtle_literal(str(domain_id), 'xsd:integer')} ;\n")
            f.write(f"    sool:courtId {turtle_literal(row['court'] or '')} ;\n")
            if row['date_decided']:
                f.write(f"    sool:dateFiled {turtle_literal(str(row['date_decided'])[:10], 'xsd:date')} ;\n")
            f.write(f"    sool:chainOutcome {turtle_literal(outcome)} ;\n")
            f.write(f"    sool:contradictionDebt {turtle_literal(str(round(cd, 4)), 'xsd:decimal')} ;\n")
            f.write(f"    sool:annotationConfidence {turtle_literal(row['confidence'] or '')} ;\n")
            f.write(f"    sool:corpus {turtle_literal('civil')} ;\n")

            # Node closures
            for n in range(1, 9):
                cl = node_closures[n]
                f.write(f"    sool:node{n}Closure {turtle_literal(cl)} ;\n")

            # Contradiction types
            for ct in cts:
                ct_class = CT_CLASSES.get(ct)
                if ct_class:
                    f.write(f"    sool:hasContradictionType sool:{ct_class} ;\n")
                f.write(f"    sool:contradictionCode {turtle_literal(ct)} ;\n")

            f.write("    .\n\n")

    conn.close()
    return len(rows)


# ── CRIMINAL CORPUS EXPORT ────────────────────────────────────────────────────

def export_criminal(ann_db: str, out_path: str) -> int:
    conn = sqlite3.connect(ann_db)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT case_id, case_name, category_id, court_id, court_type,
               date_decided,
               node1_closure, node2_closure, node3_closure,
               node4_closure, node5_closure, node6_closure,
               node7_closure, node8_closure,
               active_contradictions, contradiction_debt,
               chain_outcome, defense_type, mens_rea_type, confidence,
               outcome_notes
        FROM criminal_annotations
        WHERE confidence IN ('high','medium')
        ORDER BY category_id, case_id
    """).fetchall()

    print(f"Exporting {len(rows):,} criminal cases to RDF...")

    with open(out_path, 'w', encoding='utf-8') as f:
        write_prefixes(f)

        f.write(f"""<http://ontologyoflaw.org/corpus/criminal> a owl:Ontology ;
    rdfs:label "SOoL Criminal Norms Corpus" ;
    rdfs:comment "RDF export of SOoL criminal annotation corpus. State as claimant." ;
    owl:imports <http://ontologyoflaw.org/criminal#> ;
    crim:caseCount "{len(rows)}"^^xsd:integer ;
    crim:generatedAt "{datetime.now(timezone.utc).isoformat()}"^^xsd:dateTime .

""")

        for row in rows:
            cid = row['case_id']
            cat_id = row['category_id'] or 0
            cat_class = CRIM_CATEGORY_CLASSES.get(cat_id, 'CriminalNorm')
            outcome = row['chain_outcome'] or ''
            cd = row['contradiction_debt'] or 0
            cts = json.loads(row['active_contradictions'] or '[]')
            defense = row['defense_type'] or 'none'
            defense_class = DEFENSE_CLASSES.get(defense)

            uri = f"crimcase:case_{cid}"

            # Type assertions
            types = [f"crim:{cat_class}", "owl:NamedIndividual"]
            if outcome == 'protection_granted':
                types.append("crim:ConvictionChain")
            elif outcome == 'protection_denied':
                types.append("crim:ReversalChain")
            if defense_class:
                types.append(f"crim:{defense_class}")

            f.write(f"{uri}\n")
            f.write(f"    a {', '.join(types)} ;\n")
            f.write(f"    rdfs:label {turtle_literal(row['case_name'] or '')} ;\n")
            f.write(f"    crim:caseId {turtle_literal(str(cid), 'xsd:integer')} ;\n")
            f.write(f"    crim:categoryId {turtle_literal(str(cat_id), 'xsd:integer')} ;\n")
            f.write(f"    crim:courtId {turtle_literal(row['court_id'] or '')} ;\n")
            f.write(f"    crim:courtType {turtle_literal(row['court_type'] or '')} ;\n")
            if row['date_decided']:
                f.write(f"    crim:dateDecided {turtle_literal(str(row['date_decided'])[:10], 'xsd:date')} ;\n")
            f.write(f"    crim:chainOutcome {turtle_literal(outcome)} ;\n")
            f.write(f"    crim:contradictionDebt {turtle_literal(str(round(cd, 4)), 'xsd:decimal')} ;\n")
            f.write(f"    crim:defenseType {turtle_literal(defense)} ;\n")
            f.write(f"    crim:mensReaType {turtle_literal(row['mens_rea_type'] or '')} ;\n")
            f.write(f"    crim:annotationConfidence {turtle_literal(row['confidence'] or '')} ;\n")

            # Node closures
            for n in range(1, 9):
                cl = row[f'node{n}_closure'] or 'indeterminate'
                node_name = NODE_NAMES[n]
                f.write(f"    crim:node{n}Closure {turtle_literal(cl)} ;\n")
                # Flag failed nodes explicitly
                if cl in ('failed', 'partial'):
                    f.write(f"    crim:failedAt crim:{node_name} ;\n")

            # Contradiction types — assert as both code and class
            for ct in cts:
                ct_class = CT_CLASSES.get(ct)
                if ct_class:
                    f.write(f"    crim:hasContradictionType sool:{ct_class} ;\n")
                f.write(f"    crim:contradictionCode {turtle_literal(ct)} ;\n")

            # Irreversibility assertion for convictions in status offense cases
            if cat_id == 4 and outcome == 'protection_granted':
                f.write(f"    crim:generatesIrreversibleStatus {turtle_literal('true', 'xsd:boolean')} ;\n")

            f.write("    .\n\n")

    conn.close()
    return len(rows)


# ── VALIDATION ────────────────────────────────────────────────────────────────

def validate_ttl(path: str) -> bool:
    if not RDFLIB:
        print("  rdflib not installed — skipping validation")
        print("  Install: pip install rdflib")
        return True
    try:
        g = Graph()
        g.parse(path, format='turtle')
        print(f"  Valid Turtle — {len(g):,} triples in {path}")
        return True
    except Exception as e:
        print(f"  INVALID: {e}")
        return False


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SOoL Corpus RDF/OWL Export"
    )
    parser.add_argument('--civil-ann-db',   default='./sool_annotations.db')
    parser.add_argument('--criminal-ann-db',default='./sool_criminal_annotations.db')
    parser.add_argument('--out-dir',        default='.')
    parser.add_argument('--civil-only',     action='store_true')
    parser.add_argument('--criminal-only',  action='store_true')
    parser.add_argument('--validate',       action='store_true')
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("="*55)
    print("SOoL RDF/OWL Export")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*55)

    civil_path   = out / 'sool_corpus.ttl'
    crim_path    = out / 'sool_criminal.ttl'

    if not args.criminal_only:
        if Path(args.civil_ann_db).exists():
            n = export_civil(args.civil_ann_db, str(civil_path))
            print(f"Civil:    {n:,} cases → {civil_path}")
            if args.validate:
                validate_ttl(str(civil_path))
        else:
            print(f"Civil DB not found: {args.civil_ann_db}")

    if not args.civil_only:
        if Path(args.criminal_ann_db).exists():
            n = export_criminal(args.criminal_ann_db, str(crim_path))
            print(f"Criminal: {n:,} cases → {crim_path}")
            if args.validate:
                validate_ttl(str(crim_path))
        else:
            print(f"Criminal DB not found: {args.criminal_ann_db}")

    # Also copy the schema TTLs to output dir if present
    import shutil
    for schema_ttl in ['sool_bfo_mlc_core.ttl', 'sool_criminal_norms.ttl']:
        schema_src = Path(__file__).parent / schema_ttl
        schema_dst = out / schema_ttl
        if schema_src.exists() and not schema_dst.samefile(schema_src) if schema_dst.exists() else True:
            try:
                shutil.copy2(str(schema_src), str(schema_dst))
                print(f"Schema copied: {schema_ttl}")
            except Exception:
                pass

    print("="*55)
    print("Done. Upload TTL files to Turbify or load into Protégé/Fuseki.")


if __name__ == '__main__':
    main()
