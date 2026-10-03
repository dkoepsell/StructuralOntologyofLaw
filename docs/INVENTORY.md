# Inventory

**WS0 tasks 1, 2, 3, 5.** Written 3 October 2026. Read-only. No files, databases, or schedules were modified in producing this.

Companion documents: `docs/CREDENTIAL_REPORT.md` (task 4), `docs/SCOTUS_AUDIT.md` (task 5 and WS6 task 1).

---

## 1. Databases

Eight SQLite databases. **None of them contains a single SQL view.** A `grep` for `CREATE VIEW` across all `*.py`, `*.sql`, and `*.sh` returns zero hits outside `venv/`. WS2 task 1 therefore starts from nothing.

| File | Purpose |
|---|---|
| `sool_annotations.db` | Live civil MLC annotations |
| `sool_corpus.db` | Collected opinion metadata |
| `sool_criminal.db` | Criminal corpus |
| `sool_criminal_annotations.db` | Criminal annotations |
| `scotus_backtest.db` | SCOTUS, see `docs/SCOTUS_AUDIT.md` |
| `sool_followup.db` | Downstream citation tracking |
| `p4_control.db` | P4 prompt-variant control |
| `caselaw.db` | Legacy |

### `sool_annotations.db`

Four tables plus `sqlite_sequence`. **Total 6,165 rows**, all at `annotator = claude-pipeline-v2`. No v1 rows remain, so the database carries no v1/v2 contrast.

| Table | Rows | Notes |
|---|---|---|
| `annotations` | 6,165 | 47 columns. The live table |
| `annotations_unmasked` | 4,935 | 41 columns, separate `case_id INTEGER` primary key. A legacy pre-v2 snapshot |
| `annotation_stats` | 0 | Dead |
| `daily_update_log` | 214 | |

**`annotations_unmasked` and `annotation_stats` are tables, not views.** They are materialized snapshots and can go stale. Note that the page text says "masked annotation, n=4,934" while this table holds 4,935 rows, an off-by-one worth tracing.

#### Column notes

Present as the spec states: `was_masked`, `derived_outcome`, `court_disposition`, `court_prevailing_party`, `cd_upstream`, `adversarial_strength`, `equipoise_flagged`, `annotator`, `domain_id`, `confidence`, `needs_review`, `chain_outcome`, `structural_signature`.

Corrections:

- **`cd_score` does not exist.** The column is **`contradiction_debt`** (REAL).
- Node columns are `node1_closure` to `node8_closure` and `node1_entity` to `node8_entity`, plus a single `node3_roles` (JSON). There is **no per-node justification column** here, unlike `scotus_backtest.db`, which has `nodeN_justification`.
- **`court_disposition` is 0 of 6,165 non-null. 100% empty.** Same for `court_prevailing_party`. `derived_outcome` is populated for only 335 of 6,165. So **no independent outcome variable exists for the civil corpus.**
- `case_id` is declared **`TEXT`**. This is the root of the re-annotation bug in section 5.
- **No provenance columns.** A scan of every column in every table for `regime|weight|registry|prompt|hash|version|profile|config` returns no matches. `annotation_regime`, `weight_profile`, `registry_version`, and `prompt_sha256` are genuinely new. Note that `scotus_backtest.db.scotus_annotations` **does** have a `regime TEXT` column, so the pattern exists in a sibling and was never backported.

#### Rows by domain

| ID | Domain | n | | ID | Domain | n |
|---|---|---|---|---|---|---|
| 1 | first_amendment | 659 | | 7 | contract | 651 |
| 2 | employment_discrimination | 677 | | 8 | family_law | 520 |
| 3 | administrative_law | 752 | | 9 | habeas_corpus | 346 |
| 4 | criminal_procedure | 642 | | 10 | patent_ip | 264 |
| 5 | immigration | 680 | | 11 | securities_regulation | 301 |
| 6 | civil_rights_1983 | 673 | | | | |

Domains 1 to 8 = 5,254. Domains 9 to 11 = 911. No NULL or out-of-range domains.

#### Quality by band

| Metric | Domains 1-8 (n=5,254) | Domains 9-11 (n=911) |
|---|---|---|
| `chain_outcome = 'indeterminate'` | 55 (1.0%) | **439 (48.2%)** |
| NULL or empty `chain_outcome` | 28 (0.5%) | 0 |
| `needs_review = 1` | **2,259 (43.0%)** | **900 (98.8%)** |
| confidence high | 3,833 (73.0%) | 9 (1.0%) |
| confidence medium | 880 (16.7%) | 5 (0.5%) |
| confidence low | 541 (10.3%) | **897 (98.5%)** |
| high or medium | 4,713 (89.7%) | **14 (1.5%)** |
| `was_masked = 1` | 5,102 | **0** |

