"""
domain_analysis.py — SOoL Structural Signature by Legal Domain
==============================================================
SEAL Lab, Texas A&M University

Analyzes whether SOoL contradiction type firing patterns and CD scores
are domain-specific or domain-neutral across SCOTUS oral argument corpus.

Usage:
    python3 domain_analysis.py
    python3 domain_analysis.py --db scotus_backtest.db --out domain_report.json
"""

import argparse, json, re, sqlite3
from collections import defaultdict

# ── DOMAIN CLASSIFIER ─────────────────────────────────────────────────────────
# Maps free-text legal_domain field to canonical categories

DOMAIN_PATTERNS = [
    ("First Amendment",     ["first amendment","free speech","free exercise","establishment clause",
                             "compelled speech","overbreadth","viewpoint","press clause","assembly"]),
    ("Fourth Amendment",    ["fourth amendment","search and seizure","warrant","probable cause",
                             "unreasonable search","exclusionary"]),
    ("Fifth Amendment",     ["fifth amendment","takings","just compensation","self-incrimination",
                             "double jeopardy","due process"]),
    ("Sixth Amendment",     ["sixth amendment","right to counsel","confrontation","speedy trial",
                             "ineffective assistance","jury trial"]),
    ("Eighth Amendment",    ["eighth amendment","cruel and unusual","death penalty","capital",
                             "method of execution","proportionality"]),
    ("Criminal Procedure",  ["criminal procedure","habeas corpus","aedpa","sentencing","acca",
                             "armed career","supervised release","plea","mens rea","restitution"]),
    ("Immigration",         ["immigration","deportation","asylum","removal","daca","ina",
                             "visa","border","alien","noncitizen"]),
    ("Administrative Law",  ["administrative","chevron","deference","notice and comment",
                             "arbitrary and capricious","agency","rulemaking","apa","cms","epa","fcc"]),
    ("Antitrust",           ["antitrust","sherman act","section 1","section 2","monopoly",
                             "price fixing","market power","restraint of trade"]),
    ("Bankruptcy",          ["bankruptcy","chapter 11","debtor","creditor","automatic stay",
                             "discharge","preference","trustee"]),
    ("Civil Rights",        ["civil rights","section 1983","equal protection","title vii",
                             "discrimination","§ 1983","qualified immunity","42 u.s.c"]),
    ("Sovereign Immunity",  ["sovereign immunity","eleventh amendment","governmental immunity",
                             "sue and be sued","arm of the state","ftca"]),
    ("Patent / IP",         ["patent","copyright","trademark","lanham","intellectual property",
                             "infringement","licensee","on-sale bar"]),
    ("Arbitration",         ["arbitration","federal arbitration act","faa","arbitral","arbitrator",
                             "class arbitration"]),
    ("Tax",                 ["tax","irs","internal revenue","tax court","deduction","income tax",
                             "treasury","excise","tariff"]),
    ("Indian Law",          ["indian","tribal","tribe","treaty rights","reservation","sovereignty",
                             "indian country","native american"]),
    ("Maritime / Admiralty",["maritime","admiralty","jones act","unseaworthiness","seaman",
                             "outer continental shelf"]),
    ("Environmental",       ["environmental","clean air","clean water","endangered species",
                             "epa","superfund","cercla","anilca"]),
    ("Election / Voting",   ["election","voting rights","gerrymandering","redistricting",
                             "partisan","racial","reapportionment","vra"]),
    ("Federal Jurisdiction",["standing","mootness","ripeness","justiciability","federal courts",
                             "removal jurisdiction","class action","rule 23","cafa"]),
    ("Contract / Commerce", ["contract","commerce clause","dormant commerce","preemption",
                             "federal preemption","erisa","state law"]),
    ("Property",            ["property","takings clause","regulatory taking","land use",
                             "eminent domain","zoning"]),
    ("Family / Immigration",["family","custody","adoption","child","marriage","same-sex"]),
    ("Labor / Employment",  ["labor","employment","nlra","flsa","adea","fmla","title vii",
                             "workplace","union","collective bargaining"]),
    ("Securities",          ["securities","sec","exchange act","rule 10b","fraud","insider trading",
                             "class action securities","false claims"]),
]

