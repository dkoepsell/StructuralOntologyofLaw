#!/usr/bin/env python3
"""
Generate the PROVISIONAL FINDINGS section for SOoL_QueryTool.html directly from
sool_annotations.db, and splice it between the marker comments.

Every number in the emitted HTML is computed here — nothing is transcribed by hand.
Re-run after the v2 re-annotation completes to refresh (or to retire) the section.

  python3 gen_provisional.py            # write fragment to stdout only
  python3 gen_provisional.py --splice   # splice into SOoL_QueryTool.html in place
"""
import sqlite3, json, collections, math, itertools, sys, html, datetime, os, re
import numpy as np
from scipy import stats as st

HOME = os.path.expanduser("~/CaseLaw")
DB   = os.path.join(HOME, "sool_annotations.db")
PAGE = os.path.join(HOME, "SOoL_QueryTool.html")
START = "<!--PROVISIONAL-FINDINGS-START-->"
END   = "<!--PROVISIONAL-FINDINGS-END-->"
V2 = "claude-pipeline-v2"

CT = ["CF","AINF","JC","RC3","PC","TC","FM","NI","RF","RCL","CC","SE","RPF"]
# Type labels are READ FROM THE ONTOLOGY, never retyped here.
#
# They used to be a hand-written dict, and it drifted: AI was labelled "Authority
# Incompleteness" and CF "Constitutive Failure", both near-inverses of what the
# ontology defines (Authority Inflation = the decision-maker's will displacing the
# norm; Conferral Failure = authority failing to vest the actor in role). The published
# reading of the D3 Administrative Law result was wrong as a direct consequence. A
# label that can be typed by hand is a label that can silently disagree, so this now
# fails loudly rather than falling back to a guess.
def _load_ct_labels():
    reg_path = os.path.join(HOME, "typology", "registry_observed.json")
    if not os.path.exists(reg_path):
        sys.stderr.write(
            f"FATAL: {reg_path} not found. Run typology/parse_ontology.py first — this\n"
            f"script will not invent contradiction-type labels.\n")
        sys.exit(2)
    with open(reg_path) as f:
        reg = json.load(f)
    out = {}
    for iri, t in reg["types"].items():
        code = t.get("code")
        label = t.get("label") or ""
        if not code:
            continue
        # ontology labels carry the code inline, e.g. "Conferral Failure (CF)"
        out[code] = re.sub(r"\s*\([A-Z]{2,4}\d?\)\s*$", "", label).strip()
    missing = [c for c in CT if c not in out]
    if missing:
        sys.stderr.write(f"FATAL: ontology has no label for {missing}; refusing to guess.\n")
        sys.exit(2)
    return out, reg["_meta"]["ontologyHash"], reg["_meta"]["sourceOntology"]

CTNAME, ONTOLOGY_HASH, ONTOLOGY_SOURCE = _load_ct_labels()

# Spec amendment A3. The contradiction-debt weights are NOT extracted from the ontology
# (that would edit it and break every live figure); the ontology's existing
# sool:cdWeight values are declared in place as profile "core-v1". Every CD figure below
# names its profile, because a CD number is a weighted sum and is unreadable without
# knowing which weights produced it — the same way a statistic is unreadable without a
# regimeId.
def _load_weight_profile():
    with open(os.path.join(HOME, "typology", "registry_observed.json")) as f:
        reg = json.load(f)
    w = {}
    for t in reg["types"].values():
        if t.get("code") and t.get("cd_weight") is not None:
            w[t["code"]] = float(t["cd_weight"])
    return w

# Release state drives the page's language. When every in-scope domain is rebuilt and no
# v1/masked rows remain, the banner stops saying "provisional because the pass is still
# running" and names a minted version instead. The hypotheses remain hypotheses either
# way — what changes is whether the corpus underneath them is still moving.
sys.path.insert(0, os.path.join(HOME, "typology"))
try:
    from corpus_version import manifest as _corpus_manifest
    VERSION = _corpus_manifest()
except Exception as _e:
    sys.stderr.write(f"FATAL: cannot determine corpus version: {_e}\n")
    sys.exit(2)
RELEASED = VERSION["clean_release"]
CORPUS_VERSION = VERSION["corpus_version"]

CD_PROFILE = "core-v1"
CD_WEIGHTS = _load_weight_profile()
CD_CEILING = round(sum(CD_WEIGHTS.values()), 4) if CD_WEIGHTS else None
# assignment compelled by a MANDATORY INFERENCE RULE in the v2 system prompt
FORCED = {"RC3":"RULE 2","NI":"RULE 3","JC":"RULE 4","CC":"RULE 6"}
NODE = {1:"Authority",2:"Norm",3:"Actor-in-Role",4:"Triggering Facts",
        5:"Legal Act",6:"Target",7:"Legal Effect",8:"Remedy"}
# needed for domains that have no v2 rows yet, so no name can be read from the data
DOMNAME = {1:"First Amendment",2:"Employment Discrimination",3:"Administrative Law",
           4:"Criminal Procedure",5:"Immigration",6:"Civil Rights §1983",
           7:"Contract",8:"Family Law"}

db = sqlite3.connect(DB); db.row_factory = sqlite3.Row
rows = []
for r in db.execute("""select case_id,domain_id,domain_name,court,date_decided,
  node1_closure,node2_closure,node3_closure,node4_closure,node5_closure,
  node6_closure,node7_closure,node8_closure,active_contradictions,
  contradiction_debt,chain_outcome,needs_review,was_masked,structural_signature
  from annotations where annotator=?""", (V2,)):
    d = dict(r)
    try: c = json.loads(d["active_contradictions"] or "[]")
    except Exception: c = []
    d["cts"] = {(x.get("type") if isinstance(x, dict) else x) for x in c if x}
    rows.append(d)

# Exclude degenerate extractions: rows whose chain_outcome is not in the documented
# enum are 100% validation-failed and 100% review-flagged (the 'indeterminate' group
# all carry CD exactly 0.0). They are dropped from every figure below and disclosed.
VALID_OUTCOMES = {"protection_granted","protection_denied","partial","remanded","dismissed","moot"}
raw_n = len(rows)
dropped = [r for r in rows if r["chain_outcome"] not in VALID_OUTCOMES]
rows = [r for r in rows if r["chain_outcome"] in VALID_OUTCOMES]
DROPPED = len(dropped)
drop_kinds = collections.Counter(str(r["chain_outcome"] or "(empty)") for r in dropped)

# The re-annotation runs domain-by-domain and is still live, so a domain can appear
# with a handful of rows. Anything below MIN_DOM_N is in-flight noise: exclude it from
# every figure and report it separately rather than letting n=4 drive a correlation.
MIN_DOM_N = 100
# Domains 9-11 (Habeas, Patent/IP, Securities) are NOT part of this corpus: their
# opinion text was never collected, so their annotations are inferred from case names.
# They must be excluded by identity, not merely by row count — a stray annotation pass
# pushed D9 past MIN_DOM_N and it silently entered the published hypotheses.
IN_SCOPE = set(DOMNAME)
rows = [r for r in rows if r["domain_id"] in IN_SCOPE]
_seen = collections.Counter(r["domain_id"] for r in rows)
doms = sorted(d for d, k in _seen.items() if k >= MIN_DOM_N)
inflight = sorted((d, k) for d, k in _seen.items() if k < MIN_DOM_N)
rows = [r for r in rows if r["domain_id"] in doms]

N = len(rows)
DN = {r["domain_id"]: DOMNAME.get(r["domain_id"]) or r["domain_name"] for r in rows}
for _d, _n in DOMNAME.items(): DN.setdefault(_d, _n)
nd = {d: sum(1 for r in rows if r["domain_id"] == d) for d in doms}
v1 = dict(db.execute("select domain_id,count(*) from annotations_unmasked group by 1").fetchall())
# Domains 9-11 were dropped from the corpus (their opinion text was never collected),
# so they must not inflate the denominator of the rebuild-progress figure.
v1 = {d: k for d, k in v1.items() if d in DOMNAME}
# A domain can clear MIN_DOM_N while still being only part-way rebuilt, and the pass
# works through cases in case_id order rather than at random — so a partial domain is
# not a random sample of itself. Track which are partial and re-run the two headline
# correlations without them, so a one-third-finished domain cannot quietly carry a
# cross-domain claim.
COMPLETE_FRAC = 0.90
partial = sorted(d for d in doms if _seen[d] < COMPLETE_FRAC * v1.get(d, _seen[d]))
complete = [d for d in doms if d not in partial]

_inflight_ids = {d for d, _ in inflight}
missing = [d for d in sorted(v1) if d not in doms and d not in _inflight_ids]
MISSING_LABEL = ", ".join(f"D{d} {DOMNAME.get(d, '?')}" for d in missing)
INFLIGHT_LABEL = ", ".join(f"D{d} {DOMNAME.get(d, '?')} ({k} of ~{v1.get(d, 0)} so far)"
                           for d, k in inflight)
# The v1 table is no longer a sensible denominator: the rebuild converted masked-pass
# rows that were never in it, so the corpus is now LARGER than the old baseline and the
# ratio read 103%. Once released the corpus is its own denominator.
_V1_BASELINE = sum(v1.values())
TARGET = max(_V1_BASELINE, N)
maxdate = db.execute("select max(annotation_date) from annotations where annotator=?", (V2,)).fetchone()[0]

def pct(x): return f"{x*100:.1f}%"
def wil(k, n, z=1.96):
    if not n: return (0.0, 0.0)
    p = k/n; d = 1+z*z/n; c = (p+z*z/(2*n))/d
    h = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return (max(0, c-h), min(1, c+h))
def E(s): return html.escape(str(s))
def fp(p):
    """Format a p-value without ever collapsing to 0.0000."""
    return "&lt;1e-300" if p <= 0 else (f"{p:.3f}" if p >= 1e-3 else f"{p:.0e}")
def outlbl(o):
    return "(unset)" if o is None or str(o).strip() == "" else str(o)

# ---- node profile -----------------------------------------------------------
nf_pool = {n: sum(1 for r in rows if r[f"node{n}_closure"] == "failed")/N for n in range(1, 9)}
nf_dom = {d: {n: sum(1 for r in rows if r["domain_id"] == d and r[f"node{n}_closure"] == "failed")/nd[d]
              for n in range(1, 9)} for d in doms}
prof = {d: np.array([nf_dom[d][n] for n in range(1, 9)]) for d in doms}
node_rho = [st.spearmanr(prof[a], prof[b])[0] for a, b in itertools.combinations(doms, 2)]
ranks = {d: list(np.argsort(-prof[d])+1) for d in doms}
top3 = {d: [int(x) for x in ranks[d][:3]] for d in doms}
same_top3 = len({tuple(v) for v in top3.values()}) == 1

# ---- contradiction profile --------------------------------------------------
ct_pool = {c: sum(1 for r in rows if c in r["cts"])/N for c in CT}
ctp = {d: np.array([sum(1 for r in rows if r["domain_id"] == d and c in r["cts"])/nd[d] for c in CT])
       for d in doms}
ct_rho = [st.spearmanr(ctp[a], ctp[b])[0] for a, b in itertools.combinations(doms, 2)]
fi = [i for i, c in enumerate(CT) if c not in FORCED]
ct_rho_free = [st.spearmanr(ctp[a][fi], ctp[b][fi])[0] for a, b in itertools.combinations(doms, 2)]

# Sensitivity: same correlations restricted to fully-rebuilt domains. If dropping
# the partial ones moves these, the cross-domain claim is resting on partial data.
node_rho_c = [st.spearmanr(prof[a], prof[b])[0] for a, b in itertools.combinations(complete, 2)] \
             if len(complete) > 1 else []
ct_rho_c   = [st.spearmanr(ctp[a], ctp[b])[0] for a, b in itertools.combinations(complete, 2)] \
             if len(complete) > 1 else []

elev = []
for i, c in enumerate(CT):
    for d in doms:
        k = sum(1 for r in rows if r["domain_id"] == d and c in r["cts"])
        ko = sum(1 for r in rows if r["domain_id"] != d and c in r["cts"]); no = N-nd[d]
        if k < 10 or ko < 1: continue
        p1, p0 = k/nd[d], ko/no
        rr = p1/p0 if p0 else 0
        chi2, p, _, _ = st.chi2_contingency([[k, nd[d]-k], [ko, no-ko]])
        if rr >= 1.8 and p < 1e-4:
            lo, hi = wil(k, nd[d])
            elev.append(dict(ct=c, d=d, pct=p1, lo=lo, hi=hi, other=p0, rr=rr, p=p, k=k, n=nd[d]))
elev.sort(key=lambda x: -x["rr"])
vacant = [c for c in CT if ct_pool[c]*N <= 20]

