#!/usr/bin/env python3
"""
stage_release.py — stage the v2.0.1 citable release. Stages only; never pushes.

WS3 tasks 1 and 3. Works on a copy: `sool_v2_20260806/` is never modified
(operating rule 2).

Why 2.0.1 and not 2.0.0. The frozen directory cannot be checksum-verified as it
stands. `SHA256SUMS.txt`, `README.md` and `FILELIST.txt` are stamped 14:33, while
`blind_control.py` (15:01), `sool_v2_audit.py` (15:01), `blind_control.db` (15:03)
and `databases/` (15:38) are all later, so the manifest cannot cover them. Any
honest release has to re-manifest, and a re-manifested artifact is a new one. It is
labelled 2.0.1 and the README says exactly what differs from the 6 August freeze.

What this does:

  1. copy the freeze to a staging tree, excluding scrub targets and the two
     databases over 50 MB (those become release assets, WS3 task 3)
  2. regenerate the Turtle exports from the frozen database with the corrected
     exporter, so the release graph has no dangling type IRIs
  3. write LICENSE (MIT), LICENSE-DATA.md (CC BY 4.0), CITATION.cff, README.md
  4. write VERSION.json with 2.0.1 and the registry version
  5. write ASSETS.md listing what to attach to the GitHub release and Zenodo
  6. re-manifest SHA256SUMS.txt and FILELIST.txt over the actual tree
  7. verify the manifest against the tree it just wrote

Usage:
    python3 stage_release.py                 # stage into release/sool_v2.0.1/
    python3 stage_release.py --verify-only   # re-verify an existing staging tree
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / "sool_v2_20260806"
STAGE = ROOT / "release" / "sool_v2.1.0"      # the git tree
ASSETS_DIR = ROOT / "release" / "assets"      # attached to the release, not committed
WORK = ROOT / "release" / ".work"

VERSION = "2.1.0"
FROZEN_VERSION = "2.0.1"
# Anything at or above this goes to release assets rather than the git tree.
# 50 MB was the spec's figure, but it is the wrong rule on its own: a 47 MB
# generated Turtle graph is under it and still has no business in git history,
# where it is permanent. The tree holds source; generated artifacts and databases
# are assets at any size.
ASSET_THRESHOLD = 5 * 1024 * 1024

# Held back regardless of size, because they are generated or are data.
ASSET_DIR_PREFIX = ("databases/",)
ASSET_SUFFIX = (".db", ".db-wal", ".db-shm", ".zip")

# Removed from the tree entirely.
SCRUB_NAMES = {"CLAUDE.md"}
SCRUB_PREFIX = ("RESUME_HERE_",)
SCRUB_SUFFIX = (":Zone.Identifier",)


def is_scrubbed(p: Path) -> str | None:
    if p.name in SCRUB_NAMES:
        return "working instructions, not part of the record"
    if p.name.startswith(SCRUB_PREFIX):
        return "session scratch note"
    if p.name.endswith(SCRUB_SUFFIX):
        return "Windows download taint marker; corrupts manifest walks"
    return None


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_tree() -> tuple[list[tuple[Path, str]], list[tuple[Path, int]]]:
    """Copy the freeze into STAGE. Returns (scrubbed, assets_held_back)."""
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    scrubbed: list[tuple[Path, str]] = []
    assets: list[tuple[Path, int]] = []

    for src in sorted(FROZEN.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(FROZEN)

        why = is_scrubbed(src)
        if why:
            scrubbed.append((rel, why))
            continue

        size = src.stat().st_size
        relstr = rel.as_posix()
        if (size >= ASSET_THRESHOLD
                or relstr.startswith(ASSET_DIR_PREFIX)
                or relstr.endswith(ASSET_SUFFIX)):
            assets.append((rel, size))
            continue

        dst = STAGE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return scrubbed, assets


def regenerate_turtle() -> dict:
    """Rebuild the Turtle exports from the frozen DB with the corrected exporter.

    The frozen exports predate two fixes: export_rdf.py emitted
    sool:RoleContradictionTriad and sool:SovereigntyException, neither of which
    exists in any TTL, and it had no domain filter so the confabulated domains
    9 to 11 shipped into the graph. Shipping the frozen Turtle would publish both
    defects under a corrected release number.
    """
    WORK.mkdir(parents=True, exist_ok=True)
    frozen_db = FROZEN / "databases" / "sool_annotations.db"
    if not frozen_db.exists():
        return {"ok": False, "why": f"{frozen_db} not found"}

    work_db = WORK / "sool_annotations.db"
    shutil.copy2(frozen_db, work_db)

    # The exporter now reads scope_highconf, so the release snapshot needs the
    # views. Created on the copy, never on the frozen original.
    r = subprocess.run(
        [sys.executable, str(ROOT / "migrate_scopes.py"),
         "--db", str(work_db), "--views-only"],
        cwd=WORK, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {"ok": False, "why": f"view creation failed: {r.stderr[-400:]}"}

    out_dir = WORK / "ttl"
    out_dir.mkdir(exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(ROOT / "export_rdf.py"), "--civil-only",
         "--civil-ann-db", str(work_db), "--out-dir", str(out_dir)],
        cwd=ROOT, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {"ok": False, "why": f"export failed: {r.stderr[-400:]}"}

    ttl = out_dir / "sool_corpus.ttl"
    if not ttl.exists():
        return {"ok": False, "why": "exporter produced no sool_corpus.ttl"}

    # Dangling-IRI check against the ontology of record.
    core = (ROOT / "sool_bfo_mlc_core.ttl").read_text(encoding="utf-8")
    import re
    text = ttl.read_text(encoding="utf-8")
    used = set(re.findall(r"sool:hasContradictionType\s+(sool:[A-Za-z0-9_]+)", text))
    dangling = sorted(u for u in used if u not in core)

    # The graph is a generated artifact of ~47 MB. It is a release asset, not git
    # tree content, so the repository does not carry it in history forever.
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    dst = ASSETS_DIR / "sool_corpus.ttl"
    shutil.copy2(ttl, dst)

    conn = sqlite3.connect(f"file:{work_db}?mode=ro", uri=True)
    n = conn.execute("SELECT COUNT(*) FROM scope_highconf").fetchone()[0]
    conn.close()

    return {"ok": True, "cases": n, "classes": len(used),
            "dangling": dangling, "bytes": dst.stat().st_size}


# ---------------------------------------------------------------------------

LICENSE_MIT = """MIT License

