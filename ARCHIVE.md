# Archived v1 material

The version 1 corpus and its results are **withdrawn**. They are preserved on the
`archive/v1` branch rather than deleted, so the record stays citable and the
withdrawal is auditable.

```bash
git checkout archive/v1
```

## What is there, and why it is withdrawn

| File | Why |
|---|---|
| `sool_annotations.db` | v1 database, 4,259 rows, produced under the forcing-rule regime |
| `sool_corpus_data.json` | v1.2 export of the same |
| `sool-corpus-v2.zip` | opaque bundle that may contain the v1 pipeline |

Two structural defects, not statistical ones:

1. **Forcing rules.** The v1 annotation prompt contained rules (RULE 1, RULE 5)
   deriving a chain outcome from a node closure, plus a code-level cascade that
   added contradiction types from closures unconditionally. Reported associations
   were partly artifacts of the annotation rule.
2. **Outcome entanglement.** Five types (RF, RCL, CC, SE, RPF) are definitionally
   entangled with the disposition, so any outcome-facing analysis must use
   `cd_upstream` (nodes 1 to 6), not `cd_case`.

**Do not cite** an AUC near 0.98, a 13x or 14x ratio, an RF rate near 64%, a phi
of 0.953, or the three-cluster domain finding.

See `docs/README.md` in the current release for what survived.