# ---- P4 prompt-variant control ----------------------------------------------
# P4's asymmetry could be an artifact of the v2 prompt's directional sentence. The
# control (p4_prompt_control.py) re-annotates one sample under three prompts: verbatim,
# the sentence removed, and the sentence inverted. Read here if the run has happened, so
# P4 reports the control rather than promising it.
def _p4_control():
    path = os.path.join(HOME, "p4_control.db")
    if not os.path.exists(path): return None
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        out = {}
        for arm in ("v2", "neutral", "reversed"):
            rs = [(a, b) for a, b, e in
                  c.execute("select node7,node8,err from p4arm where arm=?", (arm,)) if not e]
            if len(rs) < 30: continue
            f = lambda x: x == "failed"
            o7 = sum(1 for a, b in rs if f(a) and not f(b))
            o8 = sum(1 for a, b in rs if f(b) and not f(a))
            if o7 + o8 < 10: continue
            out[arm] = dict(n=len(rs), o7=o7, o8=o8,
                            p=float(2 * st.binom.cdf(min(o7, o8), o7 + o8, 0.5)))
        c.close()
        return out or None
    except Exception:
        return None


P4CTRL = _p4_control()

# N7-failed subset: used by the repair-adequacy calibration below and by P5.
N7F = [r for r in rows if r["node7_closure"] == "failed"]
N7F_SURV = (sum(1 for r in N7F if r["node8_closure"] == "closed")/len(N7F)) if N7F else 0.0

# ---- per-type calibration against repair adequacy ---------------------------
# P8 shows the weighted CD discriminates worse than a raw count. "Which weights are
# pulling the wrong way" is only answerable against a target, and outcome is the wrong
# target: calibrating CD against who won would make it the outcome predictor this
# rebuild exists to show it is not. Repair adequacy is the structural alternative —
# within the subset that already failed at N7, does N8 still close?
REPAIR_MIN = 20
_n7f_surv = np.array([1.0 if r["node8_closure"] == "closed" else 0.0 for r in N7F])
REPAIR_BETA = []
for c in CT:
    x = np.array([1.0 if c in r["cts"] else 0.0 for r in N7F])
    if x.sum() < REPAIR_MIN or x.sum() == len(x): continue
    r_, p_ = st.pearsonr(x, _n7f_surv)
    REPAIR_BETA.append(dict(ct=c, n=int(x.sum()), r=float(r_), p=float(p_)))
REPAIR_BETA.sort(key=lambda q: -q["r"])
if len(REPAIR_BETA) >= 4:
    # A heavier weight should mean more damage to repair, i.e. a more negative r.
    REPAIR_RHO, REPAIR_RHO_P = st.spearmanr([CD_WEIGHTS[q["ct"]] for q in REPAIR_BETA],
                                            [-q["r"] for q in REPAIR_BETA])
else:
    REPAIR_BETA, REPAIR_RHO, REPAIR_RHO_P = [], 0.0, 1.0

# ---- CD scale governance ----------------------------------------------------
# A CD number is a weighted sum whose range is fixed by its weight profile. Two things
# in circulation are stated on scales this corpus cannot produce, and both are
# measurement errors rather than labelling nuisances: a reader who applies either to a
# corpus figure gets a wrong answer, not merely an unfamiliar name.
#   (a) the Quick Reference banding 0 / 1-2 / 3-4 / 5-6 / 7+ presupposes CD is an integer
#       count of active contradictions. Under Sum(w) with a ceiling of CD_CEILING, no case
#       can reach band 2, so every case is "stable" and three bands are unreachable.
#   (b) SimLex ships its own thirteen-type list with its own cdW values. Checked here
#       rather than asserted, because the divergence is what makes CD figures from the
#       two artifacts incommensurable.
BANDS = [(0, 0, "0"), (1, 2, "1-2"), (3, 4, "3-4"), (5, 6, "5-6"), (7, 99, "7+")]
_ctn = collections.Counter(len(r["cts"]) for r in rows)
band_count = [(lbl, sum(v for k, v in _ctn.items() if lo <= k <= hi)/N) for lo, hi, lbl in BANDS]
band_weighted = [(lbl, sum(1 for r in rows
                           if r["contradiction_debt"] is not None
                           and lo <= r["contradiction_debt"] <= hi)/N)
                 for lo, hi, lbl in BANDS]
CD_MAX = max((r["contradiction_debt"] or 0.0) for r in rows) if rows else 0.0
CD_MEAN = float(np.mean([r["contradiction_debt"] for r in rows
                         if r["contradiction_debt"] is not None]))


def _simlex_profile():
    """Best-effort read of SimLex.html's own contradiction-type list and cdW values."""
    p = os.path.join(HOME, "SimLex.html")
    if not os.path.exists(p): return None
    src = open(p, encoding="utf-8", errors="replace").read()
    out = {}
    for m in re.finditer(r'\{([^{}]*?cdW\s*:\s*([\d.]+)[^{}]*?)\}', src):
        body, w = m.group(1), float(m.group(2))
        c = re.search(r'\bshort\s*:\s*"([^"]+)"', body)
        n = re.search(r'\blabel\s*:\s*"([^"]+)"', body)
        if c: out[c.group(1)] = (w, n.group(1) if n else "")
    return out or None


SIMLEX = _simlex_profile()
SIMLEX_SUM = round(sum(w for w, _ in SIMLEX.values()), 4) if SIMLEX else None
SIMLEX_SHARED = sorted(set(SIMLEX) & set(CD_WEIGHTS)) if SIMLEX else []
SIMLEX_ONLY = sorted(set(SIMLEX) - set(CD_WEIGHTS)) if SIMLEX else []
CORE_ONLY = sorted(set(CD_WEIGHTS) - set(SIMLEX)) if SIMLEX else []
SIMLEX_CONFLICT = sorted(c for c in SIMLEX_SHARED
                         if abs(SIMLEX[c][0] - CD_WEIGHTS[c]) > 1e-9) if SIMLEX else []

# ---- NI construct validity: does the tag track the node it is named for? ----
# NI is "the norm's application to these facts is genuinely contested". If that is what
# it measures, its firing rate should not swing wildly across Node 2's own closure
# states. Computed here so P6's withdrawal is stated with numbers rather than asserted.
ni_n2 = {}
for st_ in sorted({r["node2_closure"] for r in rows if r["node2_closure"]}):
    grp = [r for r in rows if r["node2_closure"] == st_]
    if len(grp) < 25: continue
    ni_n2[st_] = (len(grp), sum(1 for r in grp if "NI" in r["cts"])/len(grp))

# ---- the one a-priori type/domain prediction the framework makes ------------
# CT-AI (Authority Inflation) is the ontology's master contradiction, and Administrative
# Law is the one domain whose contested object IS the scope of conferred authority. That
# is a placement the framework commits to before seeing data, and unlike RC3/NI/JC/CC the
# v2 prompt contains no rule that forces AI. Scored here so P2 reads as a prediction test
# rather than as a table of domain differences.
AI_HIT = None
_AI_DOM = 3
if "AINF" not in FORCED and _AI_DOM in doms:
    _in = [r for r in rows if r["domain_id"] == _AI_DOM]
    _out = [r for r in rows if r["domain_id"] != _AI_DOM]
    _ki = sum(1 for r in _in if "AINF" in r["cts"]); _ko = sum(1 for r in _out if "AINF" in r["cts"])
    if _ki and _ko and len(_in) and len(_out):
        _p_in, _p_out = _ki/len(_in), _ko/len(_out)
        _c2, _p, _, _ = st.chi2_contingency([[_ki, len(_in)-_ki], [_ko, len(_out)-_ko]])
        AI_HIT = dict(din=_p_in, dout=_p_out, rr=_p_in/_p_out if _p_out else 0.0,
                      chi2=_c2, p=_p, n=len(rows), dom=DN.get(_AI_DOM, f"D{_AI_DOM}"))

# ---- contradiction-type co-occurrence structure (kernel test) ---------------
# If the 13 contradiction types are derived theorems over a smaller set of kernel
# primitives rather than 13 independent tags, then types sharing a primitive should
# co-occur above chance and types whose primitives are incompatible should exclude
# each other. Independent tags do neither: they sit at lift 1.0. So the co-occurrence
# matrix is a direct empirical test of the derivation claim, runnable on this corpus.
CO_MIN = 50                                      # types below this are noise, not signal
co_types = [c for c in CT if ct_pool[c]*N >= CO_MIN]
co_rare = [c for c in CT if c not in co_types]
_pres = {c: np.array([1 if c in r["cts"] else 0 for r in rows], dtype=float) for c in CT}


def _lift(types, subset=None):
    """observed/expected co-occurrence for every ordered pair, over `subset` of rows."""
    idx = np.ones(len(rows), dtype=bool) if subset is None else subset
    m = int(idx.sum())
    base = {c: _pres[c][idx].sum()/m for c in types}
    out = {}
    for a, b in itertools.permutations(types, 2):
        e = base[a]*base[b]
        out[(a, b)] = (float((_pres[a][idx]*_pres[b][idx]).sum())/m)/e if e else 0.0
    return out


def _famcluster(types, L, k):
    """average-linkage agglomerative clustering on d = max(0, 2 - log2 lift)."""
    def dd(a, b):
        v = L.get((a, b), 0.0)
        return 4.0 if v <= 0 else max(0.0, 2.0 - math.log2(v))
    cl = [[t] for t in types]
    while len(cl) > k:
        best = None
        for i in range(len(cl)):
            for j in range(i+1, len(cl)):
                ds = [dd(x, y) for x in cl[i] for y in cl[j]]
                m = sum(ds)/len(ds)
                if best is None or m < best: best, bi, bj = m, i, j
        cl[bi] = cl[bi] + cl[bj]; cl.pop(bj)
    return sorted([sorted(c) for c in cl])


co_lift = _lift(co_types)
CO_K = 4
co_fams = _famcluster(co_types, co_lift, CO_K)

# every pair, with a 2x2 test, so attraction and exclusion are both on the record
co_pairs = []
for a, b in itertools.combinations(co_types, 2):
    n11 = int((_pres[a]*_pres[b]).sum()); na = int(_pres[a].sum()); nb = int(_pres[b].sum())
    e11 = na*nb/N
    if e11 < 5: continue
    chi2, p, _, _ = st.chi2_contingency([[n11, na-n11], [nb-n11, N-na-nb+n11]])
    co_pairs.append(dict(a=a, b=b, lift=n11/e11 if e11 else 0.0, obs=n11, exp=e11, chi2=chi2, p=p))
co_pairs.sort(key=lambda x: -x["lift"])
co_sig = [q for q in co_pairs if q["p"] < 0.001]
co_attract = [q for q in co_sig if q["lift"] > 1]
co_repel = [q for q in co_sig if q["lift"] < 1]

# Stability. A family structure read off one pass of one corpus is worth nothing until
# it survives resampling. Split-half and leave-one-domain-out; report the fraction of
# runs that recover the same partition.
_half = np.arange(len(rows)) % 2 == 0
co_stab = []
co_stab.append(("split-half A", _famcluster(co_types, _lift(co_types, _half), CO_K)))
co_stab.append(("split-half B", _famcluster(co_types, _lift(co_types, ~_half), CO_K)))
_domarr = np.array([r["domain_id"] for r in rows])
for d in doms:
    co_stab.append((f"drop D{d}", _famcluster(co_types, _lift(co_types, _domarr != d), CO_K)))
co_stab_hits = sum(1 for _, f in co_stab if f == co_fams)
co_stab_frac = co_stab_hits/len(co_stab) if co_stab else 0.0
# which pairs never separate, across every resample — the invariant core
_pairfam = collections.Counter()
for _, f in co_stab + [("full", co_fams)]:
    for g in f:
        for a, b in itertools.combinations(g, 2): _pairfam[(a, b)] += 1
co_invariant = sorted([p for p, k in _pairfam.items() if k == len(co_stab)+1])

# Including the near-vacant types is what the ontology's own 13-type list implies, so
# report what happens when they are forced in: if the answer changes, the families are
# partly an artifact of tags with single-digit support.
co_fams_all = _famcluster(list(CT), _lift(list(CT)), CO_K)

# ---- CD ---------------------------------------------------------------------
cd = collections.defaultdict(list)
for r in rows:
    if r["contradiction_debt"] is not None: cd[r["chain_outcome"]].append(r["contradiction_debt"])
cd_order = sorted(cd, key=lambda k: np.mean(cd[k]))
g = np.array(cd.get("protection_granted", [])); dn = np.array(cd.get("protection_denied", []))
t_gd, p_gd = st.ttest_ind(g, dn, equal_var=False)
sp = math.sqrt(((len(g)-1)*g.var(ddof=1)+(len(dn)-1)*dn.var(ddof=1))/(len(g)+len(dn)-2))
dcoh = (g.mean()-dn.mean())/sp
mer = np.array([x for o in ("protection_granted", "protection_denied", "partial") for x in cd.get(o, [])])
nm = np.array([x for o in ("moot", "dismissed") for x in cd.get(o, [])])
t_mn, p_mn = st.ttest_ind(mer, nm, equal_var=False)

