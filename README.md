# SOoL corpus release 2.1.0

**A Structural Ontology of the Law.** SEAL Lab, Texas A&M University.
PI: David R. Koepsell. Released 2026-10-03.

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

This is **2.1.0**, not 2.0.0, and the difference is not cosmetic.

1. **The 2.0.0 manifest could not be verified.** Its `SHA256SUMS.txt` was
   written at 14:33 while four payload files were modified between 15:01 and
   15:38, so the manifest never covered them. This release re-manifests over the
   actual tree, and `SHA256SUMS.txt` is verified against it at staging time.
2. **The Turtle exports are regenerated.** The frozen graph contained two type
   IRIs that exist in no ontology file, `sool:RoleContradictionTriad` and
   `sool:SovereigntyException` (the ontology has `sool:RoleContradiction` and
   `sool:SelfUnderminingEffect`, a different concept). The exporter also had no
   domain filter, so the confabulated domains 9 to 11 were included. Regenerated
   graph: 4,615 cases, 13 contradiction classes, no dangling IRIs.
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
| `scope_core` | 5,186 |
| `scope_analysis` | 5,103 |
| `scope_blind` | 5,022 |
| `scope_unflagged` | 2,940 |
| `scope_highconf` | 4,615 |

## Large files

Databases over 50 MB are distributed as GitHub release assets and on Zenodo, not
in the git tree. See `ASSETS.md`.

| Asset | Size |
|---|---|
| `blind_control.db` | 0 MB |
| `databases/p4_control.db` | 2 MB |
| `databases/scotus_backtest.db` | 73 MB |
| `databases/sool_annotations.db` | 60 MB |
| `databases/sool_cases_meta.db` | 4 MB |
| `databases/sool_criminal_annotations.db` | 6 MB |
| `databases/sool_followup.db` | 0 MB |
| `exports/sool_corpus_data.json` | 17 MB |

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