Outcome mix, domains 1 to 8: protection_denied 2,851, partial 807, remanded 663, protection_granted 579, dismissed 189, moot 82, indeterminate 55, empty 28.

**Domains 9 to 11 are unusable.** Beyond the table above, their corpus files are 0.4 to 0.95 MB per domain against 41 to 69 MB for domains 1 to 8, roughly a 60x text deficit, consistent with annotation from stub text rather than opinions. All 911 are unmasked. Decision D6 quarantines and drops them.

#### Contradiction debt

| Measure | Max (d1-8) | Mean (d1-8) | Excludes |
|---|---|---|---|
| `contradiction_debt` | 0.78 | 0.1372 | nothing |
| `cd_upstream` | 0.54 | 0.0999 | `{RF, RCL, CC, SE, RPF}` |

`annotate.py:297-319` computes `cd_upstream` by excluding the five types it describes as "definitionally entangled with the outcome", and its docstring instructs that `cd_upstream`, not `contradiction_debt`, be reported in any predictive analysis. Independently, `sool_bfo_mlc_core.ttl:140` carries the comment "Empirical max ~0.55", which matches `cd_upstream` max 0.54.

This resolves an item listed in the spec's Appendix A as a stale v1 value. **It is not stale.** The page's 0.55 and 0.78 are two different columns, and 0.54 is the more defensible of the two.

#### Verified scope counts

| Rule | n |
|---|---|
| all rows | 6,165 |
| `domain_id BETWEEN 1 AND 8` | 5,254 |
| `confidence IN ('high','medium')`, any domain | 4,727 |
| `needs_review = 0`, any domain | 3,006 |
| domains 1-8 with determinate `chain_outcome` | **5,171** |
| domains 1-8 and `was_masked = 1` | **5,102** |

**Correction (3 October 2026, later the same day):** I first wrote that the last two
"correct the page text's 5,186 and 5,103". That was wrong. Measured against the **frozen
6 August database**, `scope_core` = **5,186** and `scope_analysis` = **5,103**, exactly as
the page states. The 5,254 and 5,171 above are the **live** database, which grows nightly.
Both pairs are right for their own snapshot.

The defect is therefore not a wrong figure. It is a page regenerated nightly while its
prose describes a fixed snapshot, which is the staleness the spec names in section 1.3.
The fix is the release/live split under D5, not a correction to these numbers. Verified by
`stage_release.py`, which computes the release figures from the frozen database rather
than from any literal.

---

## 2. The five definitions of "in corpus"

The spec counts five inconsistent scopes. Confirmed, and the mechanism is worse than a count mismatch: three of the five are enforced in Python rather than SQL, so they are invisible to a reader auditing the queries.

| Definition | Enforced at |
|---|---|
| `confidence IN ('high','medium')`, **no domain or review filter** | `export_rdf.py:172` (civil), `:259` (criminal) |
| `NOT needs_review` | `daily_update.py:333`, the "Corpus total", persisted to `daily_update_log.corpus_total` at `:954-960`, reported at `:968` |
| `annotator = v2` plus 8 domains plus valid outcome plus `n >= 100` | `gen_provisional.py:105` (SQL), then `:115-118` `VALID_OUTCOMES`, `:125` `MIN_DOM_N = 100`, `:130-135` `IN_SCOPE`, `:574-575` `needs_review` drop |
| 8 domains plus `chain_outcome in OK` | `build_finder_index.py:103-105` (SQL), `:110-112` (Python) |
| **nothing** | `export_corpus.py:136`, `:158`, `:172` have no `WHERE` at all; the domain filter is Python-side at `:233-234` |

Two consequences worth flagging:

- **`export_rdf.py` has no domain filter.** Domains 9 to 11 and review-flagged rows ship into `sool_corpus.ttl` as long as confidence is not low. The nightly export therefore publishes the confabulated domains.
- **`build_finder_index.py` selects `confidence` and `needs_review` but does not filter on them**, emitting them as `conf` and `rev` fields at `:134-135` instead.

`was_masked` never appears in any `WHERE` clause anywhere. It is used only in Python, at `gen_provisional.py:487-488`.

Other `WHERE` clauses found, all benign: `export_corpus.py:270`, `:273` (corpus-count and coverage metadata), `daily_criminal.py:103`, `:162` (date only, no scope filters anywhere in that file), `gen_provisional.py:141`, `:164`.

---

## 3. Hand-typed typology, and what already reads the registry

### Already migrated

`gen_provisional.py:33-56` `_load_ct_labels()` and `:64-89` `_load_weight_profile()` read `typology/registry_observed.json`, set `CD_PROFILE = "core-v1"` and `CD_CEILING`, and **exit 2 rather than guess**. The comment block at `:24-32` documents a prior drift incident in which `AI` was mislabelled "Authority Incompleteness" and `CF` "Constitutive Failure", corrupting a published D3 result. **This is the pattern to replicate everywhere.**

