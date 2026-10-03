# Domains 9 to 11: collection failure diagnosis

**WS2 task 3, decision D6.** Written 3 October 2026, after the rows were quarantined by
`migrate_scopes.py`.

---

## 1. What happened

The annotation pipeline ran to completion on 911 cases whose opinion text had never been
collected. It produced 911 structurally valid annotation rows from case-name metadata
alone.

Measured directly from `corpus/*.jsonl`, counting cases whose `opinions` array contains
any text:

| Domain | Cases | With opinion text | Empty | Median chars |
|---|---|---|---|---|
| 9 habeas_corpus | 346 | **5** | 341 (98.6%) | 0 |
| 10 patent_ip | 264 | **4** | 260 (98.5%) | 0 |
| 11 securities_regulation | 301 | **9** | 292 (97.0%) | 0 |
| **9 to 11 total** | **911** | **18 (2.0%)** | **893** | **0** |

Against domains 1 to 8, where collection worked:

| Domain | Cases | With opinion text | Empty | Median chars |
|---|---|---|---|---|
| 1 first_amendment | 659 | 659 | 0 | 13,421 |
| 2 employment_discrimination | 677 | 677 | 0 | 8,304 |
| 3 administrative_law | 753 | 753 | 0 | 22,255 |
| 4 criminal_procedure | 642 | 641 | 1 | 16,034 |
| 5 immigration | 680 | 680 | 0 | **1,190** |
| 6 civil_rights_1983 | 673 | 673 | 0 | 13,161 |
| 7 contract | 651 | 651 | 0 | 18,175 |
| 8 family_law | 520 | 520 | 0 | 21,113 |

The failure is total and clean: `opinions: []`, not truncated text. These are not weak
annotations of difficult cases. They are confabulations from the case name, the court,
and the date.

## 2. The corroborating evidence

Two independent measures agree with the 18-case figure, which is what makes this
diagnosis safe to act on.

- **Confidence.** Only **14 of 911** rows reached high or medium confidence. That is the
  same order as the 18 cases that actually had text. 897 of 911 (98.5%) are low
  confidence.
- **Determinacy.** **439 of 911 (48.2%)** have `chain_outcome = 'indeterminate'`, against
  55 of 5,254 (1.0%) in domains 1 to 8. **900 of 911 (98.8%)** are flagged
  `needs_review`, against 43.0%.

The model was, correctly, reporting that it could not see an opinion. Nothing downstream
acted on that report.

## 3. Why it reached the database

Three gaps lined up, and each is worth fixing independently of whether these domains ever
return.

1. **No text precondition on annotation.** The pipeline annotates whatever row it is
   given. There is no check that an opinion body exists and exceeds a minimum length
   before an API call is made. Note that `export_corpus.py:273` already computes exactly
   this, as `LENGTH(COALESCE(o.plain_text,'')) > ?`, but only for coverage *reporting*.
   The predicate exists; it was never made a gate.
2. **No scope filter on export.** `export_rdf.py` filtered on
   `confidence IN ('high','medium')` with **no domain filter**, so these rows shipped into
   `sool_corpus.ttl` on every nightly export as long as confidence was not low. That is
   how 14 confabulated cases reached a published graph.
3. **Review flags were advisory.** 98.8% `needs_review` and 48.2% `indeterminate` did not
   stop collection, annotation, export, or publication. No threshold anywhere treats a
   per-domain flag rate as a failure condition.

## 4. What was done

Per decision D6, quarantine and drop. Applied by `migrate_scopes.py`:

- All 911 rows copied to `annotations_quarantine_d9_11`, then deleted from `annotations`,
  in one transaction with a verified count match. `annotations` went from 6,165 to 5,254.
- A full file-level backup was taken first, at
  `backups/pre_scopes_migration_20261003_152359/sool_annotations.db`. The rows are
  therefore recoverable two ways.
- Named scope views created, all of which exclude these domains by construction:
  `scope_core` (5,254), `scope_analysis` (5,171), `scope_blind` (5,022),
  `scope_unflagged` (2,995), `scope_highconf` (4,681).
- `export_rdf.py` now reads `scope_highconf` instead of its inline predicate, so the
  export dropped from 4,727 cases to 4,681. The 46-case difference is the confabulated
  rows plus indeterminate outcomes that were previously published.
- `daily_update.py`'s "Corpus total" now reads `scope_unflagged` rather than
  `annotations WHERE NOT needs_review`, which had also been counting these domains.

The corpus stays at 8 domains. No new API spend. No opinion text was re-fetched.

## 5. The fix, if these domains are ever revived

D6 was "drop permanently", so this is recorded for completeness rather than scheduled.

1. **Find the root cause in collection**, which this diagnosis does not establish. The
   text is absent from the JSONL, so the question is whether `collect_caselaw.py` failed
   to request opinion bodies for these domains, whether CourtListener returned cases
   without `opinions` for these query shapes, or whether the cluster-to-opinion follow-up
   request was never made. The 18 successes are the useful sample: compare their
   collection path against a failure.
2. **Establish whether full text exists at source at all.** Habeas and securities
   dockets in particular may be unpublished or summary dispositions with no opinion to
   fetch. If so, no amount of pipeline repair recovers them and the domains are
   genuinely unavailable rather than mis-collected.
3. **Add the precondition** from gap 1 above as a hard gate, so a missing opinion raises
   before an API call rather than after 911 of them.
4. Only then re-collect and re-annotate under the v2 blind regime. That is over 50 cases,
   so it needs an estimate and approval first.

## 6. One new finding, unrelated to the drop

**Domain 5 (immigration) has a median of 1,190 characters of opinion text**, against
8,304 to 22,255 for the other seven domains. It is between 7x and 19x shorter. Every case
has *some* text, so it is not the same failure, but a 1,190-character median is a
paragraph, not an appellate opinion.

This is a live domain inside `scope_core` with 680 cases, and it was not previously
flagged. Two possibilities worth separating: immigration appellate dispositions really
are much shorter (BIA summary affirmances would do it), or the collection is truncating.
Until that is settled, treat any domain-5 comparison as provisional. Recommend adding a
per-domain text-length check to the validation suite so a shift like this surfaces on its
own rather than being found by hand.
