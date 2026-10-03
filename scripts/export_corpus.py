#!/usr/bin/env python3
"""
SOoL Corpus Exporter  v1.2
============================
SEAL Lab, Texas A&M University
David R. Koepsell, A Structural Ontology of the Law (Palgrave, forthcoming)

Exports sool_annotations.db -> sool_corpus_data.json with comprehensive
precomputed rollups for the Query Tool and future scientific analysis.

New in v1.2: circuit_stats, ct_cooccurrence, outcome_cd_by_domain,
node_closure_by_outcome, role_inventory, structural_signatures,
intervention_windows, decade_profiles, cd_distribution,
cascade_stats, confidence_profile, ct_domain_normalized

Usage:
    python3 export_corpus.py
    python3 export_corpus.py --db ./sool_annotations.db --out ./sool_corpus_data.json
"""
import sqlite3, json, argparse, os, math, statistics

def _ann_code(a):
    """Collapse the annotator string to a short provenance code for the web UI."""
    a = (a or "").strip().lower()
    if "v2" in a:      return "v2"
    if "masked" in a:  return "masked"
    if "v1" in a:      return "v1"
    return "other"


def _clean_cite(raw):
    """Normalize citation strings from various CourtListener formats."""
    if not raw:
        return ""
    s = str(raw).strip()
    if s.startswith("["):
        try:
            import json as _j
            lst = _j.loads(s)
            if lst:
                first = lst[0]
                return first.get("cite","").strip() if isinstance(first,dict) else str(first).strip()
        except Exception:
            pass
    if s.startswith("{"):
        try:
            import json as _j
            return _j.loads(s).get("cite","").strip()
        except Exception:
            pass
    return s

from collections import defaultdict, Counter
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "typology"))
try:
    from corpus_version import manifest as _cv
    _CORPUS_VERSION = _cv()
except Exception as _e:          # never block an export on version metadata
    print(f"Warning: corpus version unavailable: {_e}")
    _CORPUS_VERSION = {}
from datetime import datetime, timezone

parser = argparse.ArgumentParser()
parser.add_argument("--db",  default="./sool_annotations.db")
parser.add_argument("--out", default="./sool_corpus_data.json")
args = parser.parse_args()

# The eight domains the project has actual opinion text for.
#
# Domains 9-11 (Habeas Corpus, Patent/IP, Securities Regulation) are deliberately
# ABSENT. Their opinion text was never collected -- 14 usable opinions across 907
# collected cases -- so the annotation pass ran against case names and produced 510
# rows the annotator itself flagged as underivable. They are excluded from the export
# entirely (see EXPORT_DOMAINS below), not merely from the statistics, so they cannot
# surface in case search either. If their opinions are ever collected, add them back
# here and to EXPORT_DOMAINS.
DOMAIN_NAMES = {1:"D1 First Amendment",2:"D2 Employment Discrim.",
                3:"D3 Administrative Law",4:"D4 Criminal Procedure",
                5:"D5 Immigration",6:"D6 Civil Rights §1983",
                7:"D7 Contract",8:"D8 Family Law"}
DOMAIN_COLORS= {1:"#8B1A1A",2:"#B8922A",3:"#1B3C6E",4:"#7A4500",
                5:"#5C1A7A",6:"#1A5C2E",7:"#666666",8:"#1A5C6E"}
EXPORT_DOMAINS = set(DOMAIN_NAMES)
CT_LIST = ["RF","RPF","NI","RC3","JC","AI","PC","TC","CF","FM","CC","SE","RCL"]
CT_WEIGHTS = {"CF":0.15,"AI":0.12,"JC":0.10,"RC3":0.14,"PC":0.09,"TC":0.08,
              "FM":0.11,"NI":0.07,"RF":0.11,"RCL":0.18,"CC":0.14,"SE":0.10,"RPF":0.13}
NODE_NAMES  = ["Source of Authority","Norm","Actor in Role","Triggering Facts",
               "Legal Act / Omission","Target","Legal Effect","Remedy"]
NODE_SHORT  = ["N1","N2","N3","N4","N5","N6","N7","N8"]
NODE_COLORS = ["#1B3C6E","#1B3C6E","#1B3C6E","#7A5500","#7A5500",
               "#1A5C2E","#1A5C2E","#5C1A7A"]
CLUSTERS    = ["AUTHORITY"]*3+["EFFECT"]*2+["RECOGNITION"]*2+["REPAIR"]
FAIL_STATES = {"failed","partial"}

