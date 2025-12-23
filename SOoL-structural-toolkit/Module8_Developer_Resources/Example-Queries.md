# Example Queries

This document provides sample queries for interacting with data structured according to the SOoL framework.

## SPARQL Queries

### List all authorities and their jurisdictions

```sparql
PREFIX mlc: <http://example.org/mlc#>
SELECT ?authority ?domain WHERE {
  ?record mlc:authority ?authority .
  ?record mlc:jurisdiction ?jurisdiction .
  ?jurisdiction mlc:domain ?domain .
}
```

### Find MLC records with role contradictions

```sparql
PREFIX mlc: <http://example.org/mlc#>
SELECT ?record WHERE {
  ?record mlc:role ?role .
  ?role mlc:valid false .
}
```

## RDFLib (Python)

```python
from rdflib import Graph, Namespace

SOOL = Namespace('http://example.org/sool#')
MLC = Namespace('http://example.org/mlc#')

g = Graph()
g.parse('case123.ttl', format='turtle')

# List invalid roles
for record, role in g.subject_objects(MLC.role):
    valid = g.value(role, MLC.valid)
    if valid and valid.toPython() is False:
        print('Role contradiction in record', record)
```

## OWLAPI (Java)

```java
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.*;

OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
OWLOntology ontology = manager.loadOntologyFromOntologyDocument(new File("case123.ttl"));
// Filter individuals of class mlc:MLCRecord
OWLDataFactory df = manager.getOWLDataFactory();
OWLClass mlcRecord = df.getOWLClass(IRI.create("http://example.org/mlc#MLCRecord"));
ontology.individualsInSignature().forEach(ind -> {
    if (ontology.classAssertionAxioms(ind).anyMatch(ax -> ax.getClassesInSignature().contains(mlcRecord))) {
        System.out.println("MLC Record: " + ind.getIRI());
    }
});
```

