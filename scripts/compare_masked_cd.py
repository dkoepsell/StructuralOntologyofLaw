#!/usr/bin/env python3
"""
compare_masked_cd.py
====================
Compares CD distributions between masked (blind) and unmasked annotations
for the same set of cases.

Run after:
    python3 annotate_pipeline.py --mask-disposition --domain 1 --limit 200

The masked annotations are stored in a separate table (annotations_masked)
in the same DB. This script computes:

  1. Mean CD difference (masked vs unmasked) by outcome
  2. AUC for both masked and unmasked
  3. Chain_outcome agreement rate between the two passes
  4. Per-CT firing rate differences (which CTs shift under masking)

Interpretation:
  - If masked/unmasked CD distributions are similar → structural signal
    is in the reasoning, not the outcome language
  - If masked CD is lower for protection_denied cases → annotator was
    reading the disposition and inflating CD accordingly (leakage)
  - If chain_outcome agreement is <90% → masking substantially changes
    structural diagnosis (outcome is driving annotation)

Usage:
    python3 compare_masked_cd.py
    python3 compare_masked_cd.py --db ./sool_annotations.db --domain 1
"""

import sqlite3
import json
import argparse
from collections import defaultdict


def auc(pairs):
    """Compute AUC from (cd, label) pairs where label=1 is protection_denied."""
    if not pairs:
        return None
    sorted_pairs = sorted(pairs, key=lambda x: -x[0])
    n_pos = sum(1 for _, l in pairs if l == 1)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    tp = fp = auc_sum = 0
    for cd, label in sorted_pairs:
        if label == 1:
            tp += 1
        else:
            auc_sum += tp
            fp += 1
    return round(auc_sum / (n_pos * n_neg), 4)


