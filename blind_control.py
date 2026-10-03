#!/usr/bin/env python3
"""Covariate-blinding control — are the domain and forum effects in the cases or in the header?

build_user_prompt() (annotate_pipeline.py) hands the annotator a header before it sees a
word of the opinion:

    CASE: {case_name}
    CITATION: {citation}
    COURT: {court}  |  DATE: {date_filed}
    DOCTRINAL DOMAIN: {domain_name}

The disposition is masked. The covariates that P2 (domain-specific contradiction spikes)
and P5 (forum effects on Node 7) are built on are not. So the annotator knows it is
reading a 2019 Seventh Circuit administrative-law case before it reads any law, and a
model with priors about administrative law and about the Seventh Circuit can score from
those priors rather than from the text.

The observational diagnostic in sool_v2_audit.py says it partly does. Effect sizes fall
as opinion length rises — court -> denial Cramer's V 0.279 / 0.215 / 0.147 across length
tertiles, domain -> CD eta2 0.046 / 0.047 / 0.008 — which is the wrong direction for
text-driven measurement and the right one for prior-driven scoring. Decade runs the other
way (eta2 0.0009 / 0.0017 / 0.0046) and looks text-driven.

That diagnostic is observational: opinion length is not randomly assigned, and longer
opinions differ from shorter ones in ways other than how much text they contain. This
script settles it experimentally by paired re-annotation of the same cases with the
header fields redacted.

  full          production user prompt, verbatim
  blind         case name, citation, court, date and domain all redacted
  blind_forum   court and date redacted only  (decomposition, optional)
  blind_domain  domain redacted only          (decomposition, optional)

Paired design: every arm annotates the same sampled cases, so the comparison is
within-case and the sample is its own control. Sampling is stratified by court x domain,
because those are the variables whose effects are under test and a proportional sample
leaves the small circuits too thin to estimate. Length stratum is recorded so the
full-vs-blind gap can be checked against the length interaction the diagnostic predicts:
if the gap is real, it should be widest among short opinions.

RESIDUAL LEAKAGE, stated up front: the opinion body names the parties, cites the circuit's
own precedent, and carries its era in its citation formats. The blind arm removes the
header, not the case's identity. That biases the experiment toward finding no difference,
so a difference that does show up is a lower bound on leakage, not an estimate of it.

Reading the result:
  effect sizes collapse in `blind`   -> P2 and P5 are substantially prior artifacts
  effect sizes hold in `blind`       -> P2 and P5 are defensible for the first time
  effect sizes shrink partially      -> the ratio is a leakage correction factor

All three are publishable. The first is the most useful to the field.

Usage:
    python3 blind_control.py --n 600                       # full + blind, stratified
    python3 blind_control.py --n 600 --arms blind_forum    # add a decomposition arm
    python3 blind_control.py --report                      # re-print, no API calls
"""
import argparse, json, math, os, random, re, sqlite3, sys, time
from collections import defaultdict

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

CTRL_DB   = os.path.join(HOME, "blind_control.db")
CORPUS_DB = os.path.join(HOME, "sool_corpus.db")
ANN_DB    = os.path.join(HOME, "sool_annotations.db")
V2   = "claude-pipeline-v2"
SEED = 20260806
MIN_CHARS = 2000

TYPES = ["CF","AI","JC","RC3","PC","TC","FM","NI","RF","RCL","CC","SE","RPF"]
OK_OUTCOMES = ("protection_granted","protection_denied","partial",
               "remanded","dismissed","moot")

# Which header fields each arm redacts. Keys match the FIELDS patterns below.
ARM_REDACTS = {
    "full":         set(),
    "blind":        {"case","citation","court","date","domain"},
    "blind_forum":  {"court","date"},
    "blind_domain": {"domain"},
}
DEFAULT_ARMS = ("full", "blind")

# Each header line, matched verbatim against build_user_prompt()'s output. If the
# production prompt is edited these stop matching and the script exits rather than
# silently running an arm that redacts nothing.
FIELDS = {
    "case":     (re.compile(r"^CASE: .*$", re.M),              "CASE: [redacted]"),
    "citation": (re.compile(r"^CITATION: .*$", re.M),          "CITATION: [redacted]"),
    "court":    (re.compile(r"^COURT: [^|]*", re.M),           "COURT: [redacted]  "),
    "date":     (re.compile(r"\|  DATE: .*$", re.M),           "|  DATE: [redacted]"),
    "domain":   (re.compile(r"^DOCTRINAL DOMAIN: .*$", re.M),  "DOCTRINAL DOMAIN: [redacted]"),
}