`structural_precedent_finder.html` is also clean. It fetches `sool_finder_index.json` at `:370` with a file-picker fallback at `:231`, so its labels come from `build_finder_index.py:71` and it holds no copy of its own.

### Source of truth

`sool_bfo_mlc_core.ttl:142-217` defines 13 `sool:ContradictionType` individuals, each with `rdfs:label`, `skos:altLabel` (the code), and `sool:cdWeight`. The weights sum to exactly **1.52**:

```
AI=0.12  CF=0.15  CC=0.14  FM=0.11  JC=0.10  NI=0.07  PC=0.09
RCL=0.18 RF=0.11  RPF=0.13 RC3=0.14 SE=0.10  TC=0.08
```

### Still hand-typed

| Location | What | Risk |
|---|---|---|
| `annotate.py:43-57` | `CONTRADICTION_TYPES` as `{code: (label, chain_link, weight)}`. Re-exported via `annotate_pipeline.py:46`, consumed at `:1219`; also `migrate_outcome_split.py:27`, `:57` | Matches the registry **except `RPF`**, labelled "Repair Failure" against the registry's "Repair Procedure Failure". This is amendment A1, live in code |
| `export_rdf.py:66-80` | `CT_CLASSES`, code to class name | **Two class names exist in neither TTL.** See below |
| `export_rdf.py:54-63`, `:83-90`, `:93-105`, `:108-114` | `NODE_NAMES`, `CRIM_CATEGORY_CLASSES`, `CIVIL_DOMAIN_CLASSES`, `DEFENSE_CLASSES` | `:111` has a typo, `ProceduraliBarDefense` |
| `export_corpus.py:86-87`, `annotate_criminal.py:40-44` (used `:252`), `annotate_equipoise.py:277` (used `:341`), `backtest_scotus.py:25`, `daily_case.py:288-294` | Five more independent `CT_WEIGHTS` copies | |
| `build_finder_index.py:71-79` | `LABELS`, all 13, plus `:62-63` `OK`, `:64` `CLOSURE`, `:69` `FORCED` | Carries deprecated `RPF: "Repair Failure"` |
| `blind_control.py:71`, `sool_v2_audit.py:30`, `domain_analysis.py:118`, `gen_provisional.py:23` | Four bare 13-code lists. `gen_provisional.py:23` `CT` is order-bearing | |
| `sool_poster.html:673-740` | `CT_DATA`, **and** a parallel static HTML table at `:325-345` with weights typed into `<span class="cw">0.15</span>` markup | Two copies in one file |

### `SOoL_QueryTool.html` holds six independent copies

| Line | Variable | Contents |
|---|---|---|
| `:3050-3063` | `CT_META` | `{name, links, cdw}` per code |
| `:3395+` | `CT_WHY` | `{rule, crit}` per code |
| `:3929` | `CT_TIPS` | label, chain link, and `"CD: 0.15"` baked into prose strings. Consumed `:3439`, `:3573` |
| `:5656-5659` | `AZ_CT_WEIGHTS` | Consumed `:5843`, `:5950` |
| `:5944-5946` | `CT_COLOR` | code to hex |
| `:6319-6320`, `:6321+` | `CT_W`, `CT_DESC` | A second weight table and description table in the same file |

Plus prose assertions of the ceiling and mean at `:1760`, `:2684`, `:2769`.

### Dangling IRIs in every published TTL

`export_rdf.py` maps two codes to class names that **exist in neither `sool_bfo_mlc_core.ttl` nor `sool_criminal_norms.ttl`** (verified zero occurrences):

| Line | Emitted | Ontology has |
|---|---|---|
| `:75` | `sool:RoleContradictionTriad` | `sool:RoleContradiction` |
| `:78` | `sool:SovereigntyException` | `sool:SelfUnderminingEffect` |

Emitted at `:234` and `:326` as `sool:hasContradictionType sool:...`. So **`sool_corpus.ttl` and `sool_criminal.ttl` carry dangling IRIs on every export, including the nightly one.** `SE` is the worse case: "Sovereignty Exception" and "Self-Undermining Effect" are different concepts, not spelling variants. This blocks WS5, because SHACL conformance over a graph with dangling type IRIs is meaningless.

### `SimLex.html` is a different typology

149,174 bytes. Codes `AE, AI, CC, CF, CS, EN, JC, RC, RF, RGR, RPF, RV, TA`, weights summing to **1.63**, only six overlapping `core-v1`. `CS` carries `cdW: 0.25`, a weight present in no ontology. Nodes are **0-indexed** (`nodes:[0,1]` for CF; tooltips at `:1028-1036` say "Nodes 0 & 1"), contradicting the 1-8 convention used everywhere else.

