# Release assets and large files

WS3 task 3. Files over 50 MB are **not** committed to the git tree. They are
attached to the GitHub release and deposited on Zenodo for a DOI.

## Attach to the release

| Asset | Size | Source in the freeze |
|---|---|---|
| `blind_control.db` | 0.0 MB | `sool_v2_20260806/blind_control.db` |
| `p4_control.db` | 2.4 MB | `sool_v2_20260806/databases/p4_control.db` |
| `scotus_backtest.db` | 72.6 MB | `sool_v2_20260806/databases/scotus_backtest.db` |
| `sool_annotations.db` | 60.4 MB | `sool_v2_20260806/databases/sool_annotations.db` |
| `sool_cases_meta.db` | 4.2 MB | `sool_v2_20260806/databases/sool_cases_meta.db` |
| `sool_criminal_annotations.db` | 5.6 MB | `sool_v2_20260806/databases/sool_criminal_annotations.db` |
| `sool_followup.db` | 0.2 MB | `sool_v2_20260806/databases/sool_followup.db` |
| `sool_corpus_data.json` | 17.4 MB | `sool_v2_20260806/exports/sool_corpus_data.json` |

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

| Asset | sha256 |
|---|---|
| `blind_control.db` | `485d3e832dccd1dd84c0a6066c32cefb63dd8727f48e1632dd498dad6dff0927` |
| `p4_control.db` | `fb329ca94110eb4308439091b9650228e0262db20f78a04ea556efaae794e90d` |
| `scotus_backtest.db` | `06173fb1b7a77d13dc2ebf7cfe86e7d08fd77df1e681c21a2b8260fe49069cb5` |
| `sool_annotations.db` | `bbeb9f24c62220859cb677b9e5a732e66b5b89d9f5d03543ced41aa7df3a1088` |
| `sool_cases_meta.db` | `a17bc29abb8b03df558623c6b0c2a2dedd7a546203ee8938870aecead12a129e` |
| `sool_criminal_annotations.db` | `c6b31715ee5aa3e856af62c7306c6a3475bf64684f358a8b326ed09e0feba2a9` |
| `sool_followup.db` | `92d672d842ef3e328f39c70a8dd8f65d39a0784bb95cf98cdf629b46b7099e55` |
| `sool_corpus_data.json` | `6f925de2a9e81f47663c491d38447192080bfbc729e92ba4b981b09bdc59b406` |
| `sool_corpus.ttl` (generated) | `f6f571cee98312bc28f62c79f8472803834bddddbaaaba48a8f12ffff29cde26` |
