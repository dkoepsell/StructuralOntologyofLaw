# Interactive pages

## Two pages are deliberately absent from this release

`SOoL_QueryTool.html` and `sool_poster.html` are **not** included in v2.0.1.

Both still carry version 1 predictive framing that the top-level `README.md`
declares withdrawn. Measured before removal: the query tool contained 10
occurrences and the poster 2, including the title "When the Architecture of Law
Predicts Its Outcomes", the phrase "outcome prediction" in the case analyzer, the
claim "High CD predicts reversal", a CD-to-outcome ratio of 14.0:1, and
"N7 pivotal: primary failure point in 67% of reversals".

Shipping them inside a release whose README withdraws those claims would make this
repository contradict itself, and a reader would have no way to tell which parts of
the page still stand. Removing them is the honest option, not a loss of material:

- The last published versions remain on the `archive/v1` branch.
- They are scheduled for rebuild, not deletion. The rebuild regenerates every
  figure from a named scope with a stated regime and weight profile, and fails the
  build on any numeric literal that cannot be traced to its source.

## What is here, and is clean

| File | Audited for withdrawn framing |
|---|---|
| `SimLex.html` | clean |
| `SOoL-MLC-Auditor.html` | clean |
| `scotus_case_browser.html` | clean |
| `iracplus/` | clean |

One caution on `SimLex.html`. It embeds a **different** 13-type contradiction list
whose weights sum to **1.63**, sharing only six codes with the corpus profile
`core-v1` (which sums to 1.52). It also presents three distinct quantities under
the bare name "CD" (`cd_case`, `ct_count`, `cd_stock`) without naming a weight
profile, and its `cd_case` tooltip cites the `core-v1` ceiling of 1.52 rather than
its own 1.63. Treat any number it displays as belonging to the simulator, not to
the corpus. Its codes are recorded in `vocab/registry.json` under
`simlex_unregistered_codes`.

`scotus_case_browser.html` reads SCOTUS data whose underlying annotations are
withdrawn in full; see `docs/SCOTUS_AUDIT.md`. It is retained because it contains
no predictive framing of its own, but do not treat what it displays as a finding.
