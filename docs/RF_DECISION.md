# The `RF` Collision: decision record

**Decided 3 October 2026.** Resolves the blocker recorded in the integration plan and in
`docs/INVENTORY.md` section 8. Implemented in `build_registry.py`, enforced by
`vocab/registry.json`, and visible in `vocab/crosswalk.csv`.

---

## 1. The problem

The code `RF` denoted two different things in two sources that a crosswalk was about to join:

| Source | Code | Label | Node or locus |
|---|---|---|---|
| Corpus (`core-v1`, 6,165 annotations) | `RF` | Recognition Failure | nodes 6/7 |
| Corpus (`core-v1`) | `RPF` | Repair Procedure Failure | node 8 |
| Kernel (`kernel.json` 0.2.0) | `RF` | **Repair** Failure | locus `remedy` |
| Kernel (`kernel.json` 0.2.0) | `CT-6` | **Recognition** Failure | locus `criteria` |

Joining on the code string would have mapped the kernel's **Repair** Failure onto the
corpus's **Recognition** Failure. Both directions are wrong, and nothing would have
raised an error, because both sides have a row called `RF`.

Amendment A1 made this sharper rather than easier. A1 sets `RPF`'s prefLabel to
"Repair Failure", which is exactly the kernel's label for `RF`. So after A1 the
collision exists on the **label** as well as the code.

---

## 2. What the LOF drafts settle

The decision is not a preference. Three conventions in the ODP drafts
(`lof/review-packet/lof-odp-004/src/sparql/`) determine it.

| Pattern | Rule | Consequence here |
|---|---|---|
| **LOF-P-005** | IRIs are opaque and numeric, `https://w3id.org/lof/ODP004_0001002`. Never mnemonic | **A code is not an identifier.** `RF` is notation, scoped to a vocabulary. Identity is the IRI |
| **LOF-P-003** | No two terms share a label | "Repair Failure" and "Recognition Failure" each belong to exactly one term |
| **LOF-P-012** | At most one English label per term | `prefLabel` is single-valued; everything else is `altLabel` or `hiddenLabel` |

LOF-P-005 dissolves the collision. The two `RF` rows were never competing for an
identifier, because in LOF a code never was one. They are two notations that happen to
share a string, in two different vocabularies.

LOF-P-003 then forces the alignment to be made on something that **is** identity-bearing.
Two candidates were available and they agree.

---

## 3. The mapping, and why it is not a judgement call

`kernel.json` indexes every named type to a **primitive** and a **locus**, and partitions
them by **`system_kind`**. The five `legal_order` types are the ones that can align to an
adjudication corpus at all; the seven `classification` types apply the same primitives to
classification systems, which is a different thing.

Three independent sources converge:

| Evidence | Says |
|---|---|
| `kernel.json` | `RF` has `locus = remedy`, `primitive = K-D3`, `system_kind = legal_order` |
| Corpus | `RPF` is node **N8**, confirmed in `typology/mlclink_confirmation.csv` under A4 |
| ODP-004 | node 8 is `lof:ODP004_0001002`, **"remedial position"** |

So:

> **kernel `RF` (K-D3, locus `remedy`) ↔ corpus `RPF` (node N8) ↔ `lof:ODP004_0001002`.**

And corpus `RF` (Recognition Failure, nodes 6/7) has **no `legal_order` kernel
counterpart**. The kernel's "Recognition Failure" is `CT-6`, a `classification`-kind type
at the `criteria` locus under `K-C3`. It is a failure of a classification system's
criteria, not a failure of legal recognition in an adjudication.

No weighing of preferences was required. The locus, the node, and the ODP-004 term all
point the same way.

---

## 4. What was implemented

### 4.1 Codes demoted to notation

Every registry entry carries a `notation` map keyed by vocabulary, so a code is never
read bare:

```json
"RPF": {
  "prefLabel": "Repair Failure",
  "notation": { "core-v1": "RPF", "simlex-v1.3": "RPF", "kernel-0.2.0": "RF" },
  "kernel": {
    "primitive": "K-D3", "locus": "remedy", "kernel_key": "RF",
    "code_collision": "The kernel's key 'RF' is NOT the corpus code 'RF'. This entry
                       is corpus RPF. Mapping is by locus (remedy) and node, never by
                       code string."
  }
}
```