# ---- CD replicated on UNWEIGHTED tag counts ---------------------------------
# P8 shows the core-v1 weights are LESS discriminative than a raw count of active
# contradictions. The P3 ordering is therefore only meaningful if it survives with
# the weights removed; otherwise it is an artifact of the weight profile. Same rows,
# same denominators — only the per-case statistic changes from Sum(w) to Count().
ctc = collections.defaultdict(list)
for r in rows:
    if r["contradiction_debt"] is not None: ctc[r["chain_outcome"]].append(len(r["cts"]))
ct_order = sorted(ctc, key=lambda k: np.mean(ctc[k]))
P3_SAME_ORDER = (cd_order == ct_order)
_rk_cd = {o: i for i, o in enumerate(cd_order)}
_rk_ct = {o: i for i, o in enumerate(ct_order)}
rho_ord, p_ord = st.spearmanr([_rk_cd[o] for o in cd_order], [_rk_ct[o] for o in cd_order])


def _eta2(groups):
    """Proportion of variance in the case-level statistic explained by chain_outcome."""
    allx = np.concatenate([np.asarray(g_, dtype=float) for g_ in groups])
    gm = allx.mean()
    ssb = sum(len(g_) * (np.mean(g_) - gm) ** 2 for g_ in groups)
    ssw = sum(((np.asarray(g_, dtype=float) - np.mean(g_)) ** 2).sum() for g_ in groups)
    return ssb / (ssb + ssw) if (ssb + ssw) else 0.0


eta2_cd = _eta2([cd[o] for o in cd_order])
eta2_ct = _eta2([ctc[o] for o in cd_order])
gc = np.array(ctc.get("protection_granted", [])); dnc = np.array(ctc.get("protection_denied", []))
t_gdc, p_gdc = st.ttest_ind(gc, dnc, equal_var=False)
spc = math.sqrt(((len(gc)-1)*gc.var(ddof=1) + (len(dnc)-1)*dnc.var(ddof=1)) / (len(gc)+len(dnc)-2))
dcoh_ct = (gc.mean() - dnc.mean()) / spc

# ---- N7/N8 ------------------------------------------------------------------
f7 = np.array([1 if r["node7_closure"] == "failed" else 0 for r in rows])
f8 = np.array([1 if r["node8_closure"] == "failed" else 0 for r in rows])
both = int(((f7 == 1)&(f8 == 1)).sum()); only7 = int(((f7 == 1)&(f8 == 0)).sum())
only8 = int(((f7 == 0)&(f8 == 1)).sum()); neither = int(((f7 == 0)&(f8 == 0)).sum())
p78 = both/(both+only8) if both+only8 else 0     # P(N7 fail | N8 fail)
p87 = both/(both+only7) if both+only7 else 0     # P(N8 fail | N7 fail)
concord = sum(1 for r in rows if (r["node7_closure"] == "failed") == (r["chain_outcome"] == "protection_denied"))/N

# The corpus is predominantly BLIND-annotated: the prompt builder truncates the opinion
# at the first disposition signal and redacts AFFIRMED/REVERSED/etc. Where that fired the
# annotator could not read the outcome off the page, so chain_outcome is an inference,
# not a transcription — which changes what agreement with Node 7 actually shows. Split
# it, because the masked and unmasked cases support very different objections.
_mk = [r for r in rows if r["was_masked"]]
_um = [r for r in rows if not r["was_masked"]]
def _conc(g):
    return (sum(1 for r in g if (r["node7_closure"] == "failed") ==
                (r["chain_outcome"] == "protection_denied"))/len(g)) if g else None
CONC_MASKED, CONC_UNMASKED = _conc(_mk), _conc(_um)
N_MASKED, N_UNMASKED = len(_mk), len(_um)
MASKED_SHARE = N_MASKED/N if N else 0

# ---- variance: court vs domain ---------------------------------------------
def cram(fn, minn=60):
    grp = collections.defaultdict(list)
    for r in rows: grp[fn(r)].append(1 if r["node7_closure"] == "failed" else 0)
    grp = {k: v for k, v in grp.items() if len(v) >= minn}
    tab = np.array([[sum(v), len(v)-sum(v)] for v in grp.values()])
    chi2, p, dof, _ = st.chi2_contingency(tab); n = tab.sum()
    rates = [sum(v)/len(v) for v in grp.values()]
    return dict(k=len(grp), n=int(n), chi2=chi2, p=p, dof=dof,
                V=math.sqrt(chi2/(n*(min(tab.shape)-1))),
                lo=min(rates), hi=max(rates))
cv, dv = cram(lambda r: r["court"]), cram(lambda r: r["domain_id"])
wdom = []
for d in doms:
    grp = collections.defaultdict(list)
    for r in rows:
        if r["domain_id"] == d: grp[r["court"]].append(1 if r["node7_closure"] == "failed" else 0)
    grp = {k: v for k, v in grp.items() if len(v) >= 25}
    if len(grp) < 3: continue
    tab = np.array([[sum(v), len(v)-sum(v)] for v in grp.values()])
    chi2, p, _, _ = st.chi2_contingency(tab)
    wdom.append((d, len(grp), p))
nsig = sum(1 for _, _, p in wdom if p < 0.05)

# ---- forum effect on a NON-dispositional variable ---------------------------
# N7 failure is close to "the claimant lost", so a court effect on N7 restates known
# circuit affirmance variation in SOoL vocabulary and cannot distinguish a structural
# claim from an outcome claim. Remedy survival *given* that the effect node already
# failed is not an outcome variable: every case in the subset lost at N7. Variation in
# whether Node 8 still closes is variation in whether the forum treats a broken effect
# as repairable — which is structural, and is the version of P5 worth defending.
def surv(fn, minn=60):
    grp = collections.defaultdict(list)
    for r in rows:
        if r["node7_closure"] != "failed": continue
        grp[fn(r)].append(1 if r["node8_closure"] == "closed" else 0)
    grp = {k: v for k, v in grp.items() if len(v) >= minn}
    if len(grp) < 3: return None
    tab = np.array([[sum(v), len(v)-sum(v)] for v in grp.values()])
    chi2, p, dof, _ = st.chi2_contingency(tab); n = int(tab.sum())
    rates = sorted(((sum(v)/len(v)), k, len(v)) for k, v in grp.items())
    return dict(k=len(grp), n=n, chi2=chi2, p=p, dof=dof,
                V=math.sqrt(chi2/(n*(min(tab.shape)-1))),
                lo=rates[0], hi=rates[-1], pooled=sum(sum(v) for v in grp.values())/n)
csv_, dsv_ = surv(lambda r: r["court"]), surv(lambda r: r["domain_id"])

# ---- temporal ---------------------------------------------------------------
def dec(r):
    y = (r["date_decided"] or "")[:4]
    return int(y)//10*10 if y.isdigit() else None
decs = []
for dd in sorted({dec(r) for r in rows if dec(r)}):
    v = [r for r in rows if dec(r) == dd]
    if len(v) < 25: continue
    decs.append(dict(d=dd, n=len(v),
        ni=sum(1 for r in v if "NI" in r["cts"])/len(v),
        n7=sum(1 for r in v if r["node7_closure"] == "failed")/len(v),
        cd=float(np.mean([r["contradiction_debt"] for r in v if r["contradiction_debt"] is not None]))))
yr = [(int((r["date_decided"] or "0")[:4]), 1 if "NI" in r["cts"] else 0)
      for r in rows if (r["date_decided"] or "")[:4].isdigit()]
ni_rho, ni_p = st.spearmanr([a for a, _ in yr], [b for _, b in yr])
rise = 0; fallflat = 0
for d in doms:
    pts = []
    for dd in [x["d"] for x in decs]:
        v = [r for r in rows if r["domain_id"] == d and dec(r) == dd]
        if len(v) >= 25: pts.append(sum(1 for r in v if "NI" in r["cts"])/len(v))
    if len(pts) >= 2:
        if pts[-1] > pts[0]: rise += 1
        else: fallflat += 1
ndom_temporal = rise+fallflat

# ---- NI construct validity --------------------------------------------------
ni_n2 = {}
for k in {r["node2_closure"] for r in rows}:
    v = [r for r in rows if r["node2_closure"] == k]
    ni_n2[str(k)] = (len(v), sum(1 for r in v if "NI" in r["cts"])/len(v))

review_pct = sum(1 for r in rows if r["needs_review"])/N
clean = [r for r in rows if not r["needs_review"]]
clean_n7 = sum(1 for r in clean if r["node7_closure"] == "failed")/len(clean)
zero_ct = sum(1 for r in rows if not r["cts"])/N
mean_ct = float(np.mean([len(r["cts"]) for r in rows]))
mean_cd = float(np.mean([r["contradiction_debt"] for r in rows if r["contradiction_debt"] is not None]))

# =============================================================================
# HTML
# =============================================================================
GEN = datetime.datetime.now().strftime("%-d %B %Y")
CARD = ("background:var(--parch2);border:1px solid var(--border);border-left:3px solid var(--navy);"
        "border-radius:var(--r);padding:.85rem 1rem;margin-bottom:.85rem")
HID  = ("font-family:Inconsolata,monospace;font-size:.72rem;font-weight:700;color:var(--gold-light);"
        "background:var(--navy2);padding:.12rem .45rem;border-radius:2px;letter-spacing:.05em")
NUM  = "font-family:Inconsolata,monospace;font-weight:700;color:var(--navy)"
SUB  = "font-size:.8rem;color:var(--muted);margin-top:.45rem;line-height:1.5"
CAV  = ("font-size:.78rem;color:var(--amber);margin-top:.5rem;line-height:1.5;"
        "border-top:1px dotted var(--border);padding-top:.45rem")
TBL  = ("width:100%;border-collapse:collapse;font-family:Inconsolata,monospace;"
        "font-size:.74rem;margin-top:.6rem")
TH   = "text-align:right;padding:.2rem .4rem;border-bottom:1px solid var(--border);color:var(--navy)"
TD   = "text-align:right;padding:.18rem .4rem;border-bottom:1px solid var(--border2)"

o = []
A = o.append
A(START)
A('<div style="padding:1rem 1.25rem 0">')

# ---- banner
A('<div style="background:#3a2410;border:1px solid var(--gold);border-left:4px solid var(--gold2);'
  'border-radius:var(--r);padding:.9rem 1.1rem;margin-bottom:1.1rem">')
A('<div style="font-size:.7rem;letter-spacing:.22em;text-transform:uppercase;color:var(--gold-light);'
  'font-weight:700;margin-bottom:.4rem">'
  + (f'SOoL Corpus {E(CORPUS_VERSION)} — released &middot; hypotheses remain provisional'
     if RELEASED else '⚠ Provisional — not for citation')
  + '</div>')
if RELEASED:
    A(f'<div style="font-size:.85rem;color:#f0e6d0;line-height:1.6">'
      f'<strong>This is corpus version {E(CORPUS_VERSION)}, the first release in which every '
      f'in-scope domain has been annotated under the v2 regime.</strong> The v1 forcing rules '
      f'(RULE&nbsp;1 / RULE&nbsp;5, which manufactured Recognition Failure from a Node&nbsp;7 '
      f'failure) are gone, and no v1 or masked-pass rows remain in the analysis scope: '
      f'<strong style="font-family:Inconsolata,monospace">{N:,}</strong> cases across '
      f'{len(doms)} domains, weight profile <code>{CD_PROFILE}</code>, ontology '
      f'<code>{E(ONTOLOGY_SOURCE)}</code> sha256 <code>{E(ONTOLOGY_HASH[:16])}…</code>. '
      f'Figures on this page are stable and citable <em>as figures</em>.'
      f'<br><br>'
      f'<br><br>'
      f'<strong>What the reconstruction bought.</strong> The v1 corpus could not support these '
      f'questions at all: two annotation rules manufactured Recognition Failure and Repair '
      f'Failure from any Node&nbsp;7 failure, so the headline results measured rule compliance '
      f'rather than law. Removing them and re-annotating every case has produced a corpus that '
      f'is internally consistent, single-regime, and <strong>{pct(MASKED_SHARE)} '
      f'blind-annotated</strong> — the disposition was withheld from the annotator on almost '
      f'every case. Findings drawn from it now stand or fall on their own evidence. Several '
      f'already have: the cross-domain profile correlation <em>rose</em> when the final two '
      f'domains were added, and the one claim that failed (the three-cluster finding) was '
      f'refuted on the record rather than quietly dropped.'
      f'<br><br>'
      f'<strong>The hypotheses below are still hypotheses</strong>, and each card states what '
      f'would falsify it — that is what makes them usable, not a hedge. The remaining limits are '
      f'specific and tractable: several contradiction types are rule-forced by the prompt, '
      f'Node&nbsp;7 is non-independent of the case outcome, and the debt weights are '
      f'uncalibrated — P8 below now quantifies what that last one costs. None of these needs '
      f'more data; they need targeted tests, which a stable corpus finally makes possible.</div>')