Zero occurrences of `core-v1`, `simlex-v1`, `profile_id`, or `weightProfile`, so all 13 weights are presented as bare "CD weight: X". It carries three unprofiled CD quantities (`cd_stock` 4 occurrences, `cd_case` 2, and bare CD), and its `cd_case` tooltip cites **ceiling 1.52**, which is the `core-v1` ceiling, while its own weights sum to 1.63. The tooltip does warn that "the bridge between them has not been calibrated" and "Do NOT compare it to the corpus figure cd_case", so the problem is known and unresolved in the artifact.

`typology/typology_aliases.json` has a dedicated `v2_simlex_unregistered` section with 6 entries acknowledging these codes.

---

## 4. Existing typology assets

A prior **SOoL Typology Freeze v1** effort ran to 2026-08-06 and stalled at amendment A4. WS1 extends this work rather than starting fresh.

| Asset | Contents |
|---|---|
| `typology/registry_observed.json` | 13 types keyed by IRI with `code, label, alt_labels, cd_weight, chain_link_raw, code_source, definition, iri, nodes_referenced`, plus `_meta.ontologyHash` and `_meta.sourceOntology` |
| `typology/parse_ontology.py` | The generator |
| `typology/typology_aliases.json` | The existing crosswalk: `_meta`(5), `unambiguous`(30), `deprecated_labels`(2), `AMBIGUOUS`(7), `v2_simlex_unregistered`(6), `reserved_codes`(3). `NI` is marked `UNRESOLVED_V5_MAPPING` |
| `typology/sool_typology_lint.py` | Linter, checks L01 to L12, `--error-mode`, `--strict`, `--json`. Error-level set is `{L01, L03, L04, L05, L06, L11}` |
| `typology/test_lint.py` | 12 of 12 passing. **The only test file in the project** |
| `typology/audit_page_claims.py` | Precursor to the WS4 task 1 numeric validator |
| `typology/prepare_mlclink.py`, `mlclink_confirmation.csv` | The A4 sign-off table. 12 of 13 at AGREE, TC canon-only at `2<->4`, and the `mlcLink_CONFIRMED` column is **empty on all 13 rows** |
| `typology/CENSUS.md`, `AMENDMENTS.md`, `OFFENSE_MAPPING_FINDINGS.md` | The census and owner amendments A0 to A4 |
| `backups/pre_vocab_20260806_174421/` | A vocab migration was staged for `SOoL_QueryTool.html`, `SimLex.html`, `gen_provisional.py`, `structural_precedent_finder.html` |

### Current lint census

143 files scanned, **2,740 findings, 2,283 at error level**. This is the WS1 burn-down baseline.

```
L01    33 ERROR  unknown code or label
L02    93 warn   deprecated label        <- "Repair Failure" 83x across 24 files
L03    48 ERROR  code/label mismatch
L04    56 ERROR  link grammar failure
L06     9 ERROR  0-indexed node          <- SimLex.html
L08   364 warn   weight hardcoded        <- 13 files
L11  2137 ERROR  ambiguous alias
authored: 1076   generated: 1664
spec authority: ABSENT (SOoLRev2.owl not found)
```

Two caveats before trusting it:

- `SKIP_DIRS` at `:31-32` excludes `typology` itself, plus `backups`, `logs`, and `corpus`.
- **L08 under-reports.** It matches `'CF': 0.15` dictionary form but misses `annotate.py`'s tuple form `("Conferral Failure","1→3",0.15)` and all six JS weight tables in `SOoL_QueryTool.html`, none of which appear in its file list. Fix the linter's coverage first.

### The AI/CF ambiguity is resolved

`typology_aliases.json` flags `AI` as AMBIGUOUS between Authority **Inflation** and Authority **Incompleteness**. This matters because WS4 task 5 instructs the rebuilt page to lead with the Authority Inflation elevation in administrative law.

Both the ontology and the live prompt (`annotate.py:44-45`, `annotate_pipeline.py:490-491`) say **Authority Inflation**. The ambiguity originated in a hand-typed `CTNAME` dictionary in the site text and was corrected 2026-08-06. **The D3 administrative law result (14.7%, 5.7x, p=2e-45) measures what it claims to measure.**

---

## 5. The nightly re-annotation failure, root-caused

The spec reports that the "Re-annotating mixed-perspective" step fails on all 111 cases every night while the summary reports 0 errors. Both halves are confirmed, and there are **three** distinct defects.

### The failure: a `str` versus `int` key mismatch

`daily_update.py:805-811` dispatches `annotate_pipeline.py --reannotate-mixed`, reaching `reannotate_mixed_perspective()` at `annotate_pipeline.py:1065-1186`.

