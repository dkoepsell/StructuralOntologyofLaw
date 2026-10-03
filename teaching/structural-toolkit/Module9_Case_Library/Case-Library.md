# Examples and Case Library

This library provides cross‑domain examples illustrating how to apply the SOoL structural framework.  Each case includes: (1) a one‑sentence problem; (2) four structural anchors (Authority, Event/Process, Recognition, Repair); (3) the MLC chain (links 1–8); (4) contradiction diagnosis; (5) an IRACplus draft; (6) OWL individuals and JSON export; (7) comparative notes.

## 1. Criminal Law Case – Theft of Property

- **Problem:** Whether Alice is guilty of theft for taking Bob’s bicycle without permission.
- **Anchors:**  
  - *Authority:* Criminal code defines theft and empowers courts to prosecute.  
  - *Event/Process:* Alice took the bicycle without consent.  
  - *Recognition:* Police report filed; prosecutor brings charges.  
  - *Repair:* Court may order restitution or imprisonment.
- **MLC Chain:**  
  1. Authority – Legislature enacted the Theft Statute.  
  2. Jurisdiction – Offence occurred within state borders.  
  3. Role Conferral – Prosecutor authorised to bring charges.  
  4. Normative Content – Theft statute prohibits taking property without consent.  
  5. Authorised Process – Police investigation and prosecution follow procedure.  
  6. Legal Event – The act of taking the bicycle.  
  7. Recognition – Court records the conviction.  
  8. Remedy – Imprisonment or restitution.
- **Contradiction Diagnosis:** No structural failure; all links satisfied.  
- **IRACplus Draft:**  
  - *Issue:* Whether taking another person’s property without consent constitutes theft under the statute.  
  - *Rule:* The Theft Statute provides that anyone who unlawfully takes property with intent to deprive commits theft.  
  - *Analysis:* Alice took Bob’s bicycle without permission.  The statute applies within the jurisdiction.  The prosecutor has authority to prosecute.  All procedural requirements were followed.  
  - *Conclusion:* Alice is guilty of theft.  
  - *Structural Diagnosis:* None.
- **OWL / JSON:** See `cases/theft_case.ttl` and `cases/theft_case.json`.
- **Comparative Notes:** Contrast with the contract case; here, authority and role conferral are clear, highlighting differences between doctrinal and structural analysis.

## 2. Tort Case – Battery Without Consent

- **Problem:** Whether Dr. Smith committed battery by touching Patient J without obtaining valid consent.
- **Anchors:**  
  - *Authority:* Tort law recognises battery as unauthorised physical contact.  
  - *Event/Process:* Dr. Smith touched Patient J during examination.  
  - *Recognition:* No consent form was signed; hospital records show treatment.  
  - *Repair:* Patient may sue for damages.
- **MLC Chain:**  
  1. Authority – Tort law grants individuals the right to bodily integrity.  
  2. Jurisdiction – The tort occurred within the state.  
  3. Role Conferral – Dr. Smith is a licensed physician.  
  4. Normative Content – Medical practitioners must obtain informed consent.  
  5. Authorised Process – Consent should be obtained before examination.  
  6. Legal Event – Physical contact without consent.  
  7. Recognition – No documentation of consent.  
  8. Remedy – Patient may sue for battery.
- **Contradiction Diagnosis:** Type 6 Recognition Failure – absence of consent recording; potentially Type 4 Procedural Contradiction.  
- **IRACplus Draft:**  
  - *Issue:* Whether physical contact without documented consent constitutes battery.  
  - *Rule:* The law requires medical practitioners to obtain and document informed consent before touching a patient.  
  - *Analysis:* Dr. Smith did not obtain or record consent; the patient’s autonomy is violated.  The authorised process (consent) was not followed, and recognition is absent.  
  - *Conclusion:* Dr. Smith is liable for battery.  
  - *Structural Diagnosis:* ["Type 6: Recognition Failure", "Type 4: Procedural Contradiction"].
- **OWL / JSON:** See `cases/battery_case.ttl` and `cases/battery_case.json`.
- **Comparative Notes:** Compared with the theft case, the failure here lies not in authority but in process and recognition.

## 3. Contract Case – Unauthorized Employee Signs Contract

- **Problem:** Whether a contract signed by an unauthorised intern binds the corporation.
- **Anchors:**  
  - *Authority:* Corporate board resolutions confer contracting authority.  
  - *Event/Process:* Intern signs contract with supplier.  
  - *Recognition:* Contract filed with registrar.  
  - *Repair:* Company may ratify or rescind; supplier may seek damages.
- **MLC Chain:**  
  1. Authority – Board has power to authorise contracts.  
  2. Jurisdiction – Contract concerns company business.  
  3. Role Conferral – Intern lacks role conferral.  
  4. Normative Content – Corporate law defines who may bind the company.  
  5. Authorised Process – Board approval is required.  
  6. Legal Event – Signing of contract.  
  7. Recognition – Contract recorded.  
  8. Remedy – Contract can be voided; damages may be available.
