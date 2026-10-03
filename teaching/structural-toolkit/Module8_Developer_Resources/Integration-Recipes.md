# Integration Recipes

## 1. Integrate with LLM Pipelines

Large Language Models (LLMs) can assist in extracting MLC records from unstructured legal texts.  A typical pipeline:

1. **Pre‑processing:** Use NLP techniques to split documents into sentences and identify entities (named entities, dates, roles, institutions).
2. **Prompt Engineering:** Design prompts that instruct the LLM to identify the eight MLC links.  Example prompt:

   > "Given the following legal scenario, extract the source of authority, jurisdiction, roles, norms, process, event, recognition and remedy."

3. **Structured Output:** Ask the LLM to return the data in JSON matching `MLC-schema.json`.  Validate the JSON client‑side.
4. **Validation:** Run the completeness checker and contradiction detector on the extracted record.  Feed the results back into the LLM for analysis or explanation.
5. **IRACplus Generation:** Use the extracted structure to guide the LLM in drafting the Issue, Rule, Analysis and Conclusion sections.

## 2. Integrate with Argument Mining Systems

Argument mining systems identify premises, conclusions and argument structures in legal texts.  To integrate SOoL:

1. **Annotate MLC Links:** Label segments of text that correspond to MLC links (e.g., authority statements, procedural descriptions).  
2. **Align Structural Roles:** Map argument components (claims, warrants) to structural positions.  For example, a premise asserting lack of licence aligns with a Role Contradiction.  
3. **Use Contradiction Types as Features:** In machine learning models, include the detected contradiction type as a feature to predict outcomes or argument strength.

## 3. Integrate with Knowledge Graphs

1. **Extend your ontology** by importing the SOoL kernel (`kernel_ontology.ttl`).  
2. **Instantiate MLC records** as shown in `Graph-Population-Templates.md`.  
3. **Run SHACL validation** regularly to maintain structural integrity.  
4. **Expose SPARQL endpoints** for querying structural aspects of legal cases.

## 4. Versioning and Governance

When integrating SOoL into production systems:

- Maintain a changelog of ontology updates.  
- Use semantic versioning (e.g., v1.0.0) for releases.  
- Establish a governance body to approve changes to classes, properties and rules.  
- Provide deprecation policies for removed or renamed terms.