def classify_domain(text: str) -> str:
    if not text:
        return "Unknown"
    t = text.lower()
    for domain, patterns in DOMAIN_PATTERNS:
        if any(p in t for p in patterns):
            return domain
    return "Other"

# ── MAIN ANALYSIS ──────────────────────────────────────────────────────────────

def run(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            a.node1_justification,
            a.node1_closure, a.node2_closure, a.node3_closure,
            a.node4_closure, a.node5_closure, a.node6_closure,
            a.node7_closure, a.node8_closure,
            a.active_contradictions,
            a.contradiction_debt,
            a.predicted_outcome,
            a.outcome_confidence,
            a.adversarial_strength,
            c.outcome,
            c.term,
            c.docket
        FROM scotus_annotations a
        JOIN scotus_cases c ON c.id = a.case_id
        WHERE a.node1_justification IS NOT NULL
        AND LENGTH(a.node1_justification) > 10
    """).fetchall()

    # Group by domain
    by_domain = defaultdict(list)
    for r in rows:
        # Use node1 justification as domain proxy (most domain-specific text)
        # Also check structural_narrative if available
        domain_text = (r['node1_justification'] or '')
        domain = classify_domain(domain_text)
        by_domain[domain].append(dict(r))

    # Compute per-domain stats
    results = {}
    all_cts = ["CF","AINF","JC","RC3","PC","TC","FM","NI","RF","RCL","CC","SE","RPF"]

    for domain, cases in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        if len(cases) < 5:
            continue

        cds = [c['contradiction_debt'] for c in cases if c['contradiction_debt']]
        avg_cd = sum(cds) / len(cds) if cds else 0
        max_cd = max(cds) if cds else 0
        min_cd = min(cds) if cds else 0

        # CT firing rates
        ct_counts = defaultdict(int)
        for c in cases:
            cts = []
            try:
                cts = json.loads(c['active_contradictions'] or '[]')
            except:
                pass
            for ct in cts:
                ct_counts[ct] += 1

        ct_rates = {ct: ct_counts[ct] / len(cases) for ct in all_cts if ct_counts[ct] > 0}
        ct_rates = dict(sorted(ct_rates.items(), key=lambda x: -x[1]))

        # Node closure rates (partial + failed = stress)
        node_stress = {}
        for n in range(1, 9):
            key = f'node{n}_closure'
            stressed = sum(1 for c in cases if c.get(key) in ('partial','failed'))
            node_stress[f'N{n}'] = stressed / len(cases)

        # N7 failure rate (pivotal node)
        n7_partial = sum(1 for c in cases
                        if cases[0].get('node7_closure') in ('partial','failed'))

        # Confidence distribution
        high_conf = sum(1 for c in cases if c['outcome_confidence'] == 'high')
        med_conf  = sum(1 for c in cases if c['outcome_confidence'] == 'medium')

        # Adversarial strength
        adv = [c['adversarial_strength'] for c in cases
               if c['adversarial_strength'] is not None]
        avg_adv = sum(adv) / len(adv) if adv else 0

        results[domain] = {
            'n':            len(cases),
            'avg_cd':       round(avg_cd, 4),
            'min_cd':       round(min_cd, 4),
            'max_cd':       round(max_cd, 4),
            'ct_rates':     {k: round(v, 3) for k, v in ct_rates.items()},
            'node_stress':  {k: round(v, 3) for k, v in node_stress.items()},
            'high_conf_pct': round(high_conf / len(cases), 3),
            'avg_adversarial': round(avg_adv, 3),
            'top_ct':       list(ct_rates.keys())[:3] if ct_rates else [],
        }

    return results

def print_report(results: dict):
    print("\n" + "="*72)
    print("SOoL STRUCTURAL SIGNATURE BY LEGAL DOMAIN")
    print("SCOTUS Oral Argument Corpus")
    print("="*72)

    # Sort by avg CD descending
    sorted_domains = sorted(results.items(), key=lambda x: -x[1]['avg_cd'])

    print(f"\n{'Domain':30s} {'N':>5} {'AvgCD':>7} {'MaxCD':>7} {'TopCTs':30s} {'HiConf':>7}")
    print("-"*72)
    for domain, d in sorted_domains:
        top = '+'.join(d['top_ct'][:3])
        print(f"{domain:30s} {d['n']:>5} {d['avg_cd']:>7.3f} {d['max_cd']:>7.3f} "
              f"{top:30s} {d['high_conf_pct']:>6.0%}")

    print("\n\n── DETAILED PROFILES (top 10 by n) ──")
    top10 = sorted(results.items(), key=lambda x: -x[1]['n'])[:10]
    for domain, d in top10:
        print(f"\n{domain.upper()} (n={d['n']})")
        print(f"  CD:           avg={d['avg_cd']:.3f}  min={d['min_cd']:.3f}  "
              f"max={d['max_cd']:.3f}")
        print(f"  CT firing:    " +
              "  ".join(f"{ct}={rate:.0%}" for ct, rate in list(d['ct_rates'].items())[:5]))
        print(f"  Node stress:  " +
              "  ".join(f"N{i}={d['node_stress'].get(f'N{i}',0):.0%}"
                        for i in range(1,9)))
        print(f"  Avg adversarial strength: {d['avg_adversarial']:.3f}")
        print(f"  High confidence: {d['high_conf_pct']:.0%}")

    # Cross-domain variance analysis
    print("\n\n── CD VARIANCE ACROSS DOMAINS ──")
    cds = [(d, v['avg_cd']) for d, v in results.items()]
    cds.sort(key=lambda x: -x[1])
    highest = cds[0]
    lowest  = cds[-1]
    print(f"  Highest CD domain: {highest[0]} ({highest[1]:.3f})")
    print(f"  Lowest CD domain:  {lowest[0]} ({lowest[1]:.3f})")
    print(f"  CD range:          {highest[1]-lowest[1]:.3f}")

    all_cds = [v['avg_cd'] for v in results.values()]
    mean_cd = sum(all_cds) / len(all_cds)
    variance = sum((x - mean_cd)**2 for x in all_cds) / len(all_cds)
    print(f"  Cross-domain CD variance: {variance:.6f}")
    print(f"  Std dev: {variance**0.5:.4f}")

    if variance**0.5 < 0.02:
        print("\n  → CD is DOMAIN-NEUTRAL: structural stress is consistent across legal domains.")
        print("    This supports SOoL's claim that contradiction debt measures a")
        print("    domain-independent structural property of legal chains.")
    else:
        print("\n  → CD is DOMAIN-SPECIFIC: structural stress varies by legal domain.")

    # CT pattern analysis
    print("\n\n── CT DOMAIN SPECIFICITY ──")
    # Find CTs that are unusually high or low in specific domains
    all_domains_ct = defaultdict(list)
    for domain, d in results.items():
        for ct, rate in d['ct_rates'].items():
            all_domains_ct[ct].append((domain, rate))

    for ct in ["NI","RF","JC","CF","AINF","TC","RPF","RCL","CC","SE"]:
        domain_rates = all_domains_ct.get(ct, [])
        if len(domain_rates) < 3:
            continue
        rates = [r for _, r in domain_rates]
        mean_r = sum(rates) / len(rates)
        max_domain = max(domain_rates, key=lambda x: x[1])
        min_domain = min(domain_rates, key=lambda x: x[1])
        spread = max_domain[1] - min_domain[1]
        if spread > 0.25:
            print(f"  {ct}: spread={spread:.2f}  "
                  f"highest={max_domain[0]} ({max_domain[1]:.0%})  "
                  f"lowest={min_domain[0]} ({min_domain[1]:.0%})")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',  default='scotus_backtest.db')
    parser.add_argument('--out', default=None)
    args = parser.parse_args()

    results = run(args.db)
    print_report(results)

    if args.out:
        with open(args.out, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nExported to {args.out}")
