# Refetching opinion text

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

The regenerated `scope_highconf` count should be 4,615 for this release, which is
the snapshot taken on 6 August 2026. The live corpus grows nightly, so a larger
number from a current database is expected and is not a discrepancy. A *smaller*
number, or a different one from this release's own database asset, means a
different corpus state rather than a bug in the exporter.