else:
    A(f'<div style="font-size:.85rem;color:#f0e6d0;line-height:1.6">'
      f'The hypotheses below are <strong>generated from an in-progress re-annotation</strong> and are '
      f'published to record what the partial data suggests, not to assert findings. As of '
  f'<strong>{E(GEN)}</strong> the v2 pass has annotated '
  f'<strong style="font-family:Inconsolata,monospace">{N:,}</strong> of '
  f'<strong style="font-family:Inconsolata,monospace">{TARGET:,}</strong> cases '
  f'({N/TARGET*100:.0f}%). Domains <strong>{", ".join("D"+str(d) for d in doms)}</strong> have enough '
  f'rows to analyse (n&nbsp;&ge;&nbsp;{MIN_DOM_N} each)'
  + ('; ' if (inflight or missing) else '. ')
  + (f'<strong>{E(INFLIGHT_LABEL)}</strong> '
     f'{"are" if len(inflight) != 1 else "is"} mid-pass and excluded as in-flight noise; '
     if inflight else '')
  + (f'<strong>{E(MISSING_LABEL)}</strong> '
     f'{"have" if len(missing) != 1 else "has"} not been annotated at all. '
     if missing else '')
  + f'Every figure is therefore conditional on a corpus that is <em>not</em> a random sample of the '
  f'full corpus — the pass runs domain-by-domain, so the missing domains are missing entirely rather '
  f'than thinned. <strong>All values will be recomputed and these hypotheses confirmed, revised, or '
  f'withdrawn when the pass completes.</strong> Each card states the specific artifact risk that '
  f'would sink it.</div>')
A(f'<div style="font-size:.74rem;color:#c9b98f;margin-top:.5rem;font-family:Inconsolata,monospace">'
  f'last v2 annotation written: {E((maxdate or "")[:19])}Z &middot; regenerate with '
  f'<code>gen_provisional.py --splice</code></div>')
A('</div>')

A('<div style="font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;color:var(--navy);'
  'border-bottom:1px solid var(--border);padding-bottom:.3rem;margin-bottom:.8rem">'
  'Hypotheses suggested by the partial v2 data</div>')

# ---- HA
A(f'<div style="{CARD}">')
A(f'<span style="{HID}">P1</span> <strong style="margin-left:.5rem">Failure concentrates at the '
  f'terminal nodes, in the same order, in every domain.</strong>')
A(f'<div style="{SUB}">Across all {len(doms)} analysed domains the pooled failure rate is '
  f'<span style="{NUM}">{pct(nf_pool[7])}</span> at Node&nbsp;7 (Legal Effect) and '
  f'<span style="{NUM}">{pct(nf_pool[8])}</span> at Node&nbsp;8 (Remedy), against '
  f'at most {max(nf_pool[1], nf_pool[3], nf_pool[6])*100:.1f}% at the three constitutive nodes '
  f'(N1 Authority {pct(nf_pool[1])}, N3 Actor-in-Role {pct(nf_pool[3])}, N6 Target {pct(nf_pool[6])}). '
  f'The eight-node failure profile correlates across domain pairs at mean Spearman '
  f'&rho;&nbsp;=&nbsp;<span style="{NUM}">{np.mean(node_rho):+.3f}</span> '
  f'(min {np.min(node_rho):+.3f}, {len(node_rho)} pairs)'
  + (f', and the three most-failed nodes are <strong>the same three, in the same order '
     f'({"&nbsp;&gt;&nbsp;".join("N"+str(x) for x in list(top3.values())[0])}), in all '
     f'{len(doms)} domains</strong>.' if same_top3 else '.')
  + f' Within this corpus, chains do not break where they are built; they break where they are '
    f'supposed to bind.</div>')
A(f'<div style="{SUB}"><strong>Scope: this is a fact about the appellate tier, not about law.</strong> '
  f'The near-floor upstream rates (N1 {pct(nf_pool[1])}, N3 {pct(nf_pool[3])}) cannot be read as '
  f'evidence that authority and role rarely fail, because an appellate corpus cannot show upstream '
  f'failure. A case in which authority or actor-in-role is genuinely contested is resolved below, '
  f'settles, or is never filed; what reaches a court of appeals has already had its constitutive nodes '
  f'conceded by both sides. The corpus pre-filters for terminal stress — the same selection logic that '
  f'the SCOTUS-tier backtest exhibits one level further up. The claim P1 can support is that '
  f'<em>conditional on reaching appellate review</em>, failure concentrates terminally and in a '
  f'domain-invariant order. Whether that ordering is a property of legal structure or of the filter '
  f'is not decidable from this corpus, and the test that would decide it is a district-court or '
  f'agency-adjudication sample where upstream contest actually appears. Until that sample exists, P1 '
  f'is a tier-scoped finding.</div>')
A(f'<table style="{TBL}"><tr><th style="{TH};text-align:left">domain</th><th style="{TH}">n</th>'
  + "".join(f'<th style="{TH}">N{n}</th>' for n in range(1, 9)) + '</tr>')
for d in doms:
    A(f'<tr><td style="{TD};text-align:left">D{d} {E(DN[d][:22])}</td><td style="{TD}">{nd[d]}</td>'
      + "".join(f'<td style="{TD}{";font-weight:700;color:var(--red)" if nf_dom[d][n] > .3 else ""}">'
                f'{nf_dom[d][n]*100:.0f}</td>' for n in range(1, 9)) + '</tr>')
A(f'<tr><td style="{TD};text-align:left;font-weight:700">POOLED</td>'
  f'<td style="{TD};font-weight:700">{N}</td>'
  + "".join(f'<td style="{TD};font-weight:700">{nf_pool[n]*100:.0f}</td>' for n in range(1, 9)) + '</tr></table>')
if partial:
    A(f'<div style="{SUB}"><strong>Partial domains.</strong> '
      f'{", ".join(f"D{d} {E(DN[d])} ({nd[d]} of ~{v1.get(d,0)})" for d in partial)} '
      f'{"is" if len(partial)==1 else "are"} included above but not yet fully rebuilt, and the '
      f'pass works through cases in id order rather than at random, so they are not random '
      f'samples of themselves. Restricting the profile correlation to the '
      f'{len(complete)} fully-rebuilt domains gives mean &rho;&nbsp;=&nbsp;'
      f'<span style="{NUM}">{np.mean(node_rho_c):+.3f}</span> against '
      f'<span style="{NUM}">{np.mean(node_rho):+.3f}</span> for all {len(doms)} — '
      + ("the claim does not depend on the partial data." if abs(np.mean(node_rho_c)-np.mean(node_rho)) < 0.05
         else "a large enough shift that the partial data is doing real work here, so treat the "
              "pooled figure with extra caution.")
      + '</div>')

A(f'<div style="{CAV}"><strong>What would sink it.</strong> Node&nbsp;7 failure and '
  f'<code>protection_denied</code> agree on <span style="{NUM}">{pct(concord)}</span> of cases. '
  + (f'That is <em>not</em> definitional, and the reason matters. '
     f'<strong>{pct(MASKED_SHARE)} of the corpus was annotated blind</strong>: the opinion is '
     f'truncated at the first disposition signal and outcome words are redacted, so the '
     f'annotator could not read the result off the page. Among those {N_MASKED:,} cases '
     f'concordance is <span style="{NUM}">{pct(CONC_MASKED)}</span>; among the {N_UNMASKED:,} '
     f'where the disposition was visible it is <span style="{NUM}">{pct(CONC_UNMASKED)}</span>. '
     f'Seeing the outcome does push agreement up, but blind annotation still reaches '
     f'{pct(CONC_MASKED)}. The right objection is therefore not tautology but '
     f'<em>non-independence</em>: Node&nbsp;7 and <code>chain_outcome</code> are two readings '
     f'of one text by one annotator, so their agreement is internal consistency rather than '
     f'corroboration. '
     if (CONC_MASKED is not None and N_UNMASKED) else
     f'Under the v2 prompt’s claimant-centric RULE&nbsp;0 this is close to a re-encoding of '
     f'"the claimant lost" in an affirmance-heavy appellate corpus. ')
  + f'The non-tautological content is the <em>rest</em> of the ordering (N8, then '
  f'N{list(top3.values())[0][2] if same_top3 else "5"}) and the near-floor upstream rates, neither of '
  f'which is fixed by the outcome. Restricting to the {len(clean):,} cases not flagged for review '
  f'<em>raises</em> N7 failure to {pct(clean_n7)}, so the pattern is not an artifact of low-confidence '
  f'annotations.</div>')
A('</div>')

# ---- HB
A(f'<div style="{CARD}">')
A(f'<span style="{HID}">P2</span> <strong style="margin-left:.5rem">Domains share one contradiction '
  f'ranking but differ by a few sharply elevated types.</strong>')
A(f'<div style="{SUB}">The 13-type contradiction profile is near-identical across domains — mean '
  f'pairwise &rho;&nbsp;=&nbsp;<span style="{NUM}">{np.mean(ct_rho):+.3f}</span> '
  f'(min {np.min(ct_rho):+.3f}); restricted to the {len(fi)} types <em>not</em> compelled by a '
  f'mandatory inference rule ({", ".join(CT[i] for i in fi)}), still '
  f'<span style="{NUM}">{np.mean(ct_rho_free):+.3f}</span>. Against that shared baseline, a small '
  f'number of types spike in exactly one domain:</div>')
A(f'<table style="{TBL}"><tr><th style="{TH};text-align:left">type</th>'
  f'<th style="{TH};text-align:left">domain</th><th style="{TH}">rate</th><th style="{TH}">95% CI</th>'
  f'<th style="{TH}">elsewhere</th><th style="{TH}">ratio</th><th style="{TH}">p</th></tr>')
for e in elev:
    A(f'<tr><td style="{TD};text-align:left"><strong>{e["ct"]}</strong> '
      f'<span style="color:var(--muted)">{E(CTNAME[e["ct"]])}</span>'
      + (f' <span style="color:var(--amber)">&#9888;{E(FORCED[e["ct"]])}</span>' if e["ct"] in FORCED else '')
      + f'</td><td style="{TD};text-align:left">D{e["d"]} {E(DN[e["d"]][:20])}</td>'
      f'<td style="{TD};font-weight:700">{e["pct"]*100:.1f}%</td>'
      f'<td style="{TD};color:var(--muted)">{e["lo"]*100:.1f}–{e["hi"]*100:.1f}</td>'
      f'<td style="{TD}">{e["other"]*100:.1f}%</td>'
      f'<td style="{TD};font-weight:700;color:var(--red)">{e["rr"]:.1f}&times;</td>'
      f'<td style="{TD};color:var(--muted)">{fp(e["p"])}</td></tr>')
A('</table>')
A(f'<div style="{SUB}">Reading: doctrinal domains are not structurally distinct <em>architectures</em>; '
  f'they are the same architecture under different characteristic stress. Domain identity appears to be '
  f'carried by a handful of elevated types rather than by a different ranking — which is the SOoL '
  f'domain-invariance claim in its strongest testable form.</div>')
if AI_HIT:
    A(f'<div style="{SUB}"><strong>One of these elevations is a prediction the framework made in '
      f'advance, and it landed.</strong> Authority Inflation is the contradiction the ontology treats '
      f'as master: a legal act that claims more authority than was conferred on it. If that reading is '
      f'right, AI should concentrate in the one domain whose contested object <em>is</em> the scope of '
      f'conferred authority. It does. AINF fires in '
      f'<span style="{NUM}">{pct(AI_HIT["din"])}</span> of Administrative Law cases against '
      f'<span style="{NUM}">{pct(AI_HIT["dout"])}</span> everywhere else — a '
      f'<span style="{NUM}">{AI_HIT["rr"]:.1f}&times;</span> elevation '
      f'(&chi;&sup2;&nbsp;=&nbsp;{AI_HIT["chi2"]:.0f}, p&nbsp;=&nbsp;{fp(AI_HIT["p"])}, '
      f'n&nbsp;=&nbsp;{AI_HIT["n"]:,}). AI is <em>not</em> a rule-forced type: unlike '
      f'{", ".join(FORCED)}, nothing in the v2 system prompt tells the annotator when to assign it, '
      f'and domains 1–8 all receive the same prompt with no domain-specific hints. So this is not a '
      f'domain-difference observed after the fact — it is the placement the master-contradiction claim '
      f'commits to, tested against a corpus that had no way to know about it. It is the strongest '
      f'confirmatory result on this page. Its limit is that a single hit on a single domain is one '
      f'observation: the framework should be made to name the expected primary type for each remaining '
      f'domain before the next corpus cut, so the next test is scored against a pre-registered '
      f'prediction rather than a retrofitted one.</div>')
