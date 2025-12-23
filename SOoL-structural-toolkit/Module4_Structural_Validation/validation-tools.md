# Structural Validation Tools

This module provides tools to automatically check the structural completeness of legal descriptions and detect contradictions in the Minimum Legal Chain (MLC).

## MLC Completeness Checker

The **MLC Completeness Checker** verifies that each of the eight MLC links is present and valid.  It can be implemented using:

- **SHACL shapes** (`../Module2_MLC/MLC-shapes.ttl`): define `mlc:MLCShape` and subordinate shapes for each link.  When applied to an RDF graph, the validator reports missing links or invalid values.
- **SPARQL queries**: count or select the presence of required properties in MLC records.

Example CLI invocation (using `pyshacl`):

```bash
pyshacl -s MLC-shapes.ttl -d my_mlc_dataset.ttl --inference owlrl
```

A passing dataset will produce no violations.  Violations are annotated with messages indicating which link is missing or invalid.

## Contradiction Detector

The **Contradiction Detector** classifies structural failures into the 13 contradiction types described in Module 3.  Two approaches are provided:

1. **SHACL-based detection** – `contradiction-shapes.ttl` defines shapes that fail when a contradiction is present.  Each shape includes a message specifying the contradiction type.  After validating, you can collect all violations and map them to AERR families.
2. **SWRL/rule-based detection** – `contradiction-rules.swrl` contains sample SWRL rules.  Load these into a rule-enabled reasoner (e.g., Pellet) along with your data.  The reasoner will infer instances of `ConferralFailure`, `RoleContradiction`, etc.
3. **Application logic** – Use pseudocode (e.g., `contradiction-detection-pseudocode.md`) to implement detection in Python or another language.

## Generating a Structural Integrity Report

After running the completeness checker and contradiction detector, generate a report summarising:

- Presence/absence of each MLC link
- Validity of each link
- Detected contradiction types and their AERR families
- Recommendations for remedy or repair

A template is provided in `Structural-Integrity-Report.md`.

