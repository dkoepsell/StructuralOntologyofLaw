#!/usr/bin/env python3
"""
analyze_criminal.py -- SOoL Criminal Ontology Corpus Analysis
==============================================================
SEAL Lab, Texas A&M University

Analyzes the criminal norms corpus to test:
  H1: Primary node taxonomy -- each offense category has a
      characteristic primary failure node distinct from all others
  H2: Justification/excuse structural distinction -- JC vs CF
      distributions differ significantly across defense types
  H3: Mens rea gradient -- CD correlates inversely with mens rea
      specificity (strict liability > negligence > recklessness >
      knowledge > purpose) at the system level
  H4: Criminal CD/outcome ratio -- conviction (protection_granted)
      cases show lower CD than reversal (protection_denied) cases,
      replicating the civil corpus finding at the criminal level
  H5: Irreversible residue test -- status offense cases (C4)
      show RCL at significantly higher rates than all other categories

Usage:
    python3 analyze_criminal.py
    python3 analyze_criminal.py --full  (includes cross-corpus comparison)
"""

import sqlite3, json, math, argparse
import numpy as np
from collections import Counter
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_score

ANN_DB = './sool_criminal_annotations.db'
CIVIL_ANN_DB = './sool_annotations.db'

CATEGORIES = {
    1: 'C1 Homicide/Violence      (N5 primary)',
    2: 'C2 Inchoate Offenses      (N4/N5 primary)',
    3: 'C3 Property/Fraud         (N2 primary)',
    4: 'C4 Status/Regulatory      (N3 primary)',
    5: 'C5 Strict Liability       (N5 thin)',
    6: 'C6 Affirmative Defenses   (N7 primary)',
}

CD_WEIGHTS = {
    'CF':0.15,'AINF':0.12,'JC':0.10,'RC3':0.14,'PC':0.09,'TC':0.08,
    'FM':0.11,'NI':0.07,'RF':0.11,'RCL':0.18,'CC':0.14,'SE':0.10,'RPF':0.13
}

FAIL = {'failed','partial'}


