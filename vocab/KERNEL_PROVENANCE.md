# Vendored kernel: provenance

`vocab/kernel-0.2.0.json` is a pinned copy of the recognition kernel, vendored into
this project on 3 October 2026.

| | |
|---|---|
| Upstream | `/home/drkoepsell/projects/recognition/recognition-kernel/data/kernel.json` |
| `kernel_version` | 0.2.0 |
| Cites | *A Structural Ontology of the Law* (Koepsell, forthcoming), §7.2 Table 7 |
| Licence | CC BY 4.0, consistent with `LICENSE-DATA.md` |

## Why it is vendored rather than referenced

The kernel is the **identity layer** of `vocab/registry.json`: it supplies the
`K-A1` to `K-D3` primitives, the four strata, and the locus of each named type.
The `RF` to `RPF` alignment resolves through `locus = remedy`, so losing the kernel
loses the basis of that mapping (see `docs/RF_DECISION.md`).

It previously lived only in a separate repository, which created two failure modes:

1. On the production host (a different user account) the path did not resolve, so
   `build_registry.py` reported `kernel present: False`. A regeneration there would
   have silently dropped the identity layer. `build_registry.py` now refuses to do
   that, but refusing is not the same as working.
2. A release could not reproduce its own identity layer, since the kernel was not
   part of any published artifact.

Vendoring fixes both. The registry is now reproducible from this repository alone.

## Upstream defects, recorded not patched

The vendored copy is byte-identical to upstream, including two known gaps. They are
upstream's to fix; this project does not silently diverge from the kernel.

- **Four primitives map to no named type**: `K-A2`, `K-C2`, `K-D1`, `K-D2`. A
  coverage gap, not a wrong mapping. Note that reusing a primitive across loci is
  by design, so "8 of 12 used" is not itself a defect.
- **Seven of twelve named types carry placeholder keys** `CT-1` to `CT-7` rather
  than real codes. All seven are `system_kind: classification`, and only the five
  `legal_order` types align to this corpus, so the placeholders do not affect the
  crosswalk.
- **One label collision with this corpus**: kernel `CT-6` and corpus `RF` both
  claim "Recognition Failure" for different constructs, which violates LOF-P-003.
  `build_registry.py` detects and reports it on every run. The correction belongs
  upstream; nothing here depends on the outcome, because the alignment is keyed on
  locus rather than on that label.

## Updating

```bash
cp <upstream>/kernel.json vocab/kernel-<new-version>.json
rm vocab/kernel-<old-version>.json      # the loader takes the highest version
python3 build_registry.py               # regenerate and re-verify
```

The loader picks the highest-sorting `vocab/kernel-*.json`. `SOOL_KERNEL_JSON`
overrides it for a one-off run against an unreleased kernel.
