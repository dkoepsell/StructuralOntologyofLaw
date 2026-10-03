#!/usr/bin/env python3
"""Confirm aggregates are v2-scoped and contain no NaN/None that would break the UI."""
import json, math, collections, os

d = json.load(open(os.path.expanduser("~/CaseLaw/sool_corpus_data.json")))
m = d["meta"]
print("meta.n (analysis)  :", m["n"])
print("meta.n_all (shipped):", m.get("n_all"))
print("analysis_scope     :", m.get("analysis_scope"))
print("ann_mix            :", m.get("ann_mix"))
print("cases array len    :", len(d["cases"]))
print("version            :", m.get("version"))
assert len(d["cases"]) == m["n_all"], "shipped array must be the full set"

mix = collections.Counter(c.get("ann") for c in d["cases"])
print("\nshipped case mix   :", dict(mix))

# domain_stats should now reflect v2 only
print("\ndomain_stats (n per domain):")
for k, v in sorted(d["domain_stats"].items(), key=lambda kv: int(kv[0])):
    n = v.get("n") or v.get("total") or v.get("count")
    print(f"  D{k}: n={n}  keys={list(v.keys())[:6]}")

v2n = collections.Counter(c["domain"] for c in d["cases"] if c.get("ann") == "v2")
print("\nactual v2 per domain:", dict(sorted(v2n.items())))

# hunt for NaN / Infinity / None in every aggregate block
def scan(o, path=""):
    bad = []
    if isinstance(o, dict):
        for k, v in o.items(): bad += scan(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o[:400]): bad += scan(v, f"{path}[{i}]")
    elif isinstance(o, float):
        if math.isnan(o) or math.isinf(o): bad.append((path, o))
    return bad

blocks = [k for k in d if k not in ("cases", "meta")]
print("\naggregate blocks:", blocks)
total_bad = []
for b in blocks:
    bad = scan(d[b], b)
    total_bad += bad
    print(f"  {b:<24} NaN/Inf: {len(bad)}")
if total_bad:
    print("  !! examples:", total_bad[:8])

# raw JSON must not contain literal NaN/Infinity tokens (breaks JSON.parse)
raw = open(os.path.expanduser("~/CaseLaw/sool_corpus_data.json")).read()
for tok in ("NaN", "Infinity", "-Infinity"):
    print(f"raw token {tok!r:12}: {raw.count(tok)}")

print("\nRESULT:", "PASS" if not total_bad and raw.count("NaN") == 0 else "FAIL")