INTERVENTIONS = [
    {"key":"Garcetti_2006",  "year":2006,"label":"Garcetti v. Ceballos","domain":1,"color":"#8B1A1A"},
    {"key":"Twombly_2007",   "year":2007,"label":"Bell Atlantic v. Twombly","domain":None,"color":"#555"},
    {"key":"Citizens_2010",  "year":2010,"label":"Citizens United","domain":1,"color":"#8B1A1A"},
    {"key":"Janus_2018",     "year":2018,"label":"Janus v. AFSCME","domain":1,"color":"#8B1A1A"},
    {"key":"WestVa_2022",    "year":2022,"label":"West Virginia v. EPA","domain":3,"color":"#1B3C6E"},
    {"key":"LoPerBright_2024","year":2024,"label":"Loper Bright","domain":3,"color":"#1B3C6E"},
]

def safe_mean(lst):
    return round(sum(lst)/len(lst), 4) if lst else None

def safe_std(lst):
    return round(statistics.stdev(lst), 4) if len(lst)>=2 else None

def roll(vals, w=3):
    out = []
    for i,v in enumerate(vals):
        window = [x for x in vals[max(0,i-w//2):i+w//2+1] if x is not None]
        out.append(round(sum(window)/len(window),4) if window else None)
    return out

def export(db_path, out_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Try to ATTACH sool_corpus.db to pull absolute_url and richer citations
    corpus_db = db_path.replace("sool_annotations.db", "sool_corpus.db")
    import os as _os
    has_corpus = False
    if _os.path.exists(corpus_db):
        try:
            conn.execute(f"ATTACH DATABASE '{corpus_db}' AS corpus")
            has_corpus = True
            all_rows = conn.execute("""
                SELECT a.case_id, a.case_name,
                       COALESCE(NULLIF(a.citation,''), '') AS citation,
                       a.court, a.date_decided,
                       a.domain_id, a.domain_name, a.chain_outcome, a.contradiction_debt, a.cd_upstream,
                       a.active_contradictions, a.structural_signature, a.confidence,
                       a.needs_review,
                       COALESCE(a.adversarial_strength,0.0) as adversarial_strength,
                       COALESCE(a.equipoise_flagged,0) as equipoise_flagged,
                       COALESCE(a.adversarial_notes,"") as adversarial_notes,
                       a.node1_closure,a.node1_entity,a.node2_closure,a.node2_entity,
                       a.node3_closure,a.node3_entity,a.node3_roles,
                       a.node4_closure,a.node4_entity,a.node5_closure,a.node5_entity,
                       a.node6_closure,a.node6_entity,a.node7_closure,a.node7_entity,
                       a.node8_closure,a.node8_entity,a.outcome_notes, a.annotator,
                       COALESCE(c.absolute_url, '') AS absolute_url,
                       COALESCE(c.docket_number, '') AS docket_number
                FROM annotations a
                LEFT JOIN corpus.cases c ON c.id = a.case_id
                ORDER BY a.domain_id, a.case_id
            """).fetchall()
        except Exception as _e:
            print(f"Warning: could not join corpus DB: {_e} -- falling back")
            conn.execute("DETACH DATABASE corpus")
            all_rows = conn.execute("""
                SELECT case_id, case_name, citation, court, date_decided,
                       domain_id, domain_name, chain_outcome, contradiction_debt, cd_upstream,
                       active_contradictions, structural_signature, confidence,
                       needs_review,
                       node1_closure,node1_entity,node2_closure,node2_entity,
                       node3_closure,node3_entity,node3_roles,
                       node4_closure,node4_entity,node5_closure,node5_entity,
                       node6_closure,node6_entity,node7_closure,node7_entity,
                       node8_closure,node8_entity,outcome_notes, annotator,
                       '' AS absolute_url, '' AS docket_number
                FROM annotations ORDER BY domain_id, case_id
            """).fetchall()
    else:
        all_rows = conn.execute("""
            SELECT case_id, case_name, citation, court, date_decided,
                   domain_id, domain_name, chain_outcome, contradiction_debt, cd_upstream,
                   active_contradictions, structural_signature, confidence,
                   needs_review,
                   node1_closure,node1_entity,node2_closure,node2_entity,
                   node3_closure,node3_entity,node3_roles,
                   node4_closure,node4_entity,node5_closure,node5_entity,
                   node6_closure,node6_entity,node7_closure,node7_entity,
                   node8_closure,node8_entity,outcome_notes, annotator,
                   '' AS absolute_url, '' AS docket_number
            FROM annotations ORDER BY domain_id, case_id
        """).fetchall()

    # ── BUILD CASES LIST ─────────────────────────────────────────────────────
    cases = []
    for r in all_rows:
        cases.append({
            "id":     r["case_id"],
            "name":   r["case_name"] or "",
            "cite":   _clean_cite(r["citation"]),
            "url":    r["absolute_url"] if "absolute_url" in r.keys() else "",
            "docket": r["docket_number"] if "docket_number" in r.keys() else "",
            "absolute_url": r.get("absolute_url", "") if hasattr(r, "get") else "",
            "court":  r["court"] or "",
            "year":   int(r["date_decided"][:4]) if r["date_decided"] else None,
            "date":   r["date_decided"] or "",
            "domain": r["domain_id"],
            "dname":  r["domain_name"] or "",
            "outcome":r["chain_outcome"] or "",
            "cd":     round(r["contradiction_debt"] or 0, 4),
            # Structural stress over N1-N6 only: the component NOT
            # downstream of the Pass-2 derivation rule (spec 3.2).
            "cd_upstream": round(r["cd_upstream"] or 0, 4),
            "cts":    json.loads(r["active_contradictions"] or "[]"),
            "sigs":   json.loads(r["structural_signature"] or "[]"),
            "conf":   r["confidence"] or "",
            # Annotation regime this row came from. The table mixes v1, the
            # masked/blind pass, and the v2 rebuild; without this the UI cannot
            # tell them apart and every live statistic silently averages all three.
            "ann":    _ann_code(r["annotator"] if "annotator" in r.keys() else ""),
            "review": bool(r["needs_review"]),
            "adv_strength": float(r["adversarial_strength"] or 0),
            "adv_flagged":  bool(r["equipoise_flagged"]),
            "adv_notes":    r["adversarial_notes"] or "",
            "notes":  r["outcome_notes"] or "",
            "nodes":  {str(n):{"closure":(r[f"node{n}_closure"] or "indeterminate"),
                                "entity": (r[f"node{n}_entity"] or "")[:300],
                                **( {"roles":json.loads(r["node3_roles"] or "[]")} if n==3 else {})}
                       for n in range(1,9)}
        })

    # ── ANALYSIS SCOPE ────────────────────────────────────────────────────────
    # The annotations table holds three incompatible regimes at once: v1, the
    # masked/blind pass, and the v2 rebuild. Aggregating across them produces
    # figures belonging to no regime — the CD ratio in particular *inverts*
    # between v1 and v2, so a blended mean is an artifact, not a compromise.
    #
    # Every aggregate below is therefore computed on v2 rows only, while the
    # `cases` array shipped to the browser keeps ALL rows (each tagged with
    # `ann`) so case search, permalinks and detail views still resolve.
    # If the v2 pass has not started, fall back to the full set rather than
    # emitting an empty corpus.
    # Drop domains we have no opinion text for before anything downstream sees them,
    # so they cannot reach the statistics OR case search.
    dropped_domains = Counter(c["domain"] for c in cases if c["domain"] not in EXPORT_DOMAINS)
    cases = [c for c in cases if c["domain"] in EXPORT_DOMAINS]
    if dropped_domains:
        print(f"Excluded out-of-scope domains (no opinion text): {dict(dropped_domains)}")

    all_cases = cases
    ann_mix = Counter(c.get("ann") or "other" for c in all_cases)
    v2_cases = [c for c in all_cases if c.get("ann") == "v2"]
    analysis_scope = "v2" if v2_cases else "all"
    cases = v2_cases or all_cases

    clean = [c for c in cases if not c["review"]]
    print(f"Total: {len(all_cases)} | Analysis scope: {analysis_scope} "
          f"({len(cases)}) | Clean: {len(clean)}")
    print(f"  annotator mix: {dict(ann_mix)}")

    # ── DOMAIN COVERAGE ───────────────────────────────────────────────────────
    # Every domain the project has collected, whether or not it is analysable.
    # Domains 9-11 (Habeas, Patent/IP, Securities) were collected as metadata but
    # their opinion TEXT was never fetched, so the annotation pass ran against case
    # names alone and produced unusable output. Reporting them as ordinary rows
    # would publish confabulation; omitting them hides that the gap exists. So the
    # coverage block records the real state and the UI renders it explicitly.
    COVERAGE_NAMES = {
        1:"First Amendment", 2:"Employment Discrimination", 3:"Administrative Law",
        4:"Criminal Procedure", 5:"Immigration", 6:"Civil Rights §1983",
        7:"Contract", 8:"Family Law",
    }
    MIN_TEXT = 2000        # chars; below this an opinion cannot support annotation
    MIN_ANALYSABLE = 100   # v2 rows needed before a domain drives any statistic

    coverage = []
    for did, dname in sorted(COVERAGE_NAMES.items()):
        collected = text_ok = 0
        if has_corpus:
            try:
                collected = conn.execute(
                    "SELECT COUNT(*) FROM corpus.cases WHERE domain_id=?", (did,)).fetchone()[0]
                text_ok = conn.execute(
                    "SELECT COUNT(*) FROM corpus.opinions o JOIN corpus.cases c "
                    "ON o.case_id=c.id WHERE c.domain_id=? AND LENGTH(COALESCE(o.plain_text,''))>?",
                    (did, MIN_TEXT)).fetchone()[0]
            except Exception:
                pass
        dom_all = [c for c in all_cases if c["domain"] == did]
        dom_v2  = [c for c in dom_all if c.get("ann") == "v2"]
        annotated = len(dom_all)

        if len(dom_v2) >= MIN_ANALYSABLE:
            status, note = "analysable", "Rebuilt under v2; included in all statistics."
        elif annotated and text_ok <= max(10, annotated * 0.05):
            status = "unusable"
            note = (f"Collected as metadata only — just {text_ok} of {annotated} annotated "
                    f"cases have opinion text over {MIN_TEXT:,} characters. The annotation "
                    f"pass ran without the opinions and produced output derived from case "
                    f"names, not from what the courts wrote. Excluded from every statistic; "
                    f"needs opinion collection, then re-annotation.")
        elif dom_v2:
            status = "in progress"
            note = (f"v2 rebuild running: {len(dom_v2)} of {annotated} cases done "
                    f"(under the {MIN_ANALYSABLE}-case floor for reporting).")
        else:
            status, note = "pending", "Not yet re-annotated under v2; excluded from statistics."

        coverage.append({
            "domain": did, "name": dname, "collected": collected,
            "with_text": text_ok, "annotated": annotated, "v2": len(dom_v2),
            "status": status, "note": note,
        })

    print("Domain coverage:")
    for c_ in coverage:
        print(f"  D{c_['domain']:<3}{c_['name'][:26]:<28} collected={c_['collected']:<6} "
              f"text={c_['with_text']:<6} annot={c_['annotated']:<6} v2={c_['v2']:<6} "
              f"{c_['status']}")

    # ── DOMAIN STATS ─────────────────────────────────────────────────────────
    domain_stats = {}
    for did in range(1,9):
        dc = [c for c in cases if c["domain"]==did]
        if not dc: continue
        cds = [c["cd"] for c in dc]
        domain_stats[str(did)] = {
            "n": len(dc), "avg_cd": round(sum(cds)/len(cds),4),
            "max_cd": max(cds), "min_cd": min(cds),
            "std_cd": safe_std(cds),
            "denied": sum(1 for c in dc if c["outcome"]=="protection_denied"),
            "granted":sum(1 for c in dc if c["outcome"]=="protection_granted"),
        }

    # ── CT × DOMAIN MATRIX (counts + rates) ──────────────────────────────────
    ct_matrix = {}
    ct_matrix_norm = {}
    for ct in CT_LIST:
        ct_matrix[ct] = {str(d):sum(1 for c in cases if c["domain"]==d and ct in c["cts"])
                         for d in range(1,9)}
        ct_matrix_norm[ct] = {str(d): round(ct_matrix[ct][str(d)] /
                               max(1, sum(1 for c in cases if c["domain"]==d)), 4)
                              for d in range(1,9)}

    # ── TEMPORAL CD ──────────────────────────────────────────────────────────
    YEARS = list(range(1990, 2025))
    cells = defaultdict(lambda: defaultdict(list))
    for c in clean:
        if c["year"] and 1990 <= c["year"] <= 2024:
            cells[c["domain"]][c["year"]].append(c["cd"])
    temporal_series = {}
    for did in range(1,9):
        raw = [safe_mean(cells[did][y]) if len(cells[did][y])>=3 else None for y in YEARS]
        temporal_series[str(did)] = {
            "name":DOMAIN_NAMES[did],"color":DOMAIN_COLORS[did],
            "raw":raw,"smooth":roll(raw),
            "n_per_year":[len(cells[did][y]) for y in YEARS],
        }
    all_by_year = defaultdict(list)
    for c in clean:
        if c["year"] and 1990<=c["year"]<=2024:
            all_by_year[c["year"]].append(c["cd"])
    temporal = {
        "years":YEARS,"domains":temporal_series,
        "all_mean":roll([safe_mean(all_by_year[y]) if len(all_by_year.get(y,[]))>=5 else None for y in YEARS]),
        "all_n":[len(all_by_year.get(y,[])) for y in YEARS],
        "events":[{"year":iv["year"],"label":iv["label"],"domain":iv["domain"],"color":iv["color"]}
                  for iv in INTERVENTIONS],
    }

    # ── NODE TOPOLOGY ─────────────────────────────────────────────────────────
    total = len(clean)
    cooccur = [[0]*8 for _ in range(8)]
    fail_cnt = [0]*8
    for c in clean:
        failed = [1 if (c["nodes"][str(n+1)]["closure"] or "").lower() in FAIL_STATES else 0 for n in range(8)]
        for i in range(8):
            if failed[i]: fail_cnt[i]+=1
            for j in range(i,8):
                if failed[i] and failed[j]:
                    cooccur[i][j]+=1
                    if i!=j: cooccur[j][i]+=1
    phi = [[0.0]*8 for _ in range(8)]
    for i in range(8):
        for j in range(8):
            if i==j: phi[i][j]=1.0; continue
            n11=cooccur[i][j]; n10=fail_cnt[i]-n11; n01=fail_cnt[j]-n11; n00=total-n11-n10-n01
            d=math.sqrt((n11+n10)*(n11+n01)*(n00+n10)*(n00+n01))
            phi[i][j]=round((n11*n00-n10*n01)/d,4) if d>0 else 0.0
    up_pairs=[[1,2],[0,1],[5,6],[6,7]]; cr_pairs=[[1,7],[2,7],[3,6],[0,7]]
    mean_up=round(sum(phi[i][j] for i,j in up_pairs)/len(up_pairs),4)
    mean_cr=round(sum(phi[i][j] for i,j in cr_pairs)/len(cr_pairs),4)
    topology = {
        "n_cases":total,
        "nodes":[{"id":i,"short":NODE_SHORT[i],"name":NODE_NAMES[i],
                  "cluster":CLUSTERS[i],"color":NODE_COLORS[i],
                  "fail_count":fail_cnt[i],
                  "fail_rate":round(fail_cnt[i]/total,4) if total else 0}
                 for i in range(8)],
        "phi":[[round(phi[i][j],4) for j in range(8)] for i in range(8)],
        "cooccur":cooccur,
        # mean_up / mean_cr are mean PHI CORRELATIONS, which may be negative. A ratio of
        # two opposite-signed correlations is uninterpretable, and "mean_up > mean_cr"
        # passes trivially whenever the cross-cluster mean is negative — which is how
        # this came to report "universality CONFIRMED (ratio -8.27x)". Report the
        # difference, which is always readable, and emit a ratio only when both means
        # are positive so it means what a reader will assume it means.
        "stats":{"mean_phi_upstream":mean_up,"mean_phi_cross":mean_cr,
                 "delta":round(mean_up-mean_cr,4),
                 "ratio":(round(mean_up/mean_cr,3)
                          if (mean_cr and mean_cr > 0 and mean_up > 0) else None),
                 "ratio_note":(None if (mean_cr and mean_cr > 0 and mean_up > 0) else
                               "ratio suppressed: cross-cluster mean phi is not positive, "
                               "so the quotient is uninterpretable"),
                 "confirms":bool(mean_up > mean_cr and mean_up > 0),
                 "confirms_note":("within-cluster node failures co-occur more than "
                                  "cross-cluster ones; this is a statement about phi "
                                  "structure, not about predictive power")},
    }

    # ── NEW: CIRCUIT STATS ────────────────────────────────────────────────────
    circuits = defaultdict(list)
    for c in clean: circuits[c["court"]].append(c)
    circuit_stats = {}
    for court, cs in sorted(circuits.items(), key=lambda x:-len(x[1])):
        if not court or len(cs) < 5: continue
        cds = [c["cd"] for c in cs]
        outcomes = defaultdict(int)
        for c in cs: outcomes[c["outcome"]]+=1
        ct_counts = defaultdict(int)
        for c in cs:
            for ct in c["cts"]: ct_counts[ct]+=1
        top_cts = sorted(ct_counts.items(), key=lambda x:-x[1])[:5]
        circuit_stats[court] = {
            "n":len(cs), "avg_cd":round(sum(cds)/len(cds),4),
            "max_cd":max(cds), "std_cd":safe_std(cds),
            "outcomes":dict(outcomes),
            "denied_rate":round(outcomes.get("protection_denied",0)/len(cs),4),
            "top_cts":[[ct,n] for ct,n in top_cts],
            "domains":dict(sorted(defaultdict(int, {str(c["domain"]):1 for c in cs}).items())),
        }
        for c in cs: circuit_stats[court]["domains"][str(c["domain"])] =             circuit_stats[court]["domains"].get(str(c["domain"]),0)+1

    # ── NEW: CT CO-OCCURRENCE (13×13 phi) ─────────────────────────────────────
    ct_cooccur = [[0]*13 for _ in range(13)]
    ct_fail = [0]*13
    for c in clean:
        for i,ct in enumerate(CT_LIST):
            if ct in c["cts"]: ct_fail[i]+=1
            for j,ct2 in enumerate(CT_LIST):
                if ct in c["cts"] and ct2 in c["cts"]:
                    ct_cooccur[i][j]+=1
    ct_phi = [[0.0]*13 for _ in range(13)]
    for i in range(13):
        for j in range(13):
            if i==j: ct_phi[i][j]=1.0; continue
            n11=ct_cooccur[i][j]; n10=ct_fail[i]-n11; n01=ct_fail[j]-n11; n00=total-n11-n10-n01
            d=math.sqrt((n11+n10)*(n11+n01)*(n00+n10)*(n00+n01))
            ct_phi[i][j]=round((n11*n00-n10*n01)/d,4) if d>0 else 0.0
    ct_cooccurrence = {
        "labels":CT_LIST,
        "phi":[[round(ct_phi[i][j],4) for j in range(13)] for i in range(13)],
        "counts":ct_cooccur,
        "fail_counts":ct_fail,
        "fail_rates":[round(ct_fail[i]/total,4) if total else 0 for i in range(13)],
    }

    # ── NEW: CD BY DOMAIN × OUTCOME ───────────────────────────────────────────
    OUTCOMES = ["protection_denied","protection_granted","partial","remanded","dismissed"]
    outcome_cd_by_domain = {}
    for did in range(1,9):
        dc = [c for c in clean if c["domain"]==did]
        outcome_cd_by_domain[str(did)] = {}
        for out in OUTCOMES:
            oc = [c["cd"] for c in dc if c["outcome"]==out]
            outcome_cd_by_domain[str(did)][out] = {
                "n":len(oc), "mean":safe_mean(oc),
                "std":safe_std(oc),
                "median":round(sorted(oc)[len(oc)//2],4) if oc else None,
            }
    # Overall CD/outcome ratio
    den_cds  = [c["cd"] for c in clean if c["outcome"]=="protection_denied"]
    gran_cds = [c["cd"] for c in clean if c["outcome"]=="protection_granted"]
    outcome_cd_by_domain["_overall"] = {
        "ratio": round(safe_mean(den_cds)/safe_mean(gran_cds),3) if safe_mean(gran_cds) else None,
        "denied_mean":safe_mean(den_cds), "granted_mean":safe_mean(gran_cds),
    }

    # ── NEW: NODE CLOSURE × OUTCOME ───────────────────────────────────────────
    node_closure_by_outcome = {}
    for out in OUTCOMES:
        oc = [c for c in clean if c["outcome"]==out]
        if not oc: continue
        node_closure_by_outcome[out] = {"n":len(oc)}
        for n in range(1,9):
            closures = [c["nodes"][str(n)]["closure"].lower() for c in oc]
            node_closure_by_outcome[out][f"N{n}_fail_rate"] =                 round(sum(1 for cl in closures if cl in FAIL_STATES)/len(closures),4)
            node_closure_by_outcome[out][f"N{n}_closed_rate"] =                 round(sum(1 for cl in closures if cl=="closed")/len(closures),4)

    # ── NEW: ROLE INVENTORY ───────────────────────────────────────────────────
    role_map = defaultdict(lambda: {"n":0,"domains":set(),"rc3":0,"cds":[]})
    for c in clean:
        roles = c["nodes"]["3"].get("roles",[])
        for role in roles:
            role = role.strip().lower()
            if not role or len(role)<3: continue
            role_map[role]["n"]+=1
            role_map[role]["domains"].add(c["domain"])
            if "RC3" in c["cts"]: role_map[role]["rc3"]+=1
            role_map[role]["cds"].append(c["cd"])
    role_inventory = {}
    for role, data in sorted(role_map.items(), key=lambda x:-x[1]["n"])[:100]:
        role_inventory[role] = {
            "n":data["n"],
            "domains":sorted(data["domains"]),
            "rc3_rate":round(data["rc3"]/data["n"],4) if data["n"] else 0,
            "avg_cd":safe_mean(data["cds"]),
        }

    # ── NEW: STRUCTURAL SIGNATURES ────────────────────────────────────────────
    sig_map = defaultdict(lambda: {"n":0,"domains":set(),"cds":[],"outcomes":defaultdict(int)})
    for c in clean:
        sig = "+".join(sorted(c["cts"])) if c["cts"] else "(none)"
        sig_map[sig]["n"]+=1
        sig_map[sig]["domains"].add(c["domain"])
        sig_map[sig]["cds"].append(c["cd"])
        sig_map[sig]["outcomes"][c["outcome"]]+=1
    structural_signatures = {}
    for sig, data in sorted(sig_map.items(), key=lambda x:-x[1]["n"])[:60]:
        structural_signatures[sig] = {
            "n":data["n"],
            "domains":sorted(data["domains"]),
            "avg_cd":safe_mean(data["cds"]),
            "outcomes":dict(data["outcomes"]),
            "denied_rate":round(data["outcomes"].get("protection_denied",0)/data["n"],4),
        }

    # ── NEW: INTERVENTION WINDOWS ─────────────────────────────────────────────
    intervention_windows = {}
    for iv in INTERVENTIONS:
        y,did = iv["year"],iv["domain"]
        pre  = [c for c in clean if c["year"] and iv["year"]-2<=c["year"]<iv["year"]
                and (did is None or c["domain"]==did)]
        post = [c for c in clean if c["year"] and iv["year"]<=c["year"]<=iv["year"]+2
                and (did is None or c["domain"]==did)]
        pre_cds  = [c["cd"] for c in pre]
        post_cds = [c["cd"] for c in post]
        pre_m    = safe_mean(pre_cds)
        post_m   = safe_mean(post_cds)
        intervention_windows[iv["key"]] = {
            "year":y,"label":iv["label"],"domain":did,
            "n_pre":len(pre),"n_post":len(post),
            "avg_cd_pre":pre_m,"avg_cd_post":post_m,
            "delta":round(post_m-pre_m,4) if pre_m and post_m else None,
            "direction":"increase" if (post_m and pre_m and post_m>pre_m) else
                        "decrease" if (post_m and pre_m and post_m<pre_m) else "neutral",
        }

    # ── NEW: DECADE PROFILES ──────────────────────────────────────────────────
    DECADES = [("1990s",1990,2000),("2000s",2000,2010),("2010s",2010,2020),("2020s",2020,2025)]
    decade_profiles = {}
    for did in range(1,9):
        decade_profiles[str(did)] = {}
        for dlabel,dstart,dend in DECADES:
            dc = [c for c in clean if c["domain"]==did and c["year"] and dstart<=c["year"]<dend]
            if not dc: continue
            cds=[c["cd"] for c in dc]
            ct_counts=defaultdict(int)
            for c in dc:
                for ct in c["cts"]: ct_counts[ct]+=1
            top_ct = max(ct_counts.items(),key=lambda x:x[1])[0] if ct_counts else None
            decade_profiles[str(did)][dlabel] = {
                "n":len(dc),"avg_cd":safe_mean(cds),"std_cd":safe_std(cds),
                "denied_rate":round(sum(1 for c in dc if c["outcome"]=="protection_denied")/len(dc),4),
                "top_ct":top_ct,
                "ct_rates":{ct:round(ct_counts[ct]/len(dc),4) for ct in CT_LIST if ct_counts[ct]>0},
            }

    # ── NEW: CD DISTRIBUTION (histogram) ─────────────────────────────────────
    bins = [round(i*0.02,2) for i in range(31)]  # 0.00–0.60
    def hist(cds):
        counts=[0]*len(bins)
        for cd in cds:
            idx=min(len(bins)-1,int(cd/0.02))
            counts[idx]+=1
        return counts
    cd_distribution = {
        "bins":bins,
        "overall":hist([c["cd"] for c in clean]),
        "by_domain":{str(did):hist([c["cd"] for c in clean if c["domain"]==did])
                     for did in range(1,9)},
        "by_outcome":{out:hist([c["cd"] for c in clean if c["outcome"]==out])
                      for out in OUTCOMES},
    }

    # ── NEW: CASCADE INTEGRITY ────────────────────────────────────────────────
    n7_fail = [c for c in clean if c["nodes"]["7"]["closure"].lower() in FAIL_STATES]
    cascade_ok  = [c for c in n7_fail if c["nodes"]["8"]["closure"].lower() in FAIL_STATES or
                   c["nodes"]["8"]["closure"].lower()=="partial"]
    cascade_viol= [c for c in n7_fail if c["nodes"]["8"]["closure"].lower()=="closed"]
    by_domain_casc = {}
    for did in range(1,9):
        domain_n7f = [c for c in n7_fail if c["domain"]==did]
        domain_viol= [c for c in cascade_viol if c["domain"]==did]
        by_domain_casc[str(did)] = {
            "n7_fail":len(domain_n7f),
            # v1 called this a violation because RULE 5 forced N8 to fail whenever N7
            # did. v2 assigns N8 on its own evidence, so a claimant whose asserted effect
            # did not attach but who retains a remedy is a real and interesting case, not
            # an annotation fault. Kept under both names for one release so nothing
            # reading the old key breaks silently.
            "violations":len(domain_viol),          # deprecated alias of n8_survives
            "n8_survives":len(domain_viol),
            "cascade_rate":round(1-len(domain_viol)/len(domain_n7f),4) if domain_n7f else None,
            "n8_survival_rate":round(len(domain_viol)/len(domain_n7f),4) if domain_n7f else None,
        }
    cascade_stats = {
        "n7_fail_total":len(n7_fail),
        "cascade_ok":len(cascade_ok),
        "violations":len(cascade_viol),
        "cascade_rate":round(len(cascade_ok)/len(n7_fail),4) if n7_fail else None,
        "by_domain":by_domain_casc,
    }

    # ── NEW: CONFIDENCE PROFILE ───────────────────────────────────────────────
    confidence_profile = {}
    for did in range(1,9):
        dc = [c for c in cases if c["domain"]==did]
        confidence_profile[str(did)] = {
            "high":  sum(1 for c in dc if c["conf"]=="high"),
            "medium":sum(1 for c in dc if c["conf"]=="medium"),
            "low":   sum(1 for c in dc if c["conf"]=="low"),
            "review":sum(1 for c in dc if c["review"]),
            "total": len(dc),
            "high_rate":round(sum(1 for c in dc if c["conf"]=="high")/max(1,len(dc)),4),
            "review_rate":round(sum(1 for c in dc if c["review"])/max(1,len(dc)),4),
        }

    # ── ASSEMBLE PAYLOAD ──────────────────────────────────────────────────────
    payload = {
        "meta":{
            "generated":datetime.now(timezone.utc).isoformat(),
            # n / n_clean describe the ANALYSIS scope (what every aggregate below
            # covers), not the shipped case array. n_all is the shipped total.
            "n":len(cases),"n_clean":len(clean),
            "n_all":len(all_cases),
            "analysis_scope":analysis_scope,
            "ann_mix":dict(ann_mix),
            "scope_note":(
                "Aggregates (domain_stats, ct_matrix, temporal, topology, "
                "precedent, quality) are computed from "
                f"{analysis_scope} rows only ({len(cases)} cases). The `cases` "
                f"array ships all {len(all_cases)} annotations so search and "
                "permalinks resolve; each carries an `ann` provenance code."),
            "db":os.path.basename(db_path),"version":"1.5",
            # Corpus release identity, computed from the data (typology/corpus_version.py).
            # A consumer must be able to tell a finished release from a moving one.
            "corpus_version":_CORPUS_VERSION.get("corpus_version"),
            "release_state":_CORPUS_VERSION.get("state"),
            "clean_release":_CORPUS_VERSION.get("clean_release"),
            "annotation_regime":_CORPUS_VERSION.get("annotation_regime"),
            "weight_profile":_CORPUS_VERSION.get("weight_profile"),
            "ontology":_CORPUS_VERSION.get("ontology"),
            "release_note":_CORPUS_VERSION.get("release_note"),
        },
        "domain_coverage":coverage,
        "cases":all_cases,
        "domain_stats":domain_stats,
        "ct_matrix":ct_matrix,
        "ct_matrix_normalized":ct_matrix_norm,
        "temporal":temporal,
        "topology":topology,
        "circuit_stats":circuit_stats,
        "ct_cooccurrence":ct_cooccurrence,
        "outcome_cd_by_domain":outcome_cd_by_domain,
        "node_closure_by_outcome":node_closure_by_outcome,
        "role_inventory":role_inventory,
        "structural_signatures":structural_signatures,
        "intervention_windows":intervention_windows,
        "decade_profiles":decade_profiles,
        "cd_distribution":cd_distribution,
        "cascade_stats":cascade_stats,
        "confidence_profile":confidence_profile,
    }

    with open(out_path,"w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False,separators=(",",":"))

    size_kb = os.path.getsize(out_path)//1024
    print(f"\nExported {len(cases)} cases -> {out_path} ({size_kb} KB)")
    print(f"Rollup keys: {[k for k in payload if k not in ('cases','meta')]}")
    print(f"\nKey findings:")
    print(f"  CD ratio: {payload['outcome_cd_by_domain']['_overall']['ratio']}x")
    _cs = cascade_stats
    print(f"  N7-failed cases where a remedy survives: {_cs['violations']} "
          f"({1-_cs['cascade_rate']:.1%}) — a v2 finding, not an error "
          f"(v1 forced these to fail)")
    _ts = topology["stats"]
    _r = f"ratio {_ts['ratio']}x" if _ts["ratio"] is not None else "ratio n/a (see ratio_note)"
    print(f"  Within- vs cross-cluster phi: "
          f"{'within > cross' if _ts['confirms'] else 'not separated'} "
          f"(delta {_ts['delta']}, {_r})")
    print(f"  Unique signatures: {len(structural_signatures)}")
    print(f"  Unique roles (N3): {len(role_inventory)}")

if __name__=="__main__":
    export(args.db, args.out)