def run(db_path: str, domain: int = None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check if masked table exists
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]

    if 'annotations_masked' not in tables:
        print("No masked annotations found.")
        print("Run: python3 annotate_pipeline.py --mask-disposition --domain 1 --limit 200")
        return

    # Load unmasked annotations
    q_unmasked = """
        SELECT a.case_id, a.chain_outcome, a.contradiction_debt,
               a.active_contradictions, a.domain_id
        FROM annotations a
        WHERE a.chain_outcome IN ('protection_granted','protection_denied')
    """
    if domain:
        q_unmasked += f" AND a.domain_id = {domain}"

    unmasked = {str(r['case_id']).strip("'\""): dict(r) for r in conn.execute(q_unmasked).fetchall()}

    # Load masked annotations for same cases
    q_masked = """
        SELECT m.case_id, m.chain_outcome, m.contradiction_debt,
               m.active_contradictions, m.domain_id
        FROM annotations_masked m
        WHERE m.chain_outcome IN ('protection_granted','protection_denied')
        AND CAST(m.case_id AS TEXT) IN ({})
    """.format(",".join("'" + str(k) + "'" for k in unmasked.keys()) if unmasked else "'0'")

    masked = {str(r['case_id']).strip("'\""): dict(r) for r in conn.execute(q_masked).fetchall()}

    # Only compare cases that have both
    common = set(unmasked.keys()) & set(masked.keys())
    print(f"\n{'='*60}")
    print(f"SOoL Masked vs Unmasked CD Comparison")
    if domain:
        print(f"Domain: {domain}")
    print(f"Cases with both annotations: {len(common)}")
    print(f"{'='*60}\n")

    if not common:
        print("No overlapping cases to compare.")
        return

    # ── 1. CD comparison by outcome ──────────────────────────────────────────
    print("── CD by outcome ─────────────────────────────────────────────")
    for outcome in ['protection_denied', 'protection_granted']:
        u_cds = [unmasked[c]['contradiction_debt'] for c in common
                 if unmasked[c]['chain_outcome'] == outcome
                 and unmasked[c]['contradiction_debt'] is not None]
        m_cds = [masked[c]['contradiction_debt'] for c in common
                 if masked[c]['chain_outcome'] == outcome
                 and masked[c]['contradiction_debt'] is not None]

        u_mean = sum(u_cds)/len(u_cds) if u_cds else 0
        m_mean = sum(m_cds)/len(m_cds) if m_cds else 0
        diff   = m_mean - u_mean

        arrow = "↑" if diff > 0.005 else "↓" if diff < -0.005 else "≈"
        print(f"  {outcome}:")
        print(f"    Unmasked:  avg CD={u_mean:.4f}  n={len(u_cds)}")
        print(f"    Masked:    avg CD={m_mean:.4f}  n={len(m_cds)}")
        print(f"    Δ CD:      {diff:+.4f}  {arrow}")

    # ── 2. AUC comparison ────────────────────────────────────────────────────
    print("\n── AUC (CD → protection_denied) ──────────────────────────────")
    u_pairs = [(unmasked[c]['contradiction_debt'], 1 if unmasked[c]['chain_outcome']=='protection_denied' else 0)
               for c in common if unmasked[c]['contradiction_debt'] is not None]
    m_pairs = [(masked[c]['contradiction_debt'], 1 if masked[c]['chain_outcome']=='protection_denied' else 0)
               for c in common if masked[c]['contradiction_debt'] is not None]

    u_auc = auc(u_pairs)
    m_auc = auc(m_pairs)
    print(f"  Unmasked AUC: {u_auc}")
    print(f"  Masked AUC:   {m_auc}")
    if u_auc and m_auc:
        delta = m_auc - u_auc
        print(f"  Δ AUC:        {delta:+.4f}")
        if abs(delta) < 0.01:
            print("  → AUC stable under masking — structural signal is robust")
        elif delta < -0.05:
            print("  → AUC drops substantially under masking — outcome leakage detected")
        else:
            print("  → AUC shifts — moderate masking effect")

    # ── 3. Chain_outcome agreement ───────────────────────────────────────────
    print("\n── Chain_outcome agreement ───────────────────────────────────")
    agree = sum(1 for c in common
                if unmasked[c]['chain_outcome'] == masked[c]['chain_outcome'])
    pct = agree / len(common) * 100
    print(f"  Agreement: {agree}/{len(common)} ({pct:.1f}%)")

    # Show disagreements
    disagree_cases = [c for c in common
                      if unmasked[c]['chain_outcome'] != masked[c]['chain_outcome']]
    if disagree_cases:
        print(f"\n  Disagreements ({len(disagree_cases)} cases):")
        for cid in disagree_cases[:10]:
            u = unmasked[cid]
            m = masked[cid]
            print(f"    case_id={cid}: unmasked={u['chain_outcome']} "
                  f"(CD={u['contradiction_debt']:.3f}) → "
                  f"masked={m['chain_outcome']} (CD={m['contradiction_debt']:.3f})")

    # ── 4. CT firing rate shifts ─────────────────────────────────────────────
    print("\n── CT firing rate shifts (masked − unmasked) ─────────────────")
    u_ct = defaultdict(int)
    m_ct = defaultdict(int)
    n = len(common)

    for cid in common:
        for src, counter in [(unmasked[cid], u_ct), (masked[cid], m_ct)]:
            try:
                cts = json.loads(src['active_contradictions'] or '[]')
                for ct in cts:
                    counter[ct] += 1
            except:
                pass

    all_cts = sorted(set(u_ct.keys()) | set(m_ct.keys()))
    significant = []
    for ct in all_cts:
        u_rate = u_ct[ct] / n
        m_rate = m_ct[ct] / n
        delta  = m_rate - u_rate
        if abs(delta) >= 0.03:
            significant.append((ct, u_rate, m_rate, delta))

    if significant:
        significant.sort(key=lambda x: abs(x[3]), reverse=True)
        print(f"  {'CT':<6} {'Unmasked':>10} {'Masked':>10} {'Δ':>8}")
        print(f"  {'-'*36}")
        for ct, u, m, d in significant:
            arrow = "↑" if d > 0 else "↓"
            print(f"  {ct:<6} {u:>9.1%} {m:>9.1%} {d:>+7.1%} {arrow}")
    else:
        print("  No CT firing rates shifted by ≥3% — annotation is stable under masking")

    # ── 5. Interpretation ────────────────────────────────────────────────────
    print("\n── Interpretation ────────────────────────────────────────────")
    if pct >= 90 and (u_auc and m_auc and abs(m_auc - u_auc) < 0.02):
        print("  ROBUST: High chain_outcome agreement and stable AUC.")
        print("  The structural signal is in the reasoning, not the disposition language.")
        print("  SOoL annotation is largely outcome-independent under masking.")
    elif pct < 80:
        print("  LEAKAGE DETECTED: Low chain_outcome agreement under masking.")
        print("  The annotator is substantially influenced by disposition language.")
        print("  Recommend running full masked re-annotation for valid external AUC.")
    else:
        print("  PARTIAL LEAKAGE: Moderate outcome agreement under masking.")
        print("  Some disposition signal is leaking into structural annotation.")
        print("  Report masked AUC alongside unmasked with this caveat disclosed.")

    conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='./sool_annotations.db')
    parser.add_argument('--domain', type=int, default=None)
    args = parser.parse_args()
    run(args.db, args.domain)