- `:1074-1080` selects `case_id` from `annotations`, where the column is declared **`TEXT`**, so sqlite3 returns `str`: `'195132'`.
- `:1097` builds the corpus lookup as `cid = case.get("id") or case.get("case_id")` from the corpus JSONL, where `id` is a JSON number, so Python `int`: `195132`.
- `:1111` tests `if case_id not in corpus:`. Since `hash('195132') != hash(195132)`, this is always `True`.

Verified directly: 111 mixed rows, 6,166 corpus ids, 111 reported missing, and **0 missing after `int()` coercion**. The corpus files are intact (11 files, 6,166 cases) and the working directory is correct. All 111 take the `continue` at `:1114`, so `call_claude` is never reached and the API key is irrelevant.

Confirmed in `logs/daily_20261003.log:224`: `Re-annotation complete: 0 re-annotated, 111 failed.` Identical on every run, including `daily_20260912`, `daily_20260917`, `reboot_civil_20260818`, and `reboot_civil_20260907`.

### Why the summary reports 0 errors: two independent swallows

1. **The callee never signals failure.** `reannotate_mixed_perspective()` ends at `:1185-1186` by logging and returning normally, so the exit code is 0 even at 111 of 111 failed. The normal annotation path **does** have a health gate at `:1430-1442` that calls `sys.exit(1)` when `attempted > 0 and saved == 0`, with a comment reading "the pipeline exits 0 on a dead model ID and the caller reports '0 errors'". That gate was never extended to the `--reannotate-mixed` branch, which is the identical condition.
2. **The caller never checks.** `daily_update.py:806` discards the `CompletedProcess`: no `result =`, no `check=True`, no returncode test, no `errors += 1`. Sibling subprocess calls at `:783` and `:825` **do** assign and increment. Because `capture_output=False`, the 111 warnings reach the log but never the counter.

So `errors` is still 0 at `daily_update.py:970` and 0 is written to `daily_update_log.errors`, recording the run as clean.

**Fix all three.** The coercion is one line, but the type bug would have been caught on its first run if either error path worked.

### A related prompt/schema disagreement

`annotate_pipeline.py:568`, the prompt's `CHAIN OUTCOMES - use exactly one` list, **omits `indeterminate`**, yet 55 rows in domains 1 to 8 and 439 in domains 9 to 11 carry that value.

---

## 6. Validation and CI

`validate_provisional_page.py` exists (1,552 bytes, executable, 2026-08-05) but it is **not** a data validator. It is an HTML structural check on `SOoL_QueryTool.html`:

1. Asserts the start marker appears exactly once and precedes the end marker.
2. Prints a tag-balance audit and flags any tag where open and close counts differ.
3. `:25` asserts the fragment sits inside `id="tab-hypotheses"`.
4. `:28-29` asserts no `class="tab-panel"` opens between the markers.
5. Exits 0 or 1.

It validates nothing about codes, labels, weights, or corpus scope. **WS4 task 1 is a new capability**, not an extension, though `typology/audit_page_claims.py` is a usable starting point.

**No pytest configuration, no `pyproject.toml`, `setup.cfg`, `tox.ini`, or `conftest.py`. No `.github/` directory.** WS9 task 6 is greenfield, but `sool_typology_lint.py` and `test_lint.py` supply two of its four gates already.

### Page scale, for sizing WS4

`SOoL_QueryTool.html` is 7,318 lines and 543,353 bytes, containing **299 distinct decimal literals**, 84 distinct percentage literals, and 6 `n=` literals. Each needs a `stats.json` provenance or a registry lookup. `gen_provisional.py` is 1,422 lines.

Appendix A defect strings verified present: `14.0` (10 occurrences), `13:1`, `0.252` (3), `0.017` (2), `n=4,934` (2), `67%` (2), "Predicts Its Outcomes", "outcome prediction", "High CD predicts", `42.4` (3), `sool_bfo_mlc_core.ttl` (4). All nine hypothesis ids `H1` to `H9` are present. `AINF` appears **0 times** and `AI` 48 times, so the rename has not been applied. All 13 codes appear somewhere in the page, so the missing TC, FM, and SE dropdown entries are per-dropdown gaps and need rendered-browser verification.

---

## 7. Schedule and FTP targets

**There is no crontab on this machine.** `crontab -l` returns "no crontab for drkoepsell", confirmed outside the sandbox. `/etc/cron.d/` contains only `e2scrub_all`, `sysstat`, and `.placeholder`. `systemctl list-timers` and `systemctl --user list-timers` show only OS and `launchpadlib-cache-clean` entries. No `~/.config/systemd/user/`.

Yet `logs/` shows runs today: `daily_20261003.log` at 03:01, `daily_case_20261003.log`, `scotus_20261003.log`, `scotus_pipeline_20261003.log`, with an unbroken daily series back through September. The times match `setup_cron.sh` exactly.

**Conclusion: the scheduler is external to WSL, almost certainly Windows Task Scheduler invoking `wsl.exe`.** Two consequences:

- **`setup_cron.sh` is not the live configuration. Editing it changes nothing.**
- Any change to nightly behaviour requires the Windows Task Scheduler entry. **Locating it is an open item.**

### Intended schedule per `setup_cron.sh`

All entries wrap in `source ~/.sool_env && source ~/.bashrc && cd $HOME/CaseLaw && source venv/bin/activate`.

| Line | Schedule | Target | Log |
|---|---|---|---|
| `:24` | `0 3 * * *` | `daily_update.py` (civil) | `logs/daily_<date>` |
| `:27` | `0 4 * * *` | `daily_criminal.py` | `logs/criminal_daily_<date>` |
| `:30` | `0 5 * * *` | `daily_case.py` | `logs/daily_case_<date>` |
| `:32-33` | `0 6 * * *` | `daily_scotus.py` | `logs/scotus_daily_<date>` |
| `:36` | `@reboot sleep 120` | `daily_update.py --annotate-only` | `logs/reboot_civil_<date>` |
| `:39` | `@reboot sleep 180` | `daily_criminal.py --annotate-only` | `logs/reboot_criminal_<date>` |

`setup_daily_update.sh` is a **second, overlapping installer**:

| Line | Schedule | Target |
|---|---|---|
| `:73` | `0 3 * * *` | `daily_update.py`, **duplicating** `setup_cron.sh:24` |
| `:86` | `0 2 1 * *` | `./update_corpus.sh`, monthly full rebuild |

All five target scripts exist.

### FTP targets

Host `<ftp-host>`, account `<ftp-user>`, credentials from `TURBIFY_FTP_USER` / `_PASS` / `_HOST`. Upload code at `daily_update.py:304-306` and `:833-834`, `daily_case.py:40-42`, `daily_scotus.py:261-263` and `:401-402`, `rebuild_status.py:192-194`, `scotus_oyez_pipeline.py:104-106`, `update_corpus.sh:175`, `patch_querytool.py:11` and `:203`. `daily_scotus.py:341` already provides a `--no-upload` flag.

---

## 8. Artifacts the spec declares and where they actually are

| Item | Status | Path |
|---|---|---|
| `SOoLRev2.owl` | **Name resolves, content is wrong** | `/home/drkoepsell/projects/SOoL/SOoLRev2.owl`, 598,946 bytes, byte-identical copy in `/mnt/c/Users/David/Downloads/`. Ontology IRI is `http://davidkoepsell.com/bfo-agent/working`. **Zero** occurrences of `K-A1` to `K-D3`, zero of `ontologyoflaw.org` or `seal.tamu`. Only 29 distinct `rdf:about` IRIs. It is a BFO-agent scratch file |
| Kernel primitive mapping | **Found, in another project** | `/home/drkoepsell/projects/recognition/recognition-kernel/data/kernel.json`, 24,805 bytes, `kernel_version` 0.2.0. Four strata, 12 primitives `K-A1` to `K-D3`, `named_types` of 12, citing "Structural Ontology of Law (Koepsell forthcoming), §7.2 Table 7". Supporting: `recognition-kernel.ttl` (prefix `rk: https://sool.davidkoepsell.com/ontology/rk#`), `spec/PRIMITIVES.md`, `spec/owl/recognition-kernel.owl` |
| `CORPUS_DESIGN.md` | **Found**, has the 300-case design | `/home/drkoepsell/CaseLaw/CORPUS_DESIGN.md`, 6,530 bytes. Line 142 "Gold standard: 300 cases annotated by 2+ trained annotators", line 143 "20% human spot-check", targets kappa >= 0.7 node closure and >= 0.6 contradiction type. Sampling at lines 22-33: 13 types x 8 domains = 104 cells, min cell 5, target 30+, 500 x 8 = 4,000 cases |
| Book | **Manuscript, not publisher proofs** | `/home/drkoepsell/remarkable_export/LegalOntology/A Structural Ontology of the Law - Palgrave.pdf.orig.pdf`, 403 pages, not encrypted, text-extractable. Producer "Microsoft Word for Microsoft 365", created 28 December 2025. Newer full manuscript: `/mnt/c/Users/David/OneDrive/A Structural Ontology of the Law - Palgrave.docx`, 14 January 2026. Chapter 4 only: `/mnt/c/Users/David/Downloads/Ch4-Obligation-...pdf`, 18 pages. **No typeset Palgrave proofs and no `.tex` source anywhere** |
| `sool_v2_20260806/` | **Confirmed**, all five probes positive | See section 9 |
| GitHub clone | **Found, clean** | `/home/drkoepsell/projects/StructuralOntologyofLaw/`, remote `git@github.com:dkoepsell/StructuralOntologyofLaw.git`, branch `main`, 0 modified files, last commit `d496aae` "Add files via upload", 31 March 2026. Holds `sool_annotations.db` (20.9 MB, v1), `sool_corpus_data.json` (5.9 MB), `SOL.owl`, `SOoLComplete.owl`, `SOoLKernelOntology.owl`, `SimLex.html` (123,081 bytes vs live 149,174), `sool_criminal_norms_v2.ttl`, `sool-corpus-v2.zip`, `IRACplus/`, `SOoL-structural-toolkit/`. Its `sool_bfo_mlc_core.ttl` is **53,777 bytes against the live 19,647** |
| LOF / ODP material | **Found, was Windows-only and unversioned. Now copied in** | Source `/mnt/c/Users/David/Downloads/lof-odp-review-packet/`, all four patterns at 0.1.0, CC BY 4.0, credited to Mandrick and Barry Smith. `mlc-closure.shacl.ttl` (2,788 bytes, 8 shape declarations, IRIs under `https://w3id.org/lof/odp-004/shapes`) was modified **2026-10-02**. Copied to `lof/` in this repo on 3 October 2026: 99 files, 2.0 MB |

