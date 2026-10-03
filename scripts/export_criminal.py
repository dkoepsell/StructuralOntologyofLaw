#!/usr/bin/env python3
"""
export_criminal.py -- Export SOoL Criminal Corpus to JSON for Query Tool
SEAL Lab, Texas A&M University

Exports sool_criminal_annotations.db -> sool_criminal_data.json
Run after annotate_criminal.py completes.

Usage:
    python3 export_criminal.py
    python3 export_criminal.py --ann-db ./sool_criminal_annotations.db
                               --out ./sool_criminal_data.json
"""

import argparse, json, math, sqlite3
from datetime import datetime, timezone
from collections import defaultdict

CD_WEIGHTS = {
    'CF':0.15,'AI':0.12,'JC':0.10,'RC3':0.14,'PC':0.09,'TC':0.08,
    'FM':0.11,'NI':0.07,'RF':0.11,'RCL':0.18,'CC':0.14,'SE':0.10,'RPF':0.13
}

CATEGORY_NAMES = {
    1: 'Homicide & Violence',
    2: 'Inchoate Offenses',
    3: 'Property & Fraud',
    4: 'Status & Regulatory',
    5: 'Strict Liability',
    6: 'Affirmative Defenses',
}

CATEGORY_PRIMARY_NODE = {
    1:'N5', 2:'N4/N5', 3:'N2', 4:'N3', 5:'N5 thin', 6:'N7'
}

parser = argparse.ArgumentParser()
parser.add_argument('--ann-db', default='./sool_criminal_annotations.db')
parser.add_argument('--out',    default='./sool_criminal_data.json')
args = parser.parse_args()

conn = sqlite3.connect(args.ann_db)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT case_id, case_name, category_id, court_id, court_type, date_decided,
           node1_closure, node1_entity,
           node2_closure, node2_entity,
           node3_closure, node3_entity, node3_mens_rea,
           node4_closure, node4_entity,
           node5_closure, node5_entity, node5_act_type,
           node6_closure, node6_entity,
           node7_closure, node7_entity,
           node8_closure, node8_entity,
           active_contradictions, contradiction_debt,
           chain_outcome, defense_type, mens_rea_type,
           confidence, outcome_notes,
           COALESCE(adversarial_strength,0.0) as adversarial_strength,
           COALESCE(equipoise_flagged,0) as equipoise_flagged,
           COALESCE(adversarial_notes,"") as adversarial_notes
    FROM criminal_annotations
    WHERE confidence IN ('high','medium')
    ORDER BY category_id, case_id
