#!/usr/bin/env python3
"""P4 prompt-variant control — is the N7/N8 asymmetry in the cases or in the prompt?

P4 reports that when Node 7 (Legal Effect) and Node 8 (Remedy) diverge, the divergence
runs one way at roughly 22:1 — effect fails while remedy survives, almost never the
reverse. The v2 system prompt instructs the *coupling* ("Node 8 usually follows Node 7")
and then explicitly invites divergence in both directions with a worked example of each.
So the coupling is instructed; the question this script answers is whether the
*direction* is.

Three arms, same cases, same model, same everything else:

  v2        the production prompt, verbatim — reproduces the published figure
  neutral   the directional sentence removed; Node 8 is assessed on its own evidence
            with no hint about which way it usually goes
  reversed  the directional sentence inverted — Node 7 is said to follow Node 8

If the asymmetry is a property of appellate cases, all three arms show it. If it is an
artifact of the instruction, `neutral` flattens toward parity and `reversed` flips.
`reversed` is the load-bearing arm: a prompt actively pushing the other way is the
strongest available test, because a finding that survives a prompt arguing against it
is not a finding the prompt produced.

Usage:
    python3 p4_prompt_control.py --n 120                  # pilot, all three arms
    python3 p4_prompt_control.py --n 400 --arms neutral   # extend one arm
    python3 p4_prompt_control.py --report                 # re-print results, no API calls

Results accumulate in p4_control.db; re-running with a larger --n tops up rather than
restarting, and a case already annotated in an arm is never re-annotated.
"""
import argparse, collections, json, math, os, random, re, sqlite3, sys, time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

CTRL_DB = os.path.join(HOME, "p4_control.db")
CORPUS_DB = os.path.join(HOME, "sool_corpus.db")
ANN_DB = os.path.join(HOME, "sool_annotations.db")
V2 = "claude-pipeline-v2"
SEED = 20260806          # fixed so the sample is reproducible across runs

# The exact sentence block whose direction is under test. Matched verbatim against the
# production prompt; if the prompt is edited this script fails loudly rather than
# silently testing a variant of something that no longer exists.
DIRECTIONAL = (
    "Node 8 usually follows Node 7 — a claimant whose right did not attach\n"
    "normally has no remedy. But assess Node 8 on its OWN evidence and let\n"
    "it diverge when the text supports divergence."
)
NEUTRAL = (
    "Node 7 and Node 8 are assessed independently. Neither is evidence for\n"
    "the other and neither usually follows the other. Assess Node 8 on its\n"
    "OWN evidence and let it diverge whenever the text supports divergence."
)
REVERSED = (
    "Node 7 usually follows Node 8 — a claimant with no available remedy\n"
    "normally has no legal effect that attached. But assess Node 7 on its\n"
    "OWN evidence and let it diverge when the text supports divergence."
)
ARMS = ("v2", "neutral", "reversed")


def build_prompts():
    """Return {arm: system_prompt}, failing loudly if the production prompt moved.

    call_claude() reads the module-level SYSTEM_PROMPT at call time, so an arm is applied
    by rebinding ap.SYSTEM_PROMPT rather than by threading a parameter through.
    """
    import annotate_pipeline as ap
    base = ap.SYSTEM_PROMPT
    if DIRECTIONAL not in base:
        sys.stderr.write(
            "FATAL: the N7/N8 directional clause is not present verbatim in\n"
            "annotate_pipeline.SYSTEM_PROMPT. The production prompt has changed; update\n"
            "DIRECTIONAL in this file to match before running the control, or the arms\n"
            "will differ from production in ways this script cannot see.\n")
        sys.exit(2)
    return ap, {"v2": base,
                "neutral": base.replace(DIRECTIONAL, NEUTRAL),
                "reversed": base.replace(DIRECTIONAL, REVERSED)}


def init_db():
    db = sqlite3.connect(CTRL_DB)
    db.execute("""create table if not exists p4arm(
        case_id integer, arm text, node7 text, node8 text, outcome text,
        cd real, cts text, raw text, err text, ts text,
        primary key(case_id, arm))""")
    db.commit()
    return db


def sample_cases(n):
    """Cases the production pass annotated, sampled at random with a fixed seed.

    Sampling from the annotated set (not the raw corpus) keeps the v2 arm comparable to
    the published figure and gives every arm the same denominator. No stratification on
    node7: stratifying on the variable under test would manufacture the asymmetry.
    """
    a = sqlite3.connect(ANN_DB)
    ok = ("protection_granted", "protection_denied", "partial", "remanded", "dismissed", "moot")
    q = ("select case_id from annotations where annotator=? and chain_outcome in (%s)"
         % ",".join("?" * len(ok)))
    # annotations.case_id is TEXT, corpus ids are INTEGER — coerce both sides or the
    # intersection is silently empty and the script reports a zero-case sample.
    ids = set()
    for (cid,) in a.execute(q, (V2,) + ok):
        try: ids.add(int(cid))
        except (TypeError, ValueError): pass
    a.close()
    c = sqlite3.connect(CORPUS_DB)
    have = {int(r[0]) for r in c.execute(
        "select case_id from opinions where plain_text is not null and length(plain_text)>2000")
        if r[0] is not None}
    c.close()
    ids = sorted(ids & have)
    random.Random(SEED).shuffle(ids)
    return ids[:n]


