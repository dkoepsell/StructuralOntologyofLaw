#!/usr/bin/env python3
"""
SOoL v2 corpus audit — five tests of whether dashboard findings survive.

Run from the root of the sool_v2_20260806 export:
    python3 sool_v2_audit.py [path_to_export_root]

Tests
  1  Covariate-leakage diagnostic. The annotator prompt (annotate_pipeline.py
     l.756) discloses COURT, DATE and DOMAIN. If the model is scoring from
     priors rather than text, covariate effect should GROW as text SHRINKS.
  2  Contradiction co-occurrence against a degree-preserving (curveball) null
     that fixes both per-case counts and per-type marginals — run on all 13
     types and again on the 9 non-rule-forced types.
  3  P4 (N7/N8 asymmetry) across the three prompt-control arms, under both
     failure definitions, with exact binomial tests.
  4  SCOTUS backtest against external ground truth (petitioner_won).
  5  Whether Contradiction Debt carries information beyond a raw count.
"""
import sys, json, sqlite3, warnings
import numpy as np, pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
np.random.seed(7)

ROOT = (sys.argv[1].rstrip("/") + "/") if len(sys.argv) > 1 else "./"
DB, META = ROOT + "databases/", ROOT + "databases/"

TYPES = ["CF", "AI", "JC", "RC3", "PC", "TC", "FM", "NI", "RF", "RCL", "CC", "SE", "RPF"]
FORCED = {"RC3", "NI", "JC", "CC"}                      # RULES 2,3,4,6
UNFORCED = [t for t in TYPES if t not in FORCED]
VALID = ["protection_denied", "protection_granted", "partial",
         "remanded", "dismissed", "moot"]


def parse(s):
    try:
        return set(json.loads(s)) if s else set()
    except Exception:
        return set()


def cramers_v(tab):
    chi2 = stats.chi2_contingency(tab)[0]
    n = tab.values.sum()
    return np.sqrt(chi2 / (n * (min(tab.shape) - 1)))


def eta_sq(groups):
    F, _ = stats.f_oneway(*groups)
    k, n = len(groups), sum(len(g) for g in groups)
    return (F * (k - 1)) / (F * (k - 1) + (n - k))


def curveball(M, iters):
    """Randomise a binary matrix preserving both row and column sums."""
    n = M.shape[0]
    rows = [set(np.where(M[i])[0]) for i in range(n)]
    for _ in range(iters):
        i, j = np.random.randint(0, n, 2)
        if i == j:
            continue
        A, B = rows[i], rows[j]
        inter = A & B
        da, db = list(A - inter), list(B - inter)
        if not da or not db:
            continue
        pool = da + db
        np.random.shuffle(pool)
        rows[i] = inter | set(pool[:len(da)])
        rows[j] = inter | set(pool[len(da):])
    out = np.zeros_like(M)
    for i, r in enumerate(rows):
        out[i, list(r)] = 1
    return out


def cooc_z(M, labels, reps=300, mix=6000):
    obs = M.T @ M
    null = np.zeros((reps, M.shape[1], M.shape[1]))
    Mc = M.copy()
    for r in range(reps):
        Mc = curveball(Mc, mix)
        null[r] = Mc.T @ Mc
    z = (obs - null.mean(0)) / (null.std(0) + 1e-9)
    out = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            out.append((f"{labels[i]}+{labels[j]}", obs[i, j], null.mean(0)[i, j], z[i, j]))
    return sorted(out, key=lambda x: -abs(x[3]))


def load():
    a = pd.read_sql("select * from annotations", sqlite3.connect(DB + "sool_annotations.db"))
    m = sqlite3.connect(META + "sool_cases_meta.db")
    # word_count is only populated for opinion_type '010combined'; every other
    # type is stored as 0, so a zero is "not measured", not "no text".
    wc = pd.read_sql("select case_id, max(word_count) wc from opinions_meta "
                     "where opinion_type='010combined' group by case_id", m)
    cs = pd.read_sql("select id, court_id, date_filed from cases", m)
    a["cid"] = pd.to_numeric(a.case_id, errors="coerce")
    a = a.merge(wc, left_on="cid", right_on="case_id", how="left", suffixes=("", "_w"))
    a = a.merge(cs, left_on="cid", right_on="id", how="left")
    a["year"] = pd.to_datetime(a.date_filed, errors="coerce").dt.year
    d = a[a.chain_outcome.isin(VALID)].copy()
    d["cts"] = d.active_contradictions.map(parse)
    for t in TYPES:
        d[t] = d.cts.map(lambda s, t=t: int(t in s))
    d["nct"] = d[TYPES].sum(1)
    d["denied"] = (d.chain_outcome == "protection_denied").astype(int)
    for n in range(1, 9):
        d[f"n{n}f"] = d[f"node{n}_closure"].isin(["failed", "partial"]).astype(int)
    return d