Copyright (c) 2026 David R. Koepsell, SEAL Lab, Texas A&M University

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

LICENSE_DATA = """# Data, ontology and vocabulary licence

**CC BY 4.0** — Creative Commons Attribution 4.0 International.
Full text: https://creativecommons.org/licenses/by/4.0/legalcode

Chosen to match the Legal Ontologies Foundry, so SOoL terms and LOF ODP terms can
be combined without a licence conflict. Author decision D3.

## What this covers

- `ontology/` — all `.ttl` and `.owl` files
- `vocab/` — `registry.json`, `crosswalk.csv`
- `exports/` — Turtle graphs and JSON exports
- `databases/` — annotation databases, including those distributed as release
  assets rather than in the tree

Code is licensed separately under MIT. See `LICENSE`.

## Attribution

> Koepsell, David R. (2026). *A Structural Ontology of the Law (SOoL): corpus
> release 2.0.1.* SEAL Lab, Texas A&M University. CC BY 4.0.

## What is NOT distributed here

**Opinion text is not redistributed.** The corpus carries CourtListener case
identifiers and a refetch script instead. Court opinions are public records, but
the compiled text is CourtListener's distribution, and redistributing it is not
ours to license. See `REFETCH.md`.
"""


def citation_cff() -> str:
    return f"""cff-version: 1.2.0
message: "If you use this corpus or ontology, please cite it as below."
title: "A Structural Ontology of the Law (SOoL): corpus release {VERSION}"
version: "{VERSION}"
date-released: "{date.today().isoformat()}"
type: dataset
authors:
  - family-names: Koepsell
    given-names: David R.
    affiliation: "SEAL Lab, Texas A&M University"
license: CC-BY-4.0
abstract: >-
  An empirical legal science corpus testing whether Minimum Legal Chain (MLC)
  node failures cluster structurally across doctrinal domains independently of
  doctrine content. Release {VERSION} covers eight domains and carries MLC
  node closures, contradiction-type annotations under weight profile core-v1,
  and a BFO-grounded OWL ontology aligned to Legal Ontologies Foundry patterns.
  Predictive claims made in version 1 are withdrawn; see README.
keywords:
  - legal ontology
  - BFO
  - applied ontology
  - Minimum Legal Chain
  - empirical legal studies
"""