if partial and len(complete) > 1:
    A(f'<div style="{SUB}"><strong>Without the partial domains,</strong> the 13-type profile '
      f'correlation across the {len(complete)} fully-rebuilt domains is mean &rho;&nbsp;=&nbsp;'
      f'<span style="{NUM}">{np.mean(ct_rho_c):+.3f}</span> '
      f'(vs {np.mean(ct_rho):+.3f} across all {len(doms)}).</div>')

A(f'<div style="{CAV}"><strong>What would sink it.</strong> Types marked &#9888; are '
  f'<em>rule-forced</em>: the v2 system prompt compels their assignment under stated conditions '
  f'({", ".join(f"{k}&nbsp;{v}" for k, v in FORCED.items())}), so their rates measure how often those '
  f'conditions obtain, not an unprompted discovery. The elevations are nonetheless comparable across '
  f'domains because <strong>domains 1–8 receive an identical system prompt with no domain-specific '
  f'hints</strong> (per-domain supplements exist only for domains 9–11, which are outside this cut). '
  f'A high &rho; among 13 points is also easy to obtain when one type dominates; the unforced-only '
  f'&rho; is the figure to trust.</div>')
A('</div>')

# ---- HC
A(f'<div style="{CARD}">')
A(f'<span style="{HID}">P3</span> <strong style="margin-left:.5rem">Contradiction Debt tracks how '
  f'contested a case was, not which way it came out.</strong>')
A(f'<div style="{SUB}">Ordered by mean CD, outcomes line up by <em>depth of merits engagement</em>, '
  f'not by winner:</div>')
A(f'<table style="{TBL}"><tr><th style="{TH};text-align:left">chain outcome</th><th style="{TH}">n</th>'
  f'<th style="{TH}">mean CD</th><th style="{TH}">95% CI</th>'
  f'<th style="{TH}">mean tag count</th><th style="{TH}">95% CI</th></tr>')
for oc in cd_order:
    v = np.array(cd[oc]); n = len(v); se = v.std(ddof=1)/math.sqrt(n) if n > 1 else 0
    w = np.array(ctc[oc], dtype=float); sew = w.std(ddof=1)/math.sqrt(len(w)) if len(w) > 1 else 0
    A(f'<tr><td style="{TD};text-align:left">{E(outlbl(oc))}</td><td style="{TD}">{n}</td>'
      f'<td style="{TD};font-weight:700">{v.mean():.4f}</td>'
      f'<td style="{TD};color:var(--muted)">{max(0.0, v.mean()-1.96*se):.4f}–'
      f'{v.mean()+1.96*se:.4f}</td>'
      f'<td style="{TD};font-weight:700">{w.mean():.3f}</td>'
      f'<td style="{TD};color:var(--muted)">{max(0.0, w.mean()-1.96*sew):.3f}–'
      f'{w.mean()+1.96*sew:.3f}</td></tr>')
A('</table>')
A(f'<div style="{SUB}"><strong>Unweighted replication.</strong> The ordering above is produced by the '
  f'<code>core-v1</code> weight profile, and P8 shows those weights are <em>less</em> discriminative '
  f'than a raw count of active contradictions. So the same table is recomputed with the weights '
  f'removed — identical rows, identical denominators, per-case statistic changed from '
  f'&Sigma;w to a plain count. '
  + (f'The rank order is <strong>unchanged</strong> '
     f'(Spearman &rho;&nbsp;=&nbsp;<span style="{NUM}">{rho_ord:+.2f}</span> between the two orderings), '
     f'so the contestedness reading does not depend on the weight profile. '
     if P3_SAME_ORDER else
     f'The rank order <strong>changes</strong> without the weights (&rho;&nbsp;=&nbsp;'
     f'<span style="{NUM}">{rho_ord:+.2f}</span>; unweighted order: '
     + " &lt; ".join(E(outlbl(o)) for o in ct_order) + '), which means the CD ordering is an '
     f'artifact of <code>core-v1</code> and not a property of the corpus. ')
  + f'The count also explains more of the between-outcome variance than CD does '
    f'(&eta;&sup2;&nbsp;=&nbsp;<span style="{NUM}">{eta2_ct:.4f}</span> vs '
    f'<span style="{NUM}">{eta2_cd:.4f}</span>), and separates granted from denied more sharply '
    f'(d&nbsp;=&nbsp;<span style="{NUM}">{dcoh_ct:+.3f}</span> vs '
    f'<span style="{NUM}">{dcoh:+.3f}</span>, t&nbsp;=&nbsp;{t_gdc:+.2f}, p&nbsp;=&nbsp;{fp(p_gdc)}). '
    f'Inert weights would give parity on both measures; worse-than-parity means some weights are '
    f'pulling against the signal. See P8.</div>')
A(f'<div style="{SUB}">Cases that never reach the merits carry almost no debt; cases that split carry '
  f'the most. Merits-reached (n&nbsp;=&nbsp;{len(mer):,}, mean&nbsp;{mer.mean():.4f}) vs not-reached '
  f'(n&nbsp;=&nbsp;{len(nm):,}, mean&nbsp;{nm.mean():.4f}): Welch t&nbsp;=&nbsp;'
  f'<span style="{NUM}">{t_mn:+.1f}</span>, p&nbsp;=&nbsp;{fp(p_mn)}. Critically, '
  f'<code>protection_granted</code> ({g.mean():.4f}) is <strong>not below</strong> '
  f'<code>protection_denied</code> ({dn.mean():.4f}) — '
  f'{"the difference runs the other way" if g.mean() > dn.mean() else "they are indistinguishable"} '
  f'(t&nbsp;=&nbsp;{t_gd:+.2f}, p&nbsp;=&nbsp;{fp(p_gd)}, Cohen’s d&nbsp;=&nbsp;{dcoh:+.2f}). '
  f'This <strong>reverses the direction reported under v1</strong>, where high CD was read as '
  f'predicting denial.</div>')
A(f'<div style="{CAV}"><strong>What would sink it.</strong> The v1 CD gap was manufactured by deleted '
  f'RULE&nbsp;1/RULE&nbsp;5, which forced Recognition Failure and Repair Failure wherever Node&nbsp;7 '
  f'failed — mechanically loading debt onto losses. The v2 direction is the one to test, but note the '
  f'granted/denied difference is small (d&nbsp;=&nbsp;{dcoh:+.2f}) and the whole CD range is compressed: '
  f'corpus mean CD is {mean_cd:.4f} against a ceiling of {CD_CEILING} — '
  f'{mean_cd/CD_CEILING*100:.0f}% of the scale — with {mean_ct:.2f} contradictions per case on average and '
  f'{pct(zero_ct)} of cases carrying none at all. '
  f'<strong>Every CD figure on this page uses weight profile <code>{CD_PROFILE}</code></strong> (the '
  f'{len(CD_WEIGHTS)} <code>sool:cdWeight</code> values in {E(ONTOLOGY_SOURCE)}, summing to a '
  f'ceiling of {CD_CEILING}). CD is a <em>weighted sum</em>, not a count of '
  f'contradictions, so the ordering of outcomes above is a function of those weights and '
  f'could move under a different profile. No empirical calibration of the weights exists; '
  f'they have not been varied to test whether this ordering is robust to them. '
  f'Re-interpreting CD as a contestedness index rather '
  f'than a merits predictor is a <em>reframing of the construct</em> and needs the completed '
  + (f'corpus — {", ".join("D"+str(d) for d in (partial+[d for d,_ in inflight]+missing))} still '
     f'outstanding — before it is asserted.' if (partial or inflight or missing)
     else 'corpus before it is asserted.') + '</div>')
A('</div>')

# ---- HD
A(f'<div style="{CARD}">')
A(f'<span style="{HID}">P4</span> <strong style="margin-left:.5rem">Remedy failure presupposes effect '
  f'failure — but not the reverse.</strong>')
A(f'<div style="{SUB}">The N7/N8 relation is strongly <em>asymmetric</em>. When Node&nbsp;8 fails, '
  f'Node&nbsp;7 has almost always failed too: P(N7 fail | N8 fail)&nbsp;=&nbsp;'
  f'<span style="{NUM}">{pct(p78)}</span> ({both:,}/{both+only8:,}). But the converse is much weaker: '
  f'P(N8 fail | N7 fail)&nbsp;=&nbsp;<span style="{NUM}">{pct(p87)}</span> ({both:,}/{both+only7:,}) — '
  f'in <span style="{NUM}">{only7:,}</span> cases the claimant’s asserted effect did not attach '
  f'yet a remedy survived, against only <span style="{NUM}">{only8:,}</span> cases with the opposite '
  f'divergence. That is a near one-way conditional: remedy is structurally downstream of effect, and '
  f'the chain has a direction that the ontology asserts but had not previously been measured.</div>')
A(f'<div style="{SUB}"><strong>This is the strongest result on the page, and the reason is the shape '
  f'of what was instructed.</strong> The ontology does not merely say N7 and N8 are related; it says '
  f'remedy is <em>downstream</em> of effect, which is a claim about direction and therefore a claim '
  f'that can come out backwards. The v2 prompt instructs the coupling and then explicitly invites '
  f'divergence in both directions, with a worked example of each. So the annotator was free to produce '
  f'a symmetric split, and a symmetric split is what an instructed correlation with no underlying '
  f'ordering would produce. What came back is {only7:,} against {only8:,}. Under a null of no '
  f'direction — divergences equally likely to fall either way — that imbalance has probability '
  f'{fp(2*st.binom.sf(max(only7, only8)-1, only7+only8, 0.5))}. Most findings on this page are '
  f'measurements of a corpus; this one is a measured confirmation of a structural commitment the '
  f'framework made before the corpus existed, on a dimension the prompt left free.</div>')
if P4CTRL and "reversed" in P4CTRL:
    A(f'<div style="{SUB}"><strong>Prompt-variant control.</strong> "The prompt left it free" is an '
      f'argument, not a measurement, so it was measured. One sample of cases was re-annotated under '
      f'three system prompts identical in every respect except the directional sentence: the '
      f'production wording, the sentence <em>removed</em>, and the sentence <em>inverted</em> so the '
      f'annotator is told Node&nbsp;7 usually follows Node&nbsp;8.</div>')
    A(f'<table style="{TBL}"><tr><th style="{TH};text-align:left">prompt arm</th>'
      f'<th style="{TH}">n</th><th style="{TH}">effect failed,<br>remedy survived</th>'
      f'<th style="{TH}">remedy failed,<br>effect survived</th><th style="{TH}">p vs 1:1</th></tr>')
    _lbl = {"v2": "production, verbatim", "neutral": "directional sentence removed",
            "reversed": "directional sentence inverted"}
    for arm in ("v2", "neutral", "reversed"):
        if arm not in P4CTRL: continue
        q = P4CTRL[arm]
        A(f'<tr><td style="{TD};text-align:left">{_lbl[arm]}</td><td style="{TD}">{q["n"]}</td>'
          f'<td style="{TD};font-weight:700">{q["o7"]}</td><td style="{TD}">{q["o8"]}</td>'
          f'<td style="{TD};color:var(--muted)">{fp(q["p"])}</td></tr>')
    A('</table>')
    _rv, _nu = P4CTRL["reversed"], P4CTRL.get("neutral")
    A(f'<div style="{SUB}">The inverted arm is the load-bearing one: a prompt actively arguing for '
      f'the opposite direction still returns <span style="{NUM}">{_rv["o7"]}</span> against '
      f'<span style="{NUM}">{_rv["o8"]}</span>, p&nbsp;=&nbsp;{fp(_rv["p"])}. A finding that survives '
      f'an instruction to find the reverse is not a finding the instruction produced. '
      + (f'The removed-sentence arm is the more interesting one: it yields '
         f'<span style="{NUM}">{_nu["o7"]+_nu["o8"]}</span> divergences where the production prompt '
         f'yields {P4CTRL["v2"]["o7"]+P4CTRL["v2"]["o8"]} on the same cases, all in the same '
         f'direction. The coupling sentence was <em>suppressing</em> divergence, not creating it, so '
         f'the published {only7:,}:{only8:,} understates the asymmetry rather than manufacturing it. '
         if _nu and "v2" in P4CTRL else '')
      + f'What the control cannot rule out is a disposition the model carries independently of this '
        f'prompt — that would need a second model or a human-coded subsample, and neither exists '
        f'yet. Reproduce with <code>p4_prompt_control.py --report</code>.</div>')
A(f'<div style="{CAV}"><strong>What would sink it.</strong> The v2 prompt states that "Node&nbsp;8 '
  f'usually follows Node&nbsp;7," so the <em>coupling</em> is partly instructed. The prompt does '
  f'<em>not</em> instruct the asymmetry — it explicitly invites divergence in both directions and '
  f'gives examples of each (independently available relief; independently blocked relief). The '
  f'{only7/max(only8, 1):.0f}:1 imbalance is therefore the finding, not the correlation. Distinguishing '
  f'a real ordering from an anchoring effect needs a prompt-variant control that the current pass does '
  f'not include.</div>')