- **Contradiction Diagnosis:** Type 3 Role Contradiction; possibly Type 4 Procedural Contradiction.  
- **IRACplus Draft:**  
  - *Issue:* Whether the intern’s signature binds the company.  
  - *Rule:* Only authorised agents can bind the corporation; unauthorised contracts are voidable.  
  - *Analysis:* The intern had no authority; the board did not approve the contract.  Role conferral fails; the process of approval is missing.  
  - *Conclusion:* The contract does not bind the company unless ratified.  
  - *Structural Diagnosis:* ["Type 3: Role Contradiction", "Type 4: Procedural Contradiction"].
- **OWL / JSON:** See `cases/unauth_contract_case.ttl` and `cases/unauth_contract_case.json`.
- **Comparative Notes:** Contrasts with the theft case where the role and process are clear; demonstrates structural issues in contract formation.

## 4. Constitutional / Public Law Case – Agency Rule Without Statutory Authority

- **Problem:** Whether an administrative agency’s rule is valid when enacted without statutory authority.
- **Anchors:**  
  - *Authority:* Legislature grants rulemaking authority to agencies.  
  - *Event/Process:* Agency issues rule.  
  - *Recognition:* Rule published in official register.  
  - *Repair:* Court may invalidate rule.
- **MLC Chain:**  
  1. Authority – No statute authorises the rule.  
  2. Jurisdiction – Agency acts nationwide.  
  3. Role Conferral – Agency officials act as administrators.  
  4. Normative Content – Rule purports to create obligations.  
  5. Authorised Process – Notice‑and‑comment procedure followed.  
  6. Legal Event – Promulgation of rule.  
  7. Recognition – Publication in Federal Register.  
  8. Remedy – Courts can review the rule.
- **Contradiction Diagnosis:** Type 1 Conferral Failure (no authority) – the primary structural problem.  
- **IRACplus Draft:**  
  - *Issue:* Whether a rule issued without statutory authority is valid.  
  - *Rule:* Under administrative law, an agency may only exercise power granted by statute.  
  - *Analysis:* There is no enabling statute; though the process was followed and the rule was published, the authority link fails.  
  - *Conclusion:* The rule is invalid.  
  - *Structural Diagnosis:* ["Type 1: Conferral Failure"].
- **OWL / JSON:** See `cases/agency_rule_case.ttl` and `cases/agency_rule_case.json`.
- **Comparative Notes:** Highlights differences between procedural adequacy and authority; even a perfect process cannot cure lack of authority.

## 5. Administrative Law Case – Officer from City A Issues Fine in City B

- **Problem:** Whether a citation issued by a City A police officer in City B is valid.
- **Anchors:**  
  - *Authority:* City charter empowers officers within city limits.  
  - *Event/Process:* Officer issues citation outside his jurisdiction.  
  - *Recognition:* Citation filed with court.  
  - *Repair:* Court may dismiss; defendant may seek redress.
- **MLC Chain:**  
  1. Authority – City charter.  
  2. Jurisdiction – Limited to City A.  
  3. Role Conferral – Officer holds the role of City A police officer.  
  4. Normative Content – Traffic code.  
  5. Authorised Process – Issuing citation.  
  6. Legal Event – Issuance of ticket in City B.  
  7. Recognition – Ticket recorded by court.  
  8. Remedy – Defendant can challenge citation.
- **Contradiction Diagnosis:** Type 2 Jurisdictional Contradiction; possibly Type 6 Recognition Failure if court lacks jurisdiction.  
- **IRACplus Draft:**  
  - *Issue:* Whether an officer can issue a valid citation outside his jurisdiction.  
  - *Rule:* Police authority is limited to their jurisdiction; actions outside are void.  
  - *Analysis:* The officer’s authority does not extend to City B; the role conferral is valid but the jurisdiction is not.  
  - *Conclusion:* The citation is invalid; the court should dismiss.  
  - *Structural Diagnosis:* ["Type 2: Jurisdictional Contradiction"].
- **OWL / JSON:** See `cases/jurisdiction_case.ttl` and `cases/jurisdiction_case.json`.
- **Comparative Notes:** Demonstrates how jurisdictional limits function; compare with the unlicensed surgeon case where the role, not jurisdiction, fails.

## Comparative Summary

| Case | Primary Contradiction Type | Domain |
| --- | --- | --- |
| Theft of Property | None | Criminal |
| Battery Without Consent | Type 6 (Recognition Failure) | Tort |
| Unauthorized Employee Contract | Type 3 (Role Contradiction) | Contract |
| Agency Rule Without Statutory Authority | Type 1 (Conferral Failure) | Constitutional / Public Law |
| Officer Issues Fine Outside City | Type 2 (Jurisdictional Contradiction) | Administrative |

These examples illustrate how structural analysis applies across doctrinal areas.  The case files provide reusable templates for students and developers.