### The two kernel defects

Both are **now resolved**. See `docs/RF_DECISION.md` for the full record.

- **The `RF` collision is resolved.** `kernel.json` has `K-D3 RF = "Repair Failure"` at `locus = remedy`; the corpus has `RF` = **Recognition** Failure (nodes 6/7) and `RPF` = Repair Failure (node N8). Three independent sources agree that the kernel's `RF` maps to corpus **`RPF`**, not corpus `RF`: the kernel locus (`remedy`), the corpus node (N8, confirmed under A4), and ODP-004's node 8 term `lof:ODP004_0001002` "remedial position". Per **LOF-P-005** a code is never an identifier, so codes are now `skos:notation` scoped by vocabulary and the alignment is keyed on locus and node. `build_registry.py` enforces this by construction.
- **A residual label collision is escalated, not patched.** Corpus `RF` and kernel `CT-6` both claim the label "Recognition Failure", which violates **LOF-P-003**. The generator detects and reports it. The correction belongs in the kernel (another project) under amendment A0, and nothing downstream depends on the outcome because the alignment is keyed on locus.
- **Correction to an earlier note: the "only 8 of 12 primitives" finding was overstated.** The kernel indexes types by primitive **and** locus and partitions them by `system_kind`, so reusing a primitive across loci is by design: `K-C3` legitimately carries both `CF` (locus `assessor`, `legal_order`) and `CT-6` (locus `criteria`, `classification`). The real residue is narrower: `K-A2`, `K-C2`, `K-D1`, and `K-D2` are mapped to no named type in either kind. That is a coverage gap to close, not a wrong mapping. Only the five `legal_order` types align to this corpus at all; the seven `classification` types apply the same primitives to a different kind of system.

### Namespaces: eleven, not five

The spec's section 1.5 counts five. In `~/CaseLaw` alone there are eight, across two authorities, and **no `.owl` files at all, only `.ttl`**:

```
http://ontologyoflaw.org/corpus/
http://ontologyoflaw.org/corpus/civil/
http://ontologyoflaw.org/corpus/criminal/
http://ontologyoflaw.org/criminal#
http://ontologyoflaw.org/structural#
http://seal.tamu.edu/legal-kernel/
http://seal.tamu.edu/legal-kernel/cases/
http://seal.tamu.edu/legal-kernel/mlc/
```

The `seal.tamu.edu` family comes from `turtle_export/` (9 files, 24 March 2026): `sool_corpus_all.ttl` plus `domain_1` through `domain_8`.

Widening to the whole project adds three more authorities: `davidkoepsell.com/bfo-agent/working` and `/seed#` (SOoLRev2.owl), `sool.davidkoepsell.com/ontology/rk#` (recognition kernel), and `w3id.org/lof/` (the ODP patterns). **Eleven namespaces across five authorities.** Decision D2 makes `https://w3id.org/sool#` canonical, so ten deprecation aliases are needed.

Live ontology files in `~/CaseLaw`:

| Bytes | File | Namespaces |
|---|---|---|
| 19,647 | `sool_bfo_mlc_core.ttl` | `ontologyoflaw.org/structural#` |
| 4,148,758 | `sool_corpus.ttl` | `corpus/`, `corpus/civil/`, `structural#` |
| 1,348,816 | `sool_criminal.ttl` | `criminal#`, `corpus/criminal/` |
| 26,791 | `sool_criminal_norms.ttl` | `criminal#` |

---

## 9. The frozen release, and why its checksums do not hold

`sool_v2_20260806/` top level: `FILELIST.txt` (2,038), `README.md` (6,153), `SHA256SUMS.txt` (6,988), `blind_control.db` (12,288), `blind_control.py` (18,850), `sool_v2_audit.py` (9,337), and `databases/ docs/ exports/ ontology/ scripts/ web/`.