def readme(stats: dict, assets: list[tuple[Path, int]], scopes: dict) -> str:
    asset_rows = "\n".join(
        f"| `{rel}` | {size / 1048576:.0f} MB |" for rel, size in assets
    ) or "| none | |"
    ttl_line = (
        f"{stats['cases']:,} cases, {stats['classes']} contradiction classes, "
        f"no dangling IRIs" if stats.get("ok") else "not regenerated, see ASSETS.md"
    )
    return f"""# SOoL corpus release {VERSION}

**A Structural Ontology of the Law.** SEAL Lab, Texas A&M University.
PI: David R. Koepsell. Released {date.today().isoformat()}.

Code: MIT (`LICENSE`). Ontology, vocabulary and data: CC BY 4.0
(`LICENSE-DATA.md`). Cite via `CITATION.cff`.

---

## Read this first: what was withdrawn

**Every predictive claim made in version 1 is withdrawn.** Specifically, do not
cite from any v1 artifact: an AUC near 0.98, a 13x or 14x CD-to-outcome ratio, an
RF rate near 64%, a phi of 0.953, or the three-cluster domain finding.

Two causes, both structural rather than statistical:

1. **Forcing rules in the annotation prompt.** The v1 pipeline contained rules
   (RULE 1 and RULE 5) that derived a chain outcome from a node closure, and a
   code-level cascade that added contradiction types from closures
   unconditionally. The reported association was partly an artifact of the
   annotation rule, not a finding about law. Both are removed in v2; the live
   prompt retains only RULE 0, 2, 3, 4 and 6, and the numbering gaps are the
   removals.
2. **Outcome entanglement.** Five contradiction types (RF, RCL, CC, SE, RPF) are
   definitionally entangled with the disposition. Any analysis touching outcomes
   must use `cd_upstream`, which restricts to nodes 1 to 6, not `cd_case`.

**The SCOTUS results are also withdrawn in full.** All 1,023 stored SCOTUS
annotations carry `regime = scotus-v1-cascade`, and a separate calibration script
had overwritten the scored prediction using the predictor itself. No SCOTUS figure
in any artifact should be relied on. The SCOTUS pipeline is halted pending
re-annotation. See `docs/SCOTUS_AUDIT.md`.

## What survived, and is the point of this release

- **The N7/N8 directional asymmetry**, which holds under a prompt-variant control
  that instructed the model to expect the reverse.
- **The elevation of Authority Inflation in administrative law** (14.7%, 5.7x,
  p=2e-45), which is unforced. Note that `AI` is renamed `AINF` in this release
  and `AI` is permanently reserved; the alias map in `vocab/registry.json` keeps
  the published figure readable.

## What differs from the 6 August 2026 freeze

This is **{VERSION}**, not {FROZEN_VERSION}, and the difference is not cosmetic.

1. **The {FROZEN_VERSION} manifest could not be verified.** Its `SHA256SUMS.txt` was
   written at 14:33 while four payload files were modified between 15:01 and
   15:38, so the manifest never covered them. This release re-manifests over the
   actual tree, and `SHA256SUMS.txt` is verified against it at staging time.
2. **The Turtle exports are regenerated.** The frozen graph contained two type
   IRIs that exist in no ontology file, `sool:RoleContradictionTriad` and
   `sool:SovereigntyException` (the ontology has `sool:RoleContradiction` and
   `sool:SelfUnderminingEffect`, a different concept). The exporter also had no
   domain filter, so the confabulated domains 9 to 11 were included. Regenerated
   graph: {ttl_line}.
3. **Domains 9 to 11 are excluded.** Habeas, patent/IP and securities were
   annotated from stub text: only 18 of 911 cases had any opinion body at all.
   See `docs/COLLECTION_FAILURE.md`.
4. **A vocabulary registry is included.** `vocab/registry.json` is generated, not
   hand-written, and is the single source for every type code, label, weight and
   chain link. `vocab/crosswalk.csv` maps corpus codes to SimLex codes and kernel
   primitives. See `docs/RF_DECISION.md` for why codes are never joined across
   vocabularies.
5. **Working files removed**: `CLAUDE.md`, `RESUME_HERE_*`, and Windows
   `:Zone.Identifier` taint markers.

## Measures: never cite a bare "CD"

| Measure | Meaning |
|---|---|
| `ct_count` | Unweighted count of active types, 0 to 13. **The default.** |
| `cd_case` | Weighted sum for one adjudication. Ceiling **1.52** under `core-v1`. |
| `cd_upstream` | `cd_case` restricted to nodes 1 to 6. **Use this for anything touching outcomes.** |
| `cd_stock` | An institution's accumulated debt over time, clamped to [0,1]. SimLex only, not comparable to `cd_case`. |

Two cautions. The Quick Reference card bands debt as 0 / 1-2 / 3-4 / 5-6 / 7+,
which is a `ct_count` scale; under `core-v1` every case falls in band 0 and the
upper bands are unreachable. And SimLex ships a **different** 13-type list summing
to **1.63**, sharing only six codes with `core-v1`. Always name the profile.

## Scopes

Figures are meaningless without a population. These are SQL views in the
annotation database, and every published number names one. **These counts are
this release's snapshot (6 August 2026), not the live corpus**, which grows
nightly.

| View | n |
|---|---|
{chr(10).join(f"| `{k}` | {v:,} |" for k, v in scopes.items()) or "| see VERSION.json | |"}

## Large files

Databases over 50 MB are distributed as GitHub release assets and on Zenodo, not
in the git tree. See `ASSETS.md`.

| Asset | Size |
|---|---|
{asset_rows}

## Known open items

- `vocab/a0_pending.diff` holds an unapplied ontology correction (the `RPF`
  preferred label). It is pending author review and is deliberately not applied.
- One label collision remains between the corpus and the recognition kernel, both
  claiming "Recognition Failure" for different constructs. Detected by
  `build_registry.py` and escalated; nothing downstream depends on it.
- Node 7 is claimed by two contradiction types (`CC`, `SE`), so per-node
  uniqueness is not enforceable. Treat the signature set, not the node, as the
  clustering key.
- Domain 5 (immigration) has a median opinion length of 1,190 characters against
  8,304 to 22,255 elsewhere. Unexplained; treat domain-5 comparisons as
  provisional.
- The human gold standard (300 cases, two or more trained annotators) has not yet
  been built. It gates most inferential use of this corpus.
- **`SOoL_QueryTool.html` and `sool_poster.html` are not in this release.** Both
  still carried v1 predictive framing that this README withdraws, so shipping them
  here would make the repository contradict itself. They are scheduled for rebuild
  against generated figures, and the previous versions remain on the `archive/v1`
  branch. See `web/README.md`.
"""


