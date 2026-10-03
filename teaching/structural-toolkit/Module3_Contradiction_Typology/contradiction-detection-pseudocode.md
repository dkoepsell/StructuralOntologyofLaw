# Pseudocode for LLM‑based Contradiction Detection

This pseudocode illustrates how a large language model (LLM) or rule engine might classify structural failures into contradiction types based on an MLC record represented as a Python dictionary.

```python
def classify_mlc_record(record):
    """
    Given a dictionary representing the MLC record with boolean indicators,
    return a list of detected contradiction types.
    """
    contradictions = []

    # Type 1: Conferral Failure
    if not record['authority']['valid']:
        contradictions.append('Type 1: Conferral Failure')

    # Type 2: Jurisdictional Contradiction
    if not record['jurisdiction']['withinScope']:
        contradictions.append('Type 2: Jurisdictional Contradiction')

    # Type 3: Role Contradiction
    if not record['role']['valid']:
        contradictions.append('Type 3: Role Contradiction')

    # Type 4: Procedural Contradiction
    if not record['process']['complied']:
        contradictions.append('Type 4: Procedural Contradiction')

    # Type 5: Temporal Contradiction (simple placeholder)
    # Suppose we have a function in_force_at(time) that checks if the norm is valid at event time
    if not in_force_at(record['event']['time']):
        contradictions.append('Type 5: Temporal Contradiction')

    # Type 6: Recognition Failure
    if not record['recognition']['recognised']:
        contradictions.append('Type 6: Recognition Failure')

    # Type 7: Correlativity Contradiction
    if record.get('correlation_missing', False):
        contradictions.append('Type 7: Correlativity Contradiction')

    # Types 8–11: Repair Failures
    if not record['remedy']['available']:
        contradictions.append('Type 8: Repair Failure')
    # Additional flags (proceduralRepairFailure, jurisdictionalRepairFailure, etc.) can be checked here.

    # Type 12: Compound Contradiction
    if len(contradictions) > 1:
        contradictions.append('Type 12: Compound Contradiction')

    # Type 13: Institutionalised Contradiction (requires systemic analysis)
    # Could be triggered if contradictions persist across multiple records.

    return contradictions
```

This function assumes the record structure defined in the JSON schema.  In practice, an LLM‑based system would parse natural language case descriptions into such structured records using extraction prompts, then apply logic or classification rules to identify structural failures.

