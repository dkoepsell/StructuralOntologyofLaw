# Deployment log

## 2026-10-03 — SCOTUS halt and civil scope/registry bundle

**Target:** `$SOOL_PROD_HOST:~/CaseLaw` (the host that holds the live crontab).
**Authored on:** `/home/drkoepsell/CaseLaw` (the reference version, not a git repo).

A note that cost time and is worth recording: the reference directory has **no crontab,
no systemd timer, and no visible Windows Task Scheduler action**, yet it carries daily
logs. The logs are copies. The jobs run on the production host. Changes to the reference
directory have **no operational effect until deployed**. `setup_cron.sh` and
`setup_daily_update.sh` are dead configuration on both machines.

### Pre-flight

Every prod file was checksummed against a local pre-edit baseline before being
overwritten, so each was a known-state patch rather than a blind copy. All nine matched.
`export_corpus.py` had no pre-edit backup, so its prod copy was fetched, my three edits
reverted on a copy, and the result compared: identical.

Backups taken on prod before any write:

| Path | Contents |
|---|---|
| `backups/pre_scotus_disable_20261003_160104/` | 5 SCOTUS scripts + `crontab.txt` |
| `backups/pre_civil_bundle_20261003_160743/` | 4 civil scripts, `mlclink_confirmation.csv`, `sool_annotations.db`, `sool_corpus.ttl` (71 MB) |
| `backups/crontab_<ts>_before_scotus_disable.txt` | crontab before the edit |

### 1. SCOTUS halted, two independent layers

Was running `0 0 * * *` `scotus_pipeline.py --terms 2021 2022 2023 --limit 80` (which
calls `apply_scotus_calibration.py` at line 95) and `0 6 * * *` `daily_scotus.py`, with
1,023 rows all at `regime = scotus-v1-cascade`.

- **Code layer:** `scotus_guard.py` + `SCOTUS_PIPELINE_DISABLED` deployed; all five entry
  points verified **BLOCKED** by execution on the host.
- **Schedule layer:** both cron lines commented, a clean two-line diff with `\%` escapes
  preserved. **0 active SCOTUS cron entries.** Every other job unchanged.

Re-enable: `rm SCOTUS_PIPELINE_DISABLED` and uncomment the two lines. Nothing was deleted.

### 2. Civil bundle, deployed as one unit

It had to be atomic: `export_rdf.py` now requires both `vocab/registry.json` and the
`scope_highconf` view, so copying it alone would have broken the nightly export.

Deployed: `build_registry.py`, `migrate_scopes.py`, `export_rdf.py`, `export_corpus.py`,
`annotate_pipeline.py`, `daily_update.py`, `vocab/` (registry, crosswalk, `a0_pending.diff`),
`typology/mlclink_confirmation.csv` (A4 confirmations), and six `docs/`.

**Run `--views-only`, so nothing was deleted.** The views exclude domains 9 to 11 by
definition, so every consumer reading a view is correct without a destructive step. Prod
retains all 6,165 rows.

| View | Prod | Mirror |
|---|---|---|
| `scope_core` | 5,254 | 5,254 |
| `scope_analysis` | 5,171 | 5,171 |
| `scope_blind` | 5,022 | 5,022 |
| `scope_unflagged` | 2,995 | 2,995 |
| `scope_highconf` | 4,681 | 4,681 |

Domains 9 to 11 reachable through any view: **0**.

### 3. A footgun found and closed during deployment

`build_registry.py` had `kernel.json`'s path hardcoded to `/home/drkoepsell/...`. On prod
(user `koeppy`) that resolves to nothing, so the generator reported `kernel present:
False` and **a regeneration there would have silently dropped the K-A1..K-D3 identity
layer** — which is exactly what the `RF` mapping is keyed on, since it resolves by locus.

Fixed two ways: the path is now searched and overridable via `SOOL_KERNEL_JSON`, and the
generator **refuses to overwrite a registry that already carries the kernel layer** when
it cannot find the kernel, unless `--allow-kernel-loss` is passed. Verified on prod:
exit 1, registry unchanged, 5 kernel-layer entries intact.

### Verification on production

| Check | Result |
|---|---|
| Dangling IRIs in a fresh export | 13 classes, **none**; `RoleContradictionTriad` and `SovereigntyException` absent |
| The 111-case silent failure | **111 unresolved before, 0 after**, against prod data |
| Civil entry points | `daily_update.py`, `daily_criminal.py`, `export_corpus.py`, `export_rdf.py` all run |
| SCOTUS | 0 active cron lines; guard fires |
| Kernel-loss guard | exit 1, registry untouched |

### Not done, deliberately

- **Nothing committed to GitHub and nothing published.** Operating rule 4 reserves
  `git push`, releases, Zenodo, and non-nightly FTP for explicit approval. The clone at
  `projects/StructuralOntologyofLaw` is still at `d496aae` (31 March 2026).
- **The physical deletion of the 911 quarantined rows on prod.** The mirror deleted them;
  prod retains them behind the views. Deliberate: the views already make them
  unreachable, so deletion buys nothing and is irreversible.
- **The A0 ontology correction** in `vocab/a0_pending.diff` (RPF prefLabel). Apply by
  hand after review; Claude Code does not edit the ontology.

### Known divergence

The mirror's `sool_annotations.db` holds **5,254** rows, prod holds **6,165**, because the
mirror ran the destructive quarantine and prod did not. **Deploy code to prod; never copy
the mirror's data over it.** Both agree on every scope-view count, which is what consumers
read.
