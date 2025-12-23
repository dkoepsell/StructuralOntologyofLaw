# Jurisdictional Extension Guide

The Offense Mapping Dataset is designed to be extensible across jurisdictions.  Legal definitions and structural cues vary by country, state or municipality.  This guide outlines how to adapt the mapping for new jurisdictions.

1. **Gather Local Sources** – Collect the relevant statutes, codes, case law and authoritative commentaries for the jurisdiction.  This may include penal codes, civil codes, administrative regulations and judicial decisions.

2. **Identify Offence Equivalents** – For each offence in the base dataset, determine the equivalent offence in the local law.  Where none exists, decide whether to omit or define a new entry.

3. **Modify Structural Cues** – Jurisdiction determines the scope of authority, roles and procedures.  Update the `chainFailureCue` field to reflect local terms (e.g., “federal jurisdiction” vs. “state jurisdiction”).

4. **Adjust Contradiction Types** – Some jurisdictions may define offences that correspond to different structural failures.  Map them accordingly; for instance, a local offence of “unauthorised practice of law” primarily implicates Role Contradiction.

5. **Document Differences** – When differences exist (e.g., mens rea requirements, strict liability offences), note them in the `notes` field of the dataset.  Provide citations to the local sources.

6. **Version Control** – Maintain separate versions of the dataset for each jurisdiction or include a `jurisdiction` column.  Use semantic versioning to track updates.

7. **Validation** – After mapping, use the structural validation tools to test whether offences appropriately trigger structural failures in sample cases.

By following these steps, the Offense Mapping Dataset becomes a flexible bridge between doctrine and structure across legal systems.