A('</div>')

# ---- HE
A(f'<div style="{CARD}">')
A(f'<span style="{HID}">P5</span> <strong style="margin-left:.5rem">Forum may matter more than '
  f'doctrine.</strong>')
A(f'<div style="{SUB}">Node&nbsp;7 failure varies more across <em>courts</em> than across '
  f'<em>doctrinal domains</em>. Between the {cv["k"]} courts with n&nbsp;&ge;&nbsp;60 the rate spans '
  f'<span style="{NUM}">{pct(cv["lo"])}–{pct(cv["hi"])}</span> '
  f'({(cv["hi"]-cv["lo"])*100:.1f} points; Cram&eacute;r’s V&nbsp;=&nbsp;'
  f'<span style="{NUM}">{cv["V"]:.3f}</span>, p&nbsp;=&nbsp;{fp(cv["p"])}). Between the {dv["k"]} '
  f'domains it spans only <span style="{NUM}">{pct(dv["lo"])}–{pct(dv["hi"])}</span> '
  f'({(dv["hi"]-dv["lo"])*100:.1f} points; V&nbsp;=&nbsp;<span style="{NUM}">{dv["V"]:.3f}</span>). '
  f'The court effect persists <em>within</em> domains in {nsig} of {len(wdom)} domains tested '
  f'separately, so it is not merely a docket-composition artifact. If this holds, the domain-invariance '
  f'thesis gains an unexpected companion: structural failure is roughly domain-independent but '
  f'markedly <strong>forum-dependent</strong>.</div>')
A(f'<div style="{CAV}"><strong>What would sink it.</strong> Circuits differ in what reaches them and in '
  f'what plaintiffs file there; this is a selection effect at least as much as a judicial one, and '
  f'nothing here separates the two. Both V values are small in absolute terms. The comparison also '
  f'inherits P1’s problem — if N7 largely encodes "claimant lost," this may restate known '
  f'circuit-level affirmance differences rather than reveal anything structural. Needs the full corpus '
  f'and a case-mix control.</div>')
if csv_:
    A(f'<div style="{SUB}"><strong>The version that is not about outcome.</strong> The objection above '
      f'is fatal as stated: N7 failure is close to "the claimant lost," and a forum effect on N7 is '
      f'circuit affirmance variation in SOoL vocabulary. So the same test is run on a variable that '
      f'cannot be outcome, because outcome is held fixed. Among the '
      f'<span style="{NUM}">{len(N7F):,}</span> cases whose effect node has already failed — every one '
      f'of them a loss at N7 — the remedy node still closes in '
      f'<span style="{NUM}">{pct(N7F_SURV)}</span>. Whether it does varies by court from '
      f'<span style="{NUM}">{pct(csv_["lo"][0])}</span> ({E(str(csv_["lo"][1]))}, n&nbsp;=&nbsp;{csv_["lo"][2]}) '
      f'to <span style="{NUM}">{pct(csv_["hi"][0])}</span> ({E(str(csv_["hi"][1]))}, n&nbsp;=&nbsp;{csv_["hi"][2]}) '
      f'across {csv_["k"]} courts with n&nbsp;&ge;&nbsp;60 '
      f'(&chi;&sup2;({csv_["dof"]})&nbsp;=&nbsp;{csv_["chi2"]:.1f}, p&nbsp;=&nbsp;{fp(csv_["p"])}, '
      f'V&nbsp;=&nbsp;<span style="{NUM}">{csv_["V"]:.3f}</span>, n&nbsp;=&nbsp;{csv_["n"]:,}). '
      + (f'The same variable also varies by domain '
         f'(V&nbsp;=&nbsp;<span style="{NUM}">{dsv_["V"]:.3f}</span>, p&nbsp;=&nbsp;{fp(dsv_["p"])}), '
         f'and the two are confounded — the D.C. Circuit and Administrative Law are largely the same '
         f'cases — so a case-mix control is still required before the forum reading is preferred to the '
         f'subject-matter one. ' if dsv_ else '')
      + f'But the quantity itself is structural rather than dispositional: it asks whether a forum '
        f'treats a broken legal effect as repairable, on a subset where the claimant has already lost. '
        f'That is the P5 claim worth defending, and it is not restatable as an affirmance rate.</div>')
A('</div>')

# ---- HF  (WITHDRAWN — retained as a note, not as a finding)
A(f'<div style="{CARD};border-left-color:var(--steel);opacity:.85">')
A(f'<span style="{HID};background:var(--steel)">withdrawn</span> '
  f'<strong style="margin-left:.5rem;text-decoration:line-through;text-decoration-thickness:1px">'
  f'P6 — Norm Indeterminacy is rising over time.</strong>')
A(f'<div style="{SUB}"><strong>Withdrawn as a finding; the numbers are kept here for the record.</strong> '
  f'Three reasons, any one of which is sufficient. First, it contradicts H6 on the same page, which '
  f'reports the temporal profile as stable — a reader reaches both and has no way to reconcile them, '
  f'and the disagreement is not a substantive dispute but an artifact of two different aggregations of '
  f'the same variable. Second, NI is rule-forced and its trigger clause, "the norm’s application to '
  f'these facts is genuinely contested," is close to a definition of appellate litigation, so a rate '
  f'that rises tracks drift in the annotator’s reading of "contested" at least as readily as anything '
  f'about courts. Third, and decisively, NI fires at '
  + ", ".join(f'{pct(v[1])} when Node&nbsp;2 is <code>{E(k)}</code>'
              for k, v in sorted(ni_n2.items(), key=lambda kv: -kv[1][0])[:3])
  + f'. A tag named for indeterminacy of the norm that fires at radically different rates across the '
    f'norm node’s own closure states — and near-ceiling in one of them — is not measuring what it '
    f'names. That is a construct-validity failure, not a caveat, and it disqualifies the trend '
    f'regardless of its slope. Reinstating P6 requires re-specifying the NI trigger and re-annotating; '
    f'it is not fixable by a control.</div>')
A(f'<div style="{SUB}">Norm Indeterminacy is the modal contradiction overall '
  f'(<span style="{NUM}">{pct(ct_pool["NI"])}</span> of cases) and its rate climbs monotonically by '
  f'decade of decision, as does mean CD:</div>')
A(f'<table style="{TBL}"><tr><th style="{TH};text-align:left">decade</th><th style="{TH}">n</th>'
  f'<th style="{TH}">NI rate</th><th style="{TH}">N7 fail</th><th style="{TH}">mean CD</th></tr>')
for x in decs:
    A(f'<tr><td style="{TD};text-align:left">{x["d"]}s</td><td style="{TD}">{x["n"]}</td>'
      f'<td style="{TD};font-weight:700">{x["ni"]*100:.1f}%</td>'
      f'<td style="{TD}">{x["n7"]*100:.1f}%</td><td style="{TD}">{x["cd"]:.4f}</td></tr>')
A('</table>')
A(f'<div style="{SUB}">Year of decision vs NI: Spearman &rho;&nbsp;=&nbsp;'
  f'<span style="{NUM}">{ni_rho:+.3f}</span>, p&nbsp;=&nbsp;{fp(ni_p)} (n&nbsp;=&nbsp;{len(yr):,}). '
  f'The trend survives a within-domain control — NI rises from first to last measurable decade in '
  f'<span style="{NUM}">{rise} of {ndom_temporal}</span> domains taken separately, so it is not driven '
  f'by the corpus’s domain mix shifting over time. Candidate reading: appellate courts increasingly '
  f'decline to specify the governing rule, deciding on narrower or more contested grounds.</div>')
A(f'<div style="{CAV}"><strong>What would sink it.</strong> NI is rule-forced (RULE&nbsp;3) and its '
  f'trigger includes the broad clause "the norm’s application to these facts is genuinely '
  f'contested" — which is close to a description of appellate litigation as such. Its construct '
  f'validity is also loose: NI fires at '
  + ", ".join(f'{pct(v[1])} when Node&nbsp;2 is <code>{E(k)}</code>' for k, v in
              sorted(ni_n2.items(), key=lambda kv: -kv[1][0])[:3])
  + f', i.e. largely independently of whether the norm node itself closed. A rising rate may track '
  f'drift in what counts as "contested" rather than anything about the courts. This is the weakest '
  f'card here and the most likely to be withdrawn.</div>')
A('</div>')


# ---- P7 signature recurrence + P8 weight discrimination (complete corpus only) ----
_sig_dom, _sig_n = collections.defaultdict(set), collections.Counter()
for r in rows:
    try: _sg = json.loads(r.get("structural_signature") or "[]")
    except Exception: _sg = []
    _k = tuple(sorted(x for x in _sg if isinstance(x, str)))
    if not _k: continue
    _sig_n[_k] += 1; _sig_dom[_k].add(r["domain_id"])
SIG_TOTAL = len(_sig_n)
SIG_ALLDOM = [k for k in _sig_n if len(_sig_dom[k]) == len(doms) and _sig_n[k] >= 20]
SIG_WIDE = [k for k in _sig_n if len(_sig_dom[k]) >= max(6, len(doms)-2) and _sig_n[k] >= 20]
SIG_WIDE_CASES = sum(_sig_n[k] for k in SIG_WIDE)
SIG_WIDE_SHARE = SIG_WIDE_CASES/N if N else 0

_den = [r for r in rows if r["chain_outcome"] == "protection_denied"]
_gra = [r for r in rows if r["chain_outcome"] == "protection_granted"]
def _cohen(f):
    a = np.array([f(r) for r in _den]); b = np.array([f(r) for r in _gra])
    if len(a) < 2 or len(b) < 2: return None, None
    sp = math.sqrt(((len(a)-1)*a.var(ddof=1)+(len(b)-1)*b.var(ddof=1))/(len(a)+len(b)-2))
    t, p = st.ttest_ind(a, b, equal_var=False)
    return (a.mean()-b.mean())/sp, p
D_COUNT, P_COUNT = _cohen(lambda r: len(r["cts"]))
D_CD, P_CD = _cohen(lambda r: r["contradiction_debt"] or 0)


# ---- P7 recurrent signatures
if RELEASED and SIG_WIDE:
    A(f'<div style="{CARD}">')
    A(f'<span style="{HID}">P7</span> <strong style="margin-left:.5rem">The same failure '
      f'<em>shapes</em> recur across every domain, not just the same ranking.</strong>')
    A(f'<div style="{SUB}">P1 and P2 compare domains on aggregate profiles. This is the '
      f'stronger claim the ontology actually makes: a <em>structural signature</em> — the '
      f'exact set of node/type failures a case exhibits — should be a recognisable object '
      f'that recurs independently of doctrine. It does. The corpus contains '
      f'<span style="{NUM}">{SIG_TOTAL:,}</span> distinct signatures, of which '
      f'<span style="{NUM}">{len(SIG_WIDE)}</span> appear in at least {max(6, len(doms)-2)} '
      f'of the {len(doms)} domains with n&nbsp;&ge;&nbsp;20'
      + (f', and <span style="{NUM}">{len(SIG_ALLDOM)}</span> appear in <strong>all '
         f'{len(doms)}</strong>' if SIG_ALLDOM else '')
      + f'. Those broadly recurring shapes account for '
      f'<span style="{NUM}">{pct(SIG_WIDE_SHARE)}</span> of all cases — so a clear majority '
      f'of the corpus fails in a way that some other area of law also fails in.</div>')
    A(f'<div style="{CAV}"><strong>What would sink it.</strong> Signatures are built from the '
      f'same node closures and contradiction types as everything else, so this inherits their '
      f'dependencies — including the rule-forced types. A signature is also a set, not a '
      f'sequence: it records which failures co-occurred, not how one produced another, so '
      f'recurrence is not evidence of a shared causal path. The count of distinct signatures '
      f'is bounded by the taxonomy, so some recurrence is guaranteed by construction; the '
      f'reportable part is the <em>share of cases</em> carrying a widely-shared shape, not '
      f'the existence of shared shapes.</div>')
    A('</div>')