def redact(prompt, fields):
    """Apply an arm's redactions to a production user prompt, failing loudly on a miss."""
    out = prompt
    for f in sorted(fields):
        pat, rep = FIELDS[f]
        out, n = pat.subn(rep, out, count=1)
        if n != 1:
            sys.stderr.write(
                f"FATAL: header field '{f}' not found in build_user_prompt() output.\n"
                "The production prompt has changed. Update FIELDS to match before\n"
                "running, or the blind arm will differ from `full` in unknown ways.\n")
            sys.exit(2)
    return out


def init_db():
    db = sqlite3.connect(CTRL_DB)
    db.execute("""create table if not exists blindarm(
        case_id integer, arm text, court text, domain_id integer, decade integer,
        len_stratum text, word_count integer,
        node7 text, node8 text, outcome text, cd real, cts text,
        raw text, err text, ts text,
        primary key(case_id, arm))""")
    db.commit()
    return db


def sample_cases(n):
    """Stratified by court x domain over cases the production pass annotated.

    Deliberately NOT stratified on node7, outcome or contradiction count: stratifying on
    a downstream variable would bias the very comparison the arms are meant to make.
    Strata are filled round-robin so that a circuit with few cases contributes all of
    them rather than being crowded out by ca9.
    """
    a = sqlite3.connect(ANN_DB)
    q = ("select case_id from annotations where annotator=? and chain_outcome in (%s)"
         % ",".join("?" * len(OK_OUTCOMES)))
    annotated = set()
    for (cid,) in a.execute(q, (V2,) + OK_OUTCOMES):
        try: annotated.add(int(cid))
        except (TypeError, ValueError): pass
    a.close()

    c = sqlite3.connect(CORPUS_DB); c.row_factory = sqlite3.Row
    rows = c.execute(
        """select ca.id, ca.court_id, ca.domain_id, ca.date_filed,
                  max(length(o.plain_text)) chars
           from cases ca join opinions o on o.case_id = ca.id
           where o.plain_text is not null
           group by ca.id having chars > ?""", (MIN_CHARS,)).fetchall()
    c.close()

    strata = defaultdict(list)
    meta = {}
    for r in rows:
        if r["id"] not in annotated:
            continue
        yr = int(r["date_filed"][:4]) if r["date_filed"] else None
        strata[(r["court_id"], r["domain_id"])].append(r["id"])
        meta[r["id"]] = (r["court_id"], r["domain_id"], (yr // 10 * 10) if yr else None,
                         r["chars"])

    rng = random.Random(SEED)
    for k in strata:
        rng.shuffle(strata[k])
    keys = sorted(strata)
    picked, i = [], 0
    while len(picked) < n and any(strata[k] for k in keys):
        k = keys[i % len(keys)]
        if strata[k]:
            picked.append(strata[k].pop())
        i += 1

    # Length stratum is assigned over the drawn sample, so the tertiles are comparable
    # to the ones in sool_v2_audit.py rather than to the corpus at large.
    by_len = sorted(picked, key=lambda cid: meta[cid][3])
    third = max(len(by_len) // 3, 1)
    strat = {}
    for j, cid in enumerate(by_len):
        strat[cid] = "short" if j < third else ("mid" if j < 2 * third else "long")
    return [(cid,) + meta[cid] + (strat[cid],) for cid in picked]


def load_case(c, cid):
    cs = c.execute("""select id, case_name, domain_id, domain_name, court_id,
                             date_filed, citations, docket_number, url
                      from cases where id=?""", (cid,)).fetchone()
    if not cs: return None
    case = dict(cs)
    case["opinions"] = [dict(r) for r in c.execute(
        """select opinion_type, author, per_curiam, plain_text, word_count
           from opinions where case_id=? and plain_text is not null
           order by length(plain_text) desc""", (cid,))]
    return case if case["opinions"] else None


def call_claude(ap, system, user):
    """Mirrors annotate_pipeline.call_claude()'s payload. `thinking: disabled` is load
    bearing — omitting it lets adaptive thinking eat max_tokens and truncate the JSON."""
    import urllib.request, urllib.error
    body = json.dumps({"model": ap.CLAUDE_MODEL, "max_tokens": ap.MAX_TOKENS,
                       "thinking": {"type": "disabled"},
                       "system": system,
                       "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": ap.CLAUDE_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode())
            txt = "".join(b.get("text","") for b in d.get("content",[])
                          if b.get("type") == "text").strip()
            if not txt:
                return "", f"empty response (stop_reason={d.get('stop_reason')})"
            return txt, ""
        except urllib.error.HTTPError as e:
            if e.code in (429,500,502,503,529) and attempt < 4:
                time.sleep(2 ** attempt * 3); continue
            return "", f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
        except Exception as e:
            if attempt < 4:
                time.sleep(2 ** attempt * 3); continue
            return "", f"{type(e).__name__}: {e}"
    return "", "retries exhausted"


def annotate_one(ap, arm, rec, mask):
    cid, court, dom, decade, chars, stratum = rec
    c = sqlite3.connect(f"file:{CORPUS_DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
    try:
        case = load_case(c, cid)
    finally:
        c.close()
    base = (cid, arm, court, dom, decade, stratum, chars)
    if not case:
        return base + (None,None,None,None,None,None,"no opinion text")
    try:
        user = ap.build_user_prompt(case, case["domain_id"], mask_disposition=mask)
        user = redact(user, ARM_REDACTS[arm])
        raw, err = call_claude(ap, ap.SYSTEM_PROMPT, user)
        if err: raise RuntimeError(err)
        ann, perr = ap.parse_claude_response(raw)
        if perr: raise ValueError(perr)
        nodes = ann.get("nodes") or {}
        def clo(n):
            v = nodes.get(str(n)) or nodes.get(n) or {}
            return (v.get("closure") if isinstance(v, dict) else v) or ""
        cts = [x.get("type") if isinstance(x, dict) else x
               for x in (ann.get("active_contradictions") or [])]
        return base + (clo(7), clo(8), ann.get("chain_outcome"),
                       ann.get("contradiction_debt"), json.dumps(cts), raw[:20000], None)
    except Exception as e:
        return base + (None,None,None,None,None,None, f"{type(e).__name__}: {e}"[:400])


def run_arm(ap, arm, recs, db, workers, sleep, mask):
    todo = [r for r in recs if not db.execute(
        "select 1 from blindarm where case_id=? and arm=? and err is null",
        (r[0], arm)).fetchone()]
    if not todo:
        print(f"  [{arm}] nothing to do ({len(recs)} cached)"); return
    print(f"  [{arm}] {len(todo)} to annotate ({len(recs)-len(todo)} cached), "
          f"{workers} workers", flush=True)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(annotate_one, ap, arm, r, mask) for r in todo]
        for f in as_completed(futs):
            row = f.result()
            db.execute("""insert or replace into blindarm
                (case_id,arm,court,domain_id,decade,len_stratum,word_count,
                 node7,node8,outcome,cd,cts,raw,err,ts)
                values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""", row)
            db.commit(); done += 1
            if done % 10 == 0 or done == len(todo):
                print(f"    {done}/{len(todo)}", flush=True)
            if sleep: time.sleep(sleep)


# ── analysis ────────────────────────────────────────────────────────────────
def cramers_v(tab):
    """tab: {row: {col: count}}. Returns V, or nan if degenerate."""
    rows = sorted(tab); cols = sorted({c for r in tab.values() for c in r})
    if len(rows) < 2 or len(cols) < 2: return float("nan")
    obs = [[tab[r].get(c, 0) for c in cols] for r in rows]
    n = sum(sum(r) for r in obs)
    if not n: return float("nan")
    rt = [sum(r) for r in obs]; ct = [sum(o[j] for o in obs) for j in range(len(cols))]
    chi2 = 0.0
    for i in range(len(rows)):
        for j in range(len(cols)):
            e = rt[i] * ct[j] / n
            if e > 0: chi2 += (obs[i][j] - e) ** 2 / e
    return math.sqrt(chi2 / (n * (min(len(rows), len(cols)) - 1)))


def eta_sq(groups):
    groups = [g for g in groups if len(g) > 1]
    if len(groups) < 2: return float("nan")
    allv = [x for g in groups for x in g]
    gm = sum(allv) / len(allv)
    ssb = sum(len(g) * (sum(g)/len(g) - gm) ** 2 for g in groups)
    sst = sum((x - gm) ** 2 for x in allv)
    return ssb / sst if sst else float("nan")


def report(db):
    print("\n" + "=" * 78)
    print("COVARIATE-BLINDING CONTROL")
    print("=" * 78)
    rows = db.execute("""select case_id,arm,court,domain_id,decade,len_stratum,
                                node7,outcome,cd,cts from blindarm where err is null""").fetchall()
    if not rows:
        print("  no completed annotations yet"); return
    arms = sorted({r[1] for r in rows}, key=lambda a: (a != "full", a))
    by_arm = defaultdict(list)
    for r in rows: by_arm[r[1]].append(r)

    print(f"\n  {'arm':<14}{'n':>6}{'denied':>9}{'mean CD':>10}{'mean n_ct':>11}")
    for a in arms:
        rs = by_arm[a]
        den = sum(1 for r in rs if r[7] == "protection_denied") / len(rs)
        cds = [r[8] for r in rs if r[8] is not None]
        ncts = [len(json.loads(r[9] or "[]")) for r in rs]
        print(f"  {a:<14}{len(rs):>6}{den:>9.3f}"
              f"{(sum(cds)/len(cds) if cds else float('nan')):>10.4f}"
              f"{(sum(ncts)/len(ncts) if ncts else float('nan')):>11.2f}")

    print("\n  Covariate effect size by arm — the headline comparison.")
    print("  A drop from `full` to `blind` is the leakage the header was carrying.")
    for cov, idx in [("COURT", 2), ("DOMAIN", 3), ("DECADE", 4)]:
        print(f"\n    {cov}")
        for metric in ("denied", "cd", "n_ct"):
            cells = []
            for a in arms:
                rs = [r for r in by_arm[a] if r[idx] is not None]
                grp = defaultdict(list)
                for r in rs: grp[r[idx]].append(r)
                grp = {k: v for k, v in grp.items() if len(v) >= 15}
                if len(grp) < 2:
                    cells.append(f"{a}: n/a"); continue
                if metric == "denied":
                    tab = {k: {"d": sum(1 for r in v if r[7] == "protection_denied"),
                               "o": sum(1 for r in v if r[7] != "protection_denied")}
                           for k, v in grp.items()}
                    cells.append(f"{a}: V={cramers_v(tab):.3f}")
                else:
                    f = ((lambda r: r[8]) if metric == "cd"
                         else (lambda r: len(json.loads(r[9] or "[]"))))
                    gs = [[f(r) for r in v if f(r) is not None] for v in grp.values()]
                    cells.append(f"{a}: eta2={eta_sq(gs):.4f}")
            print(f"      {metric:<8} " + "   ".join(cells))

    # Paired disagreement, and whether it concentrates where the diagnostic predicts.
    if "full" in by_arm and "blind" in by_arm:
        full = {r[0]: r for r in by_arm["full"]}
        blind = {r[0]: r for r in by_arm["blind"]}
        both = sorted(set(full) & set(blind))
        if both:
            print(f"\n  Paired agreement on {len(both)} cases annotated in both arms")
            agree_o = sum(1 for c in both if full[c][7] == blind[c][7])
            agree_n7 = sum(1 for c in both if full[c][6] == blind[c][6])
            print(f"    outcome agreement: {agree_o/len(both):.3f}   "
                  f"node7 agreement: {agree_n7/len(both):.3f}")
            print("    by length stratum (leakage predicts most disagreement in `short`):")
            for s in ("short", "mid", "long"):
                sub = [c for c in both if full[c][5] == s]
                if sub:
                    ag = sum(1 for c in sub if full[c][7] == blind[c][7]) / len(sub)
                    dcd = [blind[c][8] - full[c][8] for c in sub
                           if blind[c][8] is not None and full[c][8] is not None]
                    print(f"      {s:<6} n={len(sub):>4}  outcome agreement={ag:.3f}  "
                          f"mean CD shift={sum(dcd)/len(dcd) if dcd else float('nan'):+.4f}")
    print("\n" + "=" * 78)


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--n", type=int, default=600)
    ap_.add_argument("--arms", nargs="*", default=list(DEFAULT_ARMS),
                     choices=sorted(ARM_REDACTS))
    ap_.add_argument("--workers", type=int, default=4)
    ap_.add_argument("--sleep", type=float, default=0.0)
    ap_.add_argument("--no-mask", action="store_true",
                     help="disable disposition masking; production ran 98.4%% masked, "
                          "so leave this off to match it")
    ap_.add_argument("--report", action="store_true")
    args = ap_.parse_args()

    db = init_db()
    if args.report:
        report(db); return

    import annotate_pipeline as ap
    if not getattr(ap, "CLAUDE_API_KEY", None):
        sys.stderr.write("FATAL: no API key on annotate_pipeline (check ~/.sool_env)\n")
        sys.exit(2)

    recs = sample_cases(args.n)
    print(f"sampled {len(recs)} cases across "
          f"{len({r[1] for r in recs})} courts x {len({r[2] for r in recs})} domains")
    arms = ["full"] + [a for a in args.arms if a != "full"]
    for arm in arms:
        run_arm(ap, arm, recs, db, args.workers, args.sleep, not args.no_mask)
    report(db)


if __name__ == "__main__":
    main()
