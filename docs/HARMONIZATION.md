# Harmonizing Contradiction Debt across the corpus, the ontology, and SimLex

Status: **partly applied, 3 October 2026.** This line previously read "proposal.
Nothing in this document has been applied", which is no longer true.

| Proposal | State |
|---|---|
| Three named measures (`cd_case`, `ct_count`, `cd_stock`) | **Applied.** Declared in `vocab/registry.json` `_meta.measures`, plus a fourth, `cd_upstream`, for anything outcome-facing |
| Weight profiles named by id, never a bare "CD" | **Applied.** `core-v1` (ceiling 1.52), `simlex-v1.3` (1.63) and `count` are first-class in the registry; amendment A3 declares `core-v1` in place rather than extracting it |
| `ct_count` as the default published measure | **Applied.** Author decision D7 |
| Retire the code `AI` in favour of `AINF` | **Applied.** Amendment A2, migrated as data by `migrate_ai_to_ainf.py` with a reversible log |
| RPF preferred label corrected to "Repair Failure" | **Applied.** Amendment A1, corrected in the ontology under A0, not routed around downstream |
| Quick Reference bands are a `ct_count` scale, not Σw | **Documented, card not yet regenerated.** The governance panel in `gen_provisional.py` states it; the printed card still needs rebuilding from the registry |
| `SimLex.html` adopts registry codes and declares its profile id | **Not applied.** SimLex still ships its own 13-type list summing to 1.63, with six shared codes, and presents three quantities as a bare "CD". It is a separate vocabulary and changing it is a separate decision |
| 0-indexed node references in SimLex | **Not applied.** Still `nodes:[0,1]` against the 1-8 convention everywhere else |

The ceiling figure of ~2.27 used in places below is **wrong**; `core-v1` sums to
**1.52**. Compute it from the profile rather than restating it.

Drafted 2026-08-06 against corpus v2.0.0 (5,186 v2-annotated cases; 5,103 with a
determinate outcome), weight profile `core-v1`, and the `CT` table in `SimLex.html`.

---

## 1. The problem

Three artifacts use the term *contradiction debt* for three different quantities,
and two of them use different 13-type taxonomies. As a result the empirical corpus
cannot be used to calibrate — or even to sanity-check — the incoherence thresholds
that SimLex already asserts.

---

## 2. Typology diff: `core-v1` vs SimLex `CT`

`sool_bfo_mlc_core.ttl` defines the profile under which all 5,103 annotations were
produced. `SimLex.html` defines an independent 13-entry table. They are not the
same thirteen.

| core-v1 | w | corpus freq | SimLex counterpart | w | status |
|---|---|---|---|---|---|
| CF  Conferral Failure        | .15 |  0.48% | `conferralFailure`        | .15 | aligned |
| AI  Authority Inflation      | .12 |  4.22% | `authorityInflation`      | .12 | aligned |
| JC  Jurisdictional Contra.   | .10 | 23.60% | `jurisdictionalContra`    | .10 | aligned |
| RF  Recognition Failure      | .11 |  2.95% | `recognitionFailure`      | .11 | aligned |
| CC  Correlativity Contra.    | .14 | 18.72% | `correlativContradiction` | .14 | aligned |
| RPF Repair Failure           | .13 |  5.53% | `repairFailure`           | .13 | aligned |
| PC  Procedural Contra.       | .09 |  8.60% | `actEffectMismatch`       | .09 | different concept, same weight |
| RCL Recognition Collapse     | .18 |  0.06% | `rechtGesetzRupture`      | .18 | different concept, same weight |
| RC3 Role Contradiction       | .14 |  9.20% | `roleVacancy`             | .08 | different concept and weight |
| TC  Temporal Contra.         | .08 |  4.36% | `retroactiveContra`       | .11 | related, weight differs |
| FM  Fact Manipulation        | .11 |  6.86% | `triggeringAmbiguity`     | .07 | different concept and weight |
| SE  Self-Undermining Effect  | .10 |  0.21% | `effectNullification`     | .10 | related |
| **NI  Norm Indeterminacy**   | .07 | **54.99%** | *(none)*              | —   | **absent from SimLex** |
| *(none)*                     | —   | —      | **`chainSeverance`**      | **.25** | **no empirical counterpart** |

**Ceilings: 1.52 (core-v1) vs 1.63 (SimLex).** The 0.11 difference decomposes
exactly as `+CS(.25) − NI(.07) + (RV−RC3 = −.06) + (TA−FM = −.04) + (RC−TC = +.03)`.

Two further mismatches:

- **Node indexing.** SimLex indexes nodes `0..7`; the ontology and the annotation
  schema use `1..8`. Every `nodes:[...]` array in the `CT` table is off by one
  relative to the MLC node numbering used everywhere else.
- **Node spans.** Where both define a span, they sometimes disagree — e.g. JC is
  `2→6` in the ontology but `nodes:[1]` in SimLex.

### Consequences

1. SimLex has **no representation for NI**, the single most common contradiction in
   the corpus (55% of cases) and the largest component of the debt that survives
   repair (see §5).
2. SimLex's **heaviest weight**, `chainSeverance` at 0.25, has no counterpart in the
   annotation schema. No corpus case can ever carry it, so it can never be validated
   or falsified against data — yet it inflates the published ceiling.

---

## 3. Three quantities, one name

