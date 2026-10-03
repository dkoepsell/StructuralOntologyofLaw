# Integration Guide for Existing Ontologies

This guide describes how to integrate the SOoL structural validation tools with existing legal ontologies or knowledge graphs.

## 1. Identify Structural Elements

Most legal ontologies (e.g., LKIF‑Core, LegalRuleML) contain elements corresponding to authority, roles, norms, processes, events, recognition and remedies.  Identify how your ontology represents these concepts:

- **Authority** – look for classes like `lkif:Authority`, `lrml:InstitutionalSource`.
- **Jurisdiction** – examine metadata about spatial/temporal scope (e.g., `lrml:Jurisdiction` elements).
- **Role** – use `lkif:Role`, `lrml:Role`.
- **Norm** – use `lkif:Norm`, `lrml:Right`, `lrml:Duty`.
- **Process / Event** – align `lkif:Action`, `lrml:LegalEvent` with `sool:AuthorisedProcess` and `sool:LegalEvent`.
- **Recognition** – find classes that model institutional acknowledgment (e.g., `lkif:Decision`).
- **Remedy** – map to remedy classes or dispositions.

## 2. Map to MLC Schema

Once you have located these elements, map them to the fields defined in `MLC-schema.json`.  For each case or fact pattern:

1. Fill in the `authority.id` with the URI of the authority; set `valid` based on whether it was validly conferred.
2. Set `jurisdiction.domain` and `withinScope` according to the jurisdiction.
3. Identify the agent and its `roleName`; set `valid` depending on whether the role was properly conferred.
4. Identify the normative source and set `inForce` depending on the time.
5. Describe the `process` and whether it complied with procedural requirements.
6. Record the `event` description and time.
7. Determine whether the event was recognised (`recognition.recognised`).
8. Indicate whether a remedy was available.

## 3. Run Validation

Use the **Completeness Checker** or the API to validate each MLC record.  For RDF graphs, generate SHACL reports using `MLC-shapes.ttl` and `contradiction-shapes.ttl`.

For example, using Python and `pyshacl`:

```python
from pyshacl import validate
import rdflib

# Load your data and shapes
data_graph = rdflib.Graph().parse('my_case.ttl', format='turtle')
shapes_graph = rdflib.Graph().parse('MLC-shapes.ttl', format='turtle')
result = validate(data_graph, shacl_graph=shapes_graph, inference='rdfs')
conforms, report_graph, report_text = result
print(report_text)
```

## 4. Interpret Results

- **Conformance** means the legal description is structurally complete.  
- **Violations** indicate missing or invalid links.  Use the `Structural Integrity Report` template to communicate findings.

## 5. Extend for Domain Specifics

The MLC is domain‑neutral; for specific domains (e.g., criminal law, contract law) you may extend the schema with additional fields or shapes.  However, maintain compatibility with the core eight links to preserve interoperability.

