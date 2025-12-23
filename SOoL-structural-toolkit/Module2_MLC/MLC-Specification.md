# Minimum Legal Chain (MLC) Specification

The Minimum Legal Chain (MLC) defines the structural conditions that must hold for a legal effect to exist.  Each link corresponds to a BFO‑typed entity, and failure at any link constitutes a **legal contradiction**.  This document provides definitions, BFO mappings, examples and common failure modes for each of the eight MLC positions.

| # | MLC Position | Description | BFO Category | Example | Common Failure Modes |
| --- | --- | --- | --- | --- | --- |
| **1** | **Source of Authority** | A recognised authority that has the capacity to confer legal power.  Must be validly created by statute or constitution. | `GenericallyDependentContinuant`【873523715407077†L155-L159】 | A licensing board empowered by statute to issue medical licenses. | **Conferral Failure**: an agency issues a rule without statutory authority (public law). |
| **2** | **Jurisdictional Scope** | The spatial, temporal and subject‑matter limits within which authority may be exercised.  A relational dependent continuant linking the authority to its domain. | `RelationalDependentContinuant` | A city police department has jurisdiction only within city boundaries. | **Jurisdictional Contradiction**: an officer from City A issues a citation in City B (not within scope). |
| **3** | **Role Conferral** | An agent occupies a legally recognised role.  Roles are specifically dependent continuants that must be conferred by authority. | `SpecificallyDependentContinuant (Role)`【516386639202089†L88-L97】 | A doctor holds a valid medical licence. | **Role Contradiction**: doctor without a licence performs surgery (no licensed‑physician role). |
| **4** | **Normative Content** | Obligations, permissions or powers attached to the role.  These norms are realisable dependent continuants that prescribe behaviour. | `RealisableDependentContinuant` | A traffic code defining speed limits. | **Procedural / Temporal Contradictions**: the norm is not in force or the triggering facts occur outside its scope. |
| **5** | **Authorised Process** | Actions taken according to required procedures to realise a legal effect.  Processes are occurrents in BFO. | `Process` | A police officer following proper protocol to issue a ticket. | **Procedural Contradiction**: procedure not followed (e.g., failing to read Miranda rights). |
| **6** | **Legal Event** | A legally significant act or occurrence that realises the norm when performed through an authorised process. | `Occurrent` | Signing a contract, issuing a citation, rendering a verdict. | **Temporal Contradiction**: the event occurs outside the temporal scope; **Process Contradiction**: the event is not produced by an authorised process. |
| **7** | **Recognition / Recording** | Institutional acknowledgment of the legal event, creating a recognised legal effect.  A realisable dependent continuant created by an institution. | `RealisableDependentContinuant` | Filing the signed contract with the registrar; judge declaring a verdict in court. | **Recognition Failure**: no recording or acknowledgement (e.g., contract not filed, verdict not entered). |
| **8** | **Remedy / Repair** | Mechanisms that correct, enforce or reverse legal effects.  These may be dispositions or processes. | `Disposition` / `Process` | An appellate court overturning a conviction; damages awarded to a plaintiff. | **Repair Failure**: no remedy exists or cannot be realised; **Compound Contradictions** when multiple failures occur. |

## Examples

### Tort Example: Doctor Without Licence Performs Surgery
- **Facts:** A person performs surgery without holding a valid medical licence.  
- **MLC failure:** Link 3 (Role Conferral) fails.  The actor does not have the licensed‑physician role, producing a **Role Contradiction**.  
- **BFO perspective:** Role is a specifically dependent continuant requiring a licensing authority as bearer; since the relation does not exist, the legal effect (valid consent to treatment) cannot exist【516386639202089†L88-L97】.

### Contract Example: Unauthorized Employee Signs Contract
- **Facts:** An employee without actual authority signs a contract on behalf of the company.  
- **MLC failure:** Link 3 (Role Conferral) fails.  There is no authorised‑agent role; the contract cannot bind the company (Role Contradiction).  
- **BFO perspective:** The role requires a conferral relation from the company.  Without it, the role is unrealizable and the legal effect (binding contract) cannot exist.

### Public Law Example: Agency Issues Rule Without Statutory Authority
- **Facts:** An administrative agency promulgates a rule without statutory authorisation.  
- **MLC failure:** Link 1 (Source of Authority) fails.  The norm cannot be validly created (Conferral Failure).  
- **BFO perspective:** Authority is a generically dependent continuant that must be conferred by statute.  No such continuant exists; thus the binding rule cannot exist【873523715407077†L155-L159】.

### Jurisdictional Example: Officer from City A Issues a Fine in City B
- **Facts:** A City A police officer issues a citation to a driver in City B.  
- **MLC failure:** Link 2 (Jurisdictional Scope) fails.  The officer’s role does not extend to City B, producing a **Jurisdictional Contradiction**.  
- **BFO perspective:** The role depends on a bearer relation (jurisdiction) that does not obtain outside its domain.  The legal effect (valid citation) cannot exist.

## Common Failure Modes Summary

- **Conferral Failure (Type 1)** – absence of a valid authority.  
- **Jurisdictional Contradiction (Type 2)** – mismatch between authority and scope.  
- **Role Contradiction (Type 3)** – agent not occupying the required role.  
- **Procedural Contradiction (Type 4)** – process does not satisfy required procedure.  
- **Temporal Contradiction (Type 5)** – event occurs outside the temporal scope.  
- **Recognition Failure (Type 6)** – lack of institutional acknowledgment.  
- **Correlativity Contradiction (Type 7)** – relational norms missing one of their relata.  
- **Repair Failures (Types 8–11)** – remedy missing or misaligned.  
- **Compound Contradiction (Type 12)** – multiple failures simultaneously.  
- **Institutionalized Contradiction (Type 13)** – systemic tolerance of ontological inconsistency.

These failure modes correspond to the Contradiction Typology described in Module 3.

