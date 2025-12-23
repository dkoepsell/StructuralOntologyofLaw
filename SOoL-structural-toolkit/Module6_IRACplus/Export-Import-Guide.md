# IRACplus Export/Import Guide

This guide explains how to export IRACplus analyses to structured formats and import them into other systems.

## Exporting IRACplus Documents

1. **Author your analysis** using the IRACplus structure: Issue, Rule, Analysis, Conclusion and Structural Diagnosis.
2. **Create a JSON document** conforming to `IRACplus-schema.json`.  For example:

```json
{
  "issue": "Whether an unlicensed surgeon can create valid consent to surgery.",
  "rule": "Under the Medical Practice Act, only licensed physicians may perform surgery.",
  "analysis": "The actor lacks a valid medical licence (Role Contradiction).  Without a licence, there is no authority to perform surgery, and the norm requiring licensure applies.  The process (surgery) therefore does not satisfy the required conditions, and the legal event (consent) has no effect.",
  "conclusion": "The consent is invalid because the structural chain fails at the role link.",
  "structuralDiagnosis": ["Type 3: Role Contradiction"]
}
```
3. **Save** the JSON file with a suitable name (e.g., `case123_iracplus.json`).
4. Optionally, generate **HTML or PDF** exports by converting the fields into formatted documents.  Include the structural diagnosis in a header or footnote.

## Importing into Tools

To import an IRACplus document into a reasoning or documentation tool:

1. **Validate** the JSON against `IRACplus-schema.json` to ensure required fields are present.
2. **Parse** the JSON fields into your application.  For example, use Python:

```python
import json
with open('case123_iracplus.json') as f:
    data = json.load(f)
print(data['issue'])
```
3. **Link** the analysis to structural data.  For instance, if you also have an MLC record, cross‑reference the detected contradiction types.
4. **Render** the analysis in your desired format.  In a web application, populate templates with the issue, rule, analysis and conclusion sections.

## Round‑Trip Integrity

When importing and exporting, maintain the structural diagnosis.  If further structural validation is performed (e.g., after an appeal), update the `structuralDiagnosis` array accordingly and increment version numbers if you maintain version history.