def load_case(c, cid):
    """Assemble the case dict build_user_prompt() expects, from the corpus DB."""
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


def annotate_one(ap, system, cid):
    """One case, one arm. Returns the row tuple to store. Thread-safe: opens its own
    read-only corpus connection and passes the arm's prompt explicitly rather than
    relying on the module global, which threads would race on."""
    c = sqlite3.connect(f"file:{CORPUS_DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
    try:
        case = load_case(c, cid)
    finally:
        c.close()
    if not case:
        return (cid, None, None, None, None, None, None, "no opinion text")
    try:
        user = ap.build_user_prompt(case, case["domain_id"])
        raw, err = call_with_system(ap, system, user)
        if err: raise RuntimeError(err)
        ann, perr = ap.parse_claude_response(raw)
        if perr: raise ValueError(perr)
        nodes = ann.get("nodes") or {}

        def clo(n):
            v = nodes.get(str(n)) or nodes.get(n) or {}
            return (v.get("closure") if isinstance(v, dict) else v) or ""

        cts = [x.get("type") if isinstance(x, dict) else x
               for x in (ann.get("active_contradictions") or [])]
        return (cid, clo(7), clo(8), ann.get("chain_outcome"),
                ann.get("contradiction_debt"), json.dumps(cts), raw[:20000], None)
    except Exception as e:
        return (cid, None, None, None, None, None, None, f"{type(e).__name__}: {e}"[:400])


def call_with_system(ap, system, user):
    """ap.call_claude() reads the module global SYSTEM_PROMPT, which cannot be rebound
    per-thread. Rebuild the same request here with the arm's prompt passed in."""
    import urllib.request, urllib.error
    # Mirror annotate_pipeline.call_claude()'s payload exactly apart from the system
    # prompt. In particular `thinking: disabled` — Sonnet 5 runs adaptive thinking when
    # it is omitted, thinking counts against max_tokens, and the JSON these prompts emit
    # gets truncated or crowded out entirely. Omitting it produced 35 "Empty response"
    # and 7 truncated-JSON failures out of 50 on the first pilot attempt.
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
            txt = "".join(b.get("text", "") for b in d.get("content", [])
                          if b.get("type") == "text").strip()
            if not txt:
                return "", f"empty response (stop_reason={d.get('stop_reason')})"
            return txt, ""
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                time.sleep(2 ** attempt * 3); continue
            return "", f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
        except Exception as e:
            if attempt < 4:
                time.sleep(2 ** attempt * 3); continue
            return "", f"{type(e).__name__}: {e}"
    return "", "retries exhausted"


def run_arm(ap, system, arm, ids, db, sleep, workers):
    todo = [i for i in ids if not db.execute(
        "select 1 from p4arm where case_id=? and arm=? and err is null",
        (i, arm)).fetchone()]
    if not todo:
        print(f"  [{arm}] nothing to do ({len(ids)} already complete)")
        return
    print(f"  [{arm}] {len(todo)} to annotate ({len(ids)-len(todo)} cached), "
          f"{workers} workers", flush=True)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(annotate_one, ap, system, cid): cid for cid in todo}
        for f in as_completed(futs):
            cid, n7, n8, oc, cd, cts, raw, err = f.result()
            db.execute("""insert or replace into p4arm
                          (case_id,arm,node7,node8,outcome,cd,cts,raw,err,ts)
                          values(?,?,?,?,?,?,?,?,?,datetime('now'))""",
                       (cid, arm, n7, n8, oc, cd, cts, raw, err))
            db.commit()
            done += 1
            if done % 10 == 0 or done == len(todo):
                print(f"    {done}/{len(todo)}", flush=True)
            if sleep: time.sleep(sleep)


def binom_two_sided(k, n, p=0.5):
    """Exact two-sided binomial p-value; k is the smaller tail count."""
    if n == 0: return 1.0
    tot = 0.0
    for i in range(0, min(k, n) + 1):
        tot += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return min(1.0, 2 * tot)


