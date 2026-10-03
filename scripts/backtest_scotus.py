"""
backtest_scotus.py — SOoL SCOTUS Prediction Backtester
=======================================================
SEAL Lab, Texas A&M University

Computes accuracy metrics for the SOoL transcript-based prediction
against known SCOTUS outcomes. Generates:
  - Overall accuracy and AUC
  - CD calibration curve (accuracy by CD bin)
  - CT signature analysis
  - Term-by-term accuracy trend
  - Export to scotus_backtest_results.json for the query tool

Usage:
    python3 backtest_scotus.py              # full report
    python3 backtest_scotus.py --export     # export JSON for query tool
    python3 backtest_scotus.py --terms 2022 2023 2024
"""

import argparse, json, math, os, sqlite3, sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

CT_WEIGHTS = {
    'CF':0.15,'AI':0.12,'JC':0.10,'RC3':0.14,'PC':0.09,'TC':0.08,
    'FM':0.11,'NI':0.07,'RF':0.11,'RCL':0.18,'CC':0.14,'SE':0.10,'RPF':0.13
}

def get_db(path='scotus_backtest.db'):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def compute_auc(pairs):
    """
    Compute AUC from list of (cd_score, label) pairs where
    label=1 means protection_denied (high CD = denied is positive class).
    """
    if len(pairs) < 5:
        return None
    pairs_sorted = sorted(pairs, key=lambda x: -x[0])
    n_pos = sum(1 for _, l in pairs if l == 1)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    tp, fp = 0, 0
    auc = 0.0
    prev_fp = 0
    for _, label in pairs_sorted:
        if label == 1:
            tp += 1
        else:
            fp += 1
            auc += (fp - prev_fp) * (tp / n_pos) if n_pos else 0
            prev_fp = fp
    return auc / n_neg if n_neg else None


def get_all_cases(conn):
    """Export all annotated cases (with and without known outcomes) for the case browser.
    Includes dissent fields; falls back gracefully if columns not yet migrated."""
    try:
        rows = conn.execute("""
            SELECT
              c.docket, c.case_name, c.term, c.argument_date, c.decision_date,
              c.dissent_author,
              a.predicted_outcome, a.actual_outcome, a.prediction_correct,
              a.contradiction_debt, a.active_contradictions,
              a.outcome_confidence, a.adversarial_strength, a.adversarial_notes,
              a.structural_narrative,
              a.node1_closure, a.node2_closure, a.node3_closure, a.node4_closure,
              a.node5_closure, a.node6_closure, a.node7_closure, a.node8_closure,
              a.dissent_cd, a.dissent_failures, a.cd_divergence
            FROM scotus_annotations a
            JOIN scotus_cases c ON c.id = a.case_id
            ORDER BY c.term DESC, c.argument_date DESC
        """).fetchall()
    except Exception:
        # Dissent columns not yet migrated — query without them
        rows = conn.execute("""
            SELECT
              c.docket, c.case_name, c.term, c.argument_date, c.decision_date,
              NULL as dissent_author,
              a.predicted_outcome, a.actual_outcome, a.prediction_correct,
              a.contradiction_debt, a.active_contradictions,
              a.outcome_confidence, a.adversarial_strength, a.adversarial_notes,
              a.structural_narrative,
              a.node1_closure, a.node2_closure, a.node3_closure, a.node4_closure,
              a.node5_closure, a.node6_closure, a.node7_closure, a.node8_closure,
              NULL as dissent_cd, NULL as dissent_failures, NULL as cd_divergence
            FROM scotus_annotations a
            JOIN scotus_cases c ON c.id = a.case_id
            ORDER BY c.term DESC, c.argument_date DESC
        """).fetchall()
    return [
        {
            'docket':         r['docket'],
            'case_name':      r['case_name'],
            'term':           r['term'],
            'argument_date':  r['argument_date'],
            'decision_date':  r['decision_date'],
            'predicted':      r['predicted_outcome'],
            'actual':         r['actual_outcome'],
            'correct':        None if r['prediction_correct'] is None
                              else bool(r['prediction_correct']),
            'cd':             r['contradiction_debt'],
            'cts':            json.loads(r['active_contradictions'] or '[]'),
            'confidence':     r['outcome_confidence'],
            'adv_strength':   r['adversarial_strength'],
            'adv_notes':      (r['adversarial_notes'] or '')[:400],
            'narrative':      (r['structural_narrative'] or '')[:500],
            'nodes':          {f'N{n}': r[f'node{n}_closure'] for n in range(1, 9)},
            'dissent_author': r['dissent_author'],
            'dissent_cd':     r['dissent_cd'],
            'dissent_cts':    json.loads(r['dissent_failures'] or '[]')
                              if r['dissent_failures'] else [],
            'cd_divergence':  r['cd_divergence'],
        }
        for r in rows
    ]


