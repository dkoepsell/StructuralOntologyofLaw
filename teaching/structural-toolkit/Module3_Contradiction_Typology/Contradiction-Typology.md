# Contradiction Typology

The Minimum Legal Chain fails in structurally limited ways.  Each failure corresponds to a type of **legal contradiction**, which maps to a violation of a BFO category and to one or more MLC links.  The thirteen types are grouped into four AERR families – **Authority**, **Event/Process**, **Recognition** and **Repair** – reflecting which part of the chain is affected.

## AERR Families

1. **Authority Failures** – problems with conferral or scope: Types 1–3.  
2. **Event/Process Failures** – issues with norms, procedures or temporal alignment: Types 4–5.  
3. **Recognition Failures** – mismatches in institutional acknowledgment or correlativity: Types 6–7.  
4. **Repair Failures** – absence or invalidity of remedies: Types 8–13.

## Contradiction Types

| Type | Name | AERR Family | MLC Links | BFO Violation | Description |
| --- | --- | --- | --- | --- | --- |
| **1** | **Conferral Failure** | Authority | 1 | Generically dependent continuant does not exist【873523715407077†L155-L159】 | No valid authority is conferred; e.g., agency issues rule without statutory mandate. |
| **2** | **Jurisdictional Contradiction** | Authority | 2 | Relational dependent continuant domain fails | Authority’s jurisdiction does not extend to the situation; e.g., officer acts outside city boundaries. |
| **3** | **Role Contradiction** | Authority | 3 | Specifically dependent continuant lacks bearer【516386639202089†L88-L97】 | Actor does not hold the required role; e.g., unlicensed surgeon. |
| **4** | **Procedural Contradiction** | Event/Process | 5 | Process does not instantiate required obligations | The authorised process is not followed; e.g., missing required steps. |
| **5** | **Temporal Contradiction** | Event/Process | 5–6 | Occurrent temporal constraints violated | Event occurs outside the time when the norm is in force. |
| **6** | **Recognition Failure** | Recognition | 7 | Realisable dependent continuant not recognised | Institution fails to acknowledge or record the legal event. |
| **7** | **Correlativity Contradiction** | Recognition | 6–7 | Relational dependent continuant missing relata | A relational norm lacks one of its counterparts (e.g., obligation without corresponding duty‑holder). |
| **8** | **Repair Failure** | Repair | 8 | Disposition required but absent | No remedy exists despite requirement. |
| **9** | **Recognition Repair Failure** | Repair | 7–8 | Remedy disposition exists but not institutionally realised | A remedy exists but is not implemented (e.g., appeal not accepted). |
| **10** | **Procedural Repair Failure** | Repair | 8 | Remedy process cannot be instantiated | Procedural requirements for remedy are not met. |
| **11** | **Jurisdictional Repair Failure** | Repair | 8 | No bearer for remedy‑granting role | The institution lacks jurisdiction to provide the remedy (e.g., appellate court lacks authority). |
| **12** | **Compound Contradiction** | Multiple | Any | Multiple BFO categories violated simultaneously | Several structural failures occur at once (e.g., wrong authority and missing recognition). |
| **13** | **Institutionalised Contradiction** | Systemic | Any | Systemic tolerance of ontological inconsistency | The legal system tolerates structural breakdowns (e.g., accepted practice contrary to statute). |

## Detection Rules (Informal)

1. **Conferral Failure:** If there is no `authority.valid = true` or the `authority.id` is null, then a Type 1 contradiction.  
2. **Jurisdictional Contradiction:** If `jurisdiction.withinScope = false`, then a Type 2 contradiction.  
3. **Role Contradiction:** If `role.valid = false`, then a Type 3 contradiction.  
4. **Procedural Contradiction:** If `process.complied = false`, then a Type 4 contradiction.  
5. **Temporal Contradiction:** If `event.time` not within `norm`’s temporal scope, then a Type 5 contradiction.  
6. **Recognition Failure:** If `recognition.recognised = false`, then a Type 6 contradiction.  
7. **Correlativity Contradiction:** If a relational norm lacks a correlated role or target, then Type 7.  
8. **Repair Failures:** If `remedy.available = false` or remedy processes are invalid, then Types 8–11 depending on jurisdiction and procedure.  
9. **Compound Contradiction:** If more than one contradiction type is triggered, then Type 12.  
10. **Institutionalised Contradiction:** Recognised when structural failures persist due to systemic norms or toleration.

## SHACL Shapes for Detection

A SHACL file can be constructed to trigger validation reports for each contradiction type.  See `contradiction-shapes.ttl` for an example implementation.

## SWRL Rules

SWRL rules can automate contradiction detection.  See `contradiction-rules.swrl` for sample rules.  For example:

```
MLCRecord(?x) ^ not(AuthorityValid(?x)) -> ConferralFailure(?x)
MLCRecord(?x) ^ not(JurisdictionInScope(?x)) -> JurisdictionalContradiction(?x)
MLCRecord(?x) ^ not(RoleValid(?x)) -> RoleContradiction(?x)
```

Additional rules handle repair and institutional contradictions.

