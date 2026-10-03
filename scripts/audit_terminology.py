#!/usr/bin/env python3
"""
audit_terminology.py — check every user-facing text artifact against the registry,
the measure taxonomy, the withdrawal notice, and the LOF vocabulary.

Report-only by default. Nothing is rewritten unless --fix is passed, and --fix
only touches the mechanical substitutions listed in SAFE_FIX.

The authority is vocab/registry.json, not a list in this file. Codes, labels and
deprecated forms are read from it, so this checker cannot drift from the ontology
the way the hand-typed dictionaries did.

Checks:

  T1  deprecated contradiction label in user-facing text
  T2  deprecated contradiction code used as a code
  T3  a bare "CD" with no measure named
  T4  a contradiction-debt ceiling that is not the registry's
  T5  withdrawn v1 predictive framing
  T6  withdrawn v1 figure
  T7  superseded namespace
  T8  MLC node named without its LOF ODP-004 counterpart (advisory)
  T9  weight profile not named alongside a weighted figure
  T10 the wrong MLC expansion; LOF ODP-004 titles it "Minimum Legal Chain"

Usage:
    python3 audit_terminology.py                  # report
    python3 audit_terminology.py --fix            # apply safe substitutions
    python3 audit_terminology.py --error-mode     # exit 1 on any ERROR finding
    python3 audit_terminology.py --path FILE ...  # restrict to given files
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "vocab" / "registry.json"

SKIP_DIRS = {"backups", "venv", "release", "sool_v2_20260806", "lof", ".git",
             "corpus", "logs", "turtle_export", "__pycache__", "typology"}
SCAN_SUFFIX = {".html", ".md", ".py", ".json", ".csv", ".sh", ".txt"}

# Files whose job is to DISCUSS the deprecated forms. Findings here are expected.
EXEMPT = {
    "audit_terminology.py", "build_registry.py", "HARMONIZATION.md",
    "docs/RF_DECISION.md", "docs/INVENTORY.md", "docs/COLLECTION_FAILURE.md",
    "docs/SCOTUS_AUDIT.md", "docs/DEPLOYMENT_LOG.md", "docs/CREDENTIAL_REPORT.md",
    "SOOL_INTEGRATION_SPEC.md", "CLAUDE.md", "vocab/registry.json",
    "vocab/crosswalk.csv", "vocab/KERNEL_PROVENANCE.md", "sool_bfo_mlc_core.ttl",
    "web/README.md", "stage_release.py", "restructure_repo.py",
}

# LOF ODP-004, read off lof-odp-004-edit.ttl. The MLC node a term corresponds to.
LOF_TERMS = {
    1: ("norm-establishing power", "lof:ODP004_0001000"),
    4: ("triggering occurrence", "lof:ODP004_0001001"),
    7: ("fully grounded legal position", "lof:ODP004_0001003"),
    8: ("remedial position", "lof:ODP004_0001002"),
}

MEASURES = ("ct_count", "cd_case", "cd_upstream", "cd_stock")

WITHDRAWN_FRAMING = [
    (r"Predicts? Its Outcomes", "v1 predictive title"),
    (r"\boutcome prediction\b", "v1 predictive framing"),
    (r"High CD predicts", "v1 predictive claim"),
    (r"\bpredicts reversal\b", "v1 predictive claim"),
    (r"predictive (power|accuracy|validity)", "v1 predictive claim"),
]

WITHDRAWN_FIGURES = [
    (r"\bAUC[^.\n]{0,24}0\.9[78]", "withdrawn v1 AUC"),
    (r"\b1[34](\.0)?\s*[:x×]\s*1\b", "withdrawn v1 ratio"),
    (r"\b1[34]\.0x\b", "withdrawn v1 ratio"),
    (r"\bphi\s*=?\s*0\.95", "withdrawn v1 phi"),
    (r"three[- ]cluster", "withdrawn v1 clustering claim"),
    (r"\b67%\s+of\s+reversals", "withdrawn v1 claim"),
]

SUPERSEDED_NS = [
    "example.org/legal-ontology", "example.org/sool",
    "seal.tamu.edu/legal-kernel", "seal.tamu.edu/ontology/sool",
    "davidkoepsell.com/bfo-agent",
]

STALE_CEILINGS = ["2.27", "2.2700"]

# Split so a repo-wide rename of the full phrase cannot rewrite the detector.
_DEPRECATED_MLC = "Minim" + "al"
_CANONICAL_MLC = "Minim" + "um"


class Finding:
    __slots__ = ("path", "line", "code", "severity", "text", "why")

    def __init__(self, path, line, code, severity, text, why):
        self.path, self.line, self.code = path, line, code
        self.severity, self.text, self.why = severity, text, why


def load_registry() -> dict:
    if not REGISTRY.exists():
        sys.exit(f"*** ABORT: {REGISTRY} missing. Run: python3 build_registry.py")
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def build_rules(reg: dict):
    types = reg["types"]
    pref = {c: e["prefLabel"] for c, e in types.items()}
    ceiling = reg["_meta"]["weight_profiles"]["core-v1"]["ceiling"]

    # Deprecated labels -> the current prefLabel of the term that supersedes them.
    dep_label: dict[str, str] = {}
    for code, e in types.items():
        for alt in e.get("altLabels") or []:
            if alt and alt != e["prefLabel"] and not re.fullmatch(r"[A-Z0-9]{1,5}", alt):
                dep_label[alt] = e["prefLabel"]
    # Known superseded forms that may not survive into altLabels.
    for old, new_code in (("Repair Procedure Failure", "RPF"),
                          ("Authority Incompleteness", "AINF"),
                          ("Constitutive Failure", "CF"),
                          ("Sovereignty Exception", "SE"),
                          ("Role Contradiction Triad", "RC3")):
        if new_code in pref:
            dep_label.setdefault(old, pref[new_code])

    dep_code = {}
    for code, e in types.items():
        for d in e.get("deprecatedCodes") or []:
            dep_code[d] = code
    return pref, dep_label, dep_code, ceiling


def relpath(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def iter_files(paths: list[str] | None):
    if paths:
        for s in paths:
            p = Path(s)
            if p.is_file():
                yield p
        return
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix not in SCAN_SUFFIX:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts[:-1]):
            continue
        if p.name.endswith((".prev.html", ".pre-remediation")):
            continue
        yield p


def audit(paths=None) -> tuple[list[Finding], dict]:
    reg = load_registry()
    pref, dep_label, dep_code, ceiling = build_rules(reg)
    out: list[Finding] = []

    ceil_s = f"{ceiling:g}"
    bare_cd = re.compile(r"(?<![A-Za-z_])CD(?![_A-Za-z])")
    measure_near = re.compile("|".join(MEASURES))

    for p in iter_files(paths):
        rel = relpath(p)
        if rel in EXEMPT or p.name in EXEMPT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()

        for i, ln in enumerate(lines, 1):
            # T1 deprecated label
            for old, new in dep_label.items():
                if old in ln:
                    out.append(Finding(rel, i, "T1", "ERROR", old,
                                       f'superseded label; use "{new}"'))
            # T2 deprecated code, as a standalone token
            for old, new in dep_code.items():
                if re.search(rf"\b{re.escape(old)}\b", ln):
                    # 'AI' overwhelmingly means artificial intelligence here, so
                    # only flag it next to typology context.
                    ctx = re.search(
                        r"contradiction|cdWeight|weight|typolog|node\s*[1-8]|"
                        r"Authority|structural_signature|active_ct", ln, re.I)
                    if ctx:
                        out.append(Finding(rel, i, "T2", "ERROR", old,
                                           f"superseded code; use {new}"))
            # T3 bare CD
            if bare_cd.search(ln) and not measure_near.search(ln):
                if not re.search(r"CD\s*(weight|profile)", ln, re.I):
                    out.append(Finding(rel, i, "T3", "WARN", "CD",
                                       "bare 'CD'; name ct_count, cd_case, "
                                       "cd_upstream or cd_stock"))
            # T4 stale ceiling
            for bad in STALE_CEILINGS:
                if bad in ln and "ceiling" in ln.lower():
                    out.append(Finding(rel, i, "T4", "ERROR", bad,
                                       f"stale ceiling; core-v1 is {ceil_s}"))
            # T5 withdrawn framing
            for pat, why in WITHDRAWN_FRAMING:
                m = re.search(pat, ln, re.I)
                if m:
                    out.append(Finding(rel, i, "T5", "ERROR", m.group(0), why))
            # T6 withdrawn figures
            for pat, why in WITHDRAWN_FIGURES:
                m = re.search(pat, ln, re.I)
                if m:
                    out.append(Finding(rel, i, "T6", "ERROR", m.group(0), why))
            # T7 superseded namespace
            for ns in SUPERSEDED_NS:
                if ns in ln:
                    out.append(Finding(rel, i, "T7", "WARN", ns,
                                       "superseded namespace; canonical is "
                                       "https://w3id.org/sool#"))
            # T9 weighted figure without a profile
            if re.search(r"\bcd_case\b", ln) and not re.search(
                    r"core-v1|simlex|profile", ln, re.I):
                out.append(Finding(rel, i, "T9", "WARN", "cd_case",
                                   "weighted measure without a profile id"))
            # T10 MLC expansion. LOF-ODP-004 is titled "Minimum Legal Chain"
            # (dcterms:title), and the live corpus runs ~285 to 31 in its
            # favour, so the other form is the outlier rather than a newer term.
            #
            # The deprecated word is assembled from fragments on purpose. A bulk
            # find-and-replace of the full phrase across the repo would otherwise
            # rewrite this very line and silently invert the check, so that it
            # began flagging the correct form. That happened on 2026-10-03.
            m = re.search(rf"\b{_DEPRECATED_MLC} Legal Chain\b", ln, re.I)
            if m:
                out.append(Finding(rel, i, "T10", "ERROR", m.group(0),
                                   'LOF ODP-004 titles this "Minimum Legal '
                                   'Chain"'))

        # T8 advisory, per file: MLC nodes discussed without LOF terms
        if re.search(r"\bNode\s*[1-8]\b", text) and "ODP004" not in text:
            if p.suffix in (".html", ".md"):
                out.append(Finding(rel, 0, "T8", "INFO", "Node N",
                                   "discusses MLC nodes without citing the "
                                   "ODP-004 counterpart terms"))

    return out, {"ceiling": ceiling, "pref": pref, "dep_label": dep_label,
                 "dep_code": dep_code}


# Mechanical substitutions only. Anything requiring judgement is reported, never
# rewritten: a withdrawn claim needs removing or restating, not find-and-replace.
def safe_fix(findings: list[Finding], ctx: dict) -> dict[str, int]:
    changed: dict[str, int] = {}
    by_file: dict[str, list[Finding]] = {}
    for f in findings:
        if f.code == "T1":
            by_file.setdefault(f.path, []).append(f)
    for rel, fs in by_file.items():
        p = ROOT / rel
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        n = 0
        for old, new in ctx["dep_label"].items():
            if old in text:
                n += text.count(old)
                text = text.replace(old, new)
        if n:
            p.write_text(text, encoding="utf-8")
            changed[rel] = n
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--error-mode", action="store_true")
    ap.add_argument("--path", nargs="*")
    args = ap.parse_args()

    findings, ctx = audit(args.path)

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: (order[f.severity], f.code, f.path, f.line))

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.code] = counts.get(f.code, 0) + 1

    print(f"registry core-v1 ceiling: {ctx['ceiling']}")
    print(f"findings: {len(findings)}\n")

    labels = {
        "T1": "superseded label", "T2": "superseded code",
        "T3": "bare CD, no measure named", "T4": "stale ceiling",
        "T5": "withdrawn predictive framing", "T6": "withdrawn v1 figure",
        "T7": "superseded namespace", "T8": "no LOF term cited (advisory)",
        "T9": "weighted figure without profile id",
        "T10": '"Minimal" should be "Minimum" Legal Chain',
    }
    for code in sorted(counts):
        sev = next(f.severity for f in findings if f.code == code)
        print(f"  {code}  {counts[code]:>4}  {sev:<5}  {labels[code]}")

    print()
    shown = 0
    for f in findings:
        if f.severity == "INFO":
            continue
        if shown >= 60:
            print(f"  ... {len([x for x in findings if x.severity!='INFO'])-shown} more")
            break
        loc = f"{f.path}:{f.line}" if f.line else f.path
        print(f"  {f.code} {f.severity:<5} {loc:<46} {f.text[:30]:<32} {f.why}")
        shown += 1

    if args.fix:
        changed = safe_fix(findings, ctx)
        print(f"\n--fix applied to {len(changed)} file(s):")
        for rel, n in sorted(changed.items()):
            print(f"  {rel}: {n} substitution(s)")
        print("Only superseded labels (T1) are rewritten. T5/T6 need judgement "
              "and were not touched.")

    errs = sum(1 for f in findings if f.severity == "ERROR")
    if args.error_mode and errs:
        print(f"\n{errs} ERROR finding(s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