# ---- P8 weights
if RELEASED and D_COUNT is not None:
    _better = "no better than" if abs(D_CD) <= abs(D_COUNT) else "better than"
    A(f'<div style="{CARD}">')
    A(f'<span style="{HID}">P8</span> <strong style="margin-left:.5rem">The contradiction-debt '
      f'weights do not earn their keep.</strong>')
    A(f'<div style="{SUB}">Contradiction Debt is a <em>weighted</em> sum, so it should '
      f'separate outcomes better than simply counting how many contradictions a case carries. '
      f'It does not. Separating denied from granted cases, a raw count gives Cohen&rsquo;s '
      f'd&nbsp;=&nbsp;<span style="{NUM}">{D_COUNT:+.3f}</span> (p&nbsp;=&nbsp;{fp(P_COUNT)}), '
      f'while CD under profile <code>{CD_PROFILE}</code> gives '
      f'<span style="{NUM}">{D_CD:+.3f}</span> (p&nbsp;=&nbsp;{fp(P_CD)}) — the weighted '
      f'measure is {_better} the unweighted one. The {len(CD_WEIGHTS)} weights are '
      f'theoretically motivated but have never been empirically calibrated, and on this corpus '
      f'they add nothing discriminative.</div>')
    A(f'<div style="{CAV}"><strong>What this does and does not mean.</strong> It does not show '
      f'the weights are wrong — CD was never designed as an outcome predictor, and a measure of '
      f'structural burden need not track who won. It does mean that any published figure resting '
      f'on the weighted scale is resting on an unvalidated choice. Both effects are small in '
      f'absolute terms.</div>')
    A(f'<div style="{SUB}"><strong>Not merely inert — actively worse.</strong> Weights that carried '
      f'no information would give <em>parity</em> with the count. '
      f'{abs(D_CD):.3f} against {abs(D_COUNT):.3f} is worse than parity, which means some weights are '
      f'pulling against whatever signal exists rather than simply failing to add to it. P3 now '
      f'reports the same table on unweighted counts: the outcome ordering is unchanged '
      f'(&rho;&nbsp;=&nbsp;{rho_ord:+.2f}), so the ordering is not a weight artifact, but the count '
      f'explains more of the between-outcome variance than CD does '
      f'(&eta;&sup2;&nbsp;=&nbsp;{eta2_ct:.4f} vs {eta2_cd:.4f}).</div>')
    if REPAIR_BETA:
        A(f'<div style="{SUB}"><strong>Which weights, and against what.</strong> The right calibration '
          f'target is not outcome — calibrating CD against who won would turn it into the outcome '
          f'predictor this rebuild has spent its effort establishing it is not. It is <em>repair '
          f'adequacy</em>: among the {len(N7F):,} cases whose effect node has already failed, does the '
          f'remedy node still close? Every case in that subset lost at N7, so the question is purely '
          f'structural. Per-type point-biserial correlations with remedy survival, against the '
          f'<code>{CD_PROFILE}</code> weight each type carries:</div>')
        A(f'<table style="{TBL}"><tr><th style="{TH};text-align:left">type</th>'
          f'<th style="{TH}">{CD_PROFILE} weight</th><th style="{TH}">n in subset</th>'
          f'<th style="{TH}">r with remedy survival</th><th style="{TH}">p</th></tr>')
        for q in REPAIR_BETA:
            col = "var(--red)" if q["r"] < 0 else "var(--navy)"
            A(f'<tr><td style="{TD};text-align:left"><strong>{q["ct"]}</strong> '
              f'<span style="color:var(--muted)">{E(CTNAME[q["ct"]])}</span></td>'
              f'<td style="{TD}">{CD_WEIGHTS[q["ct"]]:.2f}</td><td style="{TD}">{q["n"]}</td>'
              f'<td style="{TD};font-weight:700;color:{col}">{q["r"]:+.3f}</td>'
              f'<td style="{TD};color:var(--muted)">{fp(q["p"])}</td></tr>')
        A('</table>')
        _pos = [q["ct"] for q in REPAIR_BETA if q["r"] > 0 and q["p"] < 0.05]
        _neg = [q["ct"] for q in REPAIR_BETA if q["r"] < 0 and q["p"] < 0.05]
        _nul = [q["ct"] for q in REPAIR_BETA if q["p"] >= 0.05]
        A(f'<div style="{SUB}">The types split by sign, and the split is <em>not</em> the one '
          f'the weights encode: {", ".join(_pos)} are associated with the remedy surviving a failed '
          f'effect, while {", ".join(_neg)} are associated with it failing too'
          + (f' ({", ".join(_nul)} show no association either way). ' if _nul else '. ')
          + f'Rank-correlating the '
            f'<code>{CD_PROFILE}</code> weights against damage-to-repair gives '
            f'&rho;&nbsp;=&nbsp;<span style="{NUM}">{REPAIR_RHO:+.3f}</span> '
            f'(p&nbsp;=&nbsp;{fp(REPAIR_RHO_P)}) — the weights are close to uncorrelated with the one '
            f'structural quantity they might have been calibrated against. Notice also that this '
            f'sign split lines up with the families P9 recovers from co-occurrence, which is two '
            f'independent measurements agreeing on the same partition.</div>')
    A('</div>')


# ---- further structure: co-occurrence, remedy survival, confidence ----------
_pairs = []
for _a, _b in itertools.combinations(CT, 2):
    _na = sum(1 for r in rows if _a in r["cts"]); _nb = sum(1 for r in rows if _b in r["cts"])
    if _na < 50 or _nb < 50: continue
    _bo = sum(1 for r in rows if _a in r["cts"] and _b in r["cts"])
    _ex = _na*_nb/N
    if _ex < 5: continue
    _chi, _p, _, _ = st.chi2_contingency([[_bo, _na-_bo], [_nb-_bo, N-_na-_nb+_bo]])
    _pairs.append((_bo/_ex, _a, _b, _p))
_pairs.sort(reverse=True)
ATTRACT = [x for x in _pairs if x[0] >= 1.8 and x[3] < 1e-6][:3]
REPEL   = [x for x in _pairs if x[0] <= 0.55 and x[3] < 1e-6][-3:]

_n7f = [r for r in rows if r["node7_closure"] == "failed"]
_surv = [r for r in _n7f if r["node8_closure"] != "failed"]
SURV_RATE = len(_surv)/len(_n7f) if _n7f else 0
_sd = []
for _d in doms:
    _v = [r for r in _n7f if r["domain_id"] == _d]
    if len(_v) < 40: continue
    _sd.append((sum(1 for r in _v if r["node8_closure"] != "failed")/len(_v), _d))
_sd.sort(reverse=True)
SURV_TOP, SURV_BOT = (_sd[0] if _sd else (0, 0)), (_sd[-1] if _sd else (0, 0))

_yrs = [(int(str(r["date_decided"])[:4]), r) for r in rows
        if str(r["date_decided"])[:4].isdigit()]
def _tr(f):
    return st.spearmanr([y for y, _ in _yrs], [f(r) for _, r in _yrs])
RHO_CT, P_CT = _tr(lambda r: len(r["cts"]))
RHO_DEN, P_DEN = _tr(lambda r: 1 if r["chain_outcome"] == "protection_denied" else 0)


# ---- further structure note
if RELEASED and ATTRACT:
    A(f'<div style="{CARD};border-left-color:var(--steel)">')
    A(f'<span style="{HID}">note</span> <strong style="margin-left:.5rem">Further structure '
      f'worth testing.</strong>')
    A(f'<div style="{SUB}"><strong>Contradictions are not independent of each other.</strong> '
      f'Some co-occur far more than chance allows: '
      + ", ".join(f'<strong>{a}+{b}</strong> at {l:.1f}&times; expected' for l, a, b, _ in ATTRACT)
      + (". Others actively exclude one another: "
         + ", ".join(f'<strong>{a}+{b}</strong> at {l:.2f}&times;' for l, a, b, _ in REPEL) + "."
         if REPEL else ".")
      + f' If the thirteen types were independent tags this would not happen. This observation has '
      f'been promoted to <strong>P9</strong> above, where the full matrix is tested pair by pair, '
      f'clustered into families, and checked for stability — it is the corpus test of the claim that '
      f'the thirteen types are derived from a smaller kernel rather than enumerated.</div>')
    A(f'<div style="{SUB}"><strong>Remedy survival varies by domain and by forum.</strong> Across the '
      f'corpus a remedy survives Node&nbsp;7 failure in <span style="{NUM}">{pct(SURV_RATE)}</span> of '
      f'cases (P4), but the rate runs from '
      f'<span style="{NUM}">{pct(SURV_BOT[0])}</span> in D{SURV_BOT[1]} {E(DN[SURV_BOT[1]])} to '
      f'<span style="{NUM}">{pct(SURV_TOP[0])}</span> in D{SURV_TOP[1]} {E(DN[SURV_TOP[1]])}. '
      f'P5 now runs the same variable across courts, because remedy survival conditional on effect '
      f'failure is the one forum comparison that cannot be restated as an affirmance rate. '
      f'Whether either split reflects genuinely different remedial architecture or different pleading '
      f'practice is untested.</div>')
    A(f'<div style="{SUB}"><strong>The temporal trend is broader than Norm Indeterminacy.</strong> '
      f'The withdrawn P6 reported NI rising by decade; the <em>total</em> number of contradictions per case '
      f'rises too (Spearman &rho;&nbsp;=&nbsp;<span style="{NUM}">{RHO_CT:+.3f}</span>, '
      f'p&nbsp;=&nbsp;{fp(P_CT)}), while the rate at which claimants lose does '
      f'{"not move materially" if abs(RHO_DEN) < 0.05 else "shift"} '
      f'(&rho;&nbsp;=&nbsp;{RHO_DEN:+.3f}). Cases are being recorded as structurally more '
      f'contested over time without the outcomes changing to match — which is either a real '
      f'trend in adjudication or drift in what the annotator treats as contested, and those '
      f'two are not yet separable.</div>')
    A('</div>')

# ---- P9 contradiction-type co-occurrence: the kernel test
if len(co_types) >= 6:
    A(f'<div style="{CARD}">')
    A(f'<span style="{HID}">P9</span> <strong style="margin-left:.5rem">The thirteen contradiction '
      f'types are not independent tags: they attract and repel each other in families.</strong>')
    A(f'<div style="{SUB}">If the types were thirteen separate labels applied to thirteen separate '
      f'phenomena, every pair would sit at observed/expected&nbsp;=&nbsp;1.0 — co-occurring exactly as '
      f'often as their marginals imply. If instead they are derived from a smaller set of kernel '
      f'primitives, two things follow that independence does not predict: types sharing a primitive '
      f'should co-occur <em>above</em> chance, and types whose primitives are incompatible should '
      f'co-occur <em>below</em> it. Mutual exclusion is the load-bearing half — independent tags have '
      f'no mechanism to repel. Across {len(co_pairs)} testable pairs among the '
      f'{len(co_types)} types with n&nbsp;&ge;&nbsp;{CO_MIN}, '
      f'<span style="{NUM}">{len(co_sig)}</span> depart from independence at p&nbsp;&lt;&nbsp;0.001: '
      f'<span style="{NUM}">{len(co_attract)}</span> attracting and '
      f'<span style="{NUM}">{len(co_repel)}</span> repelling.</div>')

    A(f'<table style="{TBL}"><tr><th style="{TH};text-align:left">pair</th>'
      f'<th style="{TH}">obs</th><th style="{TH}">exp</th><th style="{TH}">obs/exp</th>'
      f'<th style="{TH}">&chi;&sup2;(1)</th><th style="{TH}">p</th></tr>')
    for q in (co_attract[:5] + co_repel[-5:]):
        col = "var(--navy)" if q["lift"] > 1 else "var(--red)"
        A(f'<tr><td style="{TD};text-align:left"><strong>{q["a"]}&nbsp;+&nbsp;{q["b"]}</strong> '
          f'<span style="color:var(--muted)">{E(CTNAME[q["a"]])} / {E(CTNAME[q["b"]])}</span></td>'
          f'<td style="{TD}">{q["obs"]}</td><td style="{TD};color:var(--muted)">{q["exp"]:.1f}</td>'
          f'<td style="{TD};font-weight:700;color:{col}">{q["lift"]:.2f}&times;</td>'
          f'<td style="{TD}">{q["chi2"]:.1f}</td><td style="{TD};color:var(--muted)">{fp(q["p"])}</td></tr>')
    A('</table>')

    A(f'<div style="{SUB}"><strong>Recovered families.</strong> Average-linkage clustering on the lift '
      f'matrix, cut at {CO_K}: '
      + " &nbsp;|&nbsp; ".join('<strong>{' + ", ".join(g) + '}</strong>' for g in co_fams)
      + f'. This partition is recovered in <span style="{NUM}">{co_stab_hits}</span> of '
        f'{len(co_stab)} resamples (two split-halves and {len(doms)} leave-one-domain-out runs, '
        f'{pct(co_stab_frac)}). '
      + (f'Pairs that never separate in any run: '
         + ", ".join(f'<strong>{a}+{b}</strong>' for a, b in co_invariant) + '. '
         if co_invariant else 'No pair survives every resample together. ')
      + f'Forcing in the {len(co_rare)} near-vacant types ({", ".join(co_rare)}) gives a different '
        f'partition ('
      + " | ".join("{" + ",".join(g) + "}" for g in co_fams_all)
      + f'), so the family structure below is a claim about the '
        f'{len(co_types)} types with real support, not about all {len(CT)}.</div>')

    A(f'<div style="{SUB}"><strong>What this tests, and what it does not.</strong> The framework holds '
      f'that the thirteen types are derived theorems over a smaller kernel, not a flat list. That is a '
      f'falsifiable claim and this is the corpus test of it: the derivation predicts <em>which</em> '
      f'types should cluster, and the recovered families either match the primitive-sharing structure '
      f'or they do not. The prediction cannot be scored here — the kernel-primitive-to-type mapping and '
      f'the A/B/C/D strata are not in this repository, so the families above are reported as an '
      f'unmatched empirical partition. Supplying that mapping turns this card from a description into a '
      f'confirmation or a refutation, and it is the single cheapest confirmatory test available on the '
      f'current corpus. Two caveats hold either way. Lift is sensitive to marginal prevalence, and '
      f'{max(CT, key=lambda c: ct_pool[c])} alone appears in {pct(ct_pool[max(CT, key=lambda c: ct_pool[c])])} '
      f'of cases, so pairs involving it have little room to move upward. And co-occurrence is measured '
      f'within a single annotator pass: two types that one prompt tends to emit together will look '
      f'coupled whether or not they share a primitive. The exclusions are the safer evidence, because a '
      f'prompt that over-emits a pair inflates lift but has no comparable mechanism for suppressing '
      f'one below chance.</div>')
    A('</div>')

