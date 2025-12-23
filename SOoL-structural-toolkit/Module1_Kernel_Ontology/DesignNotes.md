# Kernel Ontology — Design Notes

This document explains the rationale for each class in the SOoL kernel ontology and how it aligns with the Basic Formal Ontology (BFO) and existing legal ontologies such as LKIF‑Core and LegalRuleML.

## Class Rationale and BFO Alignment

| SOoL class | Why it exists | BFO superclass | Mapping to LKIF‑Core / LegalRuleML |
| --- | --- | --- | --- |
| **Authority** | Captures the legally recognised capacity to create binding effects. Authority is treated as a generically dependent continuant because it depends on institutional bearers. | `bfo:GenericallyDependentContinuant`【873523715407077†L155-L159】 | Equivalent to `lkif:Authority`; LegalRuleML models sources of authority as *sources* of norms. |
| **Jurisdiction** | Specifies the spatial, temporal and subject‑matter limits within which authority may be exercised. It is a relational dependent continuant because it relates a bearer to domains of competence. | `bfo:RelationalDependentContinuant` | No direct LKIF equivalent; modelled in LegalRuleML as `<lrml:Jurisdiction>` restrictions. |
| **Role** | Represents positions like judge or police officer that agents occupy. Roles are specifically dependent continuants that inhere in agents and are realised through processes【516386639202089†L88-L97】. | `bfo:SpecificallyDependentContinuant` | Equivalent to `lkif:Role`; LegalRuleML uses `<lrml:Role>`. |
| **Norm** | Captures obligations, permissions and powers attached to roles. Norms are realisable dependent continuants because they are realised through actions. | `bfo:RealisableDependentContinuant` | Aligns with `lkif:Norm` and `<lrml:Right>` or `<lrml:Duty>` in LegalRuleML. |
| **AuthorisedProcess** | Represents the procedures an agent must follow to realise legal effects. These are processes (occurrent) under BFO. | `bfo:Process` | Corresponds to action patterns in LKIF and `<lrml:LegalProcess>` in LegalRuleML. |
| **LegalEvent** | Captures legally significant acts or occurrences (e.g., issuing a contract). These are occurrents that may be recognised by institutions. | `bfo:Occurrent` | Equivalent to events in LKIF (e.g., `lkif:LegalAct`); LegalRuleML uses `<lrml:LegalEvent>`. |
| **Recognition** | Represents the institutional acknowledgement of a legal event. Treated as a realisable dependent continuant because it relies on institutional realisation. | `bfo:RealisableDependentContinuant` | Corresponds to institutional facts in Searle’s terms; LegalRuleML uses `<lrml:Recognition>` type elements. |
| **Remedy** | Models dispositions or processes designed to correct, enforce or reverse legal effects. Remedies are dispositions in BFO or processes when realised. | `bfo:Disposition` / `bfo:Process` | LKIF does not have an explicit remedy class; LegalRuleML uses `<lrml:Remedy>`. |
| **Agent** | A material entity capable of occupying roles and participating in legal processes. | `bfo:MaterialEntity` | Equivalent to `lkif:Agent` and `<lrml:Person>` or `<lrml:Organization>`. |
| **Institution** | A social structure (court, agency) that confers authority, recognises events and provides remedies. Institutions are objects in BFO. | `bfo:Object` | Equivalent to `lkif:Institution`; LegalRuleML uses `<lrml:Institution>`. |

## Object Properties Rationale

- **confersAuthority** – links an institution to the authority it confers; reflects the conferral relation in LegalRuleML.
- **hasJurisdiction** – connects an authority to its jurisdiction; necessary for identifying jurisdictional contradictions.
- **assignsRole** – links an authority to the roles it confers; vital for role conferral.
- **roleRealises** – relates a role to the norms it realises; captures the normative content of roles.
- **processRealisesEvent** – links processes to the legal events they produce; ensures that events are grounded in authorised procedures.
- **recognisesEvent** – captures institutional recognition of events; crucial for establishing legal effect.
- **providesRemedy** – associates institutions with the remedies they offer; supports repair analysis.

## BFO Mapping Summary

This ontology is explicitly aligned with BFO classes. Continuants (e.g., Authority, Role) and occurrents (e.g., AuthorisedProcess, LegalEvent) are distinguished. Dependent continuants (generically, specifically, realisable, relational) model the inherent dependence of legal phenomena on agents and institutions. These alignments enable consistency with the BFO approach to ontology design.

## LKIF‑Core and LegalRuleML Alignment

SOoL builds on the LKIF‑Core ontology of basic legal concepts【343188168504826†L34-L45】 and LegalRuleML. Where possible, SOoL classes are declared as subclasses or equivalents of LKIF concepts. This facilitates interoperability and allows inference engines to leverage existing legal ontologies. LegalRuleML elements such as **Role**, **Norm**, **LegalEvent** and **Institution** map directly to the corresponding SOoL classes, allowing rule systems to import SOoL while maintaining compatibility with LegalRuleML representations.

