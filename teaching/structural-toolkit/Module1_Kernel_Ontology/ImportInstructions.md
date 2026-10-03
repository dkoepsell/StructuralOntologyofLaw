# Import Instructions

This document explains how to import the SOoL kernel ontology into common ontology tools.

## Using Protégé

1. Open [Protégé](https://protege.stanford.edu/) (version 5.5 or later).  
2. From the **File** menu, choose **Open** and select `kernel_ontology.ttl` from the `Module1_Kernel_Ontology` directory.  
3. Protégé will load the TTL file; you may be prompted to choose a format—select **Turtle**.  
4. To make use of BFO classes, add an **imports** statement: under **Active Ontology**, click **Add Import** and choose **Existing Ontology**. Specify the URI `http://purl.obolibrary.org/obo/bfo.owl` or download the latest BFO release and add it locally.  
5. Similarly, to align with LKIF‑Core, import `lkif-core.owl` (available from the Estrella project).  
6. Save your project. You can now browse classes such as `Authority`, `Role` and properties like `confersAuthority`.

## Using RDFLib (Python)

Use the [rdflib](https://rdflib.readthedocs.io/) library to load and query the ontology.  For example:

```python
from rdflib import Graph, Namespace

# Load the SOoL ontology
sool_graph = Graph()
sool_graph.parse('kernel_ontology.ttl', format='turtle')

# Bind namespaces for convenience
SOOL = Namespace('http://example.org/sool#')
BFO = Namespace('http://purl.obolibrary.org/obo/BFO_')

# Query: list all roles and their realised norms
query = """
PREFIX sool: <http://example.org/sool#>
SELECT ?role ?norm WHERE {
    ?role a sool:Role .
    ?role sool:roleRealises ?norm .
}
"""
for row in sool_graph.query(query):
    print(f"Role: {row.role}, Norm: {row.norm}")
```

Ensure that you install `rdflib` in your Python environment (`pip install rdflib`).  You can add BFO and LKIF imports by parsing those ontologies into the same graph.

## Using OWLAPI (Java)

The [OWLAPI](https://github.com/owlcs/owlapi) allows programmatic access in Java.  A minimal example:

```java
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.*;
import java.io.File;

public class LoadSOoL {
    public static void main(String[] args) throws Exception {
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        File file = new File("kernel_ontology.ttl");
        OWLOntology ontology = manager.loadOntologyFromOntologyDocument(file);
        // Example: iterate through classes
        ontology.classesInSignature().forEach(cls -> {
            System.out.println("Class: " + cls.getIRI());
        });
    }
}
```

To include BFO, load it into the same manager (e.g., `manager.loadOntology(IRI.create("http://purl.obolibrary.org/obo/bfo.owl"))`).  You can then use reasoning engines such as HermiT or Pellet to classify the ontology.