def assets_md(assets: list[tuple[Path, int]], stats: dict) -> str:
    rows = "\n".join(
        f"| `{rel.name}` | {size / 1048576:.1f} MB | `sool_v2_20260806/{rel}` |"
        for rel, size in assets
    ) or "| none | | |"
    return f"""# Release assets and large files

WS3 task 3. Files over 50 MB are **not** committed to the git tree. They are
attached to the GitHub release and deposited on Zenodo for a DOI.

## Attach to the release

| Asset | Size | Source in the freeze |
|---|---|---|
{rows}

## Not redistributed: opinion text

Court opinions are public records, but the compiled full text in these databases
is CourtListener's distribution and is not ours to relicense. The release
therefore publishes **CourtListener case identifiers plus a refetch script**, not
opinion bodies. See `REFETCH.md`.

This matters for reproduction: a third party can rebuild the corpus from the
identifiers with a CourtListener API token, and will get byte-identical case
selection.

## Zenodo deposit

1. Create the deposit, attach the assets above, set licence CC BY 4.0.
2. Copy the DOI into `CITATION.cff` as `doi:` and into the release notes.
3. Reserve the DOI *before* tagging, so the tag and the DOI agree.

## Checksums

`SHA256SUMS.txt` in this tree covers the tree only. Asset checksums are listed
here so they can be verified after download:

{{ASSET_CHECKSUMS}}
"""