def run_backtest(conn, terms=None):
    """Compute full backtest metrics. Returns results dict."""

    # Base query
    where = "WHERE a.prediction_correct IS NOT NULL"
    params = []
    if terms:
        placeholders = ','.join('?' * len(terms))
        where += f" AND c.term IN ({placeholders})"
        params = list(terms)

    rows = conn.execute(f"""
        SELECT
          c.docket, c.case_name, c.term, c.argument_date, c.decision_date,
          a.predicted_outcome, a.actual_outcome, a.prediction_correct,
          a.contradiction_debt, a.active_contradictions,
          a.outcome_confidence, a.adversarial_strength,
          a.structural_narrative,
          a.node7_closure, a.node1_closure
        FROM scotus_annotations a
        JOIN scotus_cases c ON c.id = a.case_id
        {where}
        ORDER BY c.term, c.argument_date
    """, params).fetchall()

    if not rows:
        print("No annotated cases with known outcomes found.")
        return {}

    n_total      = len(rows)
    n_correct    = sum(1 for r in rows if r['prediction_correct'] == 1)
    n_wrong      = sum(1 for r in rows if r['prediction_correct'] == 0)
    accuracy     = n_correct / n_total if n_total else 0

    # AUC
    auc_pairs = [
        (r['contradiction_debt'],
         1 if r['actual_outcome'] == 'protection_denied' else 0)
        for r in rows if r['contradiction_debt'] is not None
    ]
    auc = compute_auc(auc_pairs)

    # CD calibration by bin
    bins = [(0, 0.10), (0.10, 0.18), (0.18, 0.25), (0.25, 0.35), (0.35, 1.0)]
    calibration = []
    for lo, hi in bins:
        bin_rows = [r for r in rows if r['contradiction_debt'] is not None
                    and lo <= r['contradiction_debt'] < hi]
        if bin_rows:
            bc = sum(1 for r in bin_rows if r['prediction_correct'] == 1)
            calibration.append({
                'range':    f"{lo:.2f}-{hi:.2f}",
                'n':        len(bin_rows),
                'correct':  bc,
                'accuracy': round(bc / len(bin_rows), 3),
                'mean_cd':  round(sum(r['contradiction_debt'] for r in bin_rows) / len(bin_rows), 4),
            })

    # Term-by-term
    term_stats = defaultdict(lambda: {'correct':0,'wrong':0,'n':0})
    for r in rows:
        t = r['term'] or 'unknown'
        term_stats[t]['n'] += 1
        if r['prediction_correct'] == 1: term_stats[t]['correct'] += 1
        else: term_stats[t]['wrong'] += 1
    term_results = {
        str(t): {
            'n': s['n'],
            'correct': s['correct'],
            'accuracy': round(s['correct'] / s['n'], 3) if s['n'] else 0,
        }
        for t, s in sorted(term_stats.items())
    }

    # CT frequency analysis
    ct_counts = defaultdict(lambda: {'total':0,'correct':0,'wrong':0})
    for r in rows:
        cts = json.loads(r['active_contradictions'] or '[]')
        for ct in cts:
            ct_counts[ct]['total'] += 1
            if r['prediction_correct'] == 1: ct_counts[ct]['correct'] += 1
            elif r['prediction_correct'] == 0: ct_counts[ct]['wrong'] += 1

    ct_stats = {
        ct: {
            'n':        s['total'],
            'correct':  s['correct'],
            'accuracy': round(s['correct'] / s['total'], 3) if s['total'] else 0,
        }
        for ct, s in sorted(ct_counts.items(), key=lambda x: -x[1]['total'])
    }

    # Confidence calibration
    conf_stats = defaultdict(lambda: {'n':0,'correct':0})
    for r in rows:
        c = r['outcome_confidence'] or 'medium'
        conf_stats[c]['n'] += 1
        if r['prediction_correct'] == 1: conf_stats[c]['correct'] += 1
    conf_results = {
        c: {
            'n': s['n'],
            'accuracy': round(s['correct'] / s['n'], 3) if s['n'] else 0,
        }
        for c, s in conf_stats.items()
    }

    # Worst misses (high-confidence wrong predictions)
    misses = [
        {
            'docket':    r['docket'],
            'case_name': r['case_name'],
            'predicted': r['predicted_outcome'],
            'actual':    r['actual_outcome'],
            'cd':        r['contradiction_debt'],
            'confidence': r['outcome_confidence'],
        }
        for r in rows
        if r['prediction_correct'] == 0
        and r['outcome_confidence'] in ('high', 'medium')
    ]
    misses.sort(key=lambda x: -(x['cd'] or 0))

    # Cases (for export)
    cases_export = [
        {
            'docket':    r['docket'],
            'case_name': r['case_name'],
            'term':      r['term'],
            'predicted': r['predicted_outcome'],
            'actual':    r['actual_outcome'],
            'correct':   bool(r['prediction_correct']),
            'cd':        r['contradiction_debt'],
            'confidence': r['outcome_confidence'],
            'adv_strength': r['adversarial_strength'],
            'narrative': (r['structural_narrative'] or '')[:300],
        }
        for r in rows
    ]

    return {
        'generated_at':   datetime.utcnow().isoformat(),
        'terms':          terms,
        'n_total':        n_total,
        'n_correct':      n_correct,
        'n_wrong':        n_wrong,
        'accuracy':       round(accuracy, 4),
        'auc':            round(auc, 4) if auc else None,
        'mean_cd':        round(sum(r['contradiction_debt'] for r in rows if r['contradiction_debt']) / n_total, 4),
        'calibration':    calibration,
        'by_term':        term_results,
        'by_ct':          ct_stats,
        'by_confidence':  conf_results,
        'worst_misses':   misses[:10],
        'cases':          cases_export,
        'all_cases':      get_all_cases(conn),
    }