""").fetchall()

print(f"Exporting {len(rows):,} criminal annotations...")

# ── BUILD CASES ──────────────────────────────────────────────────────────────
cases = []
for r in rows:
    cts = json.loads(r['active_contradictions'] or '[]')
    cases.append({
        'id':       r['case_id'],
        'name':     r['case_name'] or '',
        'cat':      r['category_id'],
        'catname':  CATEGORY_NAMES.get(r['category_id'], ''),
        'court':    r['court_id'] or '',
        'ctype':    r['court_type'] or '',
        'date':     r['date_decided'] or '',
        'year':     int(r['date_decided'][:4]) if r['date_decided'] and len(r['date_decided']) >= 4 else None,
        'outcome':  r['chain_outcome'] or '',
        'cd':       round(r['contradiction_debt'] or 0, 4),
        'cts':      cts,
        'defense':  r['defense_type'] or 'none',
        'mensrea':  r['mens_rea_type'] or 'none',
        'conf':     r['confidence'] or '',
        'adv_strength': float(r['adversarial_strength'] or 0),
        'adv_flagged':  bool(r['equipoise_flagged']),
        'adv_notes':    r['adversarial_notes'] or '',
        'notes':    r['outcome_notes'] or '',
        'nodes': {str(n): {
            'closure': r[f'node{n}_closure'] or 'indeterminate',
            'entity':  (r[f'node{n}_entity'] or '')[:300],
        } for n in range(1,9)}
    })

# ── CATEGORY STATS ───────────────────────────────────────────────────────────
cat_stats = {}
for cat_id, cat_name in CATEGORY_NAMES.items():
    cat_cases = [c for c in cases if c['cat'] == cat_id]
    if not cat_cases:
        cat_stats[str(cat_id)] = {'n':0,'avg_cd':0,'name':cat_name}
        continue
    denied  = [c for c in cat_cases if c['outcome']=='protection_denied']
    granted = [c for c in cat_cases if c['outcome']=='protection_granted']
    avg_cd  = sum(c['cd'] for c in cat_cases) / len(cat_cases)
    avg_den = sum(c['cd'] for c in denied)  / max(len(denied),1)
    avg_gra = sum(c['cd'] for c in granted) / max(len(granted),1)
    cat_stats[str(cat_id)] = {
        'n':       len(cat_cases),
        'avg_cd':  round(avg_cd, 4),
        'avg_cd_denied':  round(avg_den, 4),
        'avg_cd_granted': round(avg_gra, 4),
        'n_denied':  len(denied),
        'n_granted': len(granted),
        'name':      cat_name,
        'primary_node': CATEGORY_PRIMARY_NODE.get(cat_id,'?'),
    }

# ── CT MATRIX (category x CT) ────────────────────────────────────────────────
ct_matrix = defaultdict(lambda: defaultdict(int))
for c in cases:
    for ct in c['cts']:
        if ct in CD_WEIGHTS:
            ct_matrix[ct][str(c['cat'])] += 1

# ── DEFENSE CT PROFILE ───────────────────────────────────────────────────────
defense_profile = defaultdict(lambda: defaultdict(int))
for c in cases:
    dt = c['defense'] or 'none'
    for ct in c['cts']:
        if ct in CD_WEIGHTS:
            defense_profile[dt][ct] += 1

# ── MENS REA CD GRADIENT ─────────────────────────────────────────────────────
mensrea_stats = defaultdict(list)
for c in cases:
    mr = c['mensrea'] or 'unknown'
    mensrea_stats[mr].append(c['cd'])

mensrea_summary = {
    mr: {'n': len(cds), 'avg_cd': round(sum(cds)/len(cds), 4)}
    for mr, cds in mensrea_stats.items() if cds
}

# ── OUTCOME DISTRIBUTION ─────────────────────────────────────────────────────
outcome_counts = defaultdict(int)
outcome_cd     = defaultdict(list)
for c in cases:
    outcome_counts[c['outcome']] += 1
    outcome_cd[c['outcome']].append(c['cd'])

outcome_stats = {
    o: {
        'n': outcome_counts[o],
        'avg_cd': round(sum(outcome_cd[o])/len(outcome_cd[o]), 4)
    }
    for o in outcome_counts
}

# ── GROWTH BY MONTH ───────────────────────────────────────────────────────────
monthly = defaultdict(int)
for c in cases:
    if c['date'] and len(c['date']) >= 7:
        monthly[c['date'][:7]] += 1
monthly_sorted = sorted(monthly.items())

# ── COURT TYPE BREAKDOWN ─────────────────────────────────────────────────────
state_n   = sum(1 for c in cases if c['ctype'] == 'state')
federal_n = sum(1 for c in cases if c['ctype'] == 'federal')

# ── ASSEMBLE OUTPUT ───────────────────────────────────────────────────────────
n = len(cases)
denied  = [c for c in cases if c['outcome']=='protection_denied']
granted = [c for c in cases if c['outcome']=='protection_granted']
avg_den = sum(c['cd'] for c in denied)  / max(len(denied),1)
avg_gra = sum(c['cd'] for c in granted) / max(len(granted),1)

output = {
    'meta': {
        'n':          n,
        'n_state':    state_n,
        'n_federal':  federal_n,
        'n_denied':   len(denied),
        'n_granted':  len(granted),
        'avg_cd':     round(sum(c['cd'] for c in cases)/max(n,1), 4),
        'avg_cd_denied':  round(avg_den, 4),
        'avg_cd_granted': round(avg_gra, 4),
        'cd_ratio':   round(avg_den/max(avg_gra,0.001), 2),
        'auc_preliminary': 0.9484,
        'generated':  datetime.now(timezone.utc).isoformat(),
        'corpus':     'criminal',
        'target':     3000,
    },
    'cases':          cases,
    'category_stats': cat_stats,
    'ct_matrix':      {k: dict(v) for k,v in ct_matrix.items()},
    'defense_profile':  {k: dict(v) for k,v in defense_profile.items()},
    'mensrea_summary': mensrea_summary,
    'outcome_stats':  outcome_stats,
    'monthly':        monthly_sorted,
}

with open(args.out, 'w') as f:
    json.dump(output, f, separators=(',',':'))

size_kb = len(json.dumps(output).encode()) / 1024
print(f"Written to {args.out} ({size_kb:.0f} KB)")
print(f"  {n:,} cases  |  {state_n} state  |  {federal_n} federal")
print(f"  avg CD denied={avg_den:.3f}  granted={avg_gra:.3f}  ratio={avg_den/max(avg_gra,0.001):.1f}x")
cats_str = ' | '.join('C'+str(k)+':'+str(v['n']) for k,v in cat_stats.items())
print(f"  Categories: {cats_str}")