def refetch_md(stats: dict) -> str:
    n = f"{stats['cases']:,}" if stats.get("cases") else "the figure in VERSION.json"
    return f"""# Refetching opinion text

This release does not redistribute opinion bodies. It ships CourtListener
identifiers so the corpus can be rebuilt exactly.

## Requirements

- A CourtListener API token, free for research use, from
  https://www.courtlistener.com/help/api/
- Export it as `SOOL_CL_KEY`

## Rebuild

```bash
export SOOL_CL_KEY=...            # never commit this
python3 collect_caselaw.py        # civil, domains 1 to 8
```

Case selection is driven by the stored identifiers, so the rebuilt corpus matches
this release's case set. Opinion text may differ if CourtListener has since
corrected a document.

## Verify the rebuild

```bash
python3 build_registry.py --check     # vocabulary matches the release
python3 migrate_scopes.py --verify    # scope views present, no domain leak
python3 export_rdf.py --civil-only --out-dir ./out
```

The regenerated `scope_highconf` count should be {n} for this release, which is
the snapshot taken on 6 August 2026. The live corpus grows nightly, so a larger
number from a current database is expected and is not a discrepancy. A *smaller*
number, or a different one from this release's own database asset, means a
different corpus state rather than a bug in the exporter.
"""


def write_meta(stats: dict, assets: list[tuple[Path, int]]) -> None:
    # Scope counts come from the release snapshot, never from the live database,
    # and never from a literal in this file (operating rule 7).
    scopes: dict[str, int] = {}
    try:
        conn = sqlite3.connect(f"file:{WORK/'sool_annotations.db'}?mode=ro", uri=True)
        for v in ("scope_core", "scope_analysis", "scope_blind",
                  "scope_unflagged", "scope_highconf"):
            scopes[v] = conn.execute(f"SELECT COUNT(*) FROM {v}").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        pass

    (STAGE / "LICENSE").write_text(LICENSE_MIT, encoding="utf-8")
    (STAGE / "LICENSE-DATA.md").write_text(LICENSE_DATA, encoding="utf-8")
    (STAGE / "CITATION.cff").write_text(citation_cff(), encoding="utf-8")
    (STAGE / "README.md").write_text(readme(stats, assets, scopes), encoding="utf-8")
    (STAGE / "REFETCH.md").write_text(refetch_md(stats), encoding="utf-8")

    # Asset checksums, computed from the frozen originals plus anything staged
    # into release/assets/ by this run.
    lines = ["| Asset | sha256 |", "|---|---|"]
    for rel, _ in assets:
        src = FROZEN / rel
        if src.exists():
            lines.append(f"| `{rel.name}` | `{sha256(src)}` |")
    if ASSETS_DIR.exists():
        for p in sorted(ASSETS_DIR.iterdir()):
            if p.is_file():
                lines.append(f"| `{p.name}` (generated) | `{sha256(p)}` |")
    (STAGE / "ASSETS.md").write_text(
        assets_md(assets, stats).replace("{ASSET_CHECKSUMS}", "\n".join(lines)),
        encoding="utf-8",
    )

    # Carry the registry and crosswalk into the release.
    for name in ("registry.json", "crosswalk.csv", "a0_pending.diff"):
        src = ROOT / "vocab" / name
        if src.exists():
            dst = STAGE / "vocab" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # And the documents a reader needs to interpret the withdrawal notice.
    for name in ("SCOTUS_AUDIT.md", "COLLECTION_FAILURE.md", "RF_DECISION.md",
                 "INVENTORY.md", "DEPLOYMENT_LOG.md"):
        src = ROOT / "docs" / name
        if src.exists():
            dst = STAGE / "docs" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    reg_ver = None
    try:
        reg_ver = json.loads((ROOT / "vocab" / "registry.json").read_text(
            encoding="utf-8"))["_meta"]["registry_version"]
    except Exception:
        pass

    version = {
        "corpus_version": VERSION,
        "supersedes": FROZEN_VERSION,
        "state": "staged",
        "staged": date.today().isoformat(),
        "annotation_regime": "v2",
        "weight_profile": "core-v1",
        "default_measure": "ct_count",
        "registry_version": reg_ver,
        "domains": {"included": [1, 2, 3, 4, 5, 6, 7, 8],
                    "excluded": [9, 10, 11],
                    "excluded_reason": "annotated from stub text; see "
                                       "docs/COLLECTION_FAILURE.md"},
        "scopes": scopes,          # already read from the release snapshot above
        "withdrawn": {
            "v1_predictive_claims": True,
            "scotus_all": True,
            "scotus_reason": "regime=scotus-v1-cascade on all 1,023 rows, plus "
                             "predictor/prediction entanglement in "
                             "apply_scotus_calibration.py",
        },
        "turtle_regenerated": bool(stats.get("ok")),
        "turtle_cases": stats.get("cases"),
        "licence": {"code": "MIT", "data_and_ontology": "CC-BY-4.0"},
    }
    (STAGE / "exports").mkdir(parents=True, exist_ok=True)
    (STAGE / "exports" / "VERSION.json").write_text(
        json.dumps(version, indent=1) + "\n", encoding="utf-8")