def test1_leakage(d):
    print("=" * 70)
    print("1  COVARIATE LEAKAGE — effect size by opinion-length tertile")
    print("   (declining with length => prior-driven; rising => text-driven)")
    print("=" * 70)
    s = d[d.wc > 0].copy()
    s["bin"] = pd.qcut(s.wc, 3, labels=["short", "mid", "long"])
    print(f"   n = {len(s)} with measured opinion text")
    for cov, lab in [("court_id", "COURT"), ("domain_name", "DOMAIN"), ("decade", "DECADE")]:
        print(f"\n   {lab}")
        for ov in ["denied", "nct", "contradiction_debt"]:
            cells = []
            for b in ["short", "mid", "long"]:
                sub = s[s.bin == b]
                g = (sub.year // 10 * 10) if cov == "decade" else sub[cov]
                ok = g.notna()
                sub, g = sub[ok], g[ok]
                keep = g.value_counts()
                keep = keep[keep >= 20].index
                sub, g = sub[g.isin(keep)], g[g.isin(keep)]
                if ov == "denied":
                    cells.append(f"{b}: V={cramers_v(pd.crosstab(g, sub.denied)):.3f}")
                else:
                    cells.append(f"{b}: eta2={eta_sq([sub[ov][g == k].values for k in keep]):.4f}")
            print(f"     {ov:<20} " + "  ".join(cells))


def test2_cooc(d):
    print("\n" + "=" * 70)
    print("2  CO-OCCURRENCE vs DEGREE-PRESERVING NULL")
    print("=" * 70)
    for labels, tag in [(TYPES, "all 13 types"), (UNFORCED, "9 non-rule-forced types")]:
        M = d[labels].values.astype(int)
        res = cooc_z(M, labels)
        sig = [r for r in res if abs(r[3]) > 3]
        print(f"\n   {tag}: {len(sig)} of {len(res)} pairs at |z|>3")
        for r in res[:8]:
            flag = "*" if abs(r[3]) > 3 else " "
            print(f"    {flag} {r[0]:<10} obs={r[1]:>5}  exp={r[2]:>7.1f}  z={r[3]:>6.1f}")


def test3_p4():
    print("\n" + "=" * 70)
    print("3  P4 PROMPT CONTROL — N7-only vs N8-only failure")
    print("=" * 70)
    p4 = pd.read_sql("select * from p4arm", sqlite3.connect(DB + "p4_control.db"))
    for tag, fail in [("failed only", ["failed"]), ("failed+partial", ["failed", "partial"])]:
        print(f"\n   {tag}")
        for arm, g in p4.groupby("arm"):
            g = g[g.node7.notna() & g.node8.notna()]
            n7, n8 = g.node7.isin(fail), g.node8.isin(fail)
            a, b = int((n7 & ~n8).sum()), int((~n7 & n8).sum())
            p = stats.binomtest(a, a + b, 0.5).pvalue if a + b else np.nan
            print(f"     {arm:<10} n={len(g):>4}  N7-only={a:>3}  N8-only={b:>3}  p={p:.2e}")


def test4_scotus():
    print("\n" + "=" * 70)
    print("4  SCOTUS BACKTEST vs EXTERNAL GROUND TRUTH")
    print("=" * 70)
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
        from sklearn.metrics import roc_auc_score, accuracy_score
    except ImportError:
        print("   scikit-learn not installed; skipping")
        return
    sc = sqlite3.connect(DB + "scotus_backtest.db")
    c = pd.read_sql("select docket, term, petitioner_won from scotus_cases", sc)
    cols = ", ".join(f"node{n}_closure" for n in range(1, 9))
    sa = pd.read_sql(f"select docket, contradiction_debt, active_contradictions, {cols} "
                     "from scotus_annotations", sc)
    m = sa.merge(c, on="docket").dropna(subset=["petitioner_won"]).drop_duplicates("docket")
    m["cts"] = m.active_contradictions.map(parse)
    for t in TYPES:
        m[t] = m.cts.map(lambda s, t=t: int(t in s))
    for n in range(1, 9):
        m[f"n{n}f"] = m[f"node{n}_closure"].isin(["failed", "partial"]).astype(int)
    feat = [f"n{n}f" for n in range(1, 9)] + TYPES + ["contradiction_debt"]
    X, y = m[feat].fillna(0).values, m.petitioner_won.values.astype(int)
    cv = StratifiedKFold(5, shuffle=True, random_state=0)
    pr = cross_val_predict(LogisticRegression(max_iter=2000, C=0.5), X, y, cv=cv,
                           method="predict_proba")[:, 1]
    auc = roc_auc_score(y, pr)
    perm = np.mean([roc_auc_score(np.random.permutation(y), pr) >= auc for _ in range(2000)])
    print(f"   n={len(m)}  base rate={y.mean():.3f}")
    print(f"   structural model: AUC={auc:.3f}  acc={accuracy_score(y, pr > .5):.3f}  "
          f"(base acc={max(y.mean(), 1 - y.mean()):.3f})  perm p={perm:.4f}")
    print(f"   N7 marked failed/partial in {m.n7f.sum()} of {len(m)} cases "
          f"-> {'no usable variance' if m.n7f.mean() > .95 else 'has variance'}")


def test5_cd(d):
    print("\n" + "=" * 70)
    print("5  DOES CD CARRY ANYTHING BEYOND A COUNT?")
    print("=" * 70)
    r = stats.pearsonr(d.contradiction_debt, d.nct)[0]
    print(f"   corr(CD, n contradictions) = {r:.4f}   R^2 = {r**2:.4f}")
    print(f"   => {100 * (1 - r**2):.1f}% of CD variance is independent of the count")


if __name__ == "__main__":
    d = load()
    print(f"\nloaded {len(d)} analysable rows\n")
    test1_leakage(d)
    test2_cooc(d)
    test3_p4()
    test4_scotus()
    test5_cd(d)
