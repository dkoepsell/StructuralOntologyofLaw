# Competency Questions

Competency questions are intended to test whether the kernel ontology can answer relevant queries in the legal domain.

1. **Which institution confers the authority for a given norm?**
   - *Query:* Given a norm, retrieve the authority that conferred it via the `assignsRole` and `roleRealises` relationships.

2. **What is the jurisdictional scope of a particular authority?**
   - *Query:* For a given authority, return its associated `sool:Jurisdiction` via the `hasJurisdiction` property.

3. **Which roles are assigned by a specific authority?**
   - *Query:* For an authority instance, list all `sool:Role` individuals linked through `assignsRole`.

4. **What norms are realised by a given role?**
   - *Query:* For a role instance, return all associated `sool:Norm` individuals via `roleRealises`.

5. **Does a particular legal event have institutional recognition?**
   - *Query:* Given a `sool:LegalEvent` instance, check whether there exists a `sool:Recognition` instance linked via `recognisesEvent` from an institution.

6. **Which authorised processes produce a given legal event?**
   - *Query:* For a legal event, list the `sool:AuthorisedProcess` individuals connected via `processRealisesEvent`.

7. **What remedies are provided by a specific institution?**
   - *Query:* Return all `sool:Remedy` instances linked via `providesRemedy` from an `sool:Institution`.

8. **Does an agent hold a specific role within a jurisdiction?**
   - *Query:* Determine whether an instance of `sool:Agent` is the bearer of a `sool:Role` that has been conferred within the relevant `sool:Jurisdiction`.

9. **Is there a structural contradiction in a chain of events?**
   - *Query:* Given instances of authority, role, process and event, verify that each link in the Minimum Legal Chain is present; if any link is missing, identify the type of contradiction (authority failure, jurisdictional contradiction, role contradiction, etc.).

These questions can be implemented using SPARQL queries against RDF data instantiated using the kernel ontology.

