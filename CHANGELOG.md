# Changelog

This file is the canonical record of what changed between SOoL corpus releases,
including what earlier releases reported and why it no longer stands.

It exists so the published pages can be read as a clean statement of the current
state. The pages describe what SOoL holds now; this file holds the history. Anyone
who cited an earlier figure should be able to find out here what became of it.

---

## 2.1.0 — 4 October 2026

The first release in which the vocabulary, the ontology, the annotation prompts,
the exports and the published pages all agree, and the first stated without
correction notices.

### Vocabulary and ontology

- **`AI` retired in favour of `AINF`** (Authority Inflation). Amendment A2. `AI` is
  reserved permanently under R2: never reused, never re-minted. The reason is local
  to this corpus, where the token also means artificial intelligence in 80 places.
  Migrated as data by `scripts/migrate_ai_to_ainf.py`, which parses each stored
  value as JSON and rewrites it element-wise, logging every change to a table
  inside the same database so the migration is exactly reversible. 608 values on
  the reference copy, 612 in production. Raw model output was deliberately left
  untouched, because it is the verbatim artifact the annotation derives from.
- **`RPF` preferred label corrected to "Repair Failure"**, with
  "Repair Procedure Failure" and "Remedy failure" retained as `skos:hiddenLabel`.
  Amendment A1, applied in the ontology under A0 rather than patched downstream.
  "Procedure" imported `PC`'s construct into the REPAIR cluster, which this term is
  not about: the remedy exists and is blocked.
- **MLC expands to "Minimum Legal Chain"**, matching `LOF-ODP-004`'s own
  `dcterms:title`. The other expansion was the outlier.
- **`vocab/registry.json` is now the single source** for every code, label,
  weight, chain link and alias. It is generated, never hand-written, and
  `scripts/audit_terminology.py` checks every user-facing artifact against it.

### Legal Ontologies Foundry alignment

- Four chain positions now cite their `LOF-ODP-004` counterparts: Node 1
  *norm-establishing power*, Node 4 *triggering occurrence*, Node 7 *fully grounded
  legal position*, Node 8 *remedial position*. Nodes 2, 3, 5 and 6 are stated as
  having no counterpart in that pattern rather than forced onto one.
- **The `RF` code collision is resolved.** `RF` denotes Recognition Failure in this
  corpus and Repair Failure in the recognition kernel. The kernel's `RF` (`K-D3`,
  locus *remedy*) aligns to corpus **`RPF`**, confirmed independently by the kernel
  locus, the corpus node (N8) and ODP-004's node-8 term. Under LOF-P-005 an
  identifier is opaque and a label is the claim, so vocabularies are aligned on
  identity and never on an abbreviation. Full record in `docs/RF_DECISION.md`.
- The kernel is vendored at `vocab/kernel-0.2.0.json` so the identity layer is
  reproducible from this repository alone.

### Measures

No figure is published as a bare "CD". Four named measures:

| Measure | Meaning |
|---|---|
| `ct_count` | Unweighted count of active types, 0 to 13. **The default.** |
| `cd_case` | Weighted sum for one adjudication. Ceiling **1.52** under `core-v1`. |
| `cd_upstream` | `cd_case` restricted to nodes 1 to 6. **Required for anything outcome-facing.** |
| `cd_stock` | Accumulated institutional debt over time, clamped to [0,1]. SimLex only. |

### Corpus

- **Domains 9 to 11 (habeas, patent/IP, securities) are excluded.** They were
  annotated from stub text: only 18 of 911 cases had any opinion body. Diagnosis in
  `docs/COLLECTION_FAILURE.md`.
- **Named scope views** replace five inconsistent inline definitions of
  "in corpus". Every published figure names one.

### Corrections carried forward from 2.0.x

These are the claims earlier releases made that no longer stand. They are recorded
here rather than on the pages.

| Earlier claim | Status |
|---|---|
| AUC ≈ 0.98 for outcome prediction from nodes 7 to 8 | **Withdrawn.** Nodes 7 and 8 are entailed by the disposition, so the predictor contained the outcome |
| CD-to-outcome ratio of 13:1 or 14:1 | **Withdrawn.** Computed from `contradiction_debt`, which includes five types definitionally entangled with the disposition |
| RF rate near 64% | **Withdrawn.** Produced by annotation RULE 5, which forced RF wherever Node 7 failed |
| phi = 0.953 | **Withdrawn** with the forcing rules |
| Three domain-specific failure clusters | **Refuted** by the v2 re-annotation. Domains differ by contradiction type, not by primary failure node |
| N7 pivotal in 67% of reversals | **Withdrawn.** Outcome-facing and rule-affected |
| Structure outpredicts judicial ideology | **Withdrawn.** Rested on a circular outcome variable |
| All SCOTUS results | **Withdrawn in full.** All 1,023 annotations carry `regime = scotus-v1-cascade`, and a calibration script had overwritten the scored prediction using the predictor itself. See `docs/SCOTUS_AUDIT.md` |

Two structural causes, not statistical ones:

1. **Forcing rules.** The v1 prompt contained rules (RULE 1, RULE 5) deriving chain
   outcomes from node closures, plus a code-level cascade that added contradiction
   types from closures unconditionally. Both are removed; the current prompt retains
   RULE 0, 2, 3, 4 and 6, and the numbering gaps are the removals.
2. **Outcome entanglement.** `RF`, `RCL`, `CC`, `SE` and `RPF` are definitionally
   entangled with the disposition.

**SOoL makes no predictive claims.** The v1 material remains retrievable on the
`archive/v1` branch.

### What survived, and is the point of the release

- The **N7/N8 directional asymmetry**, which holds under a prompt-variant control
  that instructed the model to expect the reverse.
- The **elevation of Authority Inflation in administrative law** (14.7%, 5.7x,
  p=2e-45), which is unforced.

### Known limits

- The human gold standard (300 cases, two or more trained annotators) is not yet
  built. It gates most inferential use of the corpus.
- `NI` is rule-forced in the current prompt, so its frequency is not independent
  evidence.
- Node 7 is claimed by two types (`CC`, `SE`), so per-node uniqueness is not
  enforceable; the signature set, not the node, is the clustering key.
- Domain 5 (immigration) has a median opinion length of 1,190 characters against
  8,304 to 22,255 elsewhere. Unexplained; treat domain-5 comparisons as provisional.
- `SimLex.html` ships a different 13-type list summing to **1.63**, sharing six
  codes with `core-v1`. Always name the profile.

---

## 2.0.1 — 3 October 2026 (staged, not published)

Re-manifested the 6 August freeze, whose `SHA256SUMS.txt` predated four of its own
payload files. Regenerated the Turtle exports, which had carried two type IRIs
(`sool:RoleContradictionTriad`, `sool:SovereigntyException`) that exist in no
ontology file. Added `LICENSE` (MIT) and `LICENSE-DATA.md` (CC BY 4.0).

## 2.0.0 — 6 August 2026 (frozen, never published)

First full v2 re-annotation under the blind regime with the forcing rules removed.

## 1.x — to 31 March 2026

Withdrawn. See the corrections table above and the `archive/v1` branch.