def section(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print('='*65)


def get_rows(conn):
    return conn.execute("""
        SELECT category_id, chain_outcome, contradiction_debt,
               active_contradictions, defense_type, mens_rea_type,
               node1_closure, node2_closure, node3_closure,
               node4_closure, node5_closure, node6_closure,
               node7_closure, node8_closure
        FROM criminal_annotations
        WHERE confidence IN ('high','medium')
    """).fetchall()


# ── H1: Primary node taxonomy ────────────────────────────────────────────────
def test_h1_primary_nodes(rows):
    section("H1: PRIMARY NODE FAILURE TAXONOMY (Criminal)")

    NODE_COLS = ['node1_closure','node2_closure','node3_closure',
                 'node4_closure','node5_closure','node6_closure']

    print(f"  {'Category':<44} {'n':>5}  Primary  OR      Runner-up OR")
    print(f"  {'-'*70}")

    for cat_id, cat_name in CATEGORIES.items():
        cat_rows = [r for r in rows if r['category_id'] == cat_id
                    and r['chain_outcome'] in
                    ('protection_granted','protection_denied')]
        if len(cat_rows) < 20:
            print(f"  {cat_name:<44} {len(cat_rows):>5}  (insufficient data)")
            continue

        X = [[1 if (r[f'node{i+1}_closure'] or '').lower() in FAIL else 0
              for i in range(6)] for r in cat_rows]
        y = [1 if r['chain_outcome'] == 'protection_granted' else 0
             for r in cat_rows]
        X, y = np.array(X), np.array(y)

        lr = LogisticRegression(max_iter=500)
        lr.fit(X, y)
        ors = [(f'N{i+1}', math.exp(c)) for i,c in enumerate(lr.coef_[0])]
        ors.sort(key=lambda x: -x[1])
        print(f"  {cat_name:<44} {len(cat_rows):>5}  "
              f"{ors[0][0]}  {ors[0][1]:>5.2f}x  "
              f"{ors[1][0]}  {ors[1][1]:>5.2f}x")


# ── H2: Justification vs Excuse distinction ──────────────────────────────────
def test_h2_defense_structure(rows):
    section("H2: JUSTIFICATION vs EXCUSE -- STRUCTURAL DISTINCTION")

    defense_cts = {}
    for r in rows:
        dt = r['defense_type'] or 'none'
        if dt == 'none': continue
        cts = json.loads(r['active_contradictions'] or '[]')
        if dt not in defense_cts:
            defense_cts[dt] = Counter()
        for ct in cts:
            defense_cts[dt][ct] += 1

    for def_type, ct_counts in sorted(defense_cts.items()):
        total = sum(ct_counts.values())
        top = sorted(ct_counts.items(), key=lambda x:-x[1])[:4]
        top_str = ', '.join(f'{ct}({n})' for ct,n in top)
        print(f"\n  {def_type:<20} (total CTs fired: {total})")
        print(f"    Top CTs: {top_str}")

    print(f"\n  EXPECTED STRUCTURAL PATTERN:")
    print(f"    justification -> JC primary (competing norms)")
    print(f"    excuse        -> CF primary (actor capacity)")
    print(f"    procedural    -> CF/TC (authority/temporal)")
    print(f"    entrapment    -> FM primary (manufactured facts)")


# ── H3: Mens rea gradient ────────────────────────────────────────────────────
def test_h3_mensrea_gradient(rows):
    section("H3: MENS REA GRADIENT -- CD BY MENTAL STATE TYPE")

    mensrea_cd = {}
    for r in rows:
        mr = r['mens_rea_type'] or 'unknown'
        cd = r['contradiction_debt'] or 0
        if mr not in mensrea_cd:
            mensrea_cd[mr] = []
        mensrea_cd[mr].append(cd)

    ORDER = ['purposely','knowingly','recklessly','negligently',
             'strict_liability','none','unknown']

    print(f"  {'Mens rea type':<20} {'n':>5}  {'Mean CD':>8}  Expected")
    print(f"  {'-'*55}")
    for mr in ORDER:
        if mr not in mensrea_cd: continue
        cds = mensrea_cd[mr]
        mean_cd = sum(cds) / len(cds) if cds else 0
        expected = {
            'purposely':       'lowest (most determined)',
            'knowingly':       'low-medium',
            'recklessly':      'medium',
            'negligently':     'medium-high',
            'strict_liability':'highest (role/act severed)',
            'none':            'variable',
        }.get(mr, '')
        print(f"  {mr:<20} {len(cds):>5}  {mean_cd:>8.3f}  {expected}")

    print(f"\n  HYPOTHESIS: CD should increase from purposely -> strict_liability")
    print(f"  (Structural stress increases as mens rea role condition weakens)")


# ── H4: CD/outcome ratio ─────────────────────────────────────────────────────
def test_h4_cd_ratio(rows, civil_conn=None):
    section("H4: CD/OUTCOME RATIO -- CRIMINAL CORPUS")

    clean = [r for r in rows if r['chain_outcome'] in
             ('protection_granted','protection_denied')]
    if len(clean) < 50:
        print("  Insufficient data")
        return

    X = np.array([[r['contradiction_debt'] or 0] for r in clean])
    y = np.array([1 if r['chain_outcome'] == 'protection_granted' else 0
                  for r in clean])

    granted_cd = [r['contradiction_debt'] or 0 for r in clean
                  if r['chain_outcome'] == 'protection_granted']
    denied_cd  = [r['contradiction_debt'] or 0 for r in clean
                  if r['chain_outcome'] == 'protection_denied']

    avg_g = sum(granted_cd) / max(len(granted_cd), 1)
    avg_d = sum(denied_cd)  / max(len(denied_cd),  1)
    ratio = avg_g / max(avg_d, 0.001)  # NOTE: inverted -- conviction = granted

    print(f"\n  n = {len(clean)} clean cases")
    print(f"  protection_granted (conviction): n={len(granted_cd)}  "
          f"avg CD={avg_g:.3f}")
    print(f"  protection_denied (reversal):    n={len(denied_cd)}  "
          f"avg CD={avg_d:.3f}")
    print(f"  CD ratio (granted/denied):       {ratio:.1f}:1")
    print(f"\n  NOTE: In criminal corpus, high CD -> reversal (not conviction)")
    print(f"  because structural incoherence undermines the state's chain.")

    if len(y) >= 50:
        scores = cross_val_score(LogisticRegression(max_iter=1000), X, y,
                                 cv=min(5, len(y)//20),
                                 scoring='roc_auc')
        print(f"\n  5-fold CV AUC (CD -> conviction): "
              f"{scores.mean():.4f} +/- {scores.std():.4f}")

    if civil_conn:
        civil_rows = civil_conn.execute("""
            SELECT chain_outcome, contradiction_debt
            FROM annotations WHERE NOT needs_review
            AND chain_outcome IN ('protection_granted','protection_denied')
        """).fetchall()
        civ_d = [r[1] for r in civil_rows if r[0]=='protection_denied']
        civ_g = [r[1] for r in civil_rows if r[0]=='protection_granted']
        civ_ratio = (sum(civ_d)/max(len(civ_d),1)) / max(
                     sum(civ_g)/max(len(civ_g),1), 0.001)
        print(f"\n  CROSS-CORPUS COMPARISON:")
        print(f"  Civil corpus CD ratio (denied/granted): {civ_ratio:.1f}:1")
        print(f"  Criminal corpus CD ratio:               {ratio:.1f}:1")
        print(f"  (Different direction: civil = denied has high CD;")
        print(f"   criminal = conviction/granted should have lower CD)")


# ── H5: RCL in status offenses ───────────────────────────────────────────────
def test_h5_rcl_status(rows):
    section("H5: RECOGNITION COLLAPSE -- STATUS OFFENSES vs OTHER CATEGORIES")

    from scipy.stats import chi2_contingency

    rcl_by_cat = {}
    for r in rows:
        cat = r['category_id']
        cts = json.loads(r['active_contradictions'] or '[]')
        has_rcl = 1 if 'RCL' in cts else 0
        if cat not in rcl_by_cat:
            rcl_by_cat[cat] = [0, 0]
        rcl_by_cat[cat][has_rcl] += 1

    print(f"\n  {'Category':<44} {'n':>5}  RCL%")
    print(f"  {'-'*55}")
    for cat_id, cat_name in CATEGORIES.items():
        if cat_id not in rcl_by_cat: continue
        no_rcl, has_rcl = rcl_by_cat[cat_id]
        n = no_rcl + has_rcl
        pct = has_rcl / n * 100 if n > 0 else 0
        flag = " <-- PREDICTED HIGH" if cat_id == 4 else ""
        print(f"  {cat_name:<44} {n:>5}  {pct:>5.1f}%{flag}")

    print(f"\n  HYPOTHESIS: C4 (Status) should show significantly higher RCL%")
    print(f"  because status offenses systematically generate recognition collapse")
    print(f"  (obligations persist after sentence completion)")


# ── CORPUS STATUS ────────────────────────────────────────────────────────────
def corpus_status(conn):
    section("CRIMINAL CORPUS STATUS")

    rows = conn.execute("""
        SELECT category_id, chain_outcome, confidence, mens_rea_type
        FROM criminal_annotations
    """).fetchall()

    total = len(rows)
    by_cat = Counter(r['category_id'] for r in rows)
    by_outcome = Counter(r['chain_outcome'] for r in rows)
    high_conf = sum(1 for r in rows if r['confidence'] == 'high')

    print(f"\n  Total annotations: {total:,}")
    print(f"  High confidence:   {high_conf:,} ({high_conf/max(total,1)*100:.0f}%)")

    print(f"\n  {'Category':<44} {'n':>5}  {'Target':>6}")
    for cat_id, cat_name in CATEGORIES.items():
        n = by_cat.get(cat_id, 0)
        print(f"  {cat_name:<44} {n:>5}  {500:>6}")

    print(f"\n  Outcome distribution:")
    for outcome, n in sorted(by_outcome.items(), key=lambda x:-x[1]):
        print(f"    {outcome:<25} {n:>5}  ({n/max(total,1)*100:.1f}%)")

    print(f"\n  Mens rea distribution:")
    mr_counts = Counter(r['mens_rea_type'] for r in rows)
    for mr, n in sorted(mr_counts.items(), key=lambda x:-x[1]):
        print(f"    {mr or 'unspecified':<25} {n:>5}")


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', action='store_true',
                        help='Include cross-corpus comparison with civil corpus')
    args = parser.parse_args()

    conn = sqlite3.connect(ANN_DB)
    conn.row_factory = sqlite3.Row
    rows = get_rows(conn)

    civil_conn = None
    if args.full:
        try:
            civil_conn = sqlite3.connect(CIVIL_ANN_DB)
            civil_conn.row_factory = sqlite3.Row
        except Exception:
            pass

    print("\n" + "="*65)
    print("  SOoL CRIMINAL ONTOLOGY CORPUS ANALYSIS")
    print("  SEAL Lab, Texas A&M University")
    print("="*65)

    corpus_status(conn)
    test_h1_primary_nodes(rows)
    test_h2_defense_structure(rows)
    test_h3_mensrea_gradient(rows)
    test_h4_cd_ratio(rows, civil_conn)
    test_h5_rcl_status(rows)

    print("\n" + "="*65)
    print("  Run monthly as corpus grows:")
    print("  python3 analyze_criminal.py          (status + hypotheses)")
    print("  python3 analyze_criminal.py --full   (+ cross-corpus)")
    print("="*65 + "\n")


if __name__ == '__main__':
    main()