| # | Quantity | Kind | Definition | Range | Observed |
|---|---|---|---|---|---|
| 1 | **Case CD** | flow | Σw over one case's `active_contradictions` | 0 – 1.52, unclamped | mean 0.1375, max 0.78 |
| 2 | **Agent CD** | stock | SimLex `contradictionDebt`, per issuer, accumulated over time | clamped [0, 1] | simulator-internal |
| 3 | **QuickRef bands** | count | 0 / 1–2 / 3–4 / 5–6 / 7+ | count of active types | mean 1.41 per case |

Under either weighted profile, every one of the 5,103 cases falls in QuickRef band
"0", and bands 3–4, 5–6 and 7+ are not merely empty but **unreachable** — max case CD
(0.78) is below the lower edge of band 3–4. The bands are coherent only as a *count*
scale, which is what they were evidently designed for.

### Proposed names

Retire the bare term `CD`. Use:

- `cd_case`  — the per-case weighted flow (ceiling 1.52 under `core-v1`)
- `cd_stock` — the per-issuer accumulated stock, clamped [0, 1]
- `ct_count` — the count of active contradiction types (what QuickRef bands measure)

Every published figure should name which one it reports, alongside its weight profile.

---

## 4. The stock/flow bridge

SimLex's `cd_stock` is an accumulation of case-level increments. Writing that down
explicitly is what makes the corpus and the simulator commensurable:

```
cd_stock(t+1) = clamp(
      cd_stock(t)
    + Σ_new_adjudications [ cd_case × archCDMult × abMult ]     # incurred
    − decay                                                     # time discharge
    − repair_credit                                             # see §5
    , 0, 1)
```

Once stated, the empirical mean `cd_case` = 0.1375 becomes a grounded *increment
rate* rather than a number incomparable to `avgDebt`. SimLex's existing regime-shift
thresholds (`avgDebt` > 0.32 collapsed, 0.47 naturalLaw, 0.48 pluralist,
0.52 ruleOfLaw, 0.55 positivist, 0.56 customary) then become claims about how many
unrepaired contradictions an institution can carry — statements that are in principle
testable.

Two implementation defects to fix while doing this:

- SimLex increments debt by **two inconsistent formulas** in different code paths —
  one scaled (`+cdW*0.4*archCDMult*abMult`), one raw (`+cdw`).
- The time-decay constant (`−0.0008` per step) is uncalibrated and currently does
  most of the work in setting equilibrium debt.

---

## 5. Repair: where the corpus and SimLex disagree

SimLex discharges debt on every fulfilled obligation at a flat rate:

```js
ob.issuer.contradictionDebt = clamp(ob.issuer.contradictionDebt - 0.025*archRepBonus, 0, 1)
```

The credit is **independent of which contradiction produced the debt**. The corpus
contradicts this. Among the 545 v2 cases where repair fully succeeded — claimant won
*and* Node 8 closed — **77.6% still carry nonzero `cd_case`**, at mean 0.1424, slightly
*above* the corpus mean of 0.1365. What survives is systematically upstream:

```
surviving in fully-repaired cases:
  NI 279   JC 188   AI 99   PC 88   RC3 65   FM 37   TC 28     <- upstream, N1-N5
  CC 17    RF 5     RPF 5   CF 2    SE 2                        <- downstream, N6-N8
```

Remedy discharges the *claim*, not the contradiction that generated it. The norm is
just as indeterminate, the authority sources just as competing, and the role conflict
just as unresolved after the plaintiff is made whole.

### Proposed rule: type-scoped repair credit

Replace the flat credit with:

- **Full discharge** for the recognition/remedy types — RF, CC, SE, RPF (Nodes 6–8)
- **Zero discharge** for the constitutive types — CF, AI, JC, RC3, PC, TC, FM, NI
  (Nodes 1–5)

This makes the simulator reproduce the observed residue instead of contradicting it,
and it is what permits systemic accumulation in the model at all. Under the present
flat credit a high-fulfillment institution pays down debt it never structurally
resolved — the exact mechanism the accumulation thesis denies.

---

## 6. Recommended sequence

1. **Re-key SimLex's `CT` table to `core-v1`.** The ontology is authoritative: 5,103
   annotations exist under it and none under the SimLex list. Add NI. Restore RC3
   (.14), FM (.11), PC (.09), TC (.08), RCL (.18), SE (.10) with ontology semantics.
2. **Resolve `chainSeverance`.** Either drop it, or retain it as an explicitly
   simulator-only construct excluded from the published ceiling — not silently
   inflating 1.52 to 1.63.
3. **Fix node indexing** (0-based → 1-based) and reconcile the node spans.
4. **Adopt the `cd_case` / `cd_stock` / `ct_count` vocabulary** across the query tool,
   QuickRef, SimLex and this repo; relabel the QuickRef card as a `ct_count` scale.
5. **Implement the type-scoped repair credit** (§5) and unify the two increment paths.
6. **Defer threshold calibration.** P8 shows the `core-v1` weights are *less*
   discriminative than a raw count (Cohen's d = 0.261 for `ct_count` vs 0.166 for
   `cd_case`). Thresholds denominated in weighted debt inherit that weakness;
   consider defining incoherence thresholds on `ct_count` instead.
7. **Only then** attempt to calibrate the regime-shift thresholds, which additionally
   requires the citation-propagation data that `sool_followup.db` does not yet hold
   (`study_c_results.subsequent_cd_mean` is null for all 119 rows).

---

## 7. What this does not settle

Harmonizing the scales makes the incoherence question *askable*; it does not answer
it. The claim that a legal regime becomes incoherent above some `cd_stock` still
requires (a) propagation data showing debt is inherited across cases, and (b) an
empirical calibration of the weights, which has never been performed. Both are
tractable; neither is done.