def manifest() -> tuple[int, int]:
    files = sorted(p for p in STAGE.rglob("*")
                   if p.is_file() and p.name not in
                   ("SHA256SUMS.txt", "FILELIST.txt"))
    sums, listing, total = [], [], 0
    for p in files:
        rel = p.relative_to(STAGE)
        size = p.stat().st_size
        total += size
        sums.append(f"{sha256(p)}  {rel}")
        listing.append(f"{size:>12}  {rel}")

    (STAGE / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    (STAGE / "FILELIST.txt").write_text(
        f"# SOoL release {VERSION}: {len(files)} files, {total:,} bytes\n"
        + "\n".join(listing) + "\n", encoding="utf-8")
    return len(files), total


def verify() -> tuple[int, list[str]]:
    sums = (STAGE / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    bad, n = [], 0
    for line in sums:
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        p = STAGE / rel
        n += 1
        if not p.exists():
            bad.append(f"MISSING  {rel}")
        elif sha256(p) != digest:
            bad.append(f"MISMATCH {rel}")
    for p in STAGE.rglob("*"):
        if p.is_file() and p.name not in ("SHA256SUMS.txt", "FILELIST.txt"):
            rel = str(p.relative_to(STAGE))
            if not any(l.endswith(f"  {rel}") for l in sums):
                bad.append(f"UNLISTED {rel}")
    return n, bad


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    if args.verify_only:
        if not (STAGE / "SHA256SUMS.txt").exists():
            print(f"*** no staging tree at {STAGE}", file=sys.stderr)
            return 1
        n, bad = verify()
        print(f"verified {n} files")
        for b in bad:
            print(f"  {b}")
        return 1 if bad else 0

    if not FROZEN.exists():
        print(f"*** ABORT: {FROZEN} not found", file=sys.stderr)
        return 1

    print(f"staging {VERSION} from {FROZEN.name} (read-only source)\n")
    scrubbed, assets = stage_tree()

    print("scrubbed from the tree:")
    for rel, why in scrubbed:
        print(f"  - {rel}   ({why})")

    print(f"\nheld back as release assets "
          f"(databases, archives, or >= {ASSET_THRESHOLD // 1048576} MB):")
    for rel, size in assets:
        print(f"  - {rel}   {size/1048576:.1f} MB")

    print("\nregenerating Turtle with the corrected exporter...")
    stats = regenerate_turtle()
    if stats.get("ok"):
        print(f"  cases={stats['cases']:,}  classes={stats['classes']}  "
              f"dangling={stats['dangling'] or 'none'}  "
              f"{stats['bytes']/1048576:.1f} MB")
        if stats["dangling"]:
            print("  *** dangling IRIs present; not releasable", file=sys.stderr)
            return 1
    else:
        print(f"  *** {stats['why']}", file=sys.stderr)
        return 1

    write_meta(stats, assets)
    count, total = manifest()
    print(f"\ngit tree: {count} files, {total/1048576:.1f} MB")
    if ASSETS_DIR.exists():
        asz = sum(p.stat().st_size for p in ASSETS_DIR.rglob("*") if p.is_file())
        print(f"assets  : staged in {ASSETS_DIR.relative_to(ROOT)}, "
              f"{asz/1048576:.1f} MB (not committed)")

    n, bad = verify()
    print(f"verify  : {n} files checked, {len(bad)} problems")
    for b in bad:
        print(f"  {b}")
    if bad:
        return 1

    print(f"\nstaged at {STAGE}")
    print("Nothing was pushed. Nothing in sool_v2_20260806/ was modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