All five of the spec's probes are positive:

| Probe | Result |
|---|---|
| `CLAUDE.md` | Present, at `docs/CLAUDE.md` |
| `RESUME_HERE_*.md` | Present, `docs/RESUME_HERE_20260803.md` |
| `*Zone.Identifier` | Present, 2 files: `blind_control.py:Zone.Identifier`, `sool_v2_audit.py:Zone.Identifier`, 25 bytes each. These will corrupt any checksum or filelist walk |
| `VERSION.json` | Present, at `exports/VERSION.json` |
| `SHA256SUMS.txt` | Present, at top level |

**The freeze is internally inconsistent in time.** `SHA256SUMS.txt`, `README.md`, and `FILELIST.txt` are stamped 14:33, but `blind_control.py` (15:01), `sool_v2_audit.py` (15:01), `blind_control.db` (15:03), and `databases/` (15:38) are all later. **The manifest cannot cover those files.**

WS3 task 1 instructs "verify `SHA256SUMS.txt`". That verification will fail. The honest options are to re-manifest, which makes it a new freeze and so should be labelled v2.0.1, or to publish with an explicitly stated manifest scope.

Its `ontology/` holds `sool_bfo_mlc_core.ttl` (19,647, identical in size to live), `sool_corpus.ttl` (4,087,285, **differs** from live 4,148,758), `sool_criminal.ttl` (1,348,816), `sool_criminal_norms.ttl` (26,791).

### Post-freeze script divergence

**WS0 task 3.** Of the 47 scripts in `sool_v2_20260806/scripts/`, **45 are byte-identical to live. Only two differ**, and in both cases **the live version is ahead of the freeze in exactly the direction the spec asks for.**

#### `gen_provisional.py`, 26 changed lines (frozen 10:14, live 17:53, same day)

The live version expands the CD governance panel to **name the three quantities explicitly**: `cd_case` (weighted per-case flow, ceiling `CD_CEILING` under `CD_PROFILE`), `ct_count` (unweighted count of active types, 0 to 13), and `cd_stock` (an institution's accumulated debt over time, clamped to [0,1], used by SimLex). It also relabels the Quick Reference band table columns from "share of corpus if CD = count" to "share as `ct_count`" and "share as `cd_case` (Σw, core-v1)".

This is **WS1 task 5 and decision D7 already partly implemented**. The panel states the finding directly: under `core-v1` every one of the N cases is band "0", and bands "3-4", "5-6", "7+" are "not merely empty but *unreachable*", coherent only under a `ct_count` reading.

#### `release_v2.sh`, 42 changed lines (frozen 2026-08-05 22:05, live 2026-08-06 15:43)

The live version adds precedent-finder release gating that the freeze has no knowledge of:

- A new `step "3b/7 build precedent finder index"` running `build_finder_index.py`, then aborting if `idx["corpus_version"] != ver["corpus_version"]` or if the index has no cases. The inline comment: "Publishing an index built against a different annotation run would put two different case counts on one site."
- A `node finder_harness.js` gate in step 5.
- `structural_precedent_finder.html` and `sool_finder_index.json` added to the step 6 FTP upload list.
- Post-upload live verification: that the query tool links to the finder, that the live finder index version matches `VERSION.json`, and that the finder links back to the query tool.

#### Consequence for WS3 task 1

The spec says to publish v2.0.0 from a scrubbed copy of the frozen directory. Doing that literally would **publish the older, weaker page generator and the older release script**, discarding the CD-measure disambiguation and the finder gates. Combined with the manifest-time problem above, the recommendation is to **cut v2.0.1 from the live scripts plus the frozen databases and exports**, re-manifest, and state in the README what differs from the 6 August freeze.

#### Stale copy on disk

`annotate_scotus.py.pre-remediation` is present live, still containing the cascade removed on 2026-08-06. Note that `annotate_scotus.py` itself is byte-identical between live and frozen, so the freeze captured the post-removal version. The `.pre-remediation` file should not reach any release.

---

## 10. Open items from this inventory

1. **Locate the live Windows Task Scheduler entries.** Without them, no nightly behaviour can be changed, and `setup_cron.sh` is misleading.
2. **The nightly SCOTUS job needs a decision.** It is producing and publishing `scotus-v1-cascade` rows. See `docs/SCOTUS_AUDIT.md`.
3. **D1 needs resolving** given that `SOoLRev2.owl` is a scratch file and the kernel mapping has two defects.
4. **The `RF` collision** between the kernel and the corpus, to be resolved jointly with amendment A1.
5. **A4 remains unconfirmed**, blocking registry generation.
6. **`export_rdf.py`'s two dangling IRIs** should be fixed before any TTL is published or any SHACL run is attempted.
