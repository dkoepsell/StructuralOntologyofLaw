# SCOTUS Audit

**WS6 task 1.** Written 3 October 2026. Read-only audit; nothing in `scotus_backtest.db` was modified.

**Purpose:** establish what `scotus_backtest.db` contains, which annotation regime produced it, whether forcing rules or unblinded dispositions touched it, and which published SCOTUS claims depend on it. This document is the prerequisite for author decision **D4** (repair-type categories and adequacy scale).

---

## 1. Bottom line

**No SCOTUS result stands.** All 1,023 stored annotations were produced by the defective `scotus-v1-cascade` regime, and a second, separately undocumented entanglement was applied on top of them. WS6 task 2 asks that each result be classified as stands, needs re-run, or withdrawn; the honest classification is that the entire set is **withdrawn pending re-annotation** under the v2 blind regime.

Three independent defects, any one of which would be disqualifying:

| # | Defect | Scope |
|---|---|---|
| 1 | v1 cascade regime, forcing rules in the prompt | All 1,023 rows |
| 2 | Calibration script overwrites predictions with the predictor | `prediction_correct` as stored |
| 3 | Accuracy rests on 241 of 1,023 rows | Any published accuracy figure |

---

## 2. Database contents

`scotus_backtest.db`, 5 tables, **0 views**.

| Table | Rows |
|---|---|
| `scotus_cases` | 993 |
| `scotus_annotations` | 1,023 |
| `scotus_backtest_runs` | 0 |
| `scotus_daily_state` | 1 |

### Outcome variables, and which are independent

This is better than the civil corpus, where `court_disposition` is 0 of 6,165 non-null. Here the outcome is split across two sources:

| Field | Source | Independent of the annotation? |
|---|---|---|
| `scotus_cases.outcome` | Oyez API, `decisions[0].winning_party`, via `fetch_outcomes.py` | **Yes** |
| `scotus_cases.petitioner_won` | same | **Yes** |
| `scotus_cases.lower_court_decision` | same | **Yes** |
| `scotus_annotations.predicted_outcome` | the annotation | No |
| `scotus_annotations.actual_outcome` | mirrored from the above | No |

So an independent outcome source already exists and is wired up. WS6 task 4 is therefore narrower than "obtain independently coded dispositions". What it needs is:

1. **Normalize `actual_outcome`.** It carries 14 unnormalized strings: `Petitioner`, `all parties`, `Dismissal`, `dismissal`, and 6 empties. Current distribution: protection_granted 619, unknown 204, protection_denied 157.
2. **Join the Supreme Court Database** on citation or docket as the citation-level standard, rather than relying on Oyez alone.
3. **Sever `actual_outcome` from `predicted_outcome`.** They are currently mirrored, which defeats the purpose of having an independent source at all.

`predicted_outcome` distribution: partial 681, protection_denied 340, protection_granted 2.

---

## 3. Which regime produced it

`scotus_annotations` **has a `regime TEXT` column.** This is notable in itself: the provenance pattern that WS2 task 2 proposes adding to the civil database already exists here and was never backported.

Its value is **`scotus-v1-cascade` for all 1,023 rows. Zero rows at `scotus-v2`.**

### Forcing rules are present in the prompt

`annotate_scotus.py`, `SYSTEM_PASS2`, lines 206-213, is titled "Derive chain_outcome STRUCTURALLY from node closures only" and carries RULES 1 to 5, including:

```
2. N7=failed → protection_denied
5. N7=indeterminate → protection_denied (default)
```

Rule 5 deterministically converts uncertainty into the majority label. Note the direction: this is **closure to outcome** forcing, not disposition to closure. Pass 1 sees only a 12,000-character oral-argument transcript, and `decision_text` / `outcome` are never placed in a prompt. So the annotations are not contaminated by the disposition directly. They are contaminated by a rule that manufactures a disposition from a node state.

### The code-level cascade was removed, but after every stored row

`annotate_scotus.py:171-199` documents the removal, dated 2026-08-06: `if n7 in ("failed","partial"): cts.add("RF")` and siblings were deleted. The comment records why this was worse than the prompt rule:

> annotation RULE 1 / RULE 5 reimplemented here in code, which is worse, because a prompt rule can be disregarded by the model whereas this rewrote its output unconditionally.

**All 1,023 stored rows predate that fix.** A stale copy of the pre-fix file remains on disk as `annotate_scotus.py.pre-remediation`.

### The cascade's signature is measurable

`active_contradictions` contains **RF in 1,018 of 1,023 rows (99.5%)**. The corrected civil corpus has RF at 2.8%. That is a 35x inflation, and it is the fingerprint of the removed cascade rather than a property of SCOTUS cases.

---

## 4. The second entanglement, not previously documented

`apply_scotus_calibration.py:24`:

```python
corrected = 'protection_granted' if (cd > 0.10 or pred == 'partial') else pred
```

This overwrites the model's prediction **using the predictor itself (`cd`)** before `prediction_correct` is scored. It also sweeps all 681 `partial` rows into `protection_granted`, which is the majority actual class at 619. Any accuracy figure computed after this script ran is measuring the calibration rule, not the annotation.

Three things to record about it:

- It is **not** captured by the `regime` tag, so a row can be tagged `scotus-v1-cascade` and still carry this additional, invisible transformation.
- It is called only from `scotus_oyez_pipeline.py:95`. It is **not** in `daily_scotus.py`, so it does not run nightly.
- Its effect on the stored `prediction_correct` column is already applied and is not reversible from the column alone.

### Accuracy rests on a quarter of the corpus

`prediction_correct` is **NULL for 782 of 1,023 rows**. Of the remainder: 0 for 172, 1 for 69. So any published SCOTUS accuracy number is computed over roughly 241 rows, and those 241 passed through the calibration rule above.

---

## 5. The nightly job is still producing defective rows

`daily_scotus.py:203` invokes `annotate_scotus.py` on the current schedule, and `daily_scotus.py:401-402` FTP-uploads the result. Since `annotate_scotus.py` still carries RULES 1 to 5, the job adds `scotus-v1-cascade` rows every night and republishes them.

A `--no-upload` flag already exists at `daily_scotus.py:341`, which would stop publication while leaving collection intact.

**Scheduling note.** There is no crontab on this machine (`crontab -l` returns "no crontab for drkoepsell"), `/etc/cron.d/` holds only OS entries, and no relevant systemd timers exist. Yet `logs/scotus_20261003.log` is stamped today. The scheduler is external to WSL, almost certainly Windows Task Scheduler invoking `wsl.exe`. **`setup_cron.sh` is not the live configuration and editing it changes nothing.** Locating the live entry is a prerequisite to stopping or altering the job.

---

## 6. Script inventory

All nine SCOTUS scripts named in the spec exist. None are missing.

| Script | Function | Writes |
|---|---|---|
| `collect_scotus.py` | Oral-argument transcripts and decisions from CourtListener (`SOOL_CL_KEY`) | `scotus_backtest.db` |
| `collect_scotus_oyez.py` | Same via Oyez for sparse pre-2019 terms; also pulls `winning_party` | `scotus_backtest.db` |
| `annotate_scotus.py` | 4-pass MLC annotation (`claude-opus-4-5`, 12k chars). **Carries RULES 1 to 5** | `scotus_backtest.db` |
| `backtest_scotus.py` | Accuracy, AUC, CD calibration curve, term trend | reads only |
| `apply_scotus_calibration.py` | **Rewrites `prediction_correct`** per section 4 | `scotus_backtest.db` |
| `daily_scotus.py` | Nightly: collect, fetch outcomes, annotate, backtest, FTP | `scotus_backtest.db` |
| `scotus_pipeline.py` | Orchestration, CourtListener path | via subprocesses |
| `scotus_oyez_pipeline.py` | Orchestration, Oyez path (terms 2005-2019). Calls the calibration script | via subprocesses |
| `fetch_outcomes.py` | Fills `scotus_cases.outcome` / `petitioner_won` from Oyez | `scotus_backtest.db` |

Also present: `annotate_scotus.py.pre-remediation` (stale, contains the removed cascade), `migrate_outcome_split.py`.

---

## 7. Framework commitments this audit must respect

From the spec, recorded here so the re-annotation design does not drift:

- SCOTUS functions as **Node 8**. The dependent variable is **repair type and repair adequacy**, not affirm or reverse.
- **Node 7 and Node 8 closures are entailed by disposition** and must be excluded from any predictor set. Upstream nodes N1 to N6 only.
- **Contradiction debt lacks discriminative variance at the cert-selection tier**, so cert-stage CD comparisons are not a valid test.

The third commitment is independently supported on the civil side: `annotate.py:297-319` computes `cd_upstream` by excluding `{RF, RCL, CC, SE, RPF}` as definitionally entangled with the outcome, and its docstring instructs that `cd_upstream`, not `contradiction_debt`, be reported in any predictive analysis. The SCOTUS pipeline does not currently honour that distinction.

---

## 8. What D4 now needs to decide

The audit is complete, so D4 is unblocked. It requires:

1. **Repair type categories.** The spec suggests vacatur, remand with instruction, declaratory, structural, none. These need to be exhaustive and mutually exclusive over the 993 cases.
2. **An adequacy scale tied to the IAT components.** The IAT components are not yet annotation fields; WS8 task 3 operationalizes them, so D4 and WS8 task 3 are coupled.
3. **A pre-registration file**, committed before any backtest runs, naming hypotheses, predictors, dependent variable, test, and what counts as failure.

## 9. Recommended sequence

1. Decide whether to stop or unpublish the nightly job (needs the Windows Task Scheduler entry).
2. **D4**: repair coding scheme and adequacy scale.
3. Normalize `actual_outcome`; join the Supreme Court Database; sever it from `predicted_outcome`.
4. Re-annotate under the v2 blind regime with the registry-driven prompt, N1 to N6 as predictors only. Tag every row `scotus-v2`. This is over 50 cases, so it needs a cost estimate and approval per operating rule 6.
5. Pre-register, then backtest.
6. Recompute the Precedent Impact tab with `ct_count`, add placebo dates and a matched-domain control, label it descriptive, and remove it if it fails the placebo test.
7. Retire or clearly quarantine `apply_scotus_calibration.py`. As written it cannot be part of a valid pipeline.