def print_report(results):
    if not results:
        return

    print(f"\n{'='*60}")
    print(f"SOoL SCOTUS Backtest Report")
    print(f"Generated: {results['generated_at']}")
    print(f"{'='*60}")
    print(f"\nOVERALL PERFORMANCE")
    print(f"  Cases annotated:      {results['n_total']}")
    print(f"  Correct predictions:  {results['n_correct']} ({results['accuracy']*100:.1f}%)")
    print(f"  Wrong predictions:    {results['n_wrong']}")
    if results.get('auc'):
        print(f"  AUC (CD → outcome):   {results['auc']:.4f}")

    print(f"\nCD CALIBRATION")
    for b in results.get('calibration', []):
        bar = '█' * int(b['accuracy'] * 20)
        print(f"  CD {b['range']:12s} n={b['n']:4d}  acc={b['accuracy']:.3f}  {bar}")

    print(f"\nBY TERM")
    for term, s in results.get('by_term', {}).items():
        print(f"  {term}: {s['correct']}/{s['n']} ({s['accuracy']*100:.0f}%)")

    print(f"\nBY CONFIDENCE LEVEL")
    for conf, s in results.get('by_confidence', {}).items():
        print(f"  {conf:10s}: {s['accuracy']*100:.0f}% accuracy (n={s['n']})")

    print(f"\nCT ACCURACY CONTRIBUTION (top 8)")
    for ct, s in list(results.get('by_ct', {}).items())[:8]:
        print(f"  {ct:5s}: {s['accuracy']*100:.0f}% accuracy when active (n={s['n']})")

    if results.get('worst_misses'):
        print(f"\nNOTABLE MISSES")
        for m in results['worst_misses'][:5]:
            print(f"  {m['docket']} — predicted {m['predicted']}, actual {m['actual']}, CD={m['cd']:.3f}")

    print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SOoL SCOTUS Backtester')
    parser.add_argument('--db',     default='scotus_backtest.db')
    parser.add_argument('--terms',  nargs='+', type=int)
    parser.add_argument('--export', action='store_true',
                        help='Export JSON for query tool')
    parser.add_argument('--out',    default='scotus_backtest_results.json')
    args = parser.parse_args()

    conn    = get_db(args.db)
    results = run_backtest(conn, terms=args.terms)
    print_report(results)

    if args.export and results:
        with open(args.out, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Exported to {args.out}")