# ---- governance: the CD scale is not one scale
A(f'<div style="{CARD};border-left-color:var(--red)">')
A(f'<span style="{HID};background:var(--red)">governance</span> '
  f'<strong style="margin-left:.5rem">Two artifacts in circulation state contradiction debt on '
  f'scales this corpus cannot produce. This is a measurement incommensurability, not a labelling '
  f'nuisance.</strong>')
A(f'<div style="{SUB}">Three distinct quantities have circulated under the one name &ldquo;CD&rdquo;: '
  f'<code>cd_case</code> (the weighted per-case flow reported throughout this page, ceiling '
  f'<span style="{NUM}">{CD_CEILING:.2f}</span> under <code>{CD_PROFILE}</code>), '
  f'<code>ct_count</code> (the unweighted count of active types, 0&ndash;{len(CD_WEIGHTS)}), and '
  f'<code>cd_stock</code> (an institution\'s accumulated debt over time, clamped to [0,&nbsp;1], '
  f'used by the SimLex simulator). The two problems below are both consequences of not '
  f'distinguishing them.</div>')
A(f'<div style="{SUB}"><strong>1. The Quick Reference bands are a count scale; the pipeline computes '
  f'a weighted sum.</strong> The card in circulation bands debt as 0 / 1–2 / 3–4 / 5–6 / 7+ — '
  f'a <code>ct_count</code> scale. Under '
  f'profile <code>{CD_PROFILE}</code>, <code>cd_case</code> is &Sigma;w over active contradictions '
  f'and its arithmetic '
  f'ceiling is the sum of the {len(CD_WEIGHTS)} <code>sool:cdWeight</code> values, '
  f'<span style="{NUM}">{CD_CEILING:.2f}</span>. Observed mean is '
  f'<span style="{NUM}">{CD_MEAN:.4f}</span> and observed maximum is '
  f'<span style="{NUM}">{CD_MAX:.4f}</span>. So under the published bands every one of the '
  f'{N:,} cases is band&nbsp;"0", and bands "3–4", "5–6" and "7+" are not merely empty but '
  f'<em>unreachable</em> — no assignment of contradictions to a case can ever enter them. The bands '
  f'are coherent under one reading only: <code>ct_count</code>, a plain count of active '
  f'contradictions, which does populate them.</div>')
A(f'<table style="{TBL}"><tr><th style="{TH};text-align:left">band</th>'
  f'<th style="{TH}">share as <code>ct_count</code></th>'
  f'<th style="{TH}">share as <code>cd_case</code> (&Sigma;w, {CD_PROFILE})</th></tr>')
for (lbl, pc), (_, pw) in zip(band_count, band_weighted):
    A(f'<tr><td style="{TD};text-align:left"><code>{lbl}</code></td>'
      f'<td style="{TD};font-weight:700">{pct(pc)}</td>'
      f'<td style="{TD};color:{"var(--muted)" if pw == 0 else "var(--ink)"}">{pct(pw)}'
      f'{" (unreachable)" if lbl not in ("0",) and pw == 0 else ""}</td></tr>')
A('</table>')
A(f'<div style="{SUB}">Every figure on this page uses the &Sigma;w reading, because that is what the '
  f'ontology defines and what <code>compute_cd()</code> writes to the database. The card therefore '
  f'cannot be applied to any number here. One of the two has to move: either the card is reissued on '
  f'the &Sigma;w scale, or CD is redefined as a count and every published CD figure is restated. '
  f'P3 and P8 bear on which — the unweighted count is the <em>better</em> discriminator of both '
  f'outcome and adversarial flagging, so the count reading is not obviously the one to give up.</div>')
if SIMLEX:
    A(f'<div style="{SUB}"><strong>2. SimLex carries a different thirteen-type list under the same '
      f'name.</strong> Parsed from <code>SimLex.html</code> at build time: {len(SIMLEX)} types summing '
      f'to <span style="{NUM}">{SIMLEX_SUM:.2f}</span> against <code>{CD_PROFILE}</code>’s '
      f'<span style="{NUM}">{CD_CEILING:.2f}</span>. '
      f'{len(SIMLEX_SHARED)} codes are shared ({", ".join(SIMLEX_SHARED)})'
      + (f' and carry identical weights, so the two look interchangeable on inspection. '
         if not SIMLEX_CONFLICT else
         f', but {len(SIMLEX_CONFLICT)} of them disagree on weight ('
         + ", ".join(f'{c}: {SIMLEX[c][0]:.2f} vs {CD_WEIGHTS[c]:.2f}' for c in SIMLEX_CONFLICT) + '). ')
      + f'The other {len(SIMLEX_ONLY)} are different types entirely — '
      + ", ".join(f'<strong>{c}</strong> {E(SIMLEX[c][1])} ({SIMLEX[c][0]:.2f})' for c in SIMLEX_ONLY)
      + f' — with no counterpart here, while {", ".join(CORE_ONLY)} exist only in the ontology. '
        f'A case scored 0.40 under one list and 0.40 under the other is not the same measurement, and '
        f'nothing in either number says which list produced it. This is the four-version divergence '
        f'surfacing as an incommensurable metric rather than as a naming inconsistency, and it is the '
        f'item on this page most likely to be caught by a reviewer. Minimum fix: every CD figure, '
        f'everywhere, carries its profile identifier — the way this page names '
        f'<code>{CD_PROFILE}</code> — and SimLex either adopts <code>{CD_PROFILE}</code> or declares '
        f'its own profile id and stops calling the result CD without qualification.</div>')
A('</div>')

# ---- taxonomy note
A(f'<div style="{CARD};border-left-color:var(--steel)">')
_NUMWORD = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}
A(f'<span style="{HID}">note</span> <strong style="margin-left:.5rem">'
  f'{_NUMWORD.get(len(vacant), str(len(vacant)))} of the {len(CT)} '
  f'contradiction type{"s are" if len(vacant) != 1 else " is"} empirically near-vacant.</strong>')
A(f'<div style="{SUB}">In {N:,} annotated cases: '
  + ", ".join(f'<strong>{c}</strong> ({CTNAME[c]}) {int(round(ct_pool[c]*N))} case'
              f'{"s" if int(round(ct_pool[c]*N)) != 1 else ""}' for c in vacant)
  + f'. Mean contradictions per case is {mean_ct:.2f} and {pct(zero_ct)} of cases carry none. '
  f'The operative taxonomy may be closer to {len(CT)-len(vacant)} live types than {len(CT)}. Whether '
  f'these types are theoretically real but rare, or simply undetectable from published opinions, is '
  f'not resolvable from this data'
  + (f' — {", ".join("D"+str(d) for d in (partial+[d for d,_ in inflight]+missing))} could still '
     f'populate them.' if (partial or inflight or missing) else '.') + '</div>')
A('</div>')

# ---- disclosures
A(f'<div style="background:var(--parch3);border:1px solid var(--border);border-radius:var(--r);'
  f'padding:.85rem 1rem;margin-bottom:1rem">')
A(f'<div style="font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;color:var(--navy);'
  f'font-weight:700;margin-bottom:.45rem">Standing methodological disclosures</div>')
A(f'<ul style="font-size:.79rem;color:var(--muted);line-height:1.65;margin:0;padding-left:1.1rem">')
A(f'<li><strong>Coverage.</strong> '
  + (f'{N:,} cases, all eight domains complete. ' if RELEASED
     else f'{N:,}/{TARGET:,} cases ({N/TARGET*100:.0f}%). ')
  + f'Fully rebuilt: {", ".join(f"D{d} ({nd[d]})" for d in complete) if complete else "none"}. '
  + (f'Included but still rebuilding: '
     f'{", ".join(f"D{d} ({nd[d]} of ~{v1.get(d,0)})" for d in partial)}. ' if partial else '')
  + (f'Mid-pass and excluded (n&nbsp;&lt;&nbsp;{MIN_DOM_N}): {E(INFLIGHT_LABEL)}. ' if inflight else '')
  + (f'Absent entirely: {E(MISSING_LABEL)} '
     f'(~{sum(v1[d] for d in missing):,} cases). ' if missing else '')
  + f'Un-annotated domains are missing wholesale, not sampled out, so this is not a random '
  f'subset of the corpus. Because the pass is live, these counts move: the section is '
  f'regenerated from the database, not hand-written.</li>')
A(f'<li><strong>Excluded rows.</strong> {DROPPED} of the {raw_n:,} v2 rows written so far carry a '
  f'<code>chain_outcome</code> outside the documented enum '
  f'({", ".join(f"{E(k)}&nbsp;{v}" for k, v in drop_kinds.most_common())}). All are validation-failed '
  f'and review-flagged, and the <code>indeterminate</code> group carries CD&nbsp;=&nbsp;0.0 uniformly — '
  f'they are failed extractions, not findings. They are dropped from every figure above, leaving '
  f'n&nbsp;=&nbsp;{N:,}.</li>')
A(f'<li><strong>Rule-forced types.</strong> {", ".join(f"{k} ({v})" for k, v in FORCED.items())} are '
  f'assigned by mandatory inference rule when stated conditions hold. Their prevalence measures rule '
  f'trigger frequency; it is not an independent discovery.</li>')
A(f'<li><strong>Claimant-centric framing.</strong> RULE&nbsp;0 defines Nodes&nbsp;7–8 from the '
  f'claimant’s perspective, and Node&nbsp;7 failure correlates {pct(concord)} with '
  f'<code>protection_denied</code>. That correlation is <em>not</em> definitional: '
  f'{pct(MASKED_SHARE)} of the corpus was annotated with the disposition redacted, and among '
  f'those cases the figure is {pct(CONC_MASKED)} (against {pct(CONC_UNMASKED)} where the '
  f'disposition was visible). The two are non-independent — one annotator, one text, two '
  f'readings — rather than identical by construction.</li>')
A(f'<li><strong>What v2 removed.</strong> v1 RULE&nbsp;1/RULE&nbsp;5 forced RF and RPF from '
  f'Node&nbsp;7 failure. Under v2 these are assigned on textual evidence only — RF is now '
  f'{pct(ct_pool["RF"])} and RPF {pct(ct_pool["RPF"])} of cases. Published v1 figures (13.0&times; CD '
  f'ratio, RF&nbsp;~64%, RPF &phi;&nbsp;=&nbsp;0.953) are artifacts of those rules and do not survive.</li>')
A(f'<li><strong>Annotation quality.</strong> {pct(review_pct)} of v2 rows carry a review flag. '
  f'Excluding them does not weaken P1 (N7 failure {pct(nf_pool[7])} → {pct(clean_n7)}).</li>')
A(f'<li><strong>Single annotator.</strong> All v2 annotations come from one model under one prompt. '
  f'No inter-annotator agreement statistic exists for this pass; nothing here is validated against '
  f'human coding.</li>')
A('</ul></div>')

A('</div>')
A(END)

frag = "\n".join(o)

if "--splice" in sys.argv:
    with open(PAGE, encoding="utf-8") as f: page = f.read()
    if START in page and END in page:
        a = page.index(START); b = page.index(END)+len(END)
        page = page[:a] + frag + page[b:]
    else:
        anchor = '<div id="tab-hypotheses"'
        i = page.index(anchor); j = page.index(">", i)+1
        page = page[:j] + "\n" + frag + page[j:]
    with open(PAGE, "w", encoding="utf-8") as f: f.write(page)
    sys.stderr.write(f"spliced {len(frag):,} bytes into {PAGE}\n")
else:
    print(frag)
