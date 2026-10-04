# SOoL Precedent Mapping — Corpus Design Rationale
## A Structural Ontology of the Law · SEAL Lab, Texas A&M

---

## Scientific Objective

Test whether MLC node failures cluster structurally across doctrinal domains —
i.e., whether Role Contradiction at Node 3 in employment law is the *same
kind of failure* as Role Contradiction in administrative law, academic freedom,
and immigration, independent of doctrine.

**Null hypothesis:** MLC failure types distribute randomly across doctrinal
domains — there are no cross-domain structural family resemblances.

**Alternative hypothesis:** MLC failure types cluster by structural position
regardless of doctrinal domain — the ontology captures domain-invariant
legal structure.

---

## Sample Size Rationale

For structural clustering analysis (chi-square / correspondence analysis):

- 13 contradiction types × 8 domains = 104 cells
- Minimum cell frequency for valid chi-square: 5 expected observations
- Target cell frequency for robust clustering: 30+
- Estimated proportion of cases exhibiting a primary contradiction: ~15–25%
- **Required per domain: 300–500 cases minimum**
- **Target corpus: 500 per domain × 8 domains = 4,000 cases**

**Superseded (3 October 2026).** This design originally called for Contradiction
Debt *predictive validity* testing, asking whether debt at decision time predicts
downstream litigation density. **That line of inquiry is withdrawn.** The v1
predictive results rested on annotation forcing rules (RULE 1, RULE 5) that derived
chain outcomes from node closures, and five contradiction types (RF, RCL, CC, SE,
RPF) are definitionally entangled with the disposition. SOoL makes no predictive
claims.

Citation-network data is still collected, but for a different and descriptive
purpose: tracing how a structural failure propagates through later citations, with
no claim that debt forecasts anything.

- Citation network data — CourtListener provides this
- Need temporal spread: 1990–2024 gives 34 years of precedent propagation
- Cases from 1990–2010 have enough downstream citation history to measure

---

## Domain Selection

Domains chosen to maximize:
1. Coverage of all 13 contradiction types across the MLC
2. Doctrinal diversity (no shared conceptual vocabulary between domains)
3. Tractability (federal courts, written opinions, full text available)
4. Theoretical interest (each domain has known structural instabilities)

| # | Domain                    | Primary MLC Failures Expected            | Anchor Cases                        |
|---|---------------------------|------------------------------------------|-------------------------------------|
| 1 | First Amendment /         | Role Contradiction (N.3),                | Garcetti v. Ceballos (2006),        |
|   | Public Employee Speech    | Norm Indeterminacy (N.2)                 | Pickering, Connick, Meriwether      |
| 2 | Employment Discrimination | Recognition Failure (N.6/7),             | McDonnell Douglas, Griggs,          |
|   | (Title VII / §1981)       | Correlativity Contradiction (N.7)        | Burlington Northern                 |
| 3 | Administrative Law /      | Authority Inflation (N.1→2),             | Chevron, MCI, West Virginia         |
|   | Agency Action             | Procedural Contradiction (N.2→5)         | v. EPA (Major Questions)            |
| 4 | Criminal Procedure        | Fact Manipulation (N.4),                 | Mapp, Terry, Franks v. Delaware,    |
|   | (4th/5th Amendment)       | Conferral Failure (N.1→3)                | Herring v. United States            |
| 5 | Immigration /             | Recognition Collapse (N.6→8),            | INS v. Cardoza-Fonseca,             |
|   | Status Recognition        | Jurisdictional Contradiction (N.2→6)     | Zadvydas, DHS v. Thuraissigiam      |
| 6 | Civil Rights (§1983) /    | Correlativity Contradiction (N.7),       | Monroe v. Pape, Monell,             |
|   | Qualified Immunity        | Repair Failure (N.8)                     | Harlow, Pearson v. Callahan         |
| 7 | Contract / Commercial     | Temporal Contradiction (N.2↔4),          | Hadley v. Baxendale lineage,        |
|   | Obligation                | Correlativity Contradiction (N.7)        | UCC cases, frustration/impossibility|
| 8 | Family Law /              | Jurisdictional Contradiction (N.2→6),    | Troxel v. Granville, Parham,        |
|   | Parental Rights           | Recognition Failure (N.6/7)              | Santosky v. Kramer                  |

---

## Court Selection

Federal circuit courts of appeals (CA1–CA11 + CADC) plus Supreme Court.

Rationale:
- Circuit courts are the primary law-making level in the federal system
- Opinions are consistently structured with explicit legal reasoning
- MLC nodes are visible: authority cited, norm stated, role identified,
  facts described, legal effect announced, remedy addressed
- Full text freely available via CourtListener

Excluded (for Phase 1):
- District courts: too variable in opinion structure
- State courts: inconsistent availability, harder to normalize
- Administrative tribunals: different structural format

---

## Date Range

**1990–2024**

Rationale:
- 1990 post-dates the consolidation of the Pickering-Connick framework
  (giving First Amendment domain a stable baseline)
- Pre-1990 cases available as precedent anchors but not in primary corpus
- Cases from 1990–2010 have 14–34 years of downstream citation history, which
  supports descriptive citation-propagation analysis. The predictive-validity use
  originally stated here is withdrawn; see the note above.
- Cases from 2010–2024 represent the current doctrinal state

---

## Data Source

**CourtListener** (Free Law Project — courtlistener.com)
- REST API v4, free tier: ~5,000 requests/day
- Full opinion text, citation networks, court metadata
- Covers all federal circuit courts comprehensively

**Supplementary** (Phase 2):
- Harvard Caselaw Access Project (historical depth)
- PACER (district court opinions if needed)

---

## Query Strategy

Each domain uses a primary keyword cluster plus exclusion filters.
Queries target:
1. Cases where the governing authority is explicitly identified (Node 1)
2. Cases where the applicable norm is contested or applied (Node 2)
3. Cases where the actor's role is material to the outcome (Node 3)

Cases that are purely procedural (jurisdiction, pleading standards,
attorneys' fees without merits) are collected but flagged for potential
exclusion during annotation.

---

## Annotation Plan (Phase 2)

Each collected case will be annotated for:
- MLC node closure status (closed / failed / partial) at each of 8 nodes
- Active contradiction types from the 13-type typology
- Contradiction Debt score (sum of CD weights for active types)
- Chain outcome (protection granted / denied / partial / remanded)
- Repair status (remedy awarded / denied / deferred)

Inter-annotator reliability target: Cohen's κ ≥ 0.7 for node closure,
κ ≥ 0.6 for contradiction type (more subjective).

Gold standard: 300 cases annotated by 2+ trained annotators.
Extended corpus: LLM-assisted annotation with human spot-check (20%).
