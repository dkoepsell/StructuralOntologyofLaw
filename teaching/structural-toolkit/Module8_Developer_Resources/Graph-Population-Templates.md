# Graph Population Templates

These templates show how to populate RDF graphs with MLC data using the SOoL kernel ontology.

## Example: Unlicensed Surgeon Case

```turtle
@prefix sool: <http://example.org/sool#> .
@prefix mlc: <http://example.org/mlc#> .
@prefix ex: <http://example.org/case#> .

ex:Case123 a mlc:MLCRecord ;
    mlc:authority ex:Authority1 ;
    mlc:jurisdiction ex:Jurisdiction1 ;
    mlc:role ex:Role1 ;
    mlc:norm ex:Norm1 ;
    mlc:process ex:Process1 ;
    mlc:event ex:Event1 ;
    mlc:recognition ex:Recognition1 ;
    mlc:remedy ex:Remedy1 .

# Authority (invalid)
ex:Authority1 a sool:Authority ;
    sool:confersAuthority ex:LicensingBoard ;
    mlc:valid false .

# Jurisdiction (in scope)
ex:Jurisdiction1 a sool:Jurisdiction ;
    mlc:withinScope true .

# Role (invalid)
ex:Role1 a sool:Role ;
    sool:assignsRole ex:LicensingBoard ;
    mlc:valid false .

# Norm (in force)
ex:Norm1 a sool:Norm ;
    mlc:inForce true .

# Process (not complied)
ex:Process1 a sool:AuthorisedProcess ;
    mlc:complied false .

# Event (surgery)
ex:Event1 a sool:LegalEvent ;
    sool:processRealisesEvent ex:Process1 ;
    mlc:time "2025-09-01T10:00:00"^^xsd:dateTime .

# Recognition (no recognition)
ex:Recognition1 a sool:Recognition ;
    mlc:recognised false .

# Remedy (available)
ex:Remedy1 a sool:Remedy ;
    mlc:available true .

```

## Example: Valid Contract Case

... (similar structure, with all `mlc:valid`, `withinScope`, etc. set to `true`).

Use these templates as a starting point and adapt them to your ontology terms.  Once populated, run SHACL validation to detect contradictions.