def report(db, ids):
    print("\n" + "=" * 78)
    print("P4 PROMPT-VARIANT CONTROL — direction of N7/N8 divergence by prompt arm")
    print("=" * 78)
    print("only7 = effect failed, remedy did not.   only8 = remedy failed, effect did not.")
    print("A prompt-induced asymmetry collapses in `neutral` and inverts in `reversed`.\n")
    print(f"{'arm':<10}{'n':>6}{'errs':>6}{'both':>7}{'only7':>7}{'only8':>7}"
          f"{'neither':>9}{'ratio':>9}{'p vs 1:1':>12}")
    out = {}
    for arm in ARMS:
        rows = db.execute("select node7,node8,err from p4arm where arm=?", (arm,)).fetchall()
        if not rows: continue
        errs = sum(1 for _, _, e in rows if e)
        good = [(a, b) for a, b, e in rows if not e]
        f7 = lambda a: a == "failed"
        both = sum(1 for a, b in good if f7(a) and f7(b))
        o7 = sum(1 for a, b in good if f7(a) and not f7(b))
        o8 = sum(1 for a, b in good if f7(b) and not f7(a))
        nei = len(good) - both - o7 - o8
        ratio = (o7 / o8) if o8 else float("inf")
        p = binom_two_sided(min(o7, o8), o7 + o8)
        out[arm] = dict(n=len(good), errs=errs, both=both, o7=o7, o8=o8, nei=nei, ratio=ratio, p=p)
        rs = "inf" if o8 == 0 else f"{ratio:.1f}:1"
        print(f"{arm:<10}{len(good):>6}{errs:>6}{both:>7}{o7:>7}{o8:>7}{nei:>9}{rs:>9}{p:>12.2e}")

    print(f"\nsample: {len(ids)} cases, seed {SEED}, drawn from v2-annotated cases with "
          f"opinion text > 2000 chars")
    MIN_DIV = 10           # below this an arm carries no information either way
    print("\nreading:")
    if not out:
        print("  no arms have data yet."); print(); return
    thin = [a for a in out if out[a]["o7"] + out[a]["o8"] < MIN_DIV]
    for arm in ARMS:
        if arm not in out: continue
        a = out[arm]
        d = a["o7"] + a["o8"]
        if d < MIN_DIV:
            print(f"  {arm}: {d} divergence{'' if d == 1 else 's'} — below the {MIN_DIV} needed to "
                  f"read a direction. Raise --n.")
            continue
        print(f"  {arm}: {a['o7']}:{a['o8']} "
              f"({'same direction as P4' if a['o7'] > a['o8'] else 'INVERTED vs P4'}), "
              f"p={a['p']:.2e} against 1:1.")
    if thin:
        print(f"\n  VERDICT: withheld — {', '.join(thin)} {'has' if len(thin) == 1 else 'have'} too "
              f"few divergences to interpret.")
        print(f"  At the corpus divergence rate (~14% of cases), roughly {int(MIN_DIV/0.14)+1} cases")
        print(f"  per arm is the floor and 150 gives a decisive test.")
    elif all(out[a]["o7"] > out[a]["o8"] for a in out):
        print("\n  VERDICT: the asymmetry survives every arm, including the one instructed to")
        print("  expect the opposite. P4 is a property of the cases, not of the prompt.")
    elif "reversed" in out and out["reversed"]["o7"] <= out["reversed"]["o8"]:
        print("\n  VERDICT: the direction inverts when the prompt is inverted. P4 measures the")
        print("  instruction, not the corpus, and must be withdrawn.")
    else:
        print("\n  VERDICT: at least one arm fails to reproduce the direction. P4 is at least")
        print("  partly prompt-induced and must be restated.")
    print()


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--n", type=int, default=120, help="cases per arm")
    ap_.add_argument("--arms", default=",".join(ARMS), help="comma-separated subset of arms")
    ap_.add_argument("--model", default=None, help="override model id")
    ap_.add_argument("--api-key", default=None,
                     help="Anthropic key; defaults to $SOOL_ANTHROPIC_KEY then $ANTHROPIC_API_KEY")
    ap_.add_argument("--sleep", type=float, default=0.0, help="seconds between completions")
    ap_.add_argument("--workers", type=int, default=6, help="concurrent API calls per arm")
    ap_.add_argument("--report", action="store_true", help="print results without calling the API")
    a = ap_.parse_args()

    db = init_db()
    ids = sample_cases(a.n)
    if a.report:
        report(db, ids); return
    if not ids:
        sys.stderr.write("FATAL: no sampleable cases (need v2 annotations + opinion text).\n")
        sys.exit(2)

    mod, prompts = build_prompts()
    # call_claude() sends the module global CLAUDE_API_KEY, which annotate_pipeline only
    # populates from its own argparse. Running this script instead of that one means
    # setting it here, from the same variable the cron jobs source.
    key = (a.api_key or os.environ.get("SOOL_ANTHROPIC_KEY")
           or os.environ.get("ANTHROPIC_API_KEY") or "")
    if not key:
        sys.stderr.write("FATAL: no API key. Set SOOL_ANTHROPIC_KEY (source ~/.sool_env) "
                         "or pass --api-key.\n")
        sys.exit(2)
    mod.CLAUDE_API_KEY = key
    if a.model: mod.CLAUDE_MODEL = a.model
    print(f"P4 control: {len(ids)} cases x {len(a.arms.split(','))} arms, "
          f"model={mod.CLAUDE_MODEL}", flush=True)
    for arm in [x.strip() for x in a.arms.split(",") if x.strip()]:
        if arm not in prompts:
            sys.stderr.write(f"unknown arm {arm!r}; known: {', '.join(ARMS)}\n"); sys.exit(2)
        run_arm(mod, prompts[arm], arm, ids, db, a.sleep, a.workers)
    report(db, ids)


if __name__ == "__main__":
    main()
