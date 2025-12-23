# The SOoL Structural Toolkit

**A modular framework for structural legal reasoning, legal ontology,
and computable law**

The SOoL Structural Toolkit provides a formally grounded, ontology-driven
approach to understanding legal validity, legal failure, and legal
reasoning across doctrinal domains. It operationalizes the core thesis
of the Structural Ontology of Law (SOoL):

> **Structural failure is ontological failure.**

The toolkit is designed for legal ontology researchers, legal AI
developers, law faculty, students, and practitioners who require a
stable, cross-domain method for analyzing legal authority, jurisdiction,
roles, procedures, legal effects, and remedies.

---

## What This Toolkit Contains

The toolkit is organized into **ten self-contained modules**, each with
a clear purpose:

### Module 0 — Overview (Start Here)
A high-level, intuitive introduction:
- One-page SOoL overview
- Legal circuit metaphor
- Structural pipeline (Ontology → MLC → Contradiction → IRAC+)
- Glossary (plain-language + formal)
- Toolkit map

### Module 1 — Kernel Ontology
- BFO-aligned minimal legal ontology
- Design rationale and mappings to BFO, LKIF-Core, LegalRuleML
- Competency questions and import instructions

### Module 2 — Minimum Legal Chain (MLC)
- Formal specification of the eight structural positions of legality
- Diagrams, examples, failure modes
- JSON Schema and SHACL validation shapes

### Module 3 — Contradiction Typology
- Thirteen structural contradiction types
- Authority–Event–Recognition–Repair (AERR) families
- Diagnostic flowcharts and poster-style diagrams

### Module 4 — Structural Validation Tools
- MLC completeness checking
- Contradiction detection logic
- Structural integrity report templates
- API specifications

### Module 5 — Offense Mapping Dataset
- Offenses mapped to structural violations
- Chain failure cues and contradiction types
- Searchable tables and extension methodology

### Module 6 — IRACplus Integration
- Structure-first legal writing pipeline
- MLC ↔ IRAC+ mappings
- JSON schema and sample outputs

### Module 7 — Teaching Materials
- Lecture modules
- Labs, worksheets, problem sets
- Rubrics and classroom-ready resources

### Module 8 — Developer Resources
- API documentation
- Graph population templates
- SPARQL, RDFLib, OWLAPI examples
- Integration recipes and governance guidance

### Module 9 — Examples and Case Library
- Criminal, tort, contract, constitutional, and administrative cases
- Each case includes:
  - One-sentence problem
  - Structural anchors
  - MLC chain
  - Contradiction diagnosis
  - IRACplus draft
  - OWL individuals and JSON export

---

## Who This Is For

- **Legal ontology researchers** seeking a BFO-aligned structural layer
- **Legal AI developers** who need non-hallucinatory reasoning structure
- **Law faculty** teaching jurisprudence, public law, or legal reasoning
- **Students** needing a stable diagnostic method across subjects
- **Practitioners** who want disciplined issue-structuring tools

---

## Conceptual Foundation

The toolkit is grounded in **Basic Formal Ontology (BFO)** and treats
legal authority, roles, norms, effects, and remedies as ontologically
typed dependent continuants and processes. Legal validity requires a
complete and coherent instantiation of the **Minimum Legal Chain (MLC)**.
Contradictions arise when BFO constraints are violated at any structural
position.

---

## Citation

If you use this toolkit in research, teaching, or software, please cite
it using the `CITATION.cff` file included in this repository.

---

## Licensing

- **Documentation, diagrams, and teaching materials:**  
  Creative Commons Attribution 4.0 (CC BY 4.0)

- **Ontologies, schemas, validation rules, and code:**  
  Apache License, Version 2.0

See the `LICENSE` file for full details.

---

## Status

Current release: **v1.0.0**

This toolkit is actively maintained as part of the broader *Structural
Ontology of Law* project.

---

## Contact

**David R. Koepsell, J.D., Ph.D.**  
Instructional Associate Professor of Philosophy  
Texas A&M University

(See ORCID and citation metadata in `CITATION.cff`)