In `vocab/crosswalk.csv` the string `RF` now appears in two different columns on two
different rows: as `corpus_code_core_v1` on the Recognition Failure row, and as
`kernel_key` on the Repair Failure row. A reader cannot conflate them, and a join on
`kernel_key` cannot hit the wrong row.

### 4.2 LOF-P-003 enforced, not assumed

`build_registry.py` checks label uniqueness across all 13 entries and exits non-zero on a
duplicate. It also checks across the kernel's other `system_kind`, which is where the
residual collision lives. The generator reports it:

```
LABEL COLLISION : 'Recognition Failure' kernel CT-6 (classification) vs corpus RF
```

This is a detected finding, not an assertion in prose. It regenerates on every run.

### 4.3 The residual collision is escalated, not patched

Corpus `RF` and kernel `CT-6` both claim the label "Recognition Failure". Under LOF-P-003
one must change. The registry records the recommendation and does **not** act on it:

> A0 escalation: relabel the kernel entry. The corpus label has 6,165 annotations behind it.

Amendment A0 forbids correcting an ontology defect by alias or downstream override. The
correction belongs in the kernel, with a diff attached, and the kernel is in another
project (`projects/recognition`). It is therefore out of scope for this repository and is
recorded as an owner action. **Nothing downstream silently depends on the outcome**,
because the alignment is keyed on locus, not on that label.

### 4.4 A1 handled through A0, not around it

The ontology of record says "Repair Procedure Failure". The registry says "Repair
Failure". Rather than diverge silently, the entry is marked
`status: pending_ontology_correction`, retains `ontologyLabel`, and the generator writes
`vocab/a0_pending.diff`:

```
## RPF  (sool:RepairProcedureFailure)
-  rdfs:label "Repair Procedure Failure"@en ;
+  rdfs:label "Repair Failure"@en ;
+  skos:hiddenLabel "Repair Procedure Failure"@en ;   # deprecated
```

Apply it by hand after review. The registry does not edit the ontology.

---

## 5. Two things this fixed on the way past

**The "8 of 12 primitives" finding was overstated.** My earlier note recorded it as a
mapping defect. It is partly by design: the kernel indexes types by primitive **and
locus** and partitions by `system_kind`, so a primitive is legitimately reused across
loci (`K-C3` carries both `CF` at the `assessor` locus and `CT-6` at `criteria`). The
real residue is narrower: `K-A2`, `K-C2`, `K-D1`, and `K-D2` are mapped to no named type
in either kind. That is a **coverage gap to close**, not a wrong mapping. Corrected here
and in `docs/INVENTORY.md`.

**N7 is claimed by two types.** The generator detects it:

```
mlclink_multiclaim: {"N7": ["CC", "SE"]}
```

So a constraint of the form "each node has exactly one registered type" is unsatisfiable
for N7 without a discriminator. Rather than invent one, the registry records the
multi-claim and notes that the **set**, not the node, is the clustering key. This matters
because `structural_signature` is built from `NodeN:TypeCode` pairs, and N7 pairs are not
unique.

---

## 6. Verification

```bash
python3 build_registry.py --check     # validates, writes nothing, exits 1 on violation
python3 build_registry.py             # regenerates vocab/registry.json + crosswalk.csv
```

Current output, which reproduces every independently known figure:

| Check | Value | Agrees with |
|---|---|---|
| types | 13 | ontology of record |
| `core-v1` ceiling | **1.52** | `CLAUDE.md`, and refutes the stale 2.27 in `AMENDMENTS.md` A3 |
| `simlex-v1.3` ceiling | **1.63** | spec section 1.6 item 3 |
| default measure | `ct_count` | decision D7 |
| `mlclink_unconfirmed` | none | A4 cleared, 12 AGREE + TC accepted as `2<->4` |
| pending A0 | `RPF` only | amendment A1 |
| simlex unregistered | `AE, CS, EN, RC, RGR, RV, TA` | 7 codes in no ontology |
| label collisions | 1, escalated | LOF-P-003 |

---

## 7. Standing rule this establishes

> **Never join vocabularies on a code string.** Codes are `skos:notation`, scoped to a
> named vocabulary, and two vocabularies may use the same string for different terms.
> Alignment is made on identity-bearing properties: the IRI, or where an IRI is not yet
> minted, a converging pair of structural coordinates such as kernel locus and MLC node.

`build_registry.py` enforces this by construction: `KERNEL_TO_CORPUS` is an explicit,
commented map annotated with the primitive and locus justifying each row, and the
identity layer is attached only through it. There is no path in the generator that joins
on a bare code.
